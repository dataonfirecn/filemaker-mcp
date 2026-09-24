import asyncio
from collections import OrderedDict
from io import BytesIO
from math import ceil
from typing import Any, Literal
from urllib.parse import urlencode, urlparse

import httpx
from fastapi import Request, APIRouter, Depends, HTTPException, Query, Response, status
from PIL import Image

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
from app.services.image_tickets import (
    TICKET_TTL_SECONDS,
    sign_thumbnail_ticket,
    verify_thumbnail_ticket,
)
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
PRODUCT_IMAGE_FIELD = "image_main"
THUMBNAIL_MAX_EDGE = 160
THUMBNAIL_MEDIA_TYPE = "image/webp"
THUMBNAIL_QUALITY = 72
# Browsers may cache for the ticket's lifetime; a new asset version changes the
# URL, so a stale thumbnail can never outlive the image it was rendered from.
THUMBNAIL_CACHE_CONTROL = f"private, max-age={TICKET_TTL_SECONDS}, immutable"
THUMBNAIL_CACHE_ENTRIES = 512
_thumbnail_cache: "OrderedDict[tuple[str, str], bytes]" = OrderedDict()

# 「最近创建」排序键：优先取 FileMaker 建立日期（文本，兼容 MM/DD/YYYY HH:MM:SS 与 ISO 两种写法，
# 形状不符的一律当作没有；按上海时间理解）；没有时，仅对 Web 端新建的产品取第一版保存时间。导入产品的第一版是
# 导入时间而不是真实建立时间，所以不能拿来当兜底。没有任何建立时间的产品排在最后。
RECENT_CREATED_ORDER = r"""
ORDER BY COALESCE(
  CASE
    WHEN fields->>'created_at' ~ '^(0?[1-9]|1[0-2])/(0?[1-9]|[12][0-9]|3[01])/[0-9]{4} [0-9]{1,2}:[0-9]{2}:[0-9]{2}$'
      THEN to_timestamp(fields->>'created_at', 'MM/DD/YYYY HH24:MI:SS')::timestamp AT TIME ZONE 'Asia/Shanghai'
    WHEN fields->>'created_at' ~ '^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])[T ][0-9]{2}:[0-9]{2}:[0-9]{2}'
      THEN to_timestamp(substr(replace(fields->>'created_at', 'T', ' '), 1, 19), 'YYYY-MM-DD HH24:MI:SS')::timestamp AT TIME ZONE 'Asia/Shanghai'
  END,
  (SELECT r.created_at FROM pm_revision r
    WHERE r.source = pm_product.source AND r.product_id = pm_product.id
      AND r.version = 1 AND r.actor->>'origin' = 'web')
) DESC NULLS LAST, id"""

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
    sort: Literal["default", "recent"] = "default",
    category: str = Query(default="", max_length=80),
    model: str = Query(default="", max_length=80),
    audit: str = Query(default="", max_length=80),
    client_name: str = Query(default="", alias="client", max_length=80),
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    operator: OperatorContext = Depends(get_operator_context),
    request: Request = None,
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
    store = _web_product_store(request)
    if store:
        from app.services.product_master.store import unpack
        filter_data = {key:value for key,value in {"類別":category.strip(),"車款":model.strip(),"審核":audit.strip(),"Client":client_name.strip()}.items() if value}
        import json
        predicate = "source=$1 AND ($2='' OR strpos(lower(concat_ws(' ',fields->>'product_sku',fields->>'product_name',fields->>'產品名稱_中文')),lower($2))>0) AND fields @> $3::jsonb"
        count = await store.pool.fetchval('SELECT count(*) FROM pm_product WHERE '+predicate,store.source,normalized_query,json.dumps(filter_data))
        snapshots = [unpack(r) for r in await store.pool.fetch('SELECT * FROM pm_product WHERE '+predicate+' '+(RECENT_CREATED_ORDER if sort=='recent' else 'ORDER BY id')+' LIMIT $4 OFFSET $5',store.source,normalized_query,json.dumps(filter_data),page_size,offset-1)]
        records = [_master_record(await store.hydrate(r,store.pool), request, operator) for r in snapshots]
        result = {"data":records,"foundCount":count,"returnedCount":len(records)}
    else:
        recent_sort = [{"fieldName": "created_at", "sortOrder": "descend"}] if sort == "recent" else None
        try:
            result = await filemaker.find_records(
                PRODUCT_API_LAYOUT, query=query, limit=page_size, offset=offset, sort=recent_sort,
            )
        except FileMakerAPIError:
            if not recent_sort:
                raise
            # 布局没有暴露建立日期字段时，退回默认顺序，不让列表整体失败。
            result = await filemaker.find_records(
                PRODUCT_API_LAYOUT, query=query, limit=page_size, offset=offset,
            )
    found_count = int(result["foundCount"] or 0)
    total_pages = max(1, ceil(found_count / page_size))
    thumb_secret = _thumbnail_secret(request)
    rows = [
        _product_row(record, thumb_secret=thumb_secret) for record in result["data"]
    ]
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
            "sort": sort,
            "filters": filters.model_dump(),
        },
        response_payload={
            "foundCount": found_count,
            "returnedCount": result["returnedCount"],
            "totalPages": total_pages,
        },
    )
    return BusinessProductsResponse(
        layout="Web 产品库" if store else PRODUCT_API_LAYOUT,
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
    request: Request = None,
) -> BusinessProductDetailResponse:
    store = _web_product_store(request)
    if store:
        snapshot = await store.get(record_id)
        if not snapshot: raise HTTPException(404, "产品不存在")
        return BusinessProductDetailResponse(layout="Web products",product=_product_row(_master_record(snapshot,request,operator),thumb_secret=_thumbnail_secret(request)))
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
    product = _product_row(
        await enrich_product_record(filemaker, record),
        thumb_secret=_thumbnail_secret(request),
    )
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
    request: Request = None,
) -> Response:
    store = _web_product_store(request)
    if store:
        snapshot = await store.get(record_id)
        if not snapshot: raise HTTPException(404, "产品不存在")
        asset = next((a for a in snapshot['assets'] if a['field'] == 'image_main' and a['mimeType'].startswith('image/')), None)
        if not asset: raise HTTPException(404, "产品没有图片")
        from app.api.product_master import download
        from uuid import UUID
        return await download(UUID(str(snapshot['id'])),UUID(asset['id']),request,{'access':_.permissions or {}})
    try:
        record = await _resolve_product_detail_record(filemaker, record_id)
    except FileMakerAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": "FileMaker 产品图片读取失败，请稍后重试。"},
        ) from exc
    fields = record.get("fieldData", {}) if isinstance(record, dict) else {}
    image_url = str(fields.get("image_main") or "").strip()
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


@router.get("/{record_id}/thumbnail")
async def get_business_product_thumbnail(
    record_id: str,
    v: str = Query(default="", max_length=80),
    exp: int = Query(default=0),
    sig: str = Query(default="", max_length=64),
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    request: Request = None,
) -> Response:
    """Serve a small WebP thumbnail against a signed ticket instead of a session.

    The ticket was minted for a caller who had already passed the product
    visibility check, so this route performs no further permission lookup -- it
    must therefore never serve anything but the downscaled image.
    """
    secret = _thumbnail_secret(request)
    if not verify_thumbnail_ticket(record_id, v, exp, sig, secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "缩略图链接无效或已过期。"},
        )

    cache_key = (record_id, v)
    cached = _thumbnail_cache.get(cache_key)
    if cached is not None:
        _thumbnail_cache.move_to_end(cache_key)
        return _thumbnail_response(cached, record_id, v)

    content, _content_type = await _load_product_image_bytes(record_id, filemaker, request)
    thumbnail = await asyncio.to_thread(_downscale_image, content)
    _thumbnail_cache[cache_key] = thumbnail
    _thumbnail_cache.move_to_end(cache_key)
    while len(_thumbnail_cache) > THUMBNAIL_CACHE_ENTRIES:
        _thumbnail_cache.popitem(last=False)
    return _thumbnail_response(thumbnail, record_id, v)


def _thumbnail_response(content: bytes, record_id: str, version: str) -> Response:
    return Response(
        content=content,
        media_type=THUMBNAIL_MEDIA_TYPE,
        headers={
            "Cache-Control": THUMBNAIL_CACHE_CONTROL,
            "ETag": f'"{record_id}-{version}-thumb"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )


def _downscale_image(content: bytes) -> bytes:
    with Image.open(BytesIO(content)) as image:
        image.load()
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        image.thumbnail((THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE), Image.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, format="WEBP", quality=THUMBNAIL_QUALITY, method=4)
    return buffer.getvalue()


async def _load_product_image_bytes(
    record_id: str,
    filemaker: FileMakerClient,
    request: Request,
) -> tuple[bytes, str]:
    """Return the full-resolution main image bytes for a product."""
    store = _web_product_store(request)
    if store:
        snapshot = await store.get(record_id)
        if not snapshot:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "产品不存在"},
            )
        asset = next(
            (
                item
                for item in snapshot["assets"]
                if item["field"] == PRODUCT_IMAGE_FIELD
                and str(item["mimeType"]).startswith("image/")
            ),
            None,
        )
        if not asset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "产品没有图片"},
            )
        storage = request.app.state.cos_storage_service
        content = await asyncio.to_thread(
            storage.get_object_bytes,
            asset["objectKey"],
            max_bytes=MAX_PRODUCT_IMAGE_BYTES,
        )
        return content, str(asset["mimeType"])

    try:
        record = await _resolve_product_detail_record(filemaker, record_id)
    except FileMakerAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": "FileMaker 产品图片读取失败，请稍后重试。"},
        ) from exc
    fields = record.get("fieldData", {}) if isinstance(record, dict) else {}
    image_url = str(fields.get(PRODUCT_IMAGE_FIELD) or "").strip()
    if not image_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "产品没有可显示的主图。"},
        )
    return await _download_product_image(filemaker, image_url)


def _thumbnail_secret(request: Request | None) -> str:
    state = getattr(getattr(request, "app", None), "state", None)
    settings = getattr(state, "settings", None)
    return str(getattr(settings, "webviewer_context_secret", "") or "")


def _thumbnail_url(
    record_id: str,
    version: str,
    *,
    has_image: bool,
    secret: str,
) -> str:
    """Mint a signed thumbnail URL, or "" when there is nothing to show."""
    if not has_image or not record_id or not secret:
        return ""
    expires_at, signature = sign_thumbnail_ticket(record_id, version, secret)
    query = urlencode({"v": version, "exp": expires_at, "sig": signature})
    return f"/api/business-products/{record_id}/thumbnail?{query}"


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


def _product_row(
    record: dict[str, Any],
    *,
    thumb_secret: str = "",
) -> BusinessProductRow:
    fields = record.get("fieldData", {})
    main_fields = _main_fields(fields)
    related_field_groups = _related_field_groups(fields)
    portals = _portal_groups(record.get("portalData", {}))
    record_id = str(record.get("recordId") or "")
    version = str(record.get("modId") or "")
    return BusinessProductRow(
        recordId=record_id,
        modId=version,
        productSku=_text(fields.get("product_sku")),
        systemProductSku=_text(fields.get("系統產品編號")),
        productName=_text(fields.get("product_name")),
        productNameCn=_text(fields.get("產品名稱_中文")),
        imageUrl=_text(fields.get(PRODUCT_IMAGE_FIELD)),
        thumbnailUrl=_thumbnail_url(
            record_id,
            version,
            has_image=bool(_text(fields.get(PRODUCT_IMAGE_FIELD)).strip()),
            secret=thumb_secret,
        ),
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
        createdAt=_text(fields.get("created_at")),
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


def _master_record(snapshot, request, operator):
    schema = request.app.state.product_master_schema
    fields = schema.filter_fields(snapshot['fields'], operator.permissions or {})
    for asset in snapshot['assets']:
        if asset['field'] in {f['name'] for f in schema.visible(operator.permissions or {})}:
            fields[asset['field']] = f"/api/product-master/products/{snapshot['id']}/assets/{asset['id']}"
    return {'recordId':str(snapshot['id']),'modId':str(snapshot['version']),'fieldData':fields}


def _web_product_store(request):
    if request is None:
        return None
    state=request.app.state
    store=getattr(state, 'product_master_store', None)
    if getattr(getattr(state, 'settings', None), 'product_master_web_only', False):
        store=store or getattr(state, 'product_master_preview_store', None)
        if not store:
            raise HTTPException(503, 'Web 产品测试库未就绪')
    return store
