from dataclasses import replace
import json

import pytest
from fastapi import HTTPException

from app.api.customer_chat import (
    bulk_disable_customer_accounts_admin,
    bulk_update_customer_account_status_admin,
    create_customer_account_admin,
    delete_customer_account_admin,
    get_customer_accounts_admin,
    update_customer_account_admin,
)
from app.core.config import Settings
from app.models.customer_chat_admin import (
    CustomerAccountAdminCreateRequest,
    CustomerAccountBulkDisableRequest,
    CustomerAccountBulkStatusRequest,
    CustomerAccountAdminUpdateRequest,
)
from app.services.customer_account_admin_store import CustomerAccountAdminStore
from app.services.customer_access import customer_access_permissions
from app.services.customer_access import (
    MAYAKO_CLIENT_NAME,
    MAYAKO_PART_CUSTOMER_ID,
    MAYAKO_PRODUCT_PRIVILEGE,
    MAYAKO_SHIPMENT_COMPANY_ID,
)
from app.services.customer_chat_auth import (
    CustomerAccount,
    CustomerAuthError,
    CustomerSession,
    customer_account_from_admin_state,
    hash_customer_password,
    issue_customer_token,
    verify_customer_token_with_store,
)
from app.services.customer_credential_store import CustomerCredentialStore


def _account(
    *,
    can_view_price: bool = False,
    access_role: str = "admin",
) -> CustomerAccount:
    return CustomerAccount(
        username="mayako",
        display_name="Mayako",
        email="mayako@example.com",
        client_name="Mayako",
        product_privilege="0780",
        part_customer_id="CU638",
        shipment_company_id=MAYAKO_SHIPMENT_COMPANY_ID,
        password_hash=hash_customer_password("test-password-value", iterations=100_000),
        can_view_price=can_view_price,
        is_admin=True,
        access_role=access_role,
    )


def _settings(account: CustomerAccount) -> Settings:
    return Settings(
        _env_file=None,
        customer_chat_enabled=True,
        customer_chat_token_secret="account-admin-test-secret-with-more-than-32-characters",
        customer_chat_accounts_json=json.dumps([{
            "username": account.username,
            "displayName": account.display_name,
            "email": account.email,
            "clientName": account.client_name,
            "productPrivilege": account.product_privilege,
            "partCustomerId": account.part_customer_id,
            "passwordHash": account.password_hash,
            "canViewPrice": account.can_view_price,
            "isAdmin": account.is_admin,
            "accessRole": account.access_role,
        }]),
    )


def _admin_session(*, can_view_price: bool = False) -> CustomerSession:
    return CustomerSession(
        session_id="admin-session",
        username="mayako",
        display_name="Mayako",
        client_name="Mayako",
        product_privilege="0780",
        part_customer_id="CU638",
        expires_at=9999999999,
        can_view_price=can_view_price,
        is_admin=True,
    )


def test_four_customer_access_roles_have_fixed_permissions() -> None:
    assert customer_access_permissions("admin") == {
        "canViewPrice": True,
        "canViewOrders": True,
        "canViewDetails": True,
        "isAdmin": True,
    }
    assert customer_access_permissions("manager") == {
        "canViewPrice": True,
        "canViewOrders": True,
        "canViewDetails": True,
        "isAdmin": False,
    }
    assert customer_access_permissions("team") == {
        "canViewPrice": False,
        "canViewOrders": True,
        "canViewDetails": True,
        "isAdmin": False,
    }
    assert customer_access_permissions("agent") == {
        "canViewPrice": False,
        "canViewOrders": False,
        "canViewDetails": False,
        "isAdmin": False,
    }


@pytest.mark.asyncio
async def test_account_store_updates_permissions_and_records_every_login_attempt() -> None:
    account = _account()
    store = CustomerAccountAdminStore("memory://")
    await store.init({"mayako": account})

    await store.record_login(
        "mayako", success=False, reason="invalid_credentials", client_ip="127.0.0.1"
    )
    await store.record_login(
        "mayako", success=True, reason="authenticated", client_ip="127.0.0.1"
    )
    updated = await store.update_account(
        "mayako", enabled=False, can_view_price=True, updated_by="admin"
    )

    assert updated is not None
    assert updated["enabled"] is False
    assert updated["canViewPrice"] is True
    assert updated["lastLoginAt"] is not None
    assert updated["lastSuccessfulLoginAt"] is not None
    assert updated["lastFailedLoginAt"] is not None
    assert updated["successfulLoginCount"] == 1
    assert updated["failedLoginCount"] == 1


@pytest.mark.asyncio
async def test_permission_change_and_disable_invalidate_existing_tokens(tmp_path) -> None:
    account = _account(access_role="team")
    settings = _settings(account)
    credential_store = CustomerCredentialStore(str(tmp_path / "credentials.db"))
    await credential_store.init()
    account_store = CustomerAccountAdminStore("memory://")
    await account_store.init({"mayako": account})
    token, _ = issue_customer_token(account, settings)

    verified = await verify_customer_token_with_store(
        token, settings, credential_store, account_store
    )
    assert verified.can_view_price is False

    await account_store.update_account(
        "mayako", enabled=True, can_view_price=True, updated_by="admin"
    )
    with pytest.raises(CustomerAuthError, match="account has changed"):
        await verify_customer_token_with_store(token, settings, credential_store, account_store)

    price_token, _ = issue_customer_token(replace(account, access_role="manager"), settings)
    assert (await verify_customer_token_with_store(
        price_token, settings, credential_store, account_store
    )).can_view_price is True

    await account_store.update_account(
        "mayako", enabled=False, can_view_price=True, updated_by="admin"
    )
    with pytest.raises(CustomerAuthError, match="disabled"):
        await verify_customer_token_with_store(price_token, settings, credential_store, account_store)


@pytest.mark.asyncio
async def test_admin_has_complete_account_crud_and_cannot_remove_self(tmp_path) -> None:
    account = _account()
    store = CustomerAccountAdminStore("memory://")
    await store.init({"mayako": account})
    credential_store = CustomerCredentialStore(str(tmp_path / "credentials.db"))
    await credential_store.init()

    class AuditLog:
        def __init__(self) -> None:
            self.rows = []

        async def record(self, **kwargs):
            self.rows.append(kwargs)

    audit_log = AuditLog()
    session = _admin_session()
    settings = _settings(account)
    created = await create_customer_account_admin(
        body=CustomerAccountAdminCreateRequest(
            username="dealer.one",
            displayName="Dealer One",
            email="dealer.one@example.com",
            password="dealer-password-value",
            enabled=True,
            accessRole="agent",
        ),
        session=session,
        account_admin_store=store,
        credential_store=credential_store,
        audit_log=audit_log,
        settings=settings,
    )
    response = await get_customer_accounts_admin(
        session=session,
        account_admin_store=store,
        settings=settings,
    )
    updated = await update_customer_account_admin(
        username="dealer.one",
        body=CustomerAccountAdminUpdateRequest(
            displayName="Dealer One Updated",
            enabled=True,
            accessRole="manager",
            newPassword="dealer-new-password",
        ),
        session=session,
        account_admin_store=store,
        credential_store=credential_store,
        audit_log=audit_log,
        settings=settings,
    )

    assert created.username == "dealer.one"
    assert created.client_name == MAYAKO_CLIENT_NAME
    assert created.product_privilege == MAYAKO_PRODUCT_PRIVILEGE
    assert created.part_customer_id == MAYAKO_PART_CUSTOMER_ID
    assert created.shipment_company_id == MAYAKO_SHIPMENT_COMPANY_ID
    assert len(response.accounts) == 2
    assert updated.display_name == "Dealer One Updated"
    assert updated.product_privilege == MAYAKO_PRODUCT_PRIVILEGE
    assert updated.access_role == "manager"
    assert updated.can_view_price is True
    assert updated.can_view_orders is True
    assert updated.is_admin is False
    assert await credential_store.get_password_hash("dealer.one") is not None

    delete_response = await delete_customer_account_admin(
        username="dealer.one",
        session=session,
        account_admin_store=store,
        credential_store=credential_store,
        audit_log=audit_log,
    )
    assert delete_response.status_code == 204
    assert await store.get_state("dealer.one") is None
    assert await credential_store.get_password_hash("dealer.one") is None
    assert [row["action_type"] for row in audit_log.rows] == [
        "CUSTOMER_ACCOUNT_CREATE",
        "CUSTOMER_ACCOUNT_UPDATE",
        "CUSTOMER_ACCOUNT_DELETE",
    ]

    with pytest.raises(HTTPException) as exc_info:
        await delete_customer_account_admin(
            username="mayako",
            session=session,
            account_admin_store=store,
            credential_store=credential_store,
            audit_log=audit_log,
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_runtime_created_account_can_be_verified_and_delete_invalidates_session(tmp_path) -> None:
    admin = _account()
    settings = _settings(admin)
    account_store = CustomerAccountAdminStore("memory://")
    await account_store.init({"mayako": admin})
    credential_store = CustomerCredentialStore(str(tmp_path / "credentials.db"))
    await credential_store.init()

    created = await account_store.create_account(
        username="dealer.two",
        display_name="Dealer Two",
        email="dealer.two@example.com",
        enabled=True,
        can_view_price=False,
        is_admin=False,
        updated_by="mayako",
    )
    password_hash = hash_customer_password("dealer-password-value", iterations=100_000)
    await credential_store.set_password_hash("dealer.two", password_hash)
    assert created is not None
    runtime_account = customer_account_from_admin_state(created, password_hash)
    token, _ = issue_customer_token(runtime_account, settings)

    verified = await verify_customer_token_with_store(
        token,
        settings,
        credential_store,
        account_store,
    )
    assert verified.username == "dealer.two"

    await account_store.delete_account("dealer.two", updated_by="mayako")
    with pytest.raises(CustomerAuthError, match="disabled"):
        await verify_customer_token_with_store(
            token,
            settings,
            credential_store,
            account_store,
        )


@pytest.mark.asyncio
async def test_legacy_quick_status_update_does_not_require_email(tmp_path) -> None:
    account = replace(_account(), email="")
    store = CustomerAccountAdminStore("memory://")
    await store.init({"mayako": account})
    credential_store = CustomerCredentialStore(str(tmp_path / "credentials.db"))
    await credential_store.init()

    class AuditLog:
        async def record(self, **kwargs):
            return None

    updated = await update_customer_account_admin(
        username="mayako",
        body=CustomerAccountAdminUpdateRequest(enabled=True, canViewPrice=True),
        session=_admin_session(),
        account_admin_store=store,
        credential_store=credential_store,
        audit_log=AuditLog(),
        settings=_settings(account),
    )

    assert updated.enabled is True
    assert updated.email == ""


@pytest.mark.asyncio
async def test_bulk_disable_updates_selected_accounts_and_preserves_roles() -> None:
    account = _account()
    store = CustomerAccountAdminStore("memory://")
    await store.init({"mayako": account})
    await store.create_account(
        username="team.one",
        display_name="Team One",
        email="team.one@example.com",
        enabled=True,
        access_role="team",
        updated_by="mayako",
    )
    await store.create_account(
        username="agent.one",
        display_name="Agent One",
        email="agent.one@example.com",
        enabled=True,
        access_role="agent",
        updated_by="mayako",
    )

    class AuditLog:
        def __init__(self) -> None:
            self.rows = []

        async def record(self, **kwargs):
            self.rows.append(kwargs)

    audit_log = AuditLog()
    response = await bulk_disable_customer_accounts_admin(
        body=CustomerAccountBulkDisableRequest(
            usernames=["team.one", "agent.one", "team.one"],
        ),
        session=_admin_session(),
        account_admin_store=store,
        audit_log=audit_log,
    )

    assert response.disabled_count == 2
    assert {item.username: item.access_role for item in response.accounts} == {
        "team.one": "team",
        "agent.one": "agent",
    }
    assert all(item.enabled is False for item in response.accounts)
    assert audit_log.rows[0]["action_type"] == "CUSTOMER_ACCOUNT_BULK_DISABLE"

    enabled_response = await bulk_update_customer_account_status_admin(
        body=CustomerAccountBulkStatusRequest(
            usernames=["team.one", "agent.one"],
            enabled=True,
        ),
        session=_admin_session(),
        account_admin_store=store,
        audit_log=audit_log,
    )

    assert enabled_response.updated_count == 2
    assert enabled_response.enabled is True
    assert all(item.enabled is True for item in enabled_response.accounts)
    assert {item.username: item.access_role for item in enabled_response.accounts} == {
        "team.one": "team",
        "agent.one": "agent",
    }
    assert audit_log.rows[1]["action_type"] == "CUSTOMER_ACCOUNT_BULK_ENABLE"
