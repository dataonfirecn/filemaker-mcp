import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.quality import (
    create_quality_inspection,
    get_quality_inspection_for_admin,
    list_quality_inspections_for_admin,
    resolve_quality_scan,
)
from app.core.config import Settings
from app.models.quality import (
    CreateQualityInspectionRequest,
    QualityScanResolveRequest,
)
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.quality_inspection_store import QualityInspectionStore


class FakeQualityOData:
    def __init__(self) -> None:
        self.settings = Settings(filemaker_odata_max_top=10)
        self.purchase_lines = [
            {
                "id": "LINE-1",
                "ID_採購單": "PT-1001",
                "零件編號": "PART-88",
                "零件名稱": "测试零件",
                "廠商編號": "V-1",
                "廠商名稱": "测试供应商",
                "內部訂單編號": "NB-2001",
                "需要品檢": "QC",
                "品檢狀況": "",
            }
        ]
        self.arrivals = [
            {
                "ID": "ARR-1",
                "ID_採購單資料": "LINE-1",
                "到貨數量": 20,
                "到貨日期": "2026-09-09",
                "倉庫數量": 2,
                "退貨數量": 1,
                "狀態": "未入库",
                "到貨狀態": "已来货",
                "品檢日期": "",
                "QC檢查員": "",
            },
            {
                "ID": "ARR-2",
                "ID_採購單資料": "LINE-1",
                "到貨數量": 5,
                "到貨日期": "2026-09-08",
                "倉庫數量": 5,
                "退貨數量": 0,
                "狀態": "已入库",
                "到貨狀態": "已来货",
                "品檢日期": "2026-09-08",
                "QC檢查員": "QC",
            },
        ]
        self.specs = [
            {
                "ID": "SPEC-PART-88",
                "零件編號": "PART-88",
                "零件品名": "测试零件",
                "品檢注意事項": "",
                "審核": "已審核",
                "品檢規範 1": "外观不得有明显划伤",
                "品檢規範 2": "核对标签与数量",
            }
        ]
        self.parts = []
        self.create_count = 0

    async def records(
        self,
        table,
        *,
        filter_expr=None,
        top=10,
        skip=0,
        **_kwargs,
    ):
        if table == "採購單資料":
            rows = [
                row
                for row in self.purchase_lines
                if _matches(filter_expr, "id", row["id"])
            ]
        elif table == "採購單資料到貨":
            rows = [
                row
                for row in self.arrivals
                if _matches(filter_expr, "ID", row["ID"])
                or _matches(filter_expr, "ID_採購單資料", row["ID_採購單資料"])
            ]
        elif table == "零件":
            rows = [row for row in self.parts if _matches(filter_expr, "part_number", row["part_number"])]
        elif table == "品檢規範":
            rows = [
                row
                for row in self.specs
                if _matches(filter_expr, "零件編號", row["零件編號"])
            ]
        else:
            raise AssertionError(f"Unexpected table: {table}")
        page = rows[skip : skip + top]
        return {
            "rows": [dict(row) for row in page],
            "foundCount": len(rows),
            "returnedCount": len(page),
        }

    async def create_record(self, table, data):
        self.create_count += 1
        raise AssertionError(f"Quality flow must never write FileMaker: {table} {data}")


def _quality_store(name: str) -> QualityInspectionStore:
    return QualityInspectionStore(f"memory://{name}")


def _operator() -> OperatorContext:
    return OperatorContext(
        session_id="session-1",
        account="qc-user",
        name="品检测试员",
        privilege="品检组",
    )


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/api/qc/inspections",
        "headers": [
            (b"x-client-channel", b"ios-pda"),
            (b"x-app-build", b"12"),
            (b"x-app-version", b"1.0.0"),
            (b"user-agent", b"StarRCPDA/12"),
        ],
        "client": ("192.0.2.10", 12345),
    })


def _stored_record(arrival_id: str = "ARR-1", inspection_id: str = "QC-1") -> dict:
    return {
        "id": inspection_id,
        "purchaseLineID": "LINE-1",
        "arrivalBatchID": arrival_id,
        "inspectionRound": 1,
        "idempotencyKey": f"quality-inspection-{arrival_id}",
        "purchaseOrderNumber": "PT-1001",
        "nbNumber": "NB-2001",
        "partNumber": "PART-88",
        "partName": "测试零件",
        "supplierName": "测试供应商",
        "arrivalDate": "2026-09-09",
        "arrivalQuantity": 20,
        "returnedQuantity": 1,
        "warehousedQuantity": 2,
        "availableQuantity": 17,
        "inspectionMethod": "抽檢",
        "sampleQuantity": 10,
        "status": "检查中",
        "conclusion": "",
        "specVersion": {
            "id": "SPEC-PART-88",
            "version": "FM-TEST",
            "approvedBy": "已審核",
            "effectiveAt": "",
        },
        "checkItems": [{
            "id": "A",
            "code": "A",
            "title": "品检规范 1",
            "instructions": "外观不得有明显划伤",
            "inputType": "result",
            "unit": "",
            "targetValue": None,
            "lowerLimit": None,
            "upperLimit": None,
            "required": True,
            "sampleCount": 1,
        }],
        "sourceSnapshot": {"schema": "starrc.quality-source-snapshot.v1"},
        "requestPayload": {"arrivalBatchID": arrival_id},
    }


def _matches(expression: str | None, field: str, value: str) -> bool:
    if not expression:
        return False
    escaped = value.replace("'", "''")
    return f'"{field}" eq \'{escaped}\'' in expression


@pytest.mark.asyncio
async def test_purchase_line_scan_returns_every_arrival_batch() -> None:
    odata = FakeQualityOData()
    response = await resolve_quality_scan(
        body=QualityScanResolveRequest(code="4|LINE-1"),
        odata=odata,
        quality_store=_quality_store("scan-purchase"),
        access={"canViewQuality": True},
        settings=Settings(filemaker_quality_max_arrivals=50),
    )

    assert response.purchase_line_id == "LINE-1"
    assert response.purchase_order_number == "PT-1001"
    assert [row.id for row in response.arrivals] == ["ARR-1", "ARR-2"]
    assert response.arrivals[0].arrival_quantity == 20
    assert response.arrivals[1].qc_status == "已完成"


@pytest.mark.asyncio
async def test_arrival_scan_returns_only_exact_batch() -> None:
    odata = FakeQualityOData()
    response = await resolve_quality_scan(
        body=QualityScanResolveRequest(code="STARRC|1|ARRIVAL|ARR-1"),
        odata=odata,
        quality_store=_quality_store("scan-arrival"),
        access={"canViewQuality": True},
        settings=Settings(),
    )

    assert [row.id for row in response.arrivals] == ["ARR-1"]
    assert response.arrivals[0].purchase_line_id == "LINE-1"


@pytest.mark.asyncio
async def test_purchase_line_scan_catalogs_inspections_across_odata_pages() -> None:
    odata = FakeQualityOData()
    odata.arrivals = [
        {
            "ID": f"ARR-{index}",
            "ID_採購單資料": "LINE-1",
            "到貨數量": 20,
            "到貨日期": "2026-09-09",
            "倉庫數量": 0,
            "退貨數量": 0,
            "狀態": "未入库",
            "到貨狀態": "已来货",
            "品檢日期": "",
            "QC檢查員": "",
        }
        for index in range(12)
    ]
    quality_store = _quality_store("scan-catalog")
    await quality_store.create_or_get(
        record=_stored_record("ARR-11", "QC-11"),
        operator=_operator(),
        event_payload={"request": "test"},
    )

    response = await resolve_quality_scan(
        body=QualityScanResolveRequest(code="4|LINE-1"),
        odata=odata,
        quality_store=quality_store,
        access={"canViewQuality": True},
        settings=Settings(filemaker_quality_max_arrivals=20),
    )

    assert len(response.arrivals) == 12
    assert response.arrivals[11].inspection_id == "QC-11"
    assert response.arrivals[11].qc_status == "检查中"


@pytest.mark.asyncio
async def test_scan_requires_quality_permission_and_supported_code() -> None:
    with pytest.raises(HTTPException) as denied:
        await resolve_quality_scan(
            body=QualityScanResolveRequest(code="4|LINE-1"),
            odata=FakeQualityOData(),
            quality_store=_quality_store("scan-denied"),
            access={"canViewQuality": False},
            settings=Settings(),
        )
    assert denied.value.status_code == 403

    with pytest.raises(HTTPException) as invalid:
        await resolve_quality_scan(
            body=QualityScanResolveRequest(code="5|PI001"),
            odata=FakeQualityOData(),
            quality_store=_quality_store("scan-invalid"),
            access={"canViewQuality": True},
            settings=Settings(),
        )
    assert invalid.value.status_code == 422


@pytest.mark.asyncio
async def test_create_inspection_writes_traceable_record_and_is_idempotent() -> None:
    odata = FakeQualityOData()
    audit = AuditLogStore("memory://quality-audit")
    await audit.init()
    quality_store = _quality_store("quality-create")
    kwargs = {
        "body": CreateQualityInspectionRequest(arrivalBatchID="ARR-1"),
        "request": _request(),
        "idempotency_key": "quality-inspection-ARR-1",
        "operator": _operator(),
        "odata": odata,
        "audit_log": audit,
        "quality_store": quality_store,
        "access": {"canViewQuality": True},
        "settings": Settings(quality_write_enabled=True, filemaker_database="DMS"),
    }

    created = await create_quality_inspection(**kwargs)
    repeated = await create_quality_inspection(**kwargs)

    assert created == repeated
    assert created.arrival_batch_id == "ARR-1"
    assert created.sample_quantity == 10
    assert len(created.check_items) == 2
    assert odata.create_count == 0

    detail = await quality_store.get_inspection(created.id)
    assert detail is not None
    assert detail["purchaseLineID"] == "LINE-1"
    assert detail["arrivalBatchID"] == "ARR-1"
    assert detail["idempotencyKey"] == "quality-inspection-ARR-1"
    assert detail["nbNumber"] == "NB-2001"
    assert detail["purchaseOrderNumber"] == "PT-1001"
    assert detail["operatorAccount"] == "qc-user"
    assert detail["operatorPrivilege"] == "品检组"
    assert detail["specVersion"]["version"].startswith("FM-")
    assert detail["sourceSnapshot"]["sourceSystem"] == "FileMaker"
    assert detail["sourceSnapshot"]["database"] == "DMS"
    assert detail["sourceSnapshot"]["purchaseLine"]["fields"]["零件編號"] == "PART-88"
    assert detail["sourceSnapshot"]["arrivalBatch"]["fields"]["到貨數量"] == 20
    assert detail["requestPayload"]["client"] == {
        "channel": "ios-pda",
        "appBuild": "12",
        "appVersion": "1.0.0",
        "userAgent": "StarRCPDA/12",
        "remoteAddress": "192.0.2.10",
    }
    assert [event["eventType"] for event in detail["events"]] == [
        "INSPECTION_CREATED",
        "IDEMPOTENT_REPLAY",
    ]


@pytest.mark.asyncio
async def test_create_inspection_rejects_disabled_write_and_wrong_key() -> None:
    common = {
        "body": CreateQualityInspectionRequest(arrivalBatchID="ARR-1"),
        "request": _request(),
        "operator": _operator(),
        "odata": FakeQualityOData(),
        "audit_log": AuditLogStore("memory://quality-audit"),
        "quality_store": _quality_store("quality-disabled"),
        "access": {"canViewQuality": True},
    }
    with pytest.raises(HTTPException) as locked:
        await create_quality_inspection(
            **common,
            idempotency_key="quality-inspection-ARR-1",
            settings=Settings(quality_write_enabled=False),
        )
    assert locked.value.status_code == 423

    with pytest.raises(HTTPException) as conflict:
        await create_quality_inspection(
            **common,
            idempotency_key="wrong-key",
            settings=Settings(quality_write_enabled=True),
        )
    assert conflict.value.status_code == 409


@pytest.mark.asyncio
async def test_admin_can_list_and_open_full_trace() -> None:
    quality_store = _quality_store("quality-admin")
    record, _ = await quality_store.create_or_get(
        record=_stored_record(),
        operator=_operator(),
        event_payload={"request": "test"},
    )

    listing = await list_quality_inspections_for_admin(
        page=1,
        page_size=20,
        q="PART-88",
        inspection_status="检查中",
        quality_store=quality_store,
        access={"canManageAccounts": True},
    )
    assert listing.total == 1
    assert listing.items[0].id == record["id"]

    detail = await get_quality_inspection_for_admin(
        inspection_id=record["id"],
        quality_store=quality_store,
        access={"canManageAccounts": True},
    )
    assert detail.source_snapshot["schema"] == "starrc.quality-source-snapshot.v1"
    assert detail.events[0].event_type == "INSPECTION_CREATED"

    with pytest.raises(HTTPException) as denied:
        await list_quality_inspections_for_admin(
            page=1,
            page_size=20,
            q="",
            inspection_status="",
            quality_store=quality_store,
            access={"canManageAccounts": False},
        )
    assert denied.value.status_code == 403
