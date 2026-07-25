import uuid
from datetime import datetime, timezone
from math import ceil
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models.bom_changes import (
    BomCalculationLine,
    BomCalculationPreviewRequest,
    BomCalculationPreviewResponse,
    BomDocumentResponse,
    ConfirmBomDocumentRequest,
    KitIssueField,
    KitIssueRecordsResponse,
    KitIssueRow,
    PartInfo,
    PartSearchResponse,
    ProductBomResponse,
    ProductInfo,
)
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.bom_document_store import BomDocumentStore
from app.services.dependencies import (
    get_audit_log_store,
    get_bom_document_store,
    get_filemaker_client,
    get_operator_context,
)
from app.services.filemaker_client import FileMakerClient

router = APIRouter(tags=["bom-documents"])

PRODUCT_LAYOUT = "產品清單_業務"
PRODUCT_BOM_LAYOUT = "@product_bom"
PART_LAYOUT = "零件清單"
KIT_ISSUE_LAYOUT = "零件包 發料分类"
KIT_ISSUE_PAGE_SIZE = 100
KIT_ISSUE_ORDER_FIELD = "BOM計算單::訂單編號"

KIT_ISSUE_FIELDS = [
    KitIssueField(source="product_qty", label="产品数量", role="header", result="number"),
    KitIssueField(source="產品_BOM::product_sku", label="产品编号", role="header", result="text"),
    KitIssueField(source="BOM計算單::訂單日期", label="订单日期", role="header", result="text"),
    KitIssueField(source="BOM計算單::訂單編號", label="订单号", role="header", result="text"),
    KitIssueField(source="BOM計算單::客戶", label="客户", role="header", result="text"),
    KitIssueField(source="產品_BOM::產品名稱_中文", label="产品中文名", role="header", result="text"),
    KitIssueField(source="發貨數量", label="发货数量", role="quantity", result="number"),
    KitIssueField(source="實發数量", label="实发数量", role="quantity", result="number"),
    KitIssueField(source="出貨單::訂單概要中文", label="订单概要", role="header", result="text"),
    KitIssueField(
        source="BOM計算單資料_NONREPEAT::收料情況_生產部",
        label="生产部收料状态",
        role="status",
        result="text",
    ),
    KitIssueField(source="id_零件", label="零件编号", role="part", result="text"),
    KitIssueField(source="零件_BOM::part_name", label="零件名称", role="part", result="text"),
    KitIssueField(source="額定數量", label="额定数量", role="quantity", result="number"),
    KitIssueField(source="零件_BOM::位置", label="位置1", role="location", result="text"),
    KitIssueField(source="零件_BOM::current_stock", label="库存", role="quantity", result="number"),
    KitIssueField(source="數量", label="需求数量", role="quantity", result="number"),
    KitIssueField(source="零件_BOM::倉庫分工", label="发料分类", role="status", result="text"),
    KitIssueField(source="零件_BOM::位置2", label="位置2", role="location", result="text"),
    KitIssueField(source="INDEX::BATCHPRICE", label="批次价格", role="finance", result="number"),
    KitIssueField(source="產品 BOM_BOM::倉庫分工", label="BOM 发料分类", role="status", result="text"),
    KitIssueField(source="BOM計算單::ID_出庫單", label="出库单", role="header", result="text"),
    KitIssueField(source="發料時間", label="发料时间", role="status", result="timeStamp"),
    KitIssueField(
        source="BOM計算單資料_NONREPEAT::g退料數量",
        label="退料数量",
        role="quantity",
        result="number",
    ),
]


@router.get("/products/{product_sku}/bom-view", response_model=ProductBomResponse)
async def get_product_bom_view(
    product_sku: str,
    client: FileMakerClient = Depends(get_filemaker_client),
    operator: OperatorContext = Depends(get_operator_context),
) -> ProductBomResponse:
    del operator
    product, bom_result = await _load_product_bom(client, product_sku)
    rows = [_product_bom_row(record) for record in bom_result["data"]]
    return ProductBomResponse(
        product=product,
        rows=rows,
        foundCount=bom_result["foundCount"],
        returnedCount=bom_result["returnedCount"],
    )


@router.post("/bom-calculations/preview", response_model=BomCalculationPreviewResponse)
async def preview_bom_calculation(
    body: BomCalculationPreviewRequest,
    client: FileMakerClient = Depends(get_filemaker_client),
    operator: OperatorContext = Depends(get_operator_context),
) -> BomCalculationPreviewResponse:
    # Intentionally no database write here. The user can edit the preview before confirming.
    del operator
    product, bom_result = await _load_product_bom(client, body.product_sku)
    lines = [
        _calculation_line(record, index=index + 1, generate_qty=body.generate_qty)
        for index, record in enumerate(bom_result["data"])
    ]
    return BomCalculationPreviewResponse(
        calculationId=str(uuid.uuid4()),
        createdAt=datetime.now(tz=timezone.utc).isoformat(),
        status="待确认",
        product=product,
        generateQty=body.generate_qty,
        lines=lines,
    )


@router.get("/parts/search", response_model=PartSearchResponse)
async def search_parts(
    q: str = Query(default="", max_length=80),
    limit: int = Query(default=30, ge=1, le=100),
    client: FileMakerClient = Depends(get_filemaker_client),
    operator: OperatorContext = Depends(get_operator_context),
) -> PartSearchResponse:
    del operator
    term = q.strip()
    query: list[dict[str, str]] | None = None
    if term:
        query = [
            {"part_number": f"*{term}*"},
            {"part_name": f"*{term}*"},
        ]
    result = await client.find_records(
        PART_LAYOUT,
        query=query,
        limit=limit,
        offset=1,
    )
    return PartSearchResponse(
        rows=[_part_info_from_record(record) for record in result["data"]],
        foundCount=result["foundCount"],
        returnedCount=result["returnedCount"],
    )


@router.get("/parts/{part_no}", response_model=PartInfo)
async def get_part_info(
    part_no: str,
    client: FileMakerClient = Depends(get_filemaker_client),
    operator: OperatorContext = Depends(get_operator_context),
) -> PartInfo:
    del operator
    result = await client.find_records(
        PART_LAYOUT,
        query={"part_number": f"=={part_no}"},
        limit=1,
        offset=1,
    )
    if not result["data"]:
        return PartInfo(partNo=part_no)
    return _part_info_from_record(result["data"][0], fallback_part_no=part_no)


@router.get("/kit-issue-records", response_model=KitIssueRecordsResponse)
async def get_kit_issue_records(
    page: int = Query(default=1, ge=1),
    order_no: str = Query(default="", alias="orderNo", max_length=80),
    client: FileMakerClient = Depends(get_filemaker_client),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    operator: OperatorContext = Depends(get_operator_context),
) -> KitIssueRecordsResponse:
    normalized_order_no = order_no.strip()
    query = (
        {KIT_ISSUE_ORDER_FIELD: f"=={normalized_order_no}"}
        if normalized_order_no
        else None
    )
    offset = ((page - 1) * KIT_ISSUE_PAGE_SIZE) + 1
    result = await client.find_records(
        KIT_ISSUE_LAYOUT,
        query=query,
        limit=KIT_ISSUE_PAGE_SIZE,
        offset=offset,
    )
    found_count = int(result["foundCount"] or 0)
    total_pages = max(1, ceil(found_count / KIT_ISSUE_PAGE_SIZE))
    rows = [
        _kit_issue_row(record, line_no=offset + index)
        for index, record in enumerate(result["data"])
    ]
    await audit_log.record(
        operator=operator,
        action_type="READ_KIT_ISSUE_RECORDS",
        status="success",
        target_layout=KIT_ISSUE_LAYOUT,
        order_id=normalized_order_no or None,
        request_payload={
            "page": page,
            "pageSize": KIT_ISSUE_PAGE_SIZE,
            "query": query or {},
        },
        response_payload={
            "foundCount": found_count,
            "returnedCount": result["returnedCount"],
            "totalPages": total_pages,
        },
    )
    return KitIssueRecordsResponse(
        layout=KIT_ISSUE_LAYOUT,
        rows=rows,
        foundCount=found_count,
        returnedCount=result["returnedCount"],
        page=page,
        pageSize=KIT_ISSUE_PAGE_SIZE,
        totalPages=total_pages,
        orderNo=normalized_order_no,
        fields=KIT_ISSUE_FIELDS,
    )


def _part_info_from_record(record: dict[str, Any], fallback_part_no: str = "") -> PartInfo:
    fields = record.get("fieldData", {})
    return PartInfo(
        partNo=str(fields.get("part_number") or fallback_part_no),
        partName=str(fields.get("part_name") or ""),
        stockSnapshot=_optional_number(fields.get("current_stock")),
        warehouse=str(fields.get("倉庫分工") or ""),
        position1=str(fields.get("位置") or ""),
        position2=str(fields.get("位置2") or ""),
        raw=fields,
    )


def _kit_issue_row(record: dict[str, Any], *, line_no: int) -> KitIssueRow:
    fields = record.get("fieldData", {})
    warehouse_division = _text(fields.get("零件_BOM::倉庫分工"))
    product_warehouse_division = _text(fields.get("產品 BOM_BOM::倉庫分工"))
    return KitIssueRow(
        recordId=str(record.get("recordId") or ""),
        modId=str(record.get("modId") or ""),
        lineNo=line_no,
        orderNo=_text(fields.get(KIT_ISSUE_ORDER_FIELD)),
        orderDate=_text(fields.get("BOM計算單::訂單日期")),
        customer=_text(fields.get("BOM計算單::客戶")),
        productSku=_text(fields.get("產品_BOM::product_sku")),
        productNameCn=_text(fields.get("產品_BOM::產品名稱_中文")),
        productQty=fields.get("product_qty"),
        partNo=_text(fields.get("id_零件")),
        partName=_text(fields.get("零件_BOM::part_name")),
        warehouseDivision=warehouse_division or product_warehouse_division,
        productWarehouseDivision=product_warehouse_division,
        position1=_text(fields.get("零件_BOM::位置")),
        position2=_text(fields.get("零件_BOM::位置2")),
        ratedQty=fields.get("額定數量"),
        stockQty=fields.get("零件_BOM::current_stock"),
        quantity=fields.get("數量"),
        shippingQty=fields.get("發貨數量"),
        actualQty=fields.get("實發数量"),
        orderSummaryCn=_text(fields.get("出貨單::訂單概要中文")),
        productionReceiptStatus=_text(fields.get("BOM計算單資料_NONREPEAT::收料情況_生產部")),
        outboundId=_text(fields.get("BOM計算單::ID_出庫單")),
        issueTime=_text(fields.get("發料時間")),
        batchPrice=fields.get("INDEX::BATCHPRICE"),
        returnQty=fields.get("BOM計算單資料_NONREPEAT::g退料數量"),
        raw=fields,
    )


@router.post("/bom-documents/confirm", response_model=BomDocumentResponse)
async def confirm_bom_document(
    body: ConfirmBomDocumentRequest,
    store: BomDocumentStore = Depends(get_bom_document_store),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    operator: OperatorContext = Depends(get_operator_context),
) -> BomDocumentResponse:
    document = await store.confirm_document(
        document_id=body.calculation_id,
        product=body.product.model_dump(by_alias=True),
        generate_qty=body.generate_qty,
        lines=[line.model_dump(by_alias=True) for line in body.lines],
        operator=operator,
    )
    await audit_log.record(
        operator=operator,
        action_type="CONFIRM_BOM_DOCUMENT",
        status="success",
        product_sku=body.product.product_sku,
        bom_calc_id=document["id"],
        request_payload={
            "calculationId": body.calculation_id,
            "generateQty": body.generate_qty,
            "lineCount": len(body.lines),
        },
        response_payload={
            "documentId": document["id"],
            "documentNo": document["documentNo"],
            "status": document["status"],
        },
    )
    return BomDocumentResponse(**document)


@router.get("/bom-documents/{document_id}", response_model=BomDocumentResponse)
async def get_bom_document(
    document_id: str,
    store: BomDocumentStore = Depends(get_bom_document_store),
    operator: OperatorContext = Depends(get_operator_context),
) -> BomDocumentResponse:
    del operator
    document = await store.get_document(document_id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "BOM document not found"},
        )
    return BomDocumentResponse(**document)


async def _load_product_bom(
    client: FileMakerClient,
    product_sku: str,
) -> tuple[ProductInfo | None, dict[str, Any]]:
    product = await _find_product(client, product_sku)
    bom_result = await client.find_records(
        PRODUCT_BOM_LAYOUT,
        query={"ID_產品編號": f"=={product_sku}"},
        limit=500,
        offset=1,
    )
    return product, bom_result


async def _find_product(client: FileMakerClient, product_sku: str) -> ProductInfo | None:
    result = await client.find_records(
        PRODUCT_LAYOUT,
        query={"product_sku": f"=={product_sku}"},
        limit=1,
        offset=1,
    )
    if not result["data"]:
        return None
    fields = result["data"][0].get("fieldData", {})
    return ProductInfo(
        productSku=str(fields.get("product_sku") or product_sku),
        productName=str(fields.get("product_name") or ""),
        productNameCn=str(fields.get("產品名稱_中文") or ""),
        raw=fields,
    )


def _product_bom_row(record: dict[str, Any]) -> dict[str, Any]:
    fields = record.get("fieldData", {})
    return {
        "recordId": str(record.get("recordId") or ""),
        "productSku": str(fields.get("ID_產品編號") or ""),
        "partNo": str(fields.get("零件編號") or ""),
        "partName": str(fields.get("零件名稱") or ""),
        "requiredQty": fields.get("需求數量"),
        "costQty": fields.get("需求成本計算數量"),
        "changeType": "",
        "changeStatus": "",
        "raw": fields,
    }


def _calculation_line(
    record: dict[str, Any],
    *,
    index: int,
    generate_qty: float,
) -> BomCalculationLine:
    fields = record.get("fieldData", {})
    bom_qty = _number(fields.get("需求數量"))
    return BomCalculationLine(
        lineNo=index,
        sourceBomRecordId=str(record.get("recordId") or ""),
        partNo=str(fields.get("零件編號") or ""),
        partName=str(fields.get("零件名稱") or ""),
        bomQty=bom_qty,
        stockSnapshot=None,
        calculatedQty=bom_qty * generate_qty,
        actualQty=None,
        warehouse="",
        position1="",
        position2="",
        issueTime="",
        raw=fields,
    )


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _optional_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return _number(value)
