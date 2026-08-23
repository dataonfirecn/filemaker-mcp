from math import ceil
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.models.business_products import (
    BusinessProductDetailResponse,
    BusinessProductFieldGroup,
    BusinessProductFilters,
    BusinessProductPortalGroup,
    BusinessProductRow,
    BusinessProductsResponse,
)
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.dependencies import (
    get_audit_log_store,
    get_filemaker_client,
    get_operator_context,
)
from app.services.filemaker_client import FileMakerAPIError, FileMakerClient
from app.services.product_api import (
    PRODUCT_LAYOUT as PRODUCT_API_LAYOUT,
    PRODUCT_STOCK_FIELD,
    enrich_product_record,
)

router = APIRouter(prefix="/business-products", tags=["business-products"])

DEFAULT_PRODUCT_PAGE_SIZE = 50
MAX_PRODUCT_PAGE_SIZE = 200
MAX_PRODUCT_IMAGE_BYTES = 12 * 1024 * 1024
PRODUCT_IMAGE_MEDIA_TYPES = {
    "image/bmp",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}
SEARCH_FIELDS = [
    "product_sku",
    "系統產品編號",
    "product_name",
    "產品名稱_中文",
    "車款",
    "類別",
    "Client",
]


@router.get("", response_model=BusinessProductsResponse)
async def list_business_products(
    q: str = Query(default="", max_length=80),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(
        default=DEFAULT_PRODUCT_PAGE_SIZE,
        alias="pageSize",
        ge=1,
        le=MAX_PRODUCT_PAGE_SIZE,
    ),
    category: str = Query(default="", max_length=80),
    model: str = Query(default="", max_length=80),
    audit: str = Query(default="", max_length=80),
    client_name: str = Query(default="", alias="client", max_length=80),
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    operator: OperatorContext = Depends(get_operator_context),
) -> BusinessProductsResponse:
    normalized_query = q.strip()
    filters = BusinessProductFilters(
        category=category.strip(),
        model=model.strip(),
        audit=audit.strip(),
        client=client_name.strip(),
    )
    offset = ((page - 1) * page_size) + 1
    query = _build_query(normalized_query, filters)
    result = await filemaker.find_records(
        PRODUCT_API_LAYOUT,
        query=query,
        limit=page_size,
        offset=offset,
    )
    found_count = int(result["foundCount"] or 0)
    total_pages = max(1, ceil(found_count / page_size))
    rows = [_product_row(record) for record in result["data"]]
    await audit_log.record(
        operator=operator,
        action_type="READ_BUSINESS_PRODUCTS",
        status="success",
        target_layout=PRODUCT_API_LAYOUT,
        product_sku=normalized_query or None,
        request_payload={
            "q": normalized_query,
            "page": page,
            "pageSize": page_size,
            "filters": filters.model_dump(),
        },
        response_payload={
            "foundCount": found_count,
            "returnedCount": result["returnedCount"],
            "totalPages": total_pages,
        },
    )
    return BusinessProductsResponse(
        layout=PRODUCT_API_LAYOUT,
        rows=rows,
        foundCount=found_count,
        returnedCount=result["returnedCount"],
        page=page,
        pageSize=page_size,
        totalPages=total_pages,
        query=normalized_query,
        filters=filters,
    )


@router.get("/{record_id}", response_model=BusinessProductDetailResponse)
async def get_business_product(
    record_id: str,
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    operator: OperatorContext = Depends(get_operator_context),
) -> BusinessProductDetailResponse:
    try:
        record = await _resolve_product_detail_record(filemaker, record_id)
    except FileMakerAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": "FileMaker 产品详情读取失败，请稍后重试。"},
        ) from exc
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Product record not found"},
        )
    product = _product_row(await enrich_product_record(filemaker, record))
    await audit_log.record(
        operator=operator,
        action_type="READ_BUSINESS_PRODUCT_DETAIL",
        status="success",
        target_layout=PRODUCT_API_LAYOUT,
        product_sku=product.product_sku,
        request_payload={"recordId": record_id},
        response_payload={
            "recordId": product.record_id,
            "productSku": product.product_sku,
        },
    )
    return BusinessProductDetailResponse(
        layout=PRODUCT_API_LAYOUT,
        product=product,
    )


@router.get("/{record_id}/image")
async def get_business_product_image(
    record_id: str,
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    _: OperatorContext = Depends(get_operator_context),
) -> Response:
    try:
        record = await _resolve_product_detail_record(filemaker, record_id)
    except FileMakerAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": "FileMaker 产品图片读取失败，请稍后重试。"},
        ) from exc
    fields = record.get("fieldData", {}) if isinstance(record, dict) else {}
    image_url = str(fields.get("檔案 1 | 容器") or "").strip()
    if not image_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "产品没有可显示的主图。"},
        )

    content, content_type = await _download_product_image(filemaker, image_url)
    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _resolve_product_detail_record(
    filemaker: FileMakerClient,
    identifier: str,
) -> dict[str, Any] | None:
    """Resolve either a Data API record id or an OData-backed product code.

    Exact natural-language lookups can be served by OData. Those rows have a
    stable product code but no FileMaker Data API record id, so the detail URL
    carries the product code. Resolve it against the live product layout before
    loading the complete field and portal payload.
    """
    normalized = identifier.strip()
    if not normalized:
        return None

    if normalized.isdigit():
        try:
            record = _first_record(
                await filemaker.get_record(PRODUCT_API_LAYOUT, normalized)
            )
            if record:
                return record
        except FileMakerAPIError:
            # Numeric product codes are valid, and stale record ids should
            # still get an exact product-code lookup before returning 404.
            pass

    result = await filemaker.find_records(
        PRODUCT_API_LAYOUT,
        query=[
            {"product_sku": f"=={normalized}"},
            {"系統產品編號": f"=={normalized}"},
        ],
        limit=2,
    )
    records = result.get("data") if isinstance(result, dict) else []
    return (
        records[0]
        if isinstance(records, list) and records and isinstance(records[0], dict)
        else None
    )


async def _download_product_image(
    filemaker: FileMakerClient,
    image_url: str,
) -> tuple[bytes, str]:
    source_host = urlparse(filemaker.settings.filemaker_host).hostname
    target = urlparse(image_url)
    if (
        not source_host
        or target.scheme != "https"
        or target.hostname != source_host
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "产品图片地址无效。"},
        )

    token = await filemaker.get_token()
    try:
        async with httpx.AsyncClient(
            timeout=filemaker.settings.filemaker_timeout_seconds,
            verify=filemaker.settings.filemaker_ssl_verify,
            follow_redirects=True,
        ) as image_client:
            response = await image_client.get(
                image_url,
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": "产品图片暂时无法读取。"},
        ) from exc

    if not response.is_success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": "产品图片暂时无法读取。"},
        )
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if (
        content_type not in PRODUCT_IMAGE_MEDIA_TYPES
        or len(response.content) > MAX_PRODUCT_IMAGE_BYTES
    ):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"message": "产品图片格式或大小不受支持。"},
        )
    return response.content, content_type


def _build_query(
    q: str,
    filters: BusinessProductFilters,
) -> dict[str, Any] | list[dict[str, Any]] | None:
    filter_criteria = _filter_criteria(filters)
    if not q:
        return filter_criteria or None

    value = _contains(q)
    exact_sku = f"=={q}"
    criteria: list[dict[str, Any]] = []
    for field in SEARCH_FIELDS:
        item = dict(filter_criteria)
        item[field] = exact_sku if field in {"product_sku", "系統產品編號"} else value
        criteria.append(item)
    return criteria


def _filter_criteria(filters: BusinessProductFilters) -> dict[str, str]:
    criteria: dict[str, str] = {}
    if filters.category:
        criteria["類別"] = _contains(filters.category)
    if filters.model:
        criteria["車款"] = _contains(filters.model)
    if filters.audit:
        criteria["審核"] = _contains(filters.audit)
    if filters.client:
        criteria["Client"] = _contains(filters.client)
    return criteria


def _contains(value: str) -> str:
    return f"*{value.strip()}*"


def _first_record(data: Any) -> dict[str, Any] | None:
    if isinstance(data, list):
        return data[0] if data else None
    if isinstance(data, dict):
        return data
    return None


def _product_row(record: dict[str, Any]) -> BusinessProductRow:
    fields = record.get("fieldData", {})
    main_fields = _main_fields(fields)
    related_field_groups = _related_field_groups(fields)
    portals = _portal_groups(record.get("portalData", {}))
    return BusinessProductRow(
        recordId=str(record.get("recordId") or ""),
        modId=str(record.get("modId") or ""),
        productSku=_text(fields.get("product_sku")),
        systemProductSku=_text(fields.get("系統產品編號")),
        productName=_text(fields.get("product_name")),
        productNameCn=_text(fields.get("產品名稱_中文")),
        imageUrl=_text(fields.get("檔案 1 | 容器")),
        selectedFileUrl=_text(fields.get("選取的文件 | 容器")),
        qrCodeUrl=_text(fields.get("qrcode")),
        modelName=_text(fields.get("車款")),
        scale=_text(fields.get("車子比例")),
        category=_text(fields.get("類別")),
        auditStatus=_text(fields.get("審核")),
        imageStatus=_text(fields.get("有圖沒圖")),
        stock=fields.get(PRODUCT_STOCK_FIELD),
        stockUsd=fields.get("Stock_USD"),
        prepaidStockUsd=fields.get("PrePaid_stock_USD"),
        bomCount=fields.get("BOM計數"),
        orderQty=fields.get("下單數量"),
        soldTotal=fields.get("產品庫存::出庫數量總合"),
        bomDate=_text(fields.get("產品 BOM::日期")),
        vendor=_text(fields.get("產品 BOM::廠商")),
        client=_text(fields.get("Client")),
        customer=_text(fields.get("客戶_Privilege::客戶公司簡稱")),
        privilege=_text(fields.get("privilege")),
        category1=_text(fields.get("Category_Product_1::title")),
        category2=_text(fields.get("Category_Product_2::title")),
        category3=_text(fields.get("Category_Product_3::title")),
        labelSpec=_text(fields.get("標籤規格")),
        packagingHours=fields.get("包裝總工時"),
        packageCheck=_text(fields.get("包裝檢查")),
        dmsStatus=_text(fields.get("轉產品資料_DMS_Product")),
        raw=fields,
        mainFields=main_fields,
        relatedFieldGroups=related_field_groups,
        portals=portals,
    )


def _main_fields(fields: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in fields.items()
        if "::" not in key and _is_visible_value(value)
    }


def _related_field_groups(fields: dict[str, Any]) -> list[BusinessProductFieldGroup]:
    grouped: dict[str, dict[str, Any]] = {}
    for key, value in fields.items():
        if "::" not in key or not _is_visible_value(value):
            continue
        table, _, field = key.partition("::")
        grouped.setdefault(table, {})[field or key] = value
    return [
        BusinessProductFieldGroup(name=name, fields=items)
        for name, items in grouped.items()
        if items
    ]


def _portal_groups(portal_data: Any) -> list[BusinessProductPortalGroup]:
    if not isinstance(portal_data, dict):
        return []

    groups: list[BusinessProductPortalGroup] = []
    for name, rows in portal_data.items():
        if not isinstance(rows, list) or not rows:
            continue
        cleaned_rows = [_portal_row(row) for row in rows if isinstance(row, dict)]
        cleaned_rows = [row for row in cleaned_rows if row]
        if cleaned_rows:
            groups.append(BusinessProductPortalGroup(name=str(name), rows=cleaned_rows))
    return groups


def _portal_row(row: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in row.items():
        if key in {"recordId", "modId"} or _is_visible_value(value):
            cleaned[key] = value
    return cleaned


def _is_visible_value(value: Any) -> bool:
    return value not in (None, "", [])


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
