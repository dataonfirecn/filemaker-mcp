from __future__ import annotations

import asyncio
import base64
import binascii
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.models.part_creation import (
    PartCreationDefaults,
    PartCreationOption,
    PartCreationOptionsResponse,
    PartCreationRequest,
    PartCreationResponse,
    PartValidationResponse,
)
from app.services.filemaker_client import FileMakerClient
from app.services.material_id_options import load_material_id_options

VALUE_LISTS = {
    "warehouseDivisions": "倉庫分工",
    "materialCategories": "零件性質",
    "machiningCategories": "加工分類",
    "departmentDivisions": "零件狀態",
    "statisticsCategories": "統計分類",
    "useDepartments": "使用公司",
    "lifecycleStatuses": "狀態",
    "partCategories": "零件品種",
    "materialProperties": "材料分類",
    "warehouseCodes": "倉庫",
    "materialSizes": "零件材料尺寸",
    "exclusiveCustomers": "客戶",
}

ENUM_REQUEST_FIELDS = {
    "warehouseDivision": "warehouse_divisions",
    "materialCategory": "material_categories",
    "machiningCategory": "machining_categories",
    "departmentDivision": "department_divisions",
    "statisticsCategory": "statistics_categories",
    "useDepartment": "use_departments",
    "lifecycleStatus": "lifecycle_statuses",
    "partCategory": "part_categories",
    "materialProperties": "material_properties",
}

DEFAULTS = {
    "departmentDivision": "采购",
    "statisticsCategory": "统计",
    "machiningCategory": "外购",
}

PART_NUMBER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,319}$")
NAME_PLACEHOLDER = "新零件，請填寫正確中文名稱＆詳細資訊"
ALLOWED_PHOTO_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}

_create_lock = asyncio.Lock()


class PartCreationError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int,
        errors: dict[str, str] | None = None,
        warnings: list[str] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.errors = errors or {}
        self.warnings = warnings or []


@dataclass(frozen=True)
class PreparedPhoto:
    name: str
    mime_type: str
    content: bytes


async def load_part_creation_options(
    filemaker: FileMakerClient,
    settings: Settings,
) -> PartCreationOptionsResponse:
    metadata, generator = await asyncio.gather(
        filemaker.get_layout_metadata(settings.filemaker_part_read_layout),
        load_material_id_options(filemaker),
    )
    value_lists = {
        str(item.get("name") or ""): item
        for item in metadata.get("valueLists", [])
        if isinstance(item, dict)
    }
    values: dict[str, list[PartCreationOption]] = {}
    for response_key, value_list_name in VALUE_LISTS.items():
        raw = (value_lists.get(value_list_name) or {}).get("values")
        if response_key == "exclusiveCustomers":
            values[response_key] = _customer_options(raw)
        else:
            values[response_key] = _standard_options(raw)

    return PartCreationOptionsResponse(
        warehouseDivisions=values["warehouseDivisions"],
        materialCategories=values["materialCategories"],
        machiningCategories=values["machiningCategories"],
        departmentDivisions=values["departmentDivisions"],
        statisticsCategories=values["statisticsCategories"],
        useDepartments=values["useDepartments"],
        lifecycleStatuses=values["lifecycleStatuses"],
        partCategories=values["partCategories"],
        materialProperties=values["materialProperties"],
        warehouseCodes=values["warehouseCodes"],
        materialSizes=values["materialSizes"],
        exclusiveCustomers=values["exclusiveCustomers"],
        generator=generator,
        defaults=PartCreationDefaults(**DEFAULTS),
    )


async def validate_part_creation(
    filemaker: FileMakerClient,
    settings: Settings,
    body: PartCreationRequest,
    *,
    options: PartCreationOptionsResponse | None = None,
    check_duplicate: bool = True,
) -> PartValidationResponse:
    live_options = options or await load_part_creation_options(filemaker, settings)
    errors, warnings = _validate_fields(body, live_options, settings)

    if check_duplicate and "partNumber" not in errors:
        existing = await _find_part_by_number(filemaker, settings, body.part_number.strip())
        if existing:
            errors["partNumber"] = "此零件编号已存在，请重新生成或修改。"

    return PartValidationResponse(valid=not errors, errors=errors, warnings=warnings)


async def create_part(
    filemaker: FileMakerClient,
    settings: Settings,
    body: PartCreationRequest,
) -> PartCreationResponse:
    if not settings.filemaker_part_create_enabled:
        raise PartCreationError(
            "新建零件的 Data API 写入尚未启用。",
            code="PART_CREATE_DISABLED",
            status_code=403,
        )

    options = await load_part_creation_options(filemaker, settings)
    preliminary = await validate_part_creation(
        filemaker,
        settings,
        body,
        options=options,
        check_duplicate=False,
    )
    if not preliminary.valid:
        raise PartCreationError(
            "请修正表单中的验证问题。",
            code="VALIDATION_FAILED",
            status_code=422,
            errors=preliminary.errors,
            warnings=preliminary.warnings,
        )

    photo = _prepare_photo(body, settings)
    record_id = ""
    async with _create_lock:
        if await _find_part_by_number(filemaker, settings, body.part_number.strip()):
            raise PartCreationError(
                "此零件编号已存在，请重新生成或修改。",
                code="DUPLICATE_PART_NUMBER",
                status_code=409,
                errors={"partNumber": "此零件编号已存在，请重新生成或修改。"},
            )

        created = await filemaker.create_record(
            settings.filemaker_part_write_layout,
            _record_fields(body),
        )
        record_id = str(created.get("recordId") or "")
        if not record_id:
            raise PartCreationError(
                "FileMaker 未返回新零件的记录 ID。",
                code="CREATE_RESPONSE_INVALID",
                status_code=502,
            )

        try:
            if photo:
                await filemaker.upload_container(
                    settings.filemaker_part_write_layout,
                    record_id,
                    settings.filemaker_part_photo_field,
                    photo.content,
                    photo.name,
                    photo.mime_type,
                )
        except Exception:
            await filemaker.delete_record(settings.filemaker_part_write_layout, record_id)
            raise

    records = await filemaker.get_record(settings.filemaker_part_write_layout, record_id)
    fields = (records[0].get("fieldData") or {}) if records else {}
    return PartCreationResponse(
        recordId=record_id,
        partId=_text(fields.get("part_id")),
        partNumber=(
            _text(fields.get(settings.filemaker_part_number_field))
            or body.part_number.strip()
        ),
        photoUploaded=bool(photo),
        warnings=preliminary.warnings,
    )


def part_creation_audit_payload(body: PartCreationRequest) -> dict[str, Any]:
    payload = body.model_dump(by_alias=True)
    payload.pop("photoBase64", None)
    payload["hasPhoto"] = bool(body.photo_base64.strip())
    return payload


def _validate_fields(
    body: PartCreationRequest,
    options: PartCreationOptionsResponse,
    settings: Settings,
) -> tuple[dict[str, str], list[str]]:
    errors: dict[str, str] = {}
    warnings: list[str] = []
    part_number = body.part_number.strip()
    internal_name = body.internal_name.strip()
    external_name = body.external_name.strip()

    if not part_number:
        errors["partNumber"] = "请填写或生成零件编号。"
    elif not PART_NUMBER_PATTERN.fullmatch(part_number):
        errors["partNumber"] = "编号只能使用英文字母、数字、点、短横线和下划线。"

    if not internal_name or internal_name == NAME_PLACEHOLDER:
        errors["internalName"] = "请填写正确的内部中文名称和详细信息。"
    if not external_name or external_name == NAME_PLACEHOLDER:
        errors["externalName"] = "请填写正确的对外中文名称和详细信息。"
    if not body.warehouse_division.strip():
        errors["warehouseDivision"] = "仓库分工为必选项。"
    if not body.material_category.strip():
        errors["materialCategory"] = "零件性质为必选项。"

    for alias, attribute in ENUM_REQUEST_FIELDS.items():
        value = _text(getattr(body, _snake_case(alias)))
        if not value:
            continue
        allowed = {item.code for item in getattr(options, attribute)}
        if allowed and value not in allowed:
            errors[alias] = "选项已在 FileMaker 中变更，请重新选择。"

    customer_id = body.customer_id.strip()
    if customer_id:
        customer = next(
            (item for item in options.exclusive_customers if item.code == customer_id),
            None,
        )
        if not customer:
            errors["customerId"] = "专属客户已在 FileMaker 中变更，请重新选择。"
        elif body.customer_name.strip() and body.customer_name.strip() != customer.label:
            errors["customerId"] = "专属客户名称与客户代码不一致，请重新选择。"

    if body.weight_grams.strip():
        try:
            weight = Decimal(body.weight_grams.strip())
            if not weight.is_finite() or weight < 0:
                raise InvalidOperation
        except InvalidOperation:
            errors["weightGrams"] = "重量必须是大于或等于 0 的数字。"

    if body.photo_base64.strip():
        try:
            _prepare_photo(body, settings)
        except PartCreationError as exc:
            errors["photo"] = str(exc)
    elif body.photo_name.strip() or body.photo_mime_type.strip():
        errors["photo"] = "照片资料不完整，请重新选择照片。"

    if body.warehouse_code.strip() and not options.warehouse_codes:
        warnings.append("FileMaker 当前没有可用的仓库值列表，已按手工输入保存。")
    return errors, warnings


def _record_fields(body: PartCreationRequest) -> dict[str, Any]:
    return {
        "part_number": body.part_number.strip(),
        "part_name_internal": body.internal_name.strip(),
        "part_name_external": body.external_name.strip(),
        "check_inventory_notice": "1" if body.inventory_notice else "",
        "倉庫分工": body.warehouse_division.strip(),
        "加工類": body.machining_category.strip(),
        "統計分類": body.statistics_category.strip(),
        "使用部門": body.use_department.strip(),
        "part_lifecycle_status": body.lifecycle_status.strip(),
        "ID_廠商": body.vendor_number.strip(),
        "material_category": body.material_category.strip(),
        "部門分工": body.department_division.strip(),
        "part_category": body.part_category.strip(),
        "material_properties": body.material_properties.strip(),
        "material_spec": body.material_spec.strip(),
        "warehouse_code": body.warehouse_code.strip(),
        "warehouse_location_primary": body.location_primary.strip(),
        "warehouse_location_secondary": body.location_secondary.strip(),
        "重量": body.weight_grams.strip(),
        "材料尺寸": body.material_size.strip(),
        "customer_id": body.customer_id.strip(),
        "exclusive_customer_name": body.customer_name.strip(),
        "customer_part_number": body.customer_part_number.strip(),
    }


async def _find_part_by_number(
    filemaker: FileMakerClient,
    settings: Settings,
    part_number: str,
) -> dict[str, Any] | None:
    result = await filemaker.find_records(
        settings.filemaker_part_write_layout,
        query={settings.filemaker_part_number_field: f"=={part_number}"},
        limit=1,
    )
    data = result.get("data") or []
    return data[0] if data else None


def _prepare_photo(
    body: PartCreationRequest,
    settings: Settings,
) -> PreparedPhoto | None:
    encoded = body.photo_base64.strip()
    if not encoded:
        return None
    mime_type = body.photo_mime_type.strip().lower()
    extension = ALLOWED_PHOTO_TYPES.get(mime_type)
    if not extension:
        raise PartCreationError(
            "照片只支持 JPG、PNG 或 WebP。",
            code="PHOTO_TYPE_INVALID",
            status_code=422,
        )
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PartCreationError(
            "照片资料无法解析，请重新选择。",
            code="PHOTO_DATA_INVALID",
            status_code=422,
        ) from exc
    if not content:
        raise PartCreationError(
            "照片内容为空，请重新选择。",
            code="PHOTO_EMPTY",
            status_code=422,
        )
    if len(content) > settings.filemaker_part_max_photo_bytes:
        max_mb = settings.filemaker_part_max_photo_bytes // (1024 * 1024)
        raise PartCreationError(
            f"处理后的照片不能超过 {max_mb} MB。",
            code="PHOTO_TOO_LARGE",
            status_code=422,
        )

    base_name = Path(body.photo_name.strip() or "零件照片").name
    stem = Path(base_name).stem.strip() or "零件照片"
    return PreparedPhoto(
        name=f"{stem}{extension}",
        mime_type=mime_type,
        content=content,
    )


def _standard_options(raw_values: Any) -> list[PartCreationOption]:
    options: list[PartCreationOption] = []
    seen: set[str] = set()
    for item in raw_values if isinstance(raw_values, list) else []:
        if not isinstance(item, dict):
            continue
        code = _text(item.get("value"))
        if not code or code in seen:
            continue
        seen.add(code)
        display = _text(item.get("displayValue"))
        label = re.sub(rf"^{re.escape(code)}(?:\s+|$)", "", display, count=1).strip()
        options.append(PartCreationOption(code=code, label=label or display or code))
    return options


def _customer_options(raw_values: Any) -> list[PartCreationOption]:
    options: list[PartCreationOption] = []
    seen: set[str] = set()
    for item in raw_values if isinstance(raw_values, list) else []:
        if not isinstance(item, dict):
            continue
        company = _text(item.get("value"))
        display = _text(item.get("displayValue"))
        tokens = display.split()
        customer_id = tokens[-1] if tokens else ""
        if not company or not customer_id or customer_id in seen:
            continue
        seen.add(customer_id)
        options.append(PartCreationOption(code=customer_id, label=company))
    return options


def _snake_case(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def _text(value: Any) -> str:
    return str(value or "").strip()
