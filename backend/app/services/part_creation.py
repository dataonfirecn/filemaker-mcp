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
    PartVendorOption,
    PartVendorSearchResponse,
    PartValidationResponse,
)
from app.services.filemaker_client import FileMakerClient
from app.services.filemaker_odata_client import FileMakerODataClient
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

CUSTOMER_TABLE = "客戶"
CUSTOMER_ID_FIELD = "ID"
CUSTOMER_CODE_FIELD = "客戶代號"
CUSTOMER_NAME_FIELDS = ("客戶公司簡稱", "客戶名稱", "公司")
VENDOR_LAYOUT = "@S廠商"
VENDOR_ID_FIELD = "ID"
VENDOR_NUMBER_FIELD = "ID_廠商編號"
VENDOR_NAME_FIELD = "廠商名稱"
VENDOR_STATUS_FIELD = "status"
APPROVED_VENDOR_STATUSES = {"已审核", "已審核"}


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


@dataclass(frozen=True)
class ResolvedCustomer:
    customer_id: str
    code: str
    name: str


@dataclass(frozen=True)
class ResolvedVendor:
    vendor_id: str
    vendor_number: str
    vendor_name: str
    status: str

    @property
    def selectable(self) -> bool:
        return self.status in APPROVED_VENDOR_STATUSES


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
        assetUploadsEnabled=(
            settings.filemaker_part_assets_enabled and settings.cos_configured
        ),
    )


async def search_part_vendors(
    filemaker: FileMakerClient,
    query: str,
    *,
    limit: int,
) -> PartVendorSearchResponse:
    term = _normalize_search_term(query)
    find_query: list[dict[str, str]] | None = None
    if term:
        criterion = f"*{term}*"
        find_query = [
            {VENDOR_NAME_FIELD: criterion},
            {VENDOR_NUMBER_FIELD: criterion},
        ]
    result = await filemaker.find_records(
        VENDOR_LAYOUT,
        query=find_query,
        limit=limit,
        sort=[{"fieldName": VENDOR_NAME_FIELD, "sortOrder": "ascend"}],
    )
    items: list[PartVendorOption] = []
    seen: set[str] = set()
    for record in result.get("data") or []:
        vendor = _vendor_from_record(record)
        if not vendor or vendor.vendor_id in seen:
            continue
        seen.add(vendor.vendor_id)
        items.append(
            PartVendorOption(
                vendorId=vendor.vendor_id,
                vendorNumber=vendor.vendor_number,
                vendorName=vendor.vendor_name,
                status=vendor.status,
                selectable=vendor.selectable,
            )
        )
    return PartVendorSearchResponse(
        items=items,
        foundCount=int(result.get("foundCount") or len(items)),
    )


async def validate_part_creation(
    filemaker: FileMakerClient,
    settings: Settings,
    body: PartCreationRequest,
    *,
    odata: FileMakerODataClient,
    options: PartCreationOptionsResponse | None = None,
    check_duplicate: bool = True,
    check_customer_mapping: bool = True,
    check_vendor_mapping: bool = True,
) -> PartValidationResponse:
    live_options = options or await load_part_creation_options(filemaker, settings)
    errors, warnings = _validate_fields(body, live_options, settings)

    if check_duplicate and "partNumber" not in errors:
        existing = await _find_part_by_number(filemaker, settings, body.part_number.strip())
        if existing:
            errors["partNumber"] = "此零件编号已存在，请重新生成或修改。"

    if (
        check_customer_mapping
        and body.customer_code.strip()
        and "customerCode" not in errors
    ):
        customer = await _resolve_customer(odata, body.customer_code.strip())
        if not customer:
            errors["customerCode"] = "无法把客户代号映射到 FileMaker 客户主键，请重新选择。"

    if check_vendor_mapping and body.vendor_id.strip() and "vendorId" not in errors:
        vendor = await _resolve_vendor(filemaker, body.vendor_id.strip())
        if not vendor:
            errors["vendorId"] = "厂商资料已变更或不存在，请重新选择。"
        elif not vendor.selectable:
            errors["vendorId"] = "该厂商尚未审核，暂时不能用于建立零件。"
        elif (
            body.vendor_number.strip()
            and body.vendor_number.strip() != vendor.vendor_number
        ):
            errors["vendorId"] = "厂商编号与 FileMaker 当前资料不一致，请重新选择。"
        elif body.vendor_name.strip() and body.vendor_name.strip() != vendor.vendor_name:
            errors["vendorId"] = "厂商名称与 FileMaker 当前资料不一致，请重新选择。"

    return PartValidationResponse(valid=not errors, errors=errors, warnings=warnings)


async def create_part(
    filemaker: FileMakerClient,
    settings: Settings,
    body: PartCreationRequest,
    *,
    odata: FileMakerODataClient,
    created_by: str,
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
        odata=odata,
        options=options,
        check_duplicate=False,
        check_customer_mapping=False,
        check_vendor_mapping=False,
    )
    if not preliminary.valid:
        raise PartCreationError(
            "请修正表单中的验证问题。",
            code="VALIDATION_FAILED",
            status_code=422,
            errors=preliminary.errors,
            warnings=preliminary.warnings,
        )

    customer = None
    if body.customer_code.strip():
        customer = await _resolve_customer(odata, body.customer_code.strip())
        if not customer:
            raise PartCreationError(
                "无法把客户代号映射到 FileMaker 客户主键。",
                code="CUSTOMER_MAPPING_FAILED",
                status_code=422,
                errors={
                    "customerCode": "客户资料已变更或内部主键不可用，请重新选择。"
                },
                warnings=preliminary.warnings,
            )

    vendor = None
    if body.vendor_id.strip():
        vendor = await _resolve_vendor(filemaker, body.vendor_id.strip())
        if not vendor or not vendor.selectable:
            raise PartCreationError(
                "无法使用所选厂商建立零件。",
                code="VENDOR_MAPPING_FAILED",
                status_code=422,
                errors={"vendorId": "厂商资料已变更、未审核或不存在，请重新选择。"},
                warnings=preliminary.warnings,
            )
        if (
            body.vendor_number.strip()
            and body.vendor_number.strip() != vendor.vendor_number
        ) or (
            body.vendor_name.strip()
            and body.vendor_name.strip() != vendor.vendor_name
        ):
            raise PartCreationError(
                "厂商显示资料与 FileMaker 当前资料不一致。",
                code="VENDOR_MAPPING_FAILED",
                status_code=422,
                errors={"vendorId": "厂商资料已更新，请重新选择。"},
                warnings=preliminary.warnings,
            )

    photo = None if body.photo_upload_id.strip() else _prepare_photo(body, settings)
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
            _record_fields(
                body,
                customer=customer,
                vendor=vendor,
                created_by=created_by,
            ),
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

    customer_code = body.customer_code.strip()
    if customer_code:
        customer = next(
            (item for item in options.exclusive_customers if item.code == customer_code),
            None,
        )
        if not customer:
            errors["customerCode"] = "专属客户已在 FileMaker 中变更，请重新选择。"
        elif body.customer_name.strip() and body.customer_name.strip() != customer.label:
            errors["customerCode"] = "专属客户名称与客户代码不一致，请重新选择。"

    if not body.vendor_id.strip() and (
        body.vendor_number.strip() or body.vendor_name.strip()
    ):
        errors["vendorId"] = "请通过厂商搜索结果选择厂商，不能只输入名称或编号。"

    if body.weight_grams.strip():
        try:
            weight = Decimal(body.weight_grams.strip())
            if not weight.is_finite() or weight < 0:
                raise InvalidOperation
        except InvalidOperation:
            errors["weightGrams"] = "重量必须是大于或等于 0 的数字。"

    if body.photo_upload_id.strip() and body.photo_base64.strip():
        errors["photo"] = "照片不能同时使用 COS 上传和 FileMaker 容器上传。"
    elif body.photo_upload_id.strip():
        if not settings.filemaker_part_assets_enabled:
            errors["photo"] = "零件资产上传尚未启用，请重新选择照片。"
    elif body.photo_base64.strip():
        try:
            _prepare_photo(body, settings)
        except PartCreationError as exc:
            errors["photo"] = str(exc)
    elif body.photo_name.strip() or body.photo_mime_type.strip():
        errors["photo"] = "照片资料不完整，请重新选择照片。"

    if body.warehouse_code.strip() and not options.warehouse_codes:
        warnings.append("FileMaker 当前没有可用的仓库值列表，已按手工输入保存。")
    return errors, warnings


def _record_fields(
    body: PartCreationRequest,
    *,
    customer: ResolvedCustomer | None,
    vendor: ResolvedVendor | None,
    created_by: str,
) -> dict[str, Any]:
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
        "ID_廠商": vendor.vendor_id if vendor else "",
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
        "customer_id": customer.customer_id if customer else "",
        "exclusive_customer_name": (
            customer.name if customer else body.customer_name.strip()
        ),
        "customer_part_number": body.customer_part_number.strip(),
        "created_by": created_by.strip(),
    }


async def _resolve_vendor(
    filemaker: FileMakerClient,
    vendor_id: str,
) -> ResolvedVendor | None:
    result = await filemaker.find_records(
        VENDOR_LAYOUT,
        query={VENDOR_ID_FIELD: f"=={vendor_id.strip()}"},
        limit=2,
    )
    matches = [
        vendor
        for record in result.get("data") or []
        if (vendor := _vendor_from_record(record))
        and vendor.vendor_id == vendor_id.strip()
    ]
    return matches[0] if len(matches) == 1 else None


def _vendor_from_record(record: Any) -> ResolvedVendor | None:
    fields = record.get("fieldData") if isinstance(record, dict) else {}
    fields = fields if isinstance(fields, dict) else {}
    vendor_id = _text(fields.get(VENDOR_ID_FIELD))
    vendor_name = _text(fields.get(VENDOR_NAME_FIELD))
    if not vendor_id or not vendor_name:
        return None
    return ResolvedVendor(
        vendor_id=vendor_id,
        vendor_number=_text(fields.get(VENDOR_NUMBER_FIELD)),
        vendor_name=vendor_name,
        status=_text(fields.get(VENDOR_STATUS_FIELD)),
    )


async def _resolve_customer(
    odata: FileMakerODataClient,
    customer_code: str,
) -> ResolvedCustomer | None:
    code = customer_code.strip()
    if not code:
        return None
    result = await odata.records(
        CUSTOMER_TABLE,
        select=[CUSTOMER_CODE_FIELD, *CUSTOMER_NAME_FIELDS],
        filter_expr=f"{CUSTOMER_CODE_FIELD} eq {_odata_literal(code)}",
        top=2,
        count=False,
    )
    matches: list[ResolvedCustomer] = []
    for row in result.get("rows") or []:
        if not isinstance(row, dict) or _text(row.get(CUSTOMER_CODE_FIELD)) != code:
            continue
        customer_id = _customer_id_from_odata_row(row)
        if not customer_id:
            continue
        name = next(
            (
                value
                for field in CUSTOMER_NAME_FIELDS
                if (value := _text(row.get(field)))
            ),
            "",
        )
        matches.append(
            ResolvedCustomer(
                customer_id=customer_id,
                code=code,
                name=name,
            )
        )
    if len(matches) != 1:
        return None
    return matches[0]


def _odata_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _customer_id_from_odata_row(row: dict[str, Any]) -> str:
    direct_value = _text(row.get(CUSTOMER_ID_FIELD))
    if direct_value:
        return direct_value
    odata_id = _text(row.get("@id"))
    match = re.search(r"\('((?:''|[^'])*)'\s*,", odata_id)
    return match.group(1).replace("''", "'") if match else ""


def _normalize_search_term(value: str) -> str:
    value = _text(value)
    return re.sub(r"[\r\n*#@!<>=…\\\"]+", " ", value).strip()[:80]


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
        customer_code = tokens[-1] if tokens else ""
        if not company or not customer_code or customer_code in seen:
            continue
        seen.add(customer_code)
        options.append(PartCreationOption(code=customer_code, label=company))
    return options


def _snake_case(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


def _text(value: Any) -> str:
    return str(value or "").strip()
