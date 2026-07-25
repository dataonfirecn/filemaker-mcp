import base64

import pytest

from app.core.config import Settings
from app.models.part_creation import PartCreationRequest
from app.services.part_creation import (
    PartCreationError,
    create_part,
    load_part_creation_options,
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
    def __init__(self, *, duplicate=False, upload_error=False):
        self.duplicate = duplicate
        self.upload_error = upload_error
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
        "materialCategory": "CB",
        "departmentDivision": "采购",
        "partCategory": "底板",
        "materialProperties": "原材料",
        "weightGrams": "12.5",
        "customerId": "0840",
        "customerName": "Army Racing",
    }
    values.update(overrides)
    return PartCreationRequest(**values)


@pytest.mark.asyncio
async def test_options_are_loaded_from_native_new_part_layout() -> None:
    options = await load_part_creation_options(FakeFileMaker(), _settings())

    assert [item.code for item in options.warehouse_divisions] == ["发料", "不发料"]
    assert options.material_categories[0].label == "碳纤维"
    assert options.exclusive_customers[0].code == "0840"
    assert options.exclusive_customers[0].label == "Army Racing"
    assert options.defaults.department_division == "采购"
    assert options.generator.customers[0].code == "007"


@pytest.mark.asyncio
async def test_validation_rejects_placeholder_duplicate_and_stale_option() -> None:
    response = await validate_part_creation(
        FakeFileMaker(duplicate=True),
        _settings(),
        _request(
            internalName="新零件，請填寫正確中文名稱＆詳細資訊",
            warehouseDivision="已删除选项",
        ),
    )

    assert response.valid is False
    assert "internalName" in response.errors
    assert "warehouseDivision" in response.errors
    assert "partNumber" in response.errors


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
    )

    assert response.record_id == "101"
    assert response.part_id == "P-101"
    assert response.photo_uploaded is True
    assert filemaker.created_fields["倉庫分工"] == "发料"
    assert filemaker.created_fields["material_category"] == "CB"
    assert filemaker.created_fields["customer_id"] == "0840"
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
        )

    assert filemaker.deleted == [("@零件", "101")]


@pytest.mark.asyncio
async def test_create_requires_dedicated_feature_toggle() -> None:
    with pytest.raises(PartCreationError) as exc:
        await create_part(
            FakeFileMaker(),
            _settings(filemaker_part_create_enabled=False),
            _request(),
        )

    assert exc.value.code == "PART_CREATE_DISABLED"
