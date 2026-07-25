import pytest

from app.services.odata_relationship_registry import ODataRelationshipExecutor, ODataRelationshipRegistry


class SettingsStub:
    filemaker_odata_max_top = 10


class FakeODataClient:
    settings = SettingsStub()

    def __init__(self):
        self.calls = []

    async def records(
        self,
        table,
        *,
        select=None,
        filter_expr=None,
        top=10,
        count=True,
        **_kwargs,
    ):
        self.calls.append(
            {
                "table": table,
                "select": select,
                "filter": filter_expr,
                "top": top,
                "count": count,
            }
        )
        if table == "零件":
            return {
                "rows": [
                    {
                        "part_number": "M01-012",
                        "stock_on_hand_qty": 3,
                    }
                ]
            }
        if table == "零件关联产品":
            return {
                "rows": [
                    {"ID_零件": "M01-012", "ID_产品": "PLM01-012-01"},
                    {"ID_零件": "M01-012", "ID_产品": "PLM01-012-02"},
                ]
            }
        if table == "產品":
            return {"rows": []}
        return {"rows": []}


@pytest.mark.asyncio
async def test_builtin_part_products_relationship_returns_linked_product_ids() -> None:
    client = FakeODataClient()
    registry = ODataRelationshipRegistry()
    relationship = registry.get("part-products")

    result = await ODataRelationshipExecutor(client, registry).query(
        relationship,
        value="M01-012",
        top=10,
    )

    assert result["targetIds"] == ["PLM01-012-01", "PLM01-012-02"]
    assert result["sourceRows"] == [{"part_number": "M01-012", "stock_on_hand_qty": 3}]
    assert result["foundCount"] == 2
    assert result["warnings"] == [
        "已找到关联编号，但目标表没有匹配到详情记录；结果先返回关联表中的目标编号。"
    ]
    assert client.calls[1]["table"] == "零件关联产品"
    assert client.calls[1]["filter"] == "ID_零件 eq 'M01-012'"


def test_relationship_registry_loads_json_mapping(tmp_path) -> None:
    mapping = tmp_path / "semantic_mapping.json"
    mapping.write_text(
        """
        {
          "version": "unit",
          "entities": [{"name": "part"}],
          "queryStrategies": [{"intent": "part_related_products"}],
          "relationships": [
            {
              "name": "custom-part-products",
              "label": "自定义零件产品关系",
              "from": {"table": "零件", "field": "part_number"},
              "through": {"table": "零件关联产品", "fromField": "ID_零件", "toField": "ID_产品"},
              "to": {"table": "產品", "lookupFields": ["product_sku"]},
              "sourceSelectFields": ["part_number"],
              "targetSelectFields": ["product_sku"],
              "confidence": 0.88,
              "source": "unit"
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    registry = ODataRelationshipRegistry.from_mapping_path(str(mapping))
    relationship = registry.get("custom-part-products")

    assert relationship is not None
    assert relationship.source == "unit"
    assert relationship.confidence == 0.88
    assert relationship.target_lookup_fields == ["product_sku"]
    assert registry.metadata()["mappingSource"] == "file"
    assert registry.metadata()["entityCount"] == 1
    assert registry.metadata()["queryStrategyCount"] == 1


def test_relationship_registry_falls_back_when_json_missing(tmp_path) -> None:
    registry = ODataRelationshipRegistry.from_mapping_path(str(tmp_path / "missing.json"))

    assert registry.get("part-products") is not None
    assert registry.metadata()["mappingSource"] == "builtin"
    assert registry.metadata()["warnings"]
