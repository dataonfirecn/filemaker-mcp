import json

import pytest
from fastapi import HTTPException

from app.api.material_ids import generate_material_id_for_filemaker
from app.core.config import Settings
from app.models.material_ids import MaterialIdGenerationRequest
from app.services.audit_log import AuditLogStore
from app.services.material_id_generator import (
    MaterialIdGenerationError,
    generate_material_id,
)
from app.services.webviewer_session import _b64encode, _sign, create_mock_context


class FakeFileMaker:
    def __init__(self, part_numbers: list[str]):
        self.part_numbers = part_numbers
        self.calls: list[dict[str, object]] = []

    async def find_records(
        self,
        layout,
        query=None,
        limit=100,
        offset=1,
        sort=None,
    ):
        assert layout == "@零件"
        self.calls.append(
            {
                "query": query,
                "limit": limit,
                "offset": offset,
                "sort": sort,
            }
        )
        criterion = str((query or {}).get("part_number") or "")
        if criterion.startswith("=="):
            expected = criterion[2:]
            matches = [value for value in self.part_numbers if value == expected]
        elif criterion.endswith("*"):
            prefix = criterion[:-1]
            matches = [value for value in self.part_numbers if value.startswith(prefix)]
        else:
            matches = []
        page = matches[offset - 1 : offset - 1 + limit]
        return {
            "data": [
                {"recordId": str(index + offset), "fieldData": {"part_number": value}}
                for index, value in enumerate(page)
            ],
            "foundCount": len(matches),
            "returnedCount": len(page),
        }


@pytest.mark.asyncio
async def test_auto_serial_matches_filemaker_rule_and_suffix_order() -> None:
    filemaker = FakeFileMaker(
        [
            "CB007-001",
            "CB007-007-LD",
            "CB007-010-BL",
            "CB007-ABC",
            "OTHER-999",
        ]
    )

    result = await generate_material_id(
        filemaker,
        MaterialIdGenerationRequest(
            material="CB",
            customer="007",
            manufacture="LD",
            color="BL",
            other="PS",
            scriptPartNumber="CB007-011-LD-BL-PS",
        ),
    )

    assert result.part_number == "CB007-011-LD-BL-PS"
    assert result.serial == "011"
    assert result.auto_serial is True
    assert result.matches_script is True
    assert result.scanned_count == 4


@pytest.mark.asyncio
async def test_first_auto_serial_is_001() -> None:
    result = await generate_material_id(
        FakeFileMaker([]),
        MaterialIdGenerationRequest(material="CB", customer="007"),
    )

    assert result.part_number == "CB007-001"
    assert result.serial == "001"
    assert result.matches_script is None


@pytest.mark.asyncio
async def test_manual_serial_is_preserved_for_compatibility() -> None:
    result = await generate_material_id(
        FakeFileMaker([]),
        MaterialIdGenerationRequest(
            material="CB",
            customer="007",
            serial="A12",
            color="BL",
        ),
    )

    assert result.part_number == "CB007-A12-BL"
    assert result.auto_serial is False
    assert result.scanned_count == 0


@pytest.mark.asyncio
async def test_duplicate_manual_number_is_rejected() -> None:
    with pytest.raises(MaterialIdGenerationError) as exc:
        await generate_material_id(
            FakeFileMaker(["CB007-015-BL"]),
            MaterialIdGenerationRequest(
                material="CB",
                customer="007",
                serial="015",
                color="BL",
            ),
        )

    assert exc.value.code == "duplicate_part_number"
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_serial_999_is_reported_as_exhausted() -> None:
    with pytest.raises(MaterialIdGenerationError) as exc:
        await generate_material_id(
            FakeFileMaker(["CB007-999"]),
            MaterialIdGenerationRequest(material="CB", customer="007"),
        )

    assert exc.value.code == "serial_exhausted"


@pytest.mark.asyncio
async def test_filemaker_direct_endpoint_verifies_signature_and_audits() -> None:
    settings = Settings(webviewer_context_secret="unit-test-secret")
    context = create_mock_context(
        operator_account="amy",
        operator_name="Amy",
        operator_privilege="filemaker",
    )
    ctx = _b64encode(json.dumps(context).encode("utf-8"))
    audit = AuditLogStore("memory://")

    response = await generate_material_id_for_filemaker(
        ctx=ctx,
        sig=_sign(ctx, settings.webviewer_context_secret),
        material="CB",
        customer="007",
        serial="",
        manufacture="",
        color="",
        other="",
        script_part_number="CB007-001",
        settings=settings,
        filemaker=FakeFileMaker([]),
        audit_log=audit,
    )

    assert response.part_number == "CB007-001"
    assert response.matches_script is True
    assert audit._memory_rows[0]["actionType"] == "GENERATE_MATERIAL_ID_FILEMAKER_API"
    assert audit._memory_rows[0]["operatorAccount"] == "amy"


@pytest.mark.asyncio
async def test_filemaker_direct_endpoint_rejects_invalid_signature() -> None:
    with pytest.raises(HTTPException) as exc:
        await generate_material_id_for_filemaker(
            ctx="invalid",
            sig="invalid",
            material="CB",
            customer="007",
            serial="",
            manufacture="",
            color="",
            other="",
            script_part_number="",
            settings=Settings(webviewer_context_secret="unit-test-secret"),
            filemaker=FakeFileMaker([]),
            audit_log=AuditLogStore("memory://"),
        )

    assert exc.value.status_code == 401
