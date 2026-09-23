"""Explicit, reviewed FileMaker field registry; never infer writability from values."""
import json
from pathlib import Path
from decimal import Decimal, InvalidOperation
from datetime import datetime


class ProductValidationError(ValueError):
    pass


class SKUValidationError(ProductValidationError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def validate_sku(value):
    if not isinstance(value, str) or not value.strip():
        raise SKUValidationError('SKU_REQUIRED', 'SKU 不能为空，请填写产品 SKU。')
    return value.strip()


class ProductSchema:
    def __init__(self, document):
        self.document = document
        self.fields = {f['name']: f for f in document.get('fields', [])}
        if not self.fields or 'ID' not in self.fields:
            raise ProductValidationError('Product schema must include ID')

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text()))

    def editable(self, name):
        field = self.fields.get(name, {})
        return field.get('managed', True) and bool(field.get('writable')) and name != 'ID' and '::' not in name and not field.get('global')

    def validate_layout(self, metadata):
        actual = {field['name']: field for field in metadata.get('fieldMetaData', [])}
        for name, field in self.fields.items():
            if not field.get('managed', True) or field.get('externalSource'):
                continue
            if name not in actual:
                raise ProductValidationError(f'API 布局缺少登记字段，禁止按空值导入：{name}')
            if actual[name].get('result') != field['result'] or int(actual[name].get('maxRepeat', 1)) != int(field.get('maxRepeat', 1)):
                raise ProductValidationError(f'API 字段类型或重复位置已改变：{name}')

    def validate(self, changes, permissions):
        for name, value in changes.items():
            if name == 'product_sku':
                validate_sku(value)
            field = self.fields.get(name)
            if not field or not self.editable(name) or field['result'] == 'container':
                raise ProductValidationError(f'字段不可写：{name}')
            permission = field.get('writePermission', 'canEditProducts')
            if not permissions.get(permission, False) or not permissions.get(field.get('readPermission','canViewProducts'),False):
                raise ProductValidationError(f'没有字段编辑权限：{name}')
            values = value if isinstance(value, list) else [value]
            if isinstance(value, list) and (int(field.get('maxRepeat',1)) == 1 or len(value) > int(field.get('maxRepeat', 1))):
                raise ProductValidationError(f'重复字段超出范围：{name}')
            for item in values:
                if not isinstance(item, (str, int, float, type(None))) or isinstance(item, bool):
                    raise ProductValidationError(f'字段值类型错误：{name}')
                if item in ('', None):
                    if field.get('required'):
                        raise ProductValidationError(f'必填字段：{name}')
                    continue
                if field.get('maxCharacters') and len(str(item)) > field['maxCharacters']:
                    raise ProductValidationError(f'字段过长：{name}')
                if field['result'] in {'date','time','timestamp'}:
                    formats = {'date':['%Y-%m-%d','%m/%d/%Y'], 'time':['%H:%M:%S','%H:%M'], 'timestamp':['%Y-%m-%dT%H:%M:%S','%m/%d/%Y %H:%M:%S','%Y-%m-%d %H:%M:%S']}[field['result']]
                    valid=False
                    for pattern in formats:
                        try: datetime.strptime(str(item),pattern); valid=True; break
                        except ValueError: pass
                    if not valid: raise ProductValidationError(f'日期或时间格式错误：{name}')
                if field['result'] == 'number':
                    try:
                        if not Decimal(str(item)).is_finite():
                            raise InvalidOperation()
                    except InvalidOperation:
                        raise ProductValidationError(f'数字格式错误：{name}')
        return changes

    def validate_complete(self, fields):
        if 'product_sku' in self.fields:
            validate_sku(fields.get('product_sku'))
        for name, field in self.fields.items():
            if self.editable(name) and field.get('required') and fields.get(name) in ('', None):
                raise ProductValidationError(f'必填字段：{name}')

    def slot(self, name, repetition, permissions):
        field = self.fields.get(name, {})
        if (not self.editable(name) or field.get('result') != 'container'
                or not 1 <= repetition <= int(field.get('maxRepeat', 1))
                or not permissions.get(field.get('writePermission', 'canEditProducts'), False)
                or not permissions.get(field.get('readPermission', 'canViewProducts'), False)):
            raise ProductValidationError('容器字段、重复位置或权限无效')

    def visible(self, permissions):
        return [f for f in self.fields.values() if f.get('managed',True) and permissions.get(f.get('readPermission', 'canViewProducts'), False)]

    def filter_fields(self, fields, permissions):
        return {k: v for k, v in fields.items() if k in self.fields and self.fields[k].get('managed',True) and permissions.get(self.fields[k].get('readPermission', 'canViewProducts'), False)}
