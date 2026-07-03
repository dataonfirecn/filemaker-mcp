from typing import Any

from fastapi import APIRouter, Depends, Query

from app.core.config import Settings
from app.models.bom_changes import (
    FileMakerRow,
    IssueRowsResponse,
    ProductBomResponse,
    ProductBomRow,
    ProductInfo,
    ReadOnlyActionRequest,
)
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.dependencies import (
    get_audit_log_store,
    get_filemaker_client,
    get_operator_context,
    get_settings,
)
from app.services.filemaker_client import FileMakerAPIError, FileMakerClient

router = APIRouter(prefix="/bom-changes", tags=["bom-changes"])

PRODUCT_LAYOUT = "產品清單_業務"
PRODUCT_BOM_LAYOUT = "@產品BOM"
KIT_ISSUE_LAYOUT = "零件包 發料分类"
ISSUE_SUMMARY_LAYOUT = "發料單 匯總_PC"
BOM_CALC_LAYOUT = "BOM計算單資料"


@router.get("/context")
async def get_context(
    settings: Settings = Depends(get_settings),
    operator: OperatorContext = Depends(get_operator_context),
) -> dict[str, Any]:
    return {
        "operator": {
            "sessionId": operator.session_id,
            "account": operator.account,
            "name": operator.name,
            "privilege": operator.privilege,
        },
        "filemakerReadOnly": settings.filemaker_read_only,
    }


@router.get("/products/{product_sku}/bom", response_model=ProductBomResponse)
async def get_product_bom(
    product_sku: str,
    client: FileMakerClient = Depends(get_filemaker_client),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    operator: OperatorContext = Depends(get_operator_context),
) -> ProductBomResponse:
    query = {"ID_產品編號": f"=={product_sku}"}
    product = await _find_product(client, product_sku)
    result = await client.find_records(
        PRODUCT_BOM_LAYOUT,
        query=query,
        limit=500,
        offset=1,
    )
    rows = [_product_bom_row(record) for record in result["data"]]
    await audit_log.record(
        operator=operator,
        action_type="READ_PRODUCT_BOM",
        status="success",
        target_layout=PRODUCT_BOM_LAYOUT,
        product_sku=product_sku,
        request_payload={"query": query, "limit": 500},
        response_payload={
            "foundCount": result["foundCount"],
            "returnedCount": result["returnedCount"],
        },
    )
    return ProductBomResponse(
        product=product,
        rows=rows,
        foundCount=result["foundCount"],
        returnedCount=result["returnedCount"],
    )


@router.get("/orders/{bom_calc_id}/materials", response_model=IssueRowsResponse)
async def get_order_materials(
    bom_calc_id: str,
    client: FileMakerClient = Depends(get_filemaker_client),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    operator: OperatorContext = Depends(get_operator_context),
) -> IssueRowsResponse:
    query = {"ID_BOM計算單": f"=={bom_calc_id}"}
    result = await client.find_records(
        BOM_CALC_LAYOUT,
        query=query,
        limit=500,
        offset=1,
    )
    await audit_log.record(
        operator=operator,
        action_type="READ_BOM_CALC_MATERIALS",
        status="success",
        target_layout=BOM_CALC_LAYOUT,
        bom_calc_id=bom_calc_id,
        request_payload={"query": query, "limit": 500},
        response_payload={
            "foundCount": result["foundCount"],
            "returnedCount": result["returnedCount"],
        },
    )
    return _issue_response(BOM_CALC_LAYOUT, result)


@router.get("/kit-issue", response_model=IssueRowsResponse)
async def get_kit_issue_rows(
    product_sku: str | None = Query(default=None, alias="productSku"),
    bom_calc_id: str | None = Query(default=None, alias="bomCalcId"),
    client: FileMakerClient = Depends(get_filemaker_client),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    operator: OperatorContext = Depends(get_operator_context),
) -> IssueRowsResponse:
    query = _issue_query(product_sku=product_sku, bom_calc_id=bom_calc_id)
    result = await _safe_find_or_records(client, KIT_ISSUE_LAYOUT, query=query, limit=100)
    await audit_log.record(
        operator=operator,
        action_type="READ_KIT_ISSUE",
        status="success",
        target_layout=KIT_ISSUE_LAYOUT,
        product_sku=product_sku,
        bom_calc_id=bom_calc_id,
        request_payload={"query": query, "limit": 100},
        response_payload={
            "foundCount": result["foundCount"],
            "returnedCount": result["returnedCount"],
        },
    )
    return _issue_response(KIT_ISSUE_LAYOUT, result)


@router.get("/issue-summary", response_model=IssueRowsResponse)
async def get_issue_summary_rows(
    product_sku: str | None = Query(default=None, alias="productSku"),
    bom_calc_id: str | None = Query(default=None, alias="bomCalcId"),
    client: FileMakerClient = Depends(get_filemaker_client),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    operator: OperatorContext = Depends(get_operator_context),
) -> IssueRowsResponse:
    query = _issue_query(product_sku=product_sku, bom_calc_id=bom_calc_id)
    result = await _safe_find_or_records(client, ISSUE_SUMMARY_LAYOUT, query=query, limit=100)
    await audit_log.record(
        operator=operator,
        action_type="READ_ISSUE_SUMMARY",
        status="success",
        target_layout=ISSUE_SUMMARY_LAYOUT,
        product_sku=product_sku,
        bom_calc_id=bom_calc_id,
        request_payload={"query": query, "limit": 100},
        response_payload={
            "foundCount": result["foundCount"],
            "returnedCount": result["returnedCount"],
        },
    )
    return _issue_response(ISSUE_SUMMARY_LAYOUT, result)


@router.get("/audit-logs")
async def list_audit_logs(
    product_sku: str | None = Query(default=None, alias="productSku"),
    bom_calc_id: str | None = Query(default=None, alias="bomCalcId"),
    limit: int = Query(default=100, ge=1, le=500),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    operator: OperatorContext = Depends(get_operator_context),
) -> dict[str, Any]:
    logs = await audit_log.list_logs(
        limit=limit,
        product_sku=product_sku,
        bom_calc_id=bom_calc_id,
    )
    return {"rows": logs}


@router.post("/batches")
async def create_batch_read_only(
    body: ReadOnlyActionRequest,
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    operator: OperatorContext = Depends(get_operator_context),
) -> dict[str, Any]:
    return await _read_only_block(
        audit_log=audit_log,
        operator=operator,
        action_type="CREATE_BATCH",
        body=body,
    )


@router.post("/items/add")
async def add_item_read_only(
    body: ReadOnlyActionRequest,
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    operator: OperatorContext = Depends(get_operator_context),
) -> dict[str, Any]:
    return await _read_only_block(
        audit_log=audit_log,
        operator=operator,
        action_type="ADD_BOM_ITEM",
        body=body,
    )


@router.post("/items/mark-delete")
async def mark_delete_read_only(
    body: ReadOnlyActionRequest,
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    operator: OperatorContext = Depends(get_operator_context),
) -> dict[str, Any]:
    return await _read_only_block(
        audit_log=audit_log,
        operator=operator,
        action_type="MARK_DELETE",
        body=body,
    )


@router.post("/items/transfer-to-issue")
async def transfer_to_issue_read_only(
    body: ReadOnlyActionRequest,
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    operator: OperatorContext = Depends(get_operator_context),
) -> dict[str, Any]:
    return await _read_only_block(
        audit_log=audit_log,
        operator=operator,
        action_type="TRANSFER_TO_ISSUE",
        body=body,
    )


@router.post("/items/warehouse-action")
async def warehouse_action_read_only(
    body: ReadOnlyActionRequest,
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    operator: OperatorContext = Depends(get_operator_context),
) -> dict[str, Any]:
    return await _read_only_block(
        audit_log=audit_log,
        operator=operator,
        action_type="WAREHOUSE_ACTION",
        body=body,
    )


@router.post("/batches/{batch_id}/complete")
async def complete_batch_read_only(
    batch_id: str,
    body: ReadOnlyActionRequest,
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    operator: OperatorContext = Depends(get_operator_context),
) -> dict[str, Any]:
    body.change_batch_id = body.change_batch_id or batch_id
    return await _read_only_block(
        audit_log=audit_log,
        operator=operator,
        action_type="COMPLETE_BATCH",
        body=body,
    )


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


def _product_bom_row(record: dict[str, Any]) -> ProductBomRow:
    fields = record.get("fieldData", {})
    return ProductBomRow(
        recordId=str(record.get("recordId") or ""),
        productSku=str(fields.get("ID_產品編號") or ""),
        partNo=str(fields.get("零件編號") or ""),
        partName=str(fields.get("零件名稱") or ""),
        requiredQty=fields.get("需求數量"),
        costQty=fields.get("需求成本計算數量"),
        changeType=str(fields.get("後續修改類型") or fields.get("後續修改標記") or ""),
        changeStatus=str(fields.get("後續修改狀態") or ""),
        raw=fields,
    )


def _issue_response(layout: str, result: dict[str, Any]) -> IssueRowsResponse:
    rows = [
        FileMakerRow(
            recordId=str(record.get("recordId") or ""),
            modId=str(record.get("modId") or ""),
            fields=record.get("fieldData", {}),
        )
        for record in result["data"]
    ]
    return IssueRowsResponse(
        layout=layout,
        rows=rows,
        foundCount=result["foundCount"],
        returnedCount=result["returnedCount"],
    )


def _issue_query(
    *,
    product_sku: str | None = None,
    bom_calc_id: str | None = None,
) -> dict[str, Any]:
    if bom_calc_id:
        return {"ID_BOM計算單": f"=={bom_calc_id}"}
    if product_sku:
        return {"產品_BOM::product_sku": f"=={product_sku}"}
    return {}


async def _safe_find_or_records(
    client: FileMakerClient,
    layout: str,
    *,
    query: dict[str, Any],
    limit: int,
) -> dict[str, Any]:
    try:
        return await client.find_records(layout, query=query, limit=limit, offset=1)
    except FileMakerAPIError:
        if query:
            return await client.find_records(layout, query={}, limit=limit, offset=1)
        raise


async def _read_only_block(
    *,
    audit_log: AuditLogStore,
    operator: OperatorContext,
    action_type: str,
    body: ReadOnlyActionRequest,
) -> dict[str, Any]:
    response = {
        "ok": False,
        "readOnly": True,
        "message": "当前为 FileMaker 只读模式，本阶段不会新增、修改或删除 FileMaker 记录。",
    }
    await audit_log.record(
        operator=operator,
        action_type=action_type,
        status="blocked_read_only",
        product_sku=body.product_sku,
        order_id=body.order_id,
        bom_calc_id=body.bom_calc_id,
        change_batch_id=body.change_batch_id,
        change_item_id=body.change_item_id,
        request_payload=body.model_dump(by_alias=True),
        response_payload=response,
    )
    return response
