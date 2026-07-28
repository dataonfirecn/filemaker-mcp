from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.services.filemaker_client import FileMakerClient
from app.services.part_asset_upload_store import (
    PartAssetUploadRecord,
    PartAssetUploadStore,
)


PART_ASSET_LAYOUT = "PartAssets"
PART_IMAGE_TYPES = ("part_image",)
READY_STATUS = "READY"


class PartAssetError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


async def require_bindable_part_asset_upload(
    *,
    settings: Settings,
    store: PartAssetUploadStore,
    upload_id: str,
    operator_account: str,
) -> PartAssetUploadRecord:
    if not settings.filemaker_part_assets_enabled:
        raise PartAssetError(
            "零件资产写入尚未启用。",
            code="PART_ASSETS_DISABLED",
            status_code=403,
        )
    record = await store.get(upload_id)
    if not record or record.operator_account != operator_account:
        raise PartAssetError(
            "图片上传记录不存在。",
            code="PART_ASSET_UPLOAD_NOT_FOUND",
            status_code=404,
        )
    if record.status != "UPLOADED":
        raise PartAssetError(
            f"图片当前状态不能绑定：{record.status}",
            code="PART_ASSET_NOT_UPLOADED",
            status_code=409,
        )
    return record


async def bind_part_asset_upload(
    *,
    filemaker: FileMakerClient,
    settings: Settings,
    store: PartAssetUploadStore,
    upload_id: str,
    operator_account: str,
    part_id: str,
    part_number: str,
    part_record_id: str,
) -> PartAssetUploadRecord:
    if not settings.filemaker_part_assets_enabled:
        raise PartAssetError(
            "零件资产写入尚未启用。",
            code="PART_ASSETS_DISABLED",
            status_code=403,
        )
    record = await store.get(upload_id)
    if not record or record.operator_account != operator_account:
        raise PartAssetError(
            "图片上传记录不存在。",
            code="PART_ASSET_UPLOAD_NOT_FOUND",
            status_code=404,
        )
    if record.status == "BOUND":
        if record.part_id != part_id:
            raise PartAssetError(
                "图片已经绑定到其他零件。",
                code="PART_ASSET_ALREADY_BOUND",
                status_code=409,
            )
        return record
    if record.status != "UPLOADED":
        raise PartAssetError(
            f"图片当前状态不能绑定：{record.status}",
            code="PART_ASSET_NOT_UPLOADED",
            status_code=409,
        )

    asset_id = upload_id
    payload = {
        "id_asset": asset_id,
        "part_id_fk": part_id.strip(),
        "part_number_snapshot": part_number.strip(),
        "asset_type": record.asset_type,
        "asset_role": record.asset_role,
        "visibility": record.visibility,
        "original_filename": record.original_filename,
        "mime_type": record.mime_type,
        "storage_provider": "cos",
        "cos_bucket": settings.cos_bucket,
        "cos_region": settings.cos_region,
        "object_key": record.object_key,
        "etag": record.etag or "",
        "sha256": record.sha256,
        "file_size": record.file_size,
        "status": READY_STATUS,
        "source_kind": (
            "user" if record.source in {"file_picker", "camera"} else record.source
        ),
        "created_by": operator_account,
        "updated_by": operator_account,
        "sort_order": 1,
        "is_primary": 1 if record.asset_role == "primary" else 0,
    }
    existing_result = await filemaker.find_records(
        settings.filemaker_part_asset_layout,
        query={"id_asset": f"=={asset_id}"},
        limit=1,
    )
    existing_records = existing_result.get("data") or []
    if existing_records:
        existing = existing_records[0]
        existing_fields = asset_fields(existing)
        if (
            str(existing_fields.get("part_id_fk") or "").strip() != part_id.strip()
            or str(existing_fields.get("object_key") or "").strip() != record.object_key
        ):
            raise PartAssetError(
                "资产 ID 已被其他零件或文件使用。",
                code="PART_ASSET_ID_CONFLICT",
                status_code=409,
            )
        asset_record_id = str(existing.get("recordId") or "")
    else:
        created = await filemaker.create_record(
            settings.filemaker_part_asset_layout,
            payload,
        )
        asset_record_id = str(created.get("recordId") or "")
    if not asset_record_id:
        raise PartAssetError(
            "FileMaker 未返回零件资产记录 ID。",
            code="PART_ASSET_CREATE_INVALID",
            status_code=502,
        )
    updated = await store.mark_bound(
        upload_id,
        part_id=part_id,
        part_number=part_number,
        part_record_id=part_record_id,
        asset_record_id=asset_record_id,
    )
    if not updated:
        raise PartAssetError(
            "图片绑定状态保存失败。",
            code="PART_ASSET_BIND_STATE_FAILED",
            status_code=500,
        )
    return updated


async def find_primary_part_asset(
    filemaker: FileMakerClient,
    settings: Settings,
    *,
    part_id: str,
    customer_visible_only: bool = False,
) -> dict[str, Any] | None:
    if not settings.filemaker_part_assets_enabled or not part_id.strip():
        return None
    base_query: dict[str, str] = {
        "part_id_fk": f"=={part_id.strip()}",
        "status": f"=={READY_STATUS}",
    }
    if customer_visible_only:
        base_query["visibility"] = "==customer"
    for asset_type in ("part_image", "drawing_2d"):
        result = await filemaker.find_records(
            settings.filemaker_part_asset_layout,
            query={**base_query, "asset_type": f"=={asset_type}"},
            limit=20,
            sort=[
                {"fieldName": "is_primary", "sortOrder": "descend"},
                {"fieldName": "sort_order", "sortOrder": "ascend"},
            ],
        )
        records = result.get("data") or []
        if records:
            return records[0]
    return None


def asset_fields(record: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(record, dict):
        return {}
    fields = record.get("fieldData")
    return fields if isinstance(fields, dict) else {}
