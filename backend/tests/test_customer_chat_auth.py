import json
from datetime import date
from types import SimpleNamespace

import pytest

from fastapi import HTTPException
import app.api.customer_chat as customer_chat_api

from app.api.customer_chat import (
    _customer_product_asset_url,
    _customer_prompt_domain,
    _customer_identifier_clarification,
    _customer_query_identifier,
    _customer_english_text,
    _customer_order_search,
    _customer_order_query_plan,
    _customer_query_answer,
    _customer_query_validation_message,
    _normalize_customer_prompt,
    _resolve_customer_identifier_domain,
    _validate_customer_prompt,
    _validate_customer_sensitive_prompt,
    change_customer_password,
    query_customer_products,
)
from app.api.natural_language_query import (
    _apply_customer_scope,
    _force_exact_customer_identifier,
    _is_scoped_customer_listing,
)
from app.core.config import Settings
from app.models.customer_chat import (
    CustomerOrderResult,
    CustomerPasswordChangeRequest,
    CustomerProductResult,
    CustomerQueryRequest,
)
from app.services.customer_chat_auth import (
    CustomerAccount,
    CustomerAuthError,
    CustomerLoginRateLimiter,
    CustomerSession,
    authenticate_customer,
    hash_customer_password,
    issue_customer_token,
    validate_customer_chat_configuration,
    verify_customer_password,
    verify_customer_token,
)
from app.services.customer_account_admin_store import CustomerAccountAdminStore
from app.services.customer_credential_store import CustomerCredentialStore
from app.services.customer_chat_history import CustomerChatHistoryStore
from app.services.natural_language_query import NaturalQueryError


def _settings(password_hash: str) -> Settings:
    return Settings(
        _env_file=None,
        customer_chat_enabled=True,
        customer_chat_token_secret="customer-token-secret-with-more-than-32-characters",
        customer_chat_session_ttl_seconds=3600,
        customer_chat_accounts_json=json.dumps(
            [
                {
                    "username": "acme",
                    "displayName": "ACME",
                    "clientName": "Mayako",
                    "productPrivilege": "0780",
                    "partCustomerId": "CU638",
                    "shipmentCompanyId": "0E254109-8698-4F5D-BE70-ABFD2B929CE9",
                    "passwordHash": password_hash,
                }
            ]
        ),
    )


def test_customer_password_hash_and_authentication() -> None:
    password_hash = hash_customer_password("correct horse battery staple", iterations=100_000)
    settings = _settings(password_hash)

    assert verify_customer_password("correct horse battery staple", password_hash) is True
    assert verify_customer_password("wrong", password_hash) is False
    assert authenticate_customer("ACME", "correct horse battery staple", settings) is not None
    assert authenticate_customer("acme", "wrong", settings) is None


def test_customer_token_round_trip_and_tamper_rejection() -> None:
    password_hash = hash_customer_password("secret-value", iterations=100_000)
    settings = _settings(password_hash)
    account = CustomerAccount(
        username="acme",
        display_name="ACME",
        client_name="Mayako",
        product_privilege="0780",
        part_customer_id="CU638",
        password_hash=password_hash,
        shipment_company_id="0E254109-8698-4F5D-BE70-ABFD2B929CE9",
    )
    token, issued = issue_customer_token(account, settings)
    verified = verify_customer_token(token, settings)

    assert verified.session_id == issued.session_id
    assert verified.client_name == "Mayako"
    assert verified.product_privilege == "0780"
    assert verified.part_customer_id == "CU638"
    assert verified.shipment_company_id == "0E254109-8698-4F5D-BE70-ABFD2B929CE9"
    assert verified.can_view_price is False
    assert verified.is_admin is False
    assert verified.operator.privilege == "external_customer"
    with pytest.raises(CustomerAuthError):
        verify_customer_token(token + "tampered", settings)

    changed_account_settings = _settings(hash_customer_password("new-secret", iterations=100_000))
    with pytest.raises(CustomerAuthError, match="customer account has changed"):
        verify_customer_token(token, changed_account_settings)


def test_customer_configuration_requires_strong_secret_and_accounts() -> None:
    settings = Settings(
        _env_file=None,
        customer_chat_enabled=True,
        customer_chat_token_secret="change-me",
        customer_chat_accounts_json="[]",
    )

    problems = validate_customer_chat_configuration(settings)

    assert any("TOKEN_SECRET" in item for item in problems)
    assert any("at least one external customer account" in item for item in problems)


@pytest.mark.asyncio
async def test_customer_password_change_persists_and_invalidates_old_session(tmp_path) -> None:
    old_password = "old-password-value"
    new_password = "new-password-value"
    settings = _settings(hash_customer_password(old_password, iterations=100_000))
    account = authenticate_customer("acme", old_password, settings)
    assert account is not None
    old_token, session = issue_customer_token(account, settings)
    store = CustomerCredentialStore(str(tmp_path / "app.db"))
    await store.init()
    account_store = CustomerAccountAdminStore("memory://")
    await account_store.init({"acme": account})

    class AuditLog:
        def __init__(self) -> None:
            self.rows = []

        async def record(self, **kwargs):
            self.rows.append(kwargs)

    audit_log = AuditLog()
    response = await change_customer_password(
        body=CustomerPasswordChangeRequest(
            oldPassword=old_password,
            newPassword=new_password,
            confirmNewPassword=new_password,
        ),
        session=session,
        settings=settings,
        credential_store=store,
        account_admin_store=account_store,
        audit_log=audit_log,
    )

    override = await store.get_password_hash("ACME")
    assert override is not None
    assert authenticate_customer(
        "acme",
        old_password,
        settings,
        password_hash_override=override,
    ) is None
    assert authenticate_customer(
        "acme",
        new_password,
        settings,
        password_hash_override=override,
    ) is not None
    with pytest.raises(CustomerAuthError, match="customer account has changed"):
        verify_customer_token(
            old_token,
            settings,
            password_hash_override=override,
        )
    renewed = verify_customer_token(
        response.token,
        settings,
        password_hash_override=override,
    )
    assert renewed.username == "acme"
    assert response.message == "Your password has been changed."
    assert audit_log.rows[-1]["action_type"] == "CUSTOMER_PASSWORD_CHANGE"
    assert audit_log.rows[-1]["status"] == "success"


@pytest.mark.asyncio
async def test_customer_password_change_rejects_wrong_current_password(tmp_path) -> None:
    old_password = "old-password-value"
    settings = _settings(hash_customer_password(old_password, iterations=100_000))
    account = authenticate_customer("acme", old_password, settings)
    assert account is not None
    _, session = issue_customer_token(account, settings)
    store = CustomerCredentialStore(str(tmp_path / "app.db"))
    await store.init()
    account_store = CustomerAccountAdminStore("memory://")
    await account_store.init({"acme": account})

    class AuditLog:
        async def record(self, **kwargs):
            return kwargs

    with pytest.raises(HTTPException) as exc_info:
        await change_customer_password(
            body=CustomerPasswordChangeRequest(
                oldPassword="incorrect-password",
                newPassword="new-password-value",
                confirmNewPassword="new-password-value",
            ),
            session=session,
            settings=settings,
            credential_store=store,
            account_admin_store=account_store,
            audit_log=AuditLog(),
        )

    assert exc_info.value.status_code == 400
    assert "current password is incorrect" in exc_info.value.detail["message"].lower()
    assert await store.get_password_hash("acme") is None


@pytest.mark.asyncio
async def test_customer_credential_store_compare_and_set_prevents_stale_overwrite(tmp_path) -> None:
    store = CustomerCredentialStore(str(tmp_path / "app.db"))
    await store.init()

    assert await store.compare_and_set_password_hash(
        "acme",
        expected_override_hash=None,
        new_password_hash="hash-one",
    ) is True
    assert await store.compare_and_set_password_hash(
        "acme",
        expected_override_hash=None,
        new_password_hash="hash-two",
    ) is False
    assert await store.compare_and_set_password_hash(
        "acme",
        expected_override_hash="stale-hash",
        new_password_hash="hash-three",
    ) is False
    assert await store.get_password_hash("acme") == "hash-one"


def test_customer_product_asset_requires_exact_source_customer_and_visibility() -> None:
    product_fields = {"id_client": "CU638"}
    asset_fields = {
        "source_record_id": "15572",
        "id_client_snapshot": "CU638",
        "asset_type": "product_image",
        "visibility": "customer",
        "migration_status": "copied",
        "asset_file": "https://filemaker.example/image.jpg",
    }

    assert _customer_product_asset_url(
        record_id="15572",
        client_id="CU638",
        product_fields=product_fields,
        asset_fields=asset_fields,
    ) == "https://filemaker.example/image.jpg"

    with pytest.raises(HTTPException) as exc_info:
        _customer_product_asset_url(
            record_id="15573",
            client_id="CU638",
            product_fields=product_fields,
            asset_fields=asset_fields,
        )

    assert exc_info.value.status_code == 404


def test_customer_scope_overrides_prompt_client_on_every_or_branch() -> None:
    plan = SimpleNamespace(
        domain="product",
        description="关键词：STRX-202；客户包含“OTHER”",
        filters={"client": "OTHER"},
        query=[
            {"product_sku": "==STRX-202", "Client": "*OTHER*"},
            {"product_name": "*STRX-202*", "Client": "*OTHER*"},
        ],
    )

    _apply_customer_scope(plan, "CU638")

    assert "client" not in plan.filters
    assert "audit" not in plan.filters
    assert plan.filters["productClientId"] == "CU638"
    assert plan.description == "关键词：STRX-202；您的可见范围"
    assert all(item["id_client"] == "==CU638" for item in plan.query)
    assert all("Client" not in item and "審核" not in item for item in plan.query)
    assert all(item.get("omit") != "true" for item in plan.query)
    assert plan.sort == [{"fieldName": "product_sku", "sortOrder": "ascend"}]


def test_customer_scope_discards_relationship_only_or_branch() -> None:
    plan = SimpleNamespace(
        domain="product",
        description="关键词：buggy",
        filters={},
        query=[
            {"product_name": "*buggy*"},
            {"Client": "*buggy*"},
            {"產品名稱_中文": "*buggy*"},
            {"Category_Product_1::title": "*buggy*"},
        ],
        sort=[],
    )

    _apply_customer_scope(plan, "CU638", "CU638")

    assert plan.query == [{"product_name": "*buggy*", "id_client": "==CU638"}]


def test_customer_scope_rejects_query_if_only_scope_fields_remain() -> None:
    plan = SimpleNamespace(
        domain="product",
        description="客户过滤",
        filters={"client": "OTHER"},
        query=[{"Client": "*OTHER*"}],
        sort=[],
    )

    with pytest.raises(NaturalQueryError, match="Please search"):
        _apply_customer_scope(plan, "CU638", "CU638")


def test_customer_part_scope_searches_only_customer_visible_fields() -> None:
    plan = SimpleNamespace(
        domain="part",
        description="关键词：carbon",
        filters={},
        query=[
            {"part_number": "==carbon"},
            {"part_name_en": "*carbon*"},
            {"part_name": "*carbon*"},
            {"Notes": "*carbon*"},
        ],
        sort=[],
    )

    _apply_customer_scope(plan, "CU638", "CU638")

    assert plan.query == [
        {"part_number": "==carbon", "customer_id": "==CU638"},
        {"part_name_en": "*carbon*", "customer_id": "==CU638"},
    ]


def test_customer_scope_forces_part_customer_id_on_every_branch() -> None:
    plan = SimpleNamespace(
        domain="part",
        description="零件资料；客户包含 OTHER",
        filters={"client": "OTHER"},
        query=[
            {"part_number": "*AL*", "customer_id": "==OTHER"},
            {"part_name": "*AL*", "omit": "true"},
        ],
        sort=[],
    )

    _apply_customer_scope(plan, "CU638", "CU638")

    assert plan.filters == {"partCustomerId": "CU638"}
    assert all(item["customer_id"] == "==CU638" for item in plan.query)
    assert all(item.get("omit") != "true" for item in plan.query)
    assert plan.sort == [{"fieldName": "part_number", "sortOrder": "ascend"}]


def test_customer_scope_rejects_part_query_without_part_customer_id() -> None:
    plan = SimpleNamespace(domain="part", description="零件资料", filters={}, query=[])

    with pytest.raises(NaturalQueryError):
        _apply_customer_scope(plan, "CU638")


@pytest.mark.asyncio
async def test_customer_login_rate_limiter_clears_after_success() -> None:
    limiter = CustomerLoginRateLimiter()
    for _ in range(2):
        await limiter.record_failure("client:acme", window_seconds=60)

    assert await limiter.retry_after("client:acme", max_attempts=2, window_seconds=60) > 0
    await limiter.clear("client:acme")
    assert await limiter.retry_after("client:acme", max_attempts=2, window_seconds=60) == 0


@pytest.mark.parametrize(
    "prompt",
    [
        "这个产品价格多少",
        "请给我单价",
        "成本报价是多少",
        "show unit price",
        "quotation for MYB0377-24",
    ],
)
def test_customer_query_rejects_price_and_cost_prompts(prompt: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _validate_customer_prompt(prompt)

    assert exc_info.value.status_code == 403
    assert (
        "does not have permission" in exc_info.value.detail["message"]
        or "not available" in exc_info.value.detail["message"]
    )


@pytest.mark.parametrize("prompt", ["这个产品价格多少", "请给我单价", "show unit price"])
def test_customer_price_prompts_are_allowed_for_price_enabled_accounts(prompt: str) -> None:
    _validate_customer_prompt(prompt, can_view_price=True)


@pytest.mark.parametrize("prompt", ["成本是多少", "给我报价", "show cost", "quotation"])
def test_customer_cost_and_quotation_prompts_remain_blocked_for_price_enabled_accounts(
    prompt: str,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _validate_customer_prompt(prompt, can_view_price=True)

    assert exc_info.value.status_code == 403


def test_customer_query_rejects_internal_prompts() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _validate_customer_prompt("查询这个产品的供应商和采购资料")

    assert exc_info.value.status_code == 403
    assert "not available" in exc_info.value.detail["message"]


def test_customer_price_permission_message_is_explicit() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _validate_customer_sensitive_prompt("What is the price for MYB0196?", can_view_price=False)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {
        "message": "Your account does not have permission to view prices.",
        "code": "price_permission",
    }


def test_customer_price_query_identifier_requires_an_item_number() -> None:
    assert _customer_query_identifier("Show unit price") is None
    assert _customer_query_identifier("What is the unit price for MYB0196?") == "MYB0196"
    assert _customer_query_identifier("零件 AL05249-TW-LD 的价格") == "AL05249-TW-LD"


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("AL050013-00", None),
        ("Check inventory for AL050013-00", None),
        ("查询零件 AL050013-00", "part"),
        ("Check part inventory for AL050013-00", "part"),
        ("查询产品 MYB0196", "product"),
        ("Check product inventory for MYB0196", "product"),
        ("Is AL050013-00 a product or part?", None),
    ],
)
def test_customer_prompt_domain_requires_an_explicit_unambiguous_domain(
    prompt: str,
    expected: str | None,
) -> None:
    assert _customer_prompt_domain(prompt) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("product_found", "part_found", "expected"),
    [
        (1, 0, "product"),
        (0, 1, "part"),
        (1, 1, "ambiguous"),
        (0, 0, "not_found"),
    ],
)
async def test_customer_unlabeled_identifier_searches_both_scoped_catalogs(
    product_found: int,
    part_found: int,
    expected: str,
) -> None:
    class FakeFileMaker:
        def __init__(self) -> None:
            self.calls = []

        async def find_records(self, layout, query=None, limit=100):
            self.calls.append((layout, query, limit))
            return {
                "data": [],
                "foundCount": product_found if layout == "@products" else part_found,
                "returnedCount": 0,
            }

    filemaker = FakeFileMaker()
    resolution = await _resolve_customer_identifier_domain(
        filemaker,
        "AL050013-00",
        customer_id="CU638",
    )

    assert resolution == expected
    assert filemaker.calls == [
        (
            "@products",
            {"product_sku": "==AL050013-00", "id_client": "==CU638"},
            1,
        ),
        (
            "Parts",
            {"part_number": "==AL050013-00", "customer_id": "==CU638"},
            1,
        ),
    ]


@pytest.mark.asyncio
async def test_customer_bare_part_identifier_is_routed_to_part_query(monkeypatch) -> None:
    class FakeFileMaker:
        async def find_records(self, layout, query=None, limit=100):
            return {
                "data": [],
                "foundCount": 1 if layout == "Parts" else 0,
                "returnedCount": 0,
            }

    captured = {}

    async def fake_query(**kwargs):
        captured["prompt"] = kwargs["body"].prompt
        return SimpleNamespace(
            plan=SimpleNamespace(domain="part"),
            rows=[],
            found_count=0,
            requires_clarification=False,
            clarification_options=[],
        )

    monkeypatch.setattr(customer_chat_api, "run_natural_language_query", fake_query)
    session = CustomerSession(
        session_id="session",
        username="acme",
        display_name="ACME",
        client_name="ACME",
        product_privilege="0780",
        part_customer_id="CU638",
        expires_at=9999999999,
    )
    history_store = CustomerChatHistoryStore("memory://")

    response = await query_customer_products(
        body=CustomerQueryRequest(prompt="AL050013-00"),
        request=SimpleNamespace(headers={}),
        session=session,
        filemaker=FakeFileMaker(),
        odata_client=None,
        rag_store=None,
        audit_log=None,
        conversation_store=None,
        history_store=history_store,
        settings=Settings(_env_file=None),
    )

    assert captured["prompt"] == "零件 AL050013-00"
    assert response.result_type == "part"
    rows, total = await history_store.list_history(include_tests=True)
    assert total == 1
    assert rows[0]["prompt"] == "AL050013-00"
    assert rows[0]["domain"] == "part"


@pytest.mark.asyncio
async def test_customer_unknown_identifier_asks_user_for_domain(monkeypatch) -> None:
    class FakeFileMaker:
        async def find_records(self, layout, query=None, limit=100):
            return {"data": [], "foundCount": 0, "returnedCount": 0}

    async def unexpected_query(**kwargs):
        raise AssertionError("The normal query must wait for the user's domain choice")

    monkeypatch.setattr(customer_chat_api, "run_natural_language_query", unexpected_query)
    session = CustomerSession(
        session_id="session",
        username="acme",
        display_name="ACME",
        client_name="ACME",
        product_privilege="0780",
        part_customer_id="CU638",
        expires_at=9999999999,
    )
    history_store = CustomerChatHistoryStore("memory://")

    response = await query_customer_products(
        body=CustomerQueryRequest(prompt="UNKNOWN-404"),
        request=SimpleNamespace(headers={}),
        session=session,
        filemaker=FakeFileMaker(),
        odata_client=None,
        rag_store=None,
        audit_log=None,
        conversation_store=None,
        history_store=history_store,
        settings=Settings(_env_file=None),
    )

    assert response.requires_clarification is True
    assert response.clarification_question == "Is UNKNOWN-404 a product or a part?"
    assert response.clarification_options == [
        "Search product UNKNOWN-404",
        "Search part UNKNOWN-404",
    ]
    rows, total = await history_store.list_history(include_tests=True)
    assert total == 1
    assert rows[0]["status"] == "clarification"
    assert rows[0]["domain"] == "unknown"


def test_customer_identifier_clarification_preserves_price_intent() -> None:
    response = _customer_identifier_clarification(
        CustomerQueryRequest(prompt="What is the price for SHARED-001?"),
        "SHARED-001",
        matched_both=True,
        asks_for_price=True,
    )

    assert response.answer.startswith("SHARED-001 exists in both")
    assert response.clarification_options == [
        "What is the unit price for product SHARED-001?",
        "What is the unit price for part SHARED-001?",
    ]


@pytest.mark.asyncio
async def test_customer_price_query_is_blocked_and_recorded_without_permission() -> None:
    history_store = CustomerChatHistoryStore("memory://")
    session = CustomerSession(
        session_id="session",
        username="acme",
        display_name="ACME",
        client_name="ACME",
        product_privilege="0780",
        part_customer_id="CU638",
        expires_at=9999999999,
    )

    with pytest.raises(HTTPException) as exc_info:
        await query_customer_products(
            body=CustomerQueryRequest(prompt="What is the unit price for MYB0196?"),
            request=SimpleNamespace(headers={}),
            session=session,
            filemaker=None,
            odata_client=None,
            rag_store=None,
            audit_log=None,
            conversation_store=None,
            history_store=history_store,
            settings=None,
        )

    rows, total = await history_store.list_history(include_tests=True)
    assert exc_info.value.status_code == 403
    assert total == 1
    assert rows[0]["status"] == "blocked"
    assert rows[0]["blockedReason"] == "price_permission"


@pytest.mark.asyncio
async def test_customer_price_query_returns_product_price_for_authorized_account(monkeypatch) -> None:
    async def fake_query(**kwargs):
        return SimpleNamespace(
            plan=SimpleNamespace(domain="product"),
            rows=[SimpleNamespace(
                record_id="123",
                product_sku="MYB0196",
                product_name="Mayako Product",
                model_name="MX8",
                scale="1:8",
                category="Buggy",
                stock=6,
                image_url="",
                raw={"系統產品編號": "MYB0196"},
            )],
            found_count=1,
            requires_clarification=False,
            clarification_options=[],
        )

    async def fake_price(*args, **kwargs):
        return {"data": [{"fieldData": {"產品編號": "MYB0196", "Price": 1.9}}]}

    class FakeFileMaker:
        async def find_records(self, layout, query=None, limit=100):
            return {
                "data": [],
                "foundCount": 1 if layout == "@products" else 0,
                "returnedCount": 0,
            }

    monkeypatch.setattr(customer_chat_api, "run_natural_language_query", fake_query)
    monkeypatch.setattr(customer_chat_api, "find_product_price", fake_price)
    session = CustomerSession(
        session_id="session",
        username="acme",
        display_name="ACME",
        client_name="ACME",
        product_privilege="0780",
        part_customer_id="CU638",
        expires_at=9999999999,
        can_view_price=True,
    )

    response = await query_customer_products(
        body=CustomerQueryRequest(prompt="What is the unit price for MYB0196?"),
        request=SimpleNamespace(headers={}),
        session=session,
        filemaker=FakeFileMaker(),
        odata_client=None,
        rag_store=None,
        audit_log=None,
        conversation_store=None,
        history_store=CustomerChatHistoryStore("memory://"),
        settings=None,
    )

    assert response.answer == "The unit price for MYB0196 is 1.9."
    assert response.rows[0].price == 1.9


@pytest.mark.parametrize("prompt", ["Hello", "What is the weather today?", "今天天气如何"])
def test_customer_query_rejects_greetings_and_out_of_scope_questions(prompt: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        _validate_customer_prompt(prompt)

    assert exc_info.value.status_code == 422
    assert "product or part" in exc_info.value.detail["message"]


def test_customer_date_query_error_reports_actual_catalog_limitation() -> None:
    exc = HTTPException(
        status_code=422,
        detail={"message": "FileMaker 日期查询字段“创建日期”不可用。"},
    )

    assert _customer_query_validation_message(exc) == (
        "Creation-date search is not available for this catalog."
    )


def test_customer_basic_list_prompt_is_normalized_for_scoped_listing() -> None:
    assert _normalize_customer_prompt("查看产品清单") == "产品"
    assert _normalize_customer_prompt("查询库存？") == "产品"
    assert _normalize_customer_prompt("查询 MYB0377-24 库存") == "查询 MYB0377-24 库存"
    assert _normalize_customer_prompt("View product list") == "产品"
    assert _normalize_customer_prompt("Show me all products") == "产品"
    assert _normalize_customer_prompt("What products do you have?") == "产品"
    assert _normalize_customer_prompt("View inventory") == "产品"
    assert _normalize_customer_prompt("View part list") == "零件"
    assert _normalize_customer_prompt("View parts list") == "零件"
    assert _normalize_customer_prompt("Show me all parts") == "零件"
    assert _normalize_customer_prompt("What parts do you have?") == "零件"
    assert _normalize_customer_prompt("所有零件") == "零件"
    assert _normalize_customer_prompt(
        'ExecuteSQLe ( "SELECT part_number FROM "零件" WHERE "customer_id" = ?";""; ""; "CU638" )'
    ) == "零件"
    assert _normalize_customer_prompt(
        'ExecuteSQLe ( "SELECT product_sku FROM "產品" WHERE "id_client" = ?";""; ""; "CU638" )'
    ) == "产品"
    assert _normalize_customer_prompt("Check inventory for MYB0377-24") == "查询 MYB0377-24 库存"

    plan = SimpleNamespace(
        domain="product",
        query=[],
        keywords=[],
        filters={},
        date_range=None,
    )
    assert _is_scoped_customer_listing(plan, "CU638", "CU638") is True
    assert _is_scoped_customer_listing(plan, "", "CU638") is False

    part_plan = SimpleNamespace(
        domain="part",
        query=[],
        keywords=[],
        filters={},
        date_range=None,
    )
    assert _is_scoped_customer_listing(part_plan, "CU638", "CU638") is True
    assert _is_scoped_customer_listing(part_plan, "CU638", "") is False


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("View order history", ""),
        ("查询出库单", ""),
        ("查询出库单号 PI-001", "PI-001"),
        ("查看出貨單 PI-001", "PI-001"),
        ("tracking 910038198088", "910038198088"),
        ("PO#292687(CA1)", "PO#292687(CA1)"),
        ("Show shipping records for UPS", "UPS"),
        ("包含产品 MYTENT33S 的出货单", "MYTENT33S"),
        ("View product list", None),
    ],
)
def test_customer_order_prompt_extracts_only_optional_catalog_search(prompt: str, expected: str | None) -> None:
    assert _customer_order_search(prompt) == expected


@pytest.mark.parametrize(
    ("prompt", "expected_search", "expected_field", "expected_range", "expected_status"),
    [
        ("查询 2026-07-01 到 2026-07-22 的出库单", "", "日期", "7/1/2026...7/22/2026", "all"),
        ("查询 2026年7月的出货单", "", "日期", "7/1/2026...7/31/2026", "all"),
        ("查询本月出库单", "", "日期", "7/1/2026...7/31/2026", "all"),
        ("Orders shipped this month", "", "日期", "7/1/2026...7/31/2026", "shipped"),
        ("查询订单日期 2026-07-01 到 2026-07-22", "", "日期", "7/1/2026...7/22/2026", "all"),
        ("查询出货日期 2026-07-01 到 2026-07-22", "", "出貨日期", "7/1/2026...7/22/2026", "all"),
        ("查询完成日期 2026-07-01 到 2026-07-22 的订单", "", "完成日期", "7/1/2026...7/22/2026", "all"),
        ("UPS 7月1日到7月5日的出货单", "UPS", "日期", "7/1/2026...7/5/2026", "all"),
    ],
)
def test_customer_order_prompt_builds_date_range_plan(
    prompt: str,
    expected_search: str,
    expected_field: str,
    expected_range: str,
    expected_status: str,
) -> None:
    plan = _customer_order_query_plan(prompt, today=date(2026, 7, 22))

    assert plan is not None
    assert plan.search == expected_search
    assert plan.date_field == expected_field
    assert plan.filemaker_date_range == expected_range
    assert plan.shipping_status == expected_status


@pytest.mark.parametrize(
    "prompt",
    [
        "查询未出货的出库单",
        "查询尚未出貨的订单",
        "Show orders not shipped",
        "List unshipped orders",
    ],
)
def test_customer_order_unshipped_query_uses_shipping_status(
    prompt: str,
) -> None:
    plan = _customer_order_query_plan(prompt, today=date(2026, 7, 22))

    assert plan is not None
    assert plan.search == ""
    assert plan.date_field is None
    assert plan.shipping_status == "notShipped"


@pytest.mark.parametrize(
    "prompt",
    [
        "查询已出货的出库单",
        "查询已發貨的訂單",
        "Show shipped orders",
    ],
)
def test_customer_order_shipped_query_uses_shipping_status(prompt: str) -> None:
    plan = _customer_order_query_plan(prompt, today=date(2026, 7, 22))

    assert plan is not None
    assert plan.search == ""
    assert plan.date_field is None
    assert plan.shipping_status == "shipped"


@pytest.mark.asyncio
async def test_customer_order_chat_uses_scoped_catalog_query() -> None:
    class FakeFileMaker:
        def __init__(self) -> None:
            self.calls = []

        async def find_records(self, layout, query=None, limit=100, offset=1, sort=None):
            self.calls.append((layout, query, limit, offset, sort))
            assert layout == "@mayako"
            return {
                "data": [{
                    "recordId": "91",
                    "fieldData": {
                        "出貨單 PI": "PI-001",
                        "內部訂單單據編號": "NB001",
                        "訂單 PO": "PO-001",
                            "出貨單_客戶::客戶名稱": "Mayako",
                            "貨款總和_price": 1250,
                            "shipping_company": "UPS",
                        "tracking_number": "1Z999",
                        "order_remarks_for_client_only": "Delivered",
                        "shipping_cost": 8.6,
                        "出貨日期": "07/22/2026",
                        "出货状态": "Shipped",
                    },
                }],
                "foundCount": 1,
                "returnedCount": 1,
            }

    filemaker = FakeFileMaker()
    session = CustomerSession(
        session_id="session",
        username="acme",
        display_name="ACME",
        client_name="ACME",
        product_privilege="0780",
        part_customer_id="CU638",
        expires_at=9999999999,
        shipment_company_id="",
        access_role="manager",
    )

    response = await query_customer_products(
        body=CustomerQueryRequest(prompt="View orders", page=1, pageSize=4),
        request=SimpleNamespace(headers={}),
        session=session,
        filemaker=filemaker,
        odata_client=None,
        rag_store=None,
        audit_log=None,
        conversation_store=None,
        history_store=CustomerChatHistoryStore("memory://"),
        settings=None,
    )

    assert response.result_type == "order"
    assert response.found_count == 1
    assert isinstance(response.rows[0], CustomerOrderResult)
    assert response.rows[0].model_dump(by_alias=True) == {
        "entityType": "order",
        "orderRef": "91",
        "clientName": "Mayako",
        "orderNumber": "PO-001",
        "orderAmount": 1250,
        "shippingCompany": "UPS",
        "trackingNumber": "1Z999",
        "shippingCost": 8.6,
        "shippedDate": "07/22/2026",
        "shippingStatus": "Shipped",
        "remarks": "Delivered",
    }
    serialized_response = response.model_dump_json(by_alias=True)
    assert "PI-001" not in serialized_response
    assert "NB001" not in serialized_response
    assert filemaker.calls[0][1] == [{
        "select_client_for_web_id": "==0780",
        "訂單 PO": "*",
    }]


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("Check inventory for MYB0377-24", "MYB0377-24"),
        ("查询 MYB0196 库存", "MYB0196"),
        ("Check inventory for PT-Tent-MYK01", "PT-TENT-MYK01"),
    ],
)
def test_customer_explicit_product_number_forces_exact_query(prompt: str, expected: str) -> None:
    plan = SimpleNamespace(
        domain="product",
        description="产品资料列表",
        filters={},
        query=[],
        keywords=[],
        date_range=None,
    )

    _force_exact_customer_identifier(plan, prompt)

    assert plan.query == [{"product_sku": f"=={expected}"}]
    assert plan.keywords == [expected]
    assert plan.description == f"Exact item number: {expected}"


def test_customer_explicit_part_number_forces_exact_query() -> None:
    plan = SimpleNamespace(
        domain="part",
        description="零件资料列表",
        filters={},
        query=[],
        keywords=[],
        date_range=None,
    )

    _force_exact_customer_identifier(plan, "Check part inventory for AL05249-TW-LD")

    assert plan.query == [{"part_number": "==AL05249-TW-LD"}]
    assert plan.keywords == ["AL05249-TW-LD"]


def test_customer_broad_inventory_prompt_is_not_forced_to_an_identifier() -> None:
    plan = SimpleNamespace(
        domain="product",
        description="产品资料列表",
        filters={},
        query=[],
        keywords=[],
        date_range=None,
    )

    _force_exact_customer_identifier(plan, "View inventory")

    assert plan.query == []


def test_customer_product_result_omits_unset_price_and_allows_authorized_price() -> None:
    row = CustomerProductResult(entityType="product", productRef="123", productSku="MYB0377-24", stock=12)
    payload = row.model_dump(by_alias=True, exclude_unset=True)

    assert payload["stock"] == 12
    assert "price" not in payload
    assert "productNameCn" not in payload
    priced = CustomerProductResult(
        entityType="product",
        productRef="123",
        productSku="MYB0377-24",
        stock=12,
        price=99,
    )
    assert priced.model_dump(by_alias=True, exclude_unset=True)["price"] == 99
    with pytest.raises(ValueError):
        CustomerProductResult(
            entityType="product",
            productRef="123",
            productSku="MYB0377-24",
            stock=12,
            internalCost=99,
        )


def test_customer_query_answer_is_truthful_for_empty_and_out_of_range_results() -> None:
    assert _customer_query_answer(
        result_type="product",
        found_count=0,
        returned_count=0,
        page=1,
        total_pages=1,
    ) == "No matching product was found in your available catalog."
    assert _customer_query_answer(
        result_type="part",
        found_count=0,
        returned_count=0,
        page=1,
        total_pages=1,
    ) == "No matching part was found in your available catalog."
    assert _customer_query_answer(
        result_type="product",
        found_count=1,
        returned_count=0,
        page=2,
        total_pages=1,
    ) == "Found 1 matching product, but page 2 has no results. Please use page 1 or earlier."


def test_customer_chat_product_names_remove_japanese_prefixes() -> None:
    assert _customer_english_text("マヤコ Mayako MX8-24 1:8th Nitro Buggy") == (
        "Mayako MX8-24 1:8th Nitro Buggy"
    )
