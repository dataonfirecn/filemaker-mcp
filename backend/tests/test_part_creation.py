import base64

import pytest

from app.core.config import Settings
from app.models.part_creation import PartCreationRequest
from app.services.part_creation import (
    PartCreationError,
    create_part,
    load_part_creation_options,
    search_part_vendors,
    validate_part_creation,
)


def _values(name, *values):
    return {
        "name": name,
        "values": [
            {"value": value, "displayValue": display}
            for value, display in values
        ],
    }


class FakeFileMaker:
    def __init__(
        self,
        *,
        duplicate=False,
        upload_error=False,
        vendor_status="已审核",
    ):
        self.duplicate = duplicate
        self.upload_error = upload_error
        self.vendor_status = vendor_status
        self.created_fields = None
        self.uploaded = None
        self.deleted = []

    async def get_layout_metadata(self, layout):
        if layout == "MaterialIDGenerator_Gen":
            return {
                "valueLists": [
                    _values("零件性質", ("CB", "CB 碳纤维")),
                    _values("客戶2", ("007", "007 Simba")),
                ]
            }
        assert layout == "新增零件资料"
        return {
            "valueLists": [
                _values("倉庫分工", ("发料", "发料"), ("不发料", "不发料")),
                _values("零件性質", ("CB", "CB 碳纤维")),
                _values("加工分類", ("外购", "外购")),
                _values("零件狀態", ("采购", "采购")),
                _values("統計分類", ("统计", "统计")),
                _values("使用公司", ("采购部", "采购部")),
                _values("狀態", ("可量产", "可量产")),
                _values("零件品種", ("底板", "底板")),
                _values("材料分類", ("原材料", "原材料")),
                _values("倉庫"),
                _values("零件材料尺寸", ("3x10", "3x10")),
                _values("客戶", ("Army Racing", "1 Army Racing 0840")),
            ]
        }

    async def find_records(self, layout, query=None, limit=100, offset=1, sort=None):
        if layout == "@零件":
            return {
                "data": (
                    [{"recordId": "88", "fieldData": {"part_number": "CB007-001"}}]
                    if self.duplicate
                    else []
                ),
                "foundCount": 1 if self.duplicate else 0,
            }
        if layout == "@S廠商":
            return {
                "data": [
                    {
                        "recordId": "19",
                        "fieldData": {
                            "ID": "FE2F8FA0-CDBB-5D4A-A3EE-C7EA9F951E68",
                            "ID_廠商編號": "10",
                            "廠商名稱": "阿雄五金",
                            "status": self.vendor_status,
                        },
                    }
                ],
                "foundCount": 1,
            }
        records = {
            "MaterialManufactor_EDIT": [("LD", "镭雕")],
            "MaterialColor_EDIT": [("DBK", "氧化黑色")],
            "MaterialOther_EDIT": [("PS", "特殊")],
        }[layout]
        return {
            "data": [
                {"fieldData": {"init": code, "description": label}}
                for code, label in records
            ]
        }

    async def create_record(self, layout, data):
        assert layout == "@零件"
        self.created_fields = data
        return {"recordId": "101", "modId": "0"}

    async def upload_container(
        self,
        layout,
        record_id,
        field_name,
        content,
        filename,
        content_type,
    ):
        if self.upload_error:
            raise RuntimeError("upload failed")
        self.uploaded = {
            "layout": layout,
            "recordId": record_id,
            "field": field_name,
            "content": content,
            "filename": filename,
            "contentType": content_type,
        }
        return {"recordId": record_id, "modId": "1"}

    async def delete_record(self, layout, record_id):
        self.deleted.append((layout, record_id))

    async def get_record(self, layout, record_id):
        return [
            {
                "recordId": record_id,
                "fieldData": {
                    "part_id": "P-101",
                    "part_number": self.created_fields["part_number"],
                },
            }
        ]


class FakeOData:
    def __init__(self, *, customer_id="CU840"):
        self.customer_id = customer_id
        self.calls = []

    async def records(
        self,
        table,
        *,
        select=None,
        filter_expr=None,
        expand=None,
        orderby=None,
        top=10,
        skip=0,
        count=True,
    ):
        self.calls.append(
            {
                "table": table,
                "filter": filter_expr,
                "top": top,
                "count": count,
            }
        )
        if not self.customer_id:
            return {"rows": [], "count": 0}
        return {
            "rows": [
                {
                    "ID": self.customer_id,
                    "客戶代號": "0840",
                    "客戶公司簡稱": "Army Racing",
                }
            ],
            "count": 1,
        }


def _settings(**overrides):
    values = {
        "filemaker_part_create_enabled": True,
        "filemaker_part_read_layout": "新增零件资料",
        "filemaker_part_write_layout": "@零件",
    }
    values.update(overrides)
    return Settings(**values)


def _request(**overrides):
    values = {
        "partNumber": "CB007-001",
        "internalName": "碳纤维底板",
        "externalName": "碳纤维底板",
        "warehouseDivision": "发料",
        "machiningCategory": "外购",
        "statisticsCategory": "统计",
        "useDepartment": "采购部",
        "lifecycleStatus": "可量产",
        "vendorId": "FE2F8FA0-CDBB-5D4A-A3EE-C7EA9F951E68",
        "vendorNumber": "10",
        "vendorName": "阿雄五金",
        "materialCategory": "CB",
        "departmentDivision": "采购",
        "partCategory": "底板",
        "materialProperties": "原材料",
        "weightGrams": "12.5",
        "customerCode": "0840",
        "customerName": "Army Racing",
    }
    values.update(overrides)
    return PartCreationRequest(**values)


def test_customer_code_uses_explicit_alias_and_accepts_legacy_payload() -> None:
    request = _request()
    payload = request.model_dump(by_alias=True)

    assert payload["customerCode"] == "0840"
    legacy_payload = {**payload, "customerId": payload["customerCode"]}
    legacy_payload.pop("customerCode")
    assert PartCreationRequest(**legacy_payload).customer_code == "0840"


@pytest.mark.asyncio
async def test_options_are_loaded_from_native_new_part_layout() -> None:
    options = await load_part_creation_options(FakeFileMaker(), _settings())

    assert [item.code for item in options.warehouse_divisions] == ["发料", "不发料"]
    assert options.material_categories[0].label == "碳纤维"
    assert options.exclusive_customers[0].code == "0840"
    assert options.exclusive_customers[0].label == "Army Racing"
    assert options.defaults.department_division == "采购"
    assert options.defaults.machining_category == ""
    assert options.generator.customers[0].code == "007"


@pytest.mark.asyncio
async def test_vendor_search_returns_uuid_display_fields_and_approval_state() -> None:
    response = await search_part_vendors(FakeFileMaker(), "阿雄", limit=40)

    assert response.found_count == 1
    assert response.items[0].vendor_id == "FE2F8FA0-CDBB-5D4A-A3EE-C7EA9F951E68"
    assert response.items[0].vendor_number == "10"
    assert response.items[0].vendor_name == "阿雄五金"
    assert response.items[0].selectable is True


@pytest.mark.asyncio
async def test_validation_rejects_placeholder_duplicate_and_stale_option() -> None:
    response = await validate_part_creation(
        FakeFileMaker(duplicate=True),
        _settings(),
        _request(
            internalName="新零件，請填寫正確中文名稱＆詳細資訊",
            warehouseDivision="已删除选项",
        ),
        odata=FakeOData(),
    )

    assert response.valid is False
    assert "internalName" in response.errors
    assert "warehouseDivision" in response.errors
    assert "partNumber" in response.errors


@pytest.mark.asyncio
async def test_validation_requires_warehouse_and_machining_categories() -> None:
    response = await validate_part_creation(
        FakeFileMaker(),
        _settings(),
        _request(warehouseDivision="", machiningCategory=""),
        odata=FakeOData(),
    )

    assert response.valid is False
    assert response.errors["warehouseDivision"] == "仓库分工为必选项。"
    assert response.errors["machiningCategory"] == "加工分类为必选项。"


@pytest.mark.asyncio
async def test_create_maps_fields_and_uploads_photo() -> None:
    filemaker = FakeFileMaker()
    response = await create_part(
        filemaker,
        _settings(),
        _request(
            photoName="sample.png",
            photoMimeType="image/jpeg",
            photoBase64=base64.b64encode(b"jpeg-data").decode(),
        ),
        odata=FakeOData(),
        created_by="amy",
    )

    assert response.record_id == "101"
    assert response.part_id == "P-101"
    assert response.photo_uploaded is True
    assert filemaker.created_fields["倉庫分工"] == "发料"
    assert filemaker.created_fields["material_category"] == "CB"
    assert filemaker.created_fields["customer_id"] == "CU840"
    assert filemaker.created_fields["exclusive_customer_name"] == "Army Racing"
    assert (
        filemaker.created_fields["ID_廠商"]
        == "FE2F8FA0-CDBB-5D4A-A3EE-C7EA9F951E68"
    )
    assert filemaker.created_fields["created_by"] == "amy"
    assert filemaker.uploaded["field"] == "影像 | 容器"
    assert filemaker.uploaded["filename"] == "sample.jpg"


@pytest.mark.asyncio
async def test_photo_upload_failure_rolls_back_new_record() -> None:
    filemaker = FakeFileMaker(upload_error=True)

    with pytest.raises(RuntimeError, match="upload failed"):
        await create_part(
            filemaker,
            _settings(),
            _request(
                photoName="sample.jpg",
                photoMimeType="image/jpeg",
                photoBase64=base64.b64encode(b"jpeg-data").decode(),
            ),
            odata=FakeOData(),
            created_by="amy",
        )

    assert filemaker.deleted == [("@零件", "101")]


@pytest.mark.asyncio
async def test_create_requires_dedicated_feature_toggle() -> None:
    with pytest.raises(PartCreationError) as exc:
        await create_part(
            FakeFileMaker(),
            _settings(filemaker_part_create_enabled=False),
            _request(),
            odata=FakeOData(),
            created_by="amy",
        )

    assert exc.value.code == "PART_CREATE_DISABLED"


@pytest.mark.asyncio
async def test_validation_rejects_customer_code_without_internal_id_mapping() -> None:
    response = await validate_part_creation(
        FakeFileMaker(),
        _settings(),
        _request(),
        odata=FakeOData(customer_id=""),
    )

    assert response.valid is False
    assert "customerCode" in response.errors


@pytest.mark.asyncio
async def test_validation_rejects_unapproved_vendor() -> None:
    response = await validate_part_creation(
        FakeFileMaker(vendor_status="未审核"),
        _settings(),
        _request(),
        odata=FakeOData(),
    )

    assert response.valid is False
    assert response.errors["vendorId"] == "该厂商尚未审核，暂时不能用于建立零件。"


@pytest.mark.asyncio
async def test_validation_rejects_vendor_display_data_mismatch() -> None:
    response = await validate_part_creation(
        FakeFileMaker(),
        _settings(),
        _request(vendorName="旧厂商名称"),
        odata=FakeOData(),
    )

    assert response.valid is False
    assert "vendorId" in response.errors
