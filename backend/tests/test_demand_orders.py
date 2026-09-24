from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from starlette.requests import Request

from app.api import demand_orders as api
from app.services.dependencies import (
    _permission_for_request, get_filemaker_client, get_filemaker_odata_client,
    get_webviewer_session_context,
)
from app.services.filemaker_client import FileMakerAPIError, FileMakerClient
from app.services.filemaker_odata_client import FileMakerODataError


@pytest_asyncio.fixture
async def setup_api():
    app = FastAPI()
    app.include_router(api.router, prefix="/api")
    fm = AsyncMock()
    fm._is_no_records_error = lambda exc: FileMakerClient._is_no_records_error(None, exc)
    fm.find_records.return_value = {"data": [{"recordId": "12", "fieldData": {
        "id": "DM26001", "日期": "09/23/2026", "需求簽名": "未簽名",
        "完成日期": "", "status": 0, "稅率": 0.13,
    }}], "foundCount": 61}
    fm.get_record.return_value = fm.find_records.return_value["data"]
    od = AsyncMock()
    od.records.return_value = {"rows": [{"@id": "https://fm.test/需求單BOM(123)",
        "數量": 0, "額外數量": None, "入庫數量": "1.5", "需求日期": "2026-09-23", "總金額": 999}], "foundCount": 61}
    app.dependency_overrides[get_filemaker_client] = lambda: fm
    app.dependency_overrides[get_filemaker_odata_client] = lambda: od
    app.dependency_overrides[get_webviewer_session_context] = lambda: {"access": {"canViewOrders": True}}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield app, client, fm, od


@pytest.mark.asyncio
async def test_search_pagination_and_filters(setup_api):
    _, client, fm, _ = setup_api
    response = await client.get('/api/demand-orders', params={"q": 'DM*"', "completion": "open", "page": 2})
    assert response.status_code == 200
    result = response.json()
    assert result["foundCount"] == 61 and result["totalPages"] == 3
    assert result["rows"][0]["orderDate"] == "2026-09-23"
    assert "稅率" not in str(result)
    args = fm.find_records.call_args.kwargs
    assert args["offset"] == 26 and args["limit"] == 25
    assert len(args["query"]) == 5
    assert all(q["完成日期"] == "=" for q in args["query"])
    assert args["query"][0]["id"] == '"DM*\\""'


@pytest.mark.asyncio
async def test_detail_scoping_numbers_and_no_cost_leak(setup_api):
    _, client, _, od = setup_api
    result = (await client.get('/api/demand-orders/12?page=2')).json()
    args = od.records.call_args.kwargs
    assert args["filter_expr"] == "ID_需求單 eq 'DM26001'"
    assert args["skip"] == 25 and args["orderby"] == "ROWID"
    assert result["totalPages"] == 3
    line = result["items"][0]
    assert line["id"] == "123"
    assert line["quantity"] == 0 and line["extraQuantity"] is None and line["receivedQuantity"] == 1.5
    assert "總金額" not in str(result)


@pytest.mark.asyncio
async def test_missing_order_and_source_failure(setup_api):
    _, client, fm, od = setup_api
    fm.get_record.side_effect = FileMakerAPIError("missing", 500, {"messages": [{"code": "101"}]})
    assert (await client.get('/api/demand-orders/12')).status_code == 404
    od.records.assert_not_called()
    fm.get_record.side_effect = None
    od.records.side_effect = FileMakerODataError("secret upstream details")
    response = await client.get('/api/demand-orders/12')
    assert response.status_code == 502
    assert 'secret' not in response.text


@pytest.mark.asyncio
async def test_empty_and_invalid_parameters(setup_api):
    _, client, fm, _ = setup_api
    fm.find_records.return_value = {"data": [], "foundCount": 0}
    assert (await client.get('/api/demand-orders')).json()["rows"] == []
    for url in ('/api/demand-orders?page=0', '/api/demand-orders?page_size=101',
                '/api/demand-orders?completion=invalid', '/api/demand-orders/not-a-record'):
        assert (await client.get(url)).status_code == 422


@pytest.mark.asyncio
async def test_authentication_required(setup_api):
    app, client, fm, _ = setup_api
    del app.dependency_overrides[get_webviewer_session_context]
    app.state.settings = object()
    assert (await client.get('/api/demand-orders')).status_code == 401
    fm.find_records.assert_not_called()


def test_order_permission_mapping():
    for path in ('/api/demand-orders', '/api/demand-orders/12'):
        request = Request({"type": "http", "method": "GET", "path": path, "headers": []})
        assert _permission_for_request(request) == "canViewOrders"


@pytest.mark.asyncio
async def test_denied_order_permission(setup_api, monkeypatch):
    from app.services import dependencies
    app, client, fm, _ = setup_api
    del app.dependency_overrides[get_webviewer_session_context]
    app.state.settings = object()
    account = {"origin": "web", "enabled": True, "mobileOnly": False,
               "permissions": {"canViewOrders": False}, "partPermissions": {}}
    store = AsyncMock()
    store.get_account.return_value = account
    app.state.webviewer_account_access_store = store
    monkeypatch.setattr(dependencies, "verify_session_token", lambda *_: {"operator": {"account": "limited"}})
    response = await client.get('/api/demand-orders', headers={"Authorization": "Bearer test"})
    assert response.status_code == 403
    fm.find_records.assert_not_called()


@pytest.mark.asyncio
async def test_sort_direction_defaults_to_newest_and_can_flip(setup_api):
    _, client, fm, _ = setup_api
    assert (await client.get('/api/demand-orders')).status_code == 200
    assert [s["sortOrder"] for s in fm.find_records.call_args.kwargs["sort"]] == ["descend", "descend"]
    assert (await client.get('/api/demand-orders', params={"sort": "oldest"})).status_code == 200
    assert fm.find_records.call_args.kwargs["sort"] == [
        {"fieldName": "日期", "sortOrder": "ascend"}, {"fieldName": "id", "sortOrder": "ascend"}]
    assert (await client.get('/api/demand-orders', params={"sort": "bogus"})).status_code == 422
