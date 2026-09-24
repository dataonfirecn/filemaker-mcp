import pytest
from fastapi import HTTPException

from app.api.orders import list_orders
from app.services.filemaker_client import FileMakerAPIError


class FakeFileMaker:
    def __init__(self, *, fail_first_sort: bool = False) -> None:
        self.calls = []
        self.fail_first_sort = fail_first_sort

    async def find_records(self, layout, query=None, limit=100, offset=1, sort=None):
        self.calls.append({"layout": layout, "query": query, "limit": limit, "offset": offset, "sort": sort})
        if layout == "訂單 清單_業務":
            if self.fail_first_sort and sort and sort[0]["fieldName"] == "日期":
                raise FileMakerAPIError("Field is missing", 500, {"messages": [{"code": "102"}]})
            return {
                "data": [
                    {
                        "recordId": "17452",
                        "fieldData": {
                            "internal_id": "NB25828-9674",
                            "訂單分類": "内部订单",
                            "訂單確認": "内部订单",
                            "訂單概要中文": "DRIFT RTR",
                            "貨款總和": "58275",
                            "包裝狀態": "还没好",
                            "已過天數": "325 天",
                            "出貨單_客戶::客戶名稱": "SARL IMODEL",
                        },
                    },
                    {
                        "recordId": "17453",
                        "fieldData": {"internal_id": "NB25901-0001", "出貨單_客戶::客戶名稱": "ACME"},
                    },
                ],
                "foundCount": 61,
            }
        if layout == "@出貨單":
            if query and any("出貨單 PI" in criteria for criteria in query):
                return {"data": [{"recordId": "9", "fieldData": {"internal_id": "NB25828-9674"}}], "foundCount": 1}
            return {
                "data": [
                    {
                        "recordId": "17452",
                        "fieldData": {
                            "id": "PI0017287",
                            "出貨單 PI": "QO-IM20250828 DRIFT RTR",
                            "訂單 PO": "PC000872",
                            "internal_id": "NB25828-9674",
                            "修改日期": "07/18/2026",
                        },
                    }
                ]
            }
        return {
            "data": [
                {
                    "recordId": "17452",
                    "fieldData": {
                        "internal_id": "NB25828-9674",
                        "日期": "08/28/2025",
                        "總和": "58275",
                        "付款狀態": "未收款",
                    },
                }
            ]
        }


def _session(**extra):
    return {"access": {"canViewOrders": True, "canViewPrice": True}, **extra}


@pytest.mark.asyncio
async def test_list_orders_pairs_each_row_with_shipment_id_used_by_detail() -> None:
    filemaker = FakeFileMaker()

    response = await list_orders(q="", page=2, page_size=25, session_context=_session(), client=filemaker)

    rich_call = filemaker.calls[0]
    assert rich_call["layout"] == "訂單 清單_業務"
    assert rich_call["query"] == [{"internal_id": "*"}]
    assert rich_call["limit"] == 25 and rich_call["offset"] == 26
    assert rich_call["sort"][0] == {"fieldName": "日期", "sortOrder": "descend"}
    assert [call["layout"] for call in filemaker.calls] == [
        "訂單 清單_業務", "@出貨單", "訂單 清單"
    ]
    assert response["foundCount"] == 61 and response["totalPages"] == 3
    assert response["page"] == 2 and response["pageSize"] == 25
    first, second = response["rows"]
    assert first["orderId"] == "PI0017287"
    assert first["internalOrderNo"] == "NB25828-9674"
    assert first["customerName"] == "SARL IMODEL"
    assert first["piNo"] == "QO-IM20250828 DRIFT RTR" and first["customerPo"] == "PC000872"
    assert first["orderDate"] == "08/28/2025"
    assert first["paymentStatus"] == "未收款" and first["amount"] == 58275.0
    # 找不到对应出貨單的记录仍会列出，但没有 orderId，前端不会给它明细入口。
    assert second["orderId"] == "" and second["internalOrderNo"] == "NB25901-0001"


@pytest.mark.asyncio
async def test_list_orders_hides_amount_without_price_permission() -> None:
    session = {"access": {"canViewOrders": True, "canViewPrice": False}}

    response = await list_orders(q="", page=1, page_size=25, session_context=session, client=FakeFileMaker())

    assert all(row["amount"] is None for row in response["rows"])
    assert "58275" not in str(response)


@pytest.mark.asyncio
async def test_list_orders_scopes_customer_sessions_to_their_own_orders() -> None:
    filemaker = FakeFileMaker()

    await list_orders(
        q="", page=1, page_size=25, session_context=_session(customerName="SARL IMODEL"), client=filemaker
    )

    assert filemaker.calls[0]["query"] == [
        {"internal_id": "*", "出貨單_客戶::客戶名稱": "==SARL IMODEL"}
    ]


@pytest.mark.asyncio
async def test_list_orders_search_matches_shipment_ids_and_quotes_user_input() -> None:
    filemaker = FakeFileMaker()

    await list_orders(
        q='PI*"', page=1, page_size=25, session_context=_session(customerName="ACME"), client=filemaker
    )

    shipment_search, rich_call = filemaker.calls[0], filemaker.calls[1]
    assert shipment_search["layout"] == "@出貨單"
    assert shipment_search["query"] == [
        {"id": '"PI*\\""'}, {"出貨單 PI": '"PI*\\""'}, {"訂單 PO": '"PI*\\""'}
    ]
    assert rich_call["layout"] == "訂單 清單_業務"
    # 客户专属会话：客户名称是范围条件，不参与搜索匹配；每个条件都保留客户范围。
    assert rich_call["query"] == [
        {"出貨單_客戶::客戶名稱": "==ACME", "internal_id": '"PI*\\""'},
        {"出貨單_客戶::客戶名稱": "==ACME", "訂單概要中文": '"PI*\\""'},
        # 由 PI / PO 命中的订单按内部单号精确补进结果。
        {"出貨單_客戶::客戶名稱": "==ACME", "internal_id": "==NB25828-9674"},
    ]


@pytest.mark.asyncio
async def test_list_orders_unscoped_search_also_matches_customer_name() -> None:
    filemaker = FakeFileMaker()

    await list_orders(q="IMODEL", page=1, page_size=25, session_context=_session(), client=filemaker)

    rich_call = filemaker.calls[1]
    assert [next(iter(criteria)) for criteria in rich_call["query"]] == [
        "internal_id", "訂單概要中文", "出貨單_客戶::客戶名稱", "internal_id"
    ]
    assert rich_call["query"][2] == {"出貨單_客戶::客戶名稱": '"IMODEL"'}


@pytest.mark.asyncio
async def test_list_orders_falls_back_to_internal_number_sort_when_date_field_missing() -> None:
    filemaker = FakeFileMaker(fail_first_sort=True)

    response = await list_orders(q="", page=1, page_size=25, session_context=_session(), client=filemaker)

    rich_sorts = [call["sort"] for call in filemaker.calls if call["layout"] == "訂單 清單_業務"]
    assert len(rich_sorts) == 2
    assert rich_sorts[1] == [{"fieldName": "internal_id", "sortOrder": "descend"}]
    assert response["rows"][0]["orderId"] == "PI0017287"


@pytest.mark.asyncio
async def test_list_orders_reports_source_failure_without_upstream_details() -> None:
    class BrokenFileMaker:
        async def find_records(self, *args, **kwargs):
            raise FileMakerAPIError("secret upstream host details", 502, {"detail": "secret"})

    with pytest.raises(HTTPException) as caught:
        await list_orders(q="", page=1, page_size=25, session_context=_session(), client=BrokenFileMaker())

    assert caught.value.status_code == 502
    assert "secret" not in str(caught.value.detail)


@pytest.mark.asyncio
async def test_orders_route_serves_list_and_requires_view_orders_permission() -> None:
    import httpx
    from fastapi import FastAPI
    from starlette.requests import Request

    from app.api import orders as api
    from app.services.dependencies import (
        _permission_for_request,
        get_filemaker_client,
        get_webviewer_session_context,
    )

    app = FastAPI()
    app.include_router(api.router, prefix="/api")
    app.dependency_overrides[get_filemaker_client] = lambda: FakeFileMaker()
    app.dependency_overrides[get_webviewer_session_context] = lambda: _session()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        response = await http.get("/api/orders", params={"page": 1, "page_size": 25})
        too_large = await http.get("/api/orders", params={"page_size": 101})

    assert response.status_code == 200
    assert response.json()["rows"][0]["orderId"] == "PI0017287"
    assert too_large.status_code == 422
    request = Request({"type": "http", "method": "GET", "path": "/api/orders", "headers": []})
    assert _permission_for_request(request) == "canViewOrders"
