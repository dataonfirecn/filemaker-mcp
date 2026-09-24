"""Read-only demand orders from FileMaker; no raw records or cost fields exposed."""
import math
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.dependencies import (
    get_filemaker_client, get_filemaker_odata_client, get_webviewer_session_context,
)
from app.services.filemaker_client import FileMakerAPIError, FileMakerClient
from app.services.filemaker_odata_client import FileMakerODataClient, FileMakerODataError

router = APIRouter(prefix="/demand-orders", tags=["demand-orders"],
                   dependencies=[Depends(get_webviewer_session_context)])
HEADER_LAYOUT = "@需求單"
LINE_TABLE = "需求單BOM"
LINE_FIELDS = ['ID_需求單', '零件編號', '零件名稱', '數量', '額外數量',
               '入庫數量', '需求日期', '需求狀態', '採購已下單', '加工廠商', '需求備註', '額外備註']


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _date(value: Any) -> str:
    text = _text(value)
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.strftime("%Y-%m-%d %H:%M:%S" if "%H" in fmt else "%Y-%m-%d")
        except ValueError:
            pass
    return text


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def _header(record: dict) -> dict:
    fields = record.get("fieldData") or {}
    result = {key: _text(fields.get(source)) for key, source in {
        "id": "id", "internalOrderNo": "內部訂單編號", "summary": "概要",
        "reviewStatus": "需求簽名", "purchaseStatus": "已打採購單", "type": "類型",
        "createdBy": "打單人", "modifiedBy": "修改人", "notes": "採購單註解",
        "method": "方式", "bomId": "ID_BOM",
    }.items()}
    result.update({key: _date(fields.get(source)) for key, source in {
        "orderDate": "日期", "dueDate": "期限", "completedDate": "完成日期", "modifiedAt": "修改日期",
    }.items()})
    result["company"] = _text(fields.get("需求公司")) or _text(fields.get("公司"))
    result["recordId"] = _text(record.get("recordId"))
    return result


def _line(fields: dict) -> dict:
    result = {key: _text(fields.get(source)) for key, source in {
        "id": "id", "partNo": "零件編號", "partName": "零件名稱", "status": "需求狀態",
        "purchaseStatus": "採購已下單", "supplier": "加工廠商", "notes": "需求備註", "extraNotes": "額外備註",
    }.items()}
    result.update({key: _number(fields.get(source)) for key, source in {
        "quantity": "數量", "extraQuantity": "額外數量", "receivedQuantity": "入庫數量",
    }.items()})
    result["id"] = _text(fields.get("@id")).rsplit("(", 1)[-1].rstrip(")")
    result["dueDate"] = _date(fields.get("需求日期"))
    return result


def _literal_find(text: str) -> str:
    # Quote the user's input: FileMaker find operators must not change query semantics.
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _source_error(exc: Exception) -> HTTPException:
    return HTTPException(502, detail={"message": "无法读取 FileMaker 需求单，请稍后重试；若持续失败，请联系管理员检查 API 连接和读取权限。"})


@router.get("")
async def list_demand_orders(
    q: str = Query("", max_length=100),
    completion: Literal["all", "open", "completed"] = "all",
    sort: Literal["newest", "oldest"] = "newest",
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    client: FileMakerClient = Depends(get_filemaker_client),
) -> dict:
    criteria = {"id": "*"}
    if completion != "all":
        criteria["完成日期"] = "=" if completion == "open" else "*"
    term = q.strip()
    query = [{**criteria, field: _literal_find(term)} for field in
             ("id", "內部訂單編號", "概要", "需求公司", "公司")] if term else [criteria]
    # 默认「最近优先」；「最早优先」把日期与单号一起反向，同日单据仍按创建先后排。
    order = "ascend" if sort == "oldest" else "descend"
    try:
        result = await client.find_records(HEADER_LAYOUT, query=query,
            limit=page_size, offset=(page - 1) * page_size + 1,
            sort=[{"fieldName": "日期", "sortOrder": order}, {"fieldName": "id", "sortOrder": order}])
    except FileMakerAPIError as exc:
        raise _source_error(exc) from exc
    count = int(result.get("foundCount") or 0)
    return {"rows": [_header(row) for row in result.get("data", [])],
            "foundCount": count, "page": page, "pageSize": page_size,
            "totalPages": max(1, math.ceil(count / page_size))}


@router.get("/{record_id}")
async def get_demand_order(
    record_id: str, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    client: FileMakerClient = Depends(get_filemaker_client),
    odata: FileMakerODataClient = Depends(get_filemaker_odata_client),
) -> dict:
    if not record_id.isascii() or not record_id.isdigit():
        raise HTTPException(422, detail={"message": "需求单记录编号无效，请从列表重新打开。"})
    try:
        records = await client.get_record(HEADER_LAYOUT, record_id)
    except FileMakerAPIError as exc:
        if client._is_no_records_error(exc) or exc.status_code == 404:
            raise HTTPException(404, detail={"message": "需求单不存在或已删除，请返回列表刷新。"}) from exc
        raise _source_error(exc) from exc
    if not records:
        raise HTTPException(404, detail={"message": "需求单不存在或已删除，请返回列表刷新。"})
    order = _header(records[0])
    if not order["id"]:
        raise HTTPException(502, detail={"message": "需求单缺少业务单号，无法读取关联明细。"})
    try:
        result = await odata.records(LINE_TABLE, select=LINE_FIELDS,
            filter_expr="ID_需求單 eq '" + order["id"].replace("'", "''") + "'",
            orderby="ROWID", top=page_size, skip=(page - 1) * page_size, count=True)
    except FileMakerODataError as exc:
        raise _source_error(exc) from exc
    count = int(result.get("foundCount") or 0)
    return {"order": order, "items": [_line(row) for row in result.get("rows", [])],
            "foundCount": count, "page": page, "pageSize": page_size,
            "totalPages": max(1, math.ceil(count / page_size))}
