import pytest
from fastapi import HTTPException

from app.api.natural_language_query import run_natural_language_query
from app.core.config import Settings
from app.models.natural_language_query import NaturalLanguageQueryRequest
from app.services.audit_log import OperatorContext
from app.services.dependencies import assert_webviewer_part_permission
from app.services.part_permission_catalog import (
    PART_PERMISSION_KEYS,
    permission_catalog,
)
from app.services.rag_semantic_registry import RagSemanticRegistry
from app.services.webviewer_account_access import (
    WebViewerAccountAccessStore,
    default_permissions_for_privilege_set,
    load_privilege_set_policies,
    sanitize_price_data,
)


@pytest.mark.asyncio
async def test_filemaker_privilege_set_is_inherited_and_can_be_overridden() -> None:
    store = WebViewerAccountAccessStore("memory://webviewer-access")
    await store.init()
    account = await store.observe_account(
        username="amy",
        display_name="Amy",
        privilege_set="Sales",
    )

    assert account["filemakerPrivilegeSet"] == "Sales"
    assert account["permissions"]["canViewProducts"] is True
    assert account["permissions"]["canViewPrice"] is False
    assert account["permissions"]["canManageAccounts"] is False

    privilege = await store.update_privilege_set(
        "Sales",
        enabled=True,
        permissions={**account["permissions"], "canViewPrice": True},
        updated_by="admin",
    )
    assert privilege is not None
    inherited = await store.get_account("amy")
    assert inherited is not None
    assert inherited["permissions"]["canViewPrice"] is True

    overridden = await store.update_account(
        "amy",
        enabled=True,
        permissions={**inherited["permissions"], "canViewPrice": False},
        updated_by="admin",
    )
    assert overridden is not None
    assert overridden["permissions"]["canViewPrice"] is False
    assert overridden["inheritsPrivilegeSet"] is False


@pytest.mark.asyncio
async def test_account_override_only_freezes_permissions_that_differ_from_set() -> None:
    store = WebViewerAccountAccessStore("memory://webviewer-diff-only")
    await store.init()
    account = await store.observe_account(
        username="amy",
        display_name="Amy",
        privilege_set="Sales",
    )

    updated = await store.update_account(
        "amy",
        enabled=True,
        permissions={**account["permissions"], "canViewPrice": True},
        updated_by="admin",
    )
    assert updated is not None
    assert updated["permissions"]["canViewPrice"] is True

    await store.update_privilege_set(
        "Sales",
        enabled=True,
        permissions={
            **account["permissions"],
            "canViewProducts": False,
        },
        updated_by="admin",
    )
    refreshed = await store.get_account("amy")

    assert refreshed is not None
    assert refreshed["permissions"]["canViewPrice"] is True
    assert refreshed["permissions"]["canViewProducts"] is False
    assert refreshed["inheritsPrivilegeSet"] is False


@pytest.mark.asyncio
async def test_full_access_privilege_bootstraps_account_admin() -> None:
    store = WebViewerAccountAccessStore("memory://webviewer-full")
    await store.init()
    account = await store.observe_account(
        username="admin",
        display_name="Administrator",
        privilege_set="[Full Access]",
    )

    assert account["permissions"]["canManageAccounts"] is True
    assert account["permissions"]["canViewPrice"] is True
    assert all(account["permissions"].values())
    assert all(account["partPermissions"].values())


@pytest.mark.asyncio
async def test_part_permissions_inherit_override_and_delete() -> None:
    store = WebViewerAccountAccessStore("memory://webviewer-part-access")
    await store.init()
    account = await store.observe_account(
        username="buyer",
        display_name="Buyer",
        privilege_set="採購助理_一般權限",
    )
    read_key = "part.procurement.quotations.read"
    approve_key = "part.procurement.quotations.approve"

    assert account["partPermissions"][read_key] is True
    assert account["partPermissions"][approve_key] is False
    assert account["inheritsPartPermissions"] is True

    updated = await store.update_account(
        "buyer",
        enabled=True,
        permissions=account["permissions"],
        part_permissions={
            **account["partPermissions"],
            approve_key: True,
        },
        updated_by="admin",
    )

    assert updated is not None
    assert updated["partPermissions"][approve_key] is True
    assert updated["inheritsPartPermissions"] is False

    deleted = await store.delete_account("buyer")
    assert deleted is not None
    assert await store.get_account("buyer") is None


def test_part_permission_catalog_has_six_groups_and_stable_keys() -> None:
    catalog = permission_catalog()

    assert [group["key"] for group in catalog["groups"]] == [
        "procurement",
        "business",
        "design",
        "quality",
        "warehouse",
        "laser",
    ]
    assert catalog["permissionCount"] == len(PART_PERMISSION_KEYS)
    assert len(PART_PERMISSION_KEYS) == len(set(PART_PERMISSION_KEYS))
    assert all(key.startswith("part.") for key in PART_PERMISSION_KEYS)


def test_exact_part_permission_is_enforced_server_side() -> None:
    permission = "part.design.drawings2d.publish"

    with pytest.raises(HTTPException) as denied:
        assert_webviewer_part_permission({permission: False}, permission)

    assert denied.value.status_code == 403
    assert denied.value.detail["permission"] == permission
    assert_webviewer_part_permission({permission: True}, permission)


def test_localized_full_access_privilege_bootstraps_account_admin() -> None:
    permissions = default_permissions_for_privilege_set("[完全访问权限]")

    assert permissions["canManageAccounts"] is True
    assert permissions["canViewPrice"] is True
    assert all(permissions.values())


@pytest.mark.asyncio
async def test_audited_filemaker_privilege_sets_seed_conservative_price_policy() -> None:
    policies = load_privilege_set_policies(
        "backend/config/webviewer_privilege_sets.json"
    )
    store = WebViewerAccountAccessStore("memory://filemaker-policy-seed")
    await store.init(seed_privilege_sets=policies)

    privilege_sets = {
        item["name"]: item for item in await store.list_privilege_sets()
    }

    assert len(privilege_sets) == 39
    assert privilege_sets["[完全访问权限]"]["permissions"]["canManageAccounts"]
    assert privilege_sets["業務部"]["permissions"]["canViewPrice"]
    assert privilege_sets["貿易產品入資料"]["permissions"]["canViewPrice"]
    assert privilege_sets["TW財務總監 访问权限"]["permissions"]["canViewPrice"]
    assert not privilege_sets["設計部"]["permissions"]["canViewPrice"]
    assert not privilege_sets["倉庫_組長"]["permissions"]["canViewPrice"]
    assert not privilege_sets["採購助理_一般權限"]["permissions"]["canViewPrice"]


@pytest.mark.asyncio
async def test_manual_privilege_policy_survives_configuration_resync() -> None:
    policies = load_privilege_set_policies(
        "backend/config/webviewer_privilege_sets.json"
    )
    store = WebViewerAccountAccessStore("memory://filemaker-policy-preserve")
    await store.init(seed_privilege_sets=policies)
    sales = next(item for item in policies if item["name"] == "業務部")
    await store.update_privilege_set(
        "業務部",
        enabled=True,
        permissions={
            **sales["permissions"],
            "canViewPrice": False,
        },
        updated_by="admin",
    )

    await store.init(seed_privilege_sets=policies)
    refreshed = next(
        item for item in await store.list_privilege_sets() if item["name"] == "業務部"
    )

    assert refreshed["permissions"]["canViewPrice"] is False
    assert refreshed["updatedBy"] == "admin"


def test_price_sanitizer_removes_nested_financial_fields_and_descriptors() -> None:
    payload = {
        "productSku": "STRX-202",
        "unitPrice": 25,
        "amount": 300,
        "permissions": {"canViewPrice": False},
        "raw": {
            "產品售價::Price": 25,
            "current_stock": 9,
            "成本价": 12,
        },
        "rows": [
            {"role": "finance", "source": "INDEX::BATCHPRICE", "label": "批次价格"},
            {"role": "quantity", "source": "current_stock", "label": "库存"},
        ],
    }

    cleaned = sanitize_price_data(payload)

    assert "unitPrice" not in cleaned
    assert "amount" not in cleaned
    assert cleaned["permissions"] == {"canViewPrice": False}
    assert cleaned["raw"] == {"current_stock": 9}
    assert cleaned["rows"] == [
        {"role": "quantity", "source": "current_stock", "label": "库存"}
    ]


def test_price_sanitizer_uses_explicit_aliases_for_misses_and_false_positives() -> None:
    registry = RagSemanticRegistry.from_mapping_path(
        "backend/config/semantic_mapping.json"
    )
    payload = {
        "說明書接單總價": 120,
        "內部估價": 80,
        "ProductPriceID": "PP-100",
        "關聯編號_Price": "REL-200",
    }

    cleaned = sanitize_price_data(payload, semantic_registry=registry)

    assert cleaned == {
        "ProductPriceID": "PP-100",
        "關聯編號_Price": "REL-200",
    }


@pytest.mark.parametrize(
    "prompt",
    [
        "STRX-202 的价格是多少",
        "STRX-202 多少钱",
        "STRX-202 的成本多少",
        "出货单 NB000001 的金额是多少",
        "出货单 NB000001 的运费是多少",
        "STRX-202 的报价给我看一下",
        "What is the unit cost of STRX-202?",
    ],
)
@pytest.mark.asyncio
async def test_internal_natural_query_rejects_price_without_permission(
    prompt: str,
) -> None:
    with pytest.raises(HTTPException) as exc:
        await run_natural_language_query(
            body=NaturalLanguageQueryRequest(prompt=prompt),
            filemaker=None,
            odata_client=None,
            rag_store=None,
            audit_log=None,
            conversation_store=None,
            analytics_worker=None,
            operator=OperatorContext(
                session_id="session",
                account="amy",
                name="Amy",
                privilege="Sales",
                permissions={"canViewPrice": False},
            ),
            settings=Settings(_env_file=None, natural_query_llm_enabled=False),
            enforced_product_client_id="",
            enforced_part_customer_id="",
        )

    assert exc.value.status_code == 403
    assert exc.value.detail["permission"] == "canViewPrice"
