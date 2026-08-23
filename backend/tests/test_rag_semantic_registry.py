from app.core.config import Settings
from app.services.rag_semantic_registry import RagSemanticRegistry


def test_registry_remembers_product_bom_primary_and_foreign_keys() -> None:
    registry = RagSemanticRegistry.from_mapping_path("backend/config/semantic_mapping.json")
    product = registry.entity_for_layout("@products")
    bom = registry.entity_for_layout("@product_bom")

    assert product is not None
    assert product.primary_keys == ("product_sku", "系統產品編號")
    assert bom is not None
    assert bom.primary_keys == ("ID",)
    assert [item.to_dict() for item in bom.foreign_keys] == [
        {
            "field": "ID_產品編號",
            "referencesEntity": "product",
            "referencesFields": ["product_sku", "系統產品編號"],
            "relationship": "product-bom-lines",
        },
        {
            "field": "零件編號",
            "referencesEntity": "part",
            "referencesFields": ["part_number"],
            "relationship": "bom-line-part",
        },
    ]


def test_registry_context_exposes_relationship_join_paths() -> None:
    registry = RagSemanticRegistry.from_mapping_path("backend/config/semantic_mapping.json")

    context = registry.context_for_layout("@product_bom")

    assert context["entity"]["indexFields"][:3] == ["ID", "ID_產品編號", "零件編號"]
    relationships = {item["name"]: item for item in context["relationships"]}
    assert relationships["product-bom-lines"]["joins"][0] == {
        "fromField": "product_sku",
        "toField": "ID_產品編號",
    }
    assert relationships["bom-line-part"]["joins"][0] == {
        "fromField": "零件編號",
        "toField": "part_number",
    }


def test_registry_uses_minimal_record_cache_fields_but_keeps_profile_fields() -> None:
    registry = RagSemanticRegistry.from_mapping_path("backend/config/semantic_mapping.json")
    product = registry.entity_for_layout("@products")
    part = registry.entity_for_layout("@零件")

    assert product is not None
    assert product.record_cache_fields == [
        "product_sku",
        "系統產品編號",
        "product_name",
        "產品名稱_中文",
    ]
    assert "stock" in product.index_fields
    assert "stock" not in product.record_cache_fields
    assert part is not None
    assert part.record_cache_fields == [
        "part_number",
        "part_name_internal",
        "part_name_external",
        "part_name_en",
        "customer_part_number",
    ]


def test_hybrid_defaults_only_cache_product_and_part_records() -> None:
    settings = Settings(_env_file=None)

    assert settings.rag_index_layout_include == "@products_RAG,@零件_RAG"
    assert settings.natural_query_use_cached_records is False
    assert settings.filemaker_odata_enabled is True


def test_registry_exposes_canonical_financial_fields_and_price_policy() -> None:
    registry = RagSemanticRegistry.from_mapping_path("backend/config/semantic_mapping.json")

    order_amount = registry.field_semantic(
        "貨款總和_price",
        layout="@mayako",
    )
    internal_estimate = registry.field_semantic(
        "內部估價",
        layout="@零件成本",
    )
    price_identifier = registry.field_semantic(
        "ProductPriceID",
        layout="@ProductPriceCustomer",
    )

    assert order_amount is not None
    assert order_amount.canonical_field == "amount_order_customer_po"
    assert order_amount.is_price_restricted
    assert internal_estimate is not None
    assert internal_estimate.canonical_field == "cost_internal_estimate"
    assert internal_estimate.is_price_restricted
    assert price_identifier is not None
    assert price_identifier.canonical_field == "id_product_price"
    assert not price_identifier.is_price_restricted


def test_all_restricted_financial_aliases_use_a_semantic_prefix() -> None:
    registry = RagSemanticRegistry.from_mapping_path("backend/config/semantic_mapping.json")
    allowed_prefixes = ("price_", "cost_", "amount_", "fee_", "value_", "rate_")

    assert registry.field_semantics
    assert all(
        item.canonical_field.startswith(allowed_prefixes)
        for item in registry.field_semantics
        if item.is_price_restricted
    )
