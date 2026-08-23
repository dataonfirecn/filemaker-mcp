import asyncio
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
import logging
import re
from math import ceil
import time
from typing import Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from app.api.customer_catalog import find_customer_orders_for_chat
from app.api.natural_language_query import run_natural_language_query
from app.core.config import Settings
from app.models.customer_chat import (
    CustomerLoginRequest,
    CustomerLoginResponse,
    CustomerOrderResult,
    CustomerPasswordChangeRequest,
    CustomerPasswordChangeResponse,
    CustomerProductResult,
    CustomerProfile,
    CustomerQueryRequest,
    CustomerQueryResponse,
)
from app.models.customer_chat_admin import (
    CustomerAccountBulkDisableRequest,
    CustomerAccountBulkDisableResponse,
    CustomerAccountBulkStatusRequest,
    CustomerAccountBulkStatusResponse,
    CustomerAccountAdminCreateRequest,
    CustomerAccountAdminItem,
    CustomerAccountAdminResponse,
    CustomerAccountAdminUpdateRequest,
    CustomerCredentialsEmailLogItem,
    CustomerCredentialsEmailLogResponse,
    CustomerChatHistoryItem,
    CustomerChatHistoryResponse,
    CustomerChatQuestionSummaryItem,
    CustomerChatQuestionSummaryResponse,
)
from app.models.natural_language_query import NaturalLanguageQueryRequest
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.customer_access import (
    customer_access_permissions,
    normalize_customer_access_role,
)
from app.services.customer_chat_auth import (
    CustomerAuthError,
    CustomerAccount,
    CustomerLoginRateLimiter,
    CustomerSession,
    account_with_password_hash,
    authenticate_customer,
    customer_account_from_admin_state,
    hash_customer_password,
    issue_customer_token,
    load_customer_accounts,
    verify_customer_password,
)
from app.services.customer_chat_history import CustomerChatHistoryStore
from app.services.customer_account_admin_store import CustomerAccountAdminStore
from app.services.customer_credential_store import CustomerCredentialStore
from app.services.customer_email import (
    CustomerEmailError,
    send_customer_credentials_email,
)
from app.services.dependencies import (
    get_audit_log_store,
    get_customer_account_admin_store,
    get_customer_credential_store,
    get_customer_chat_history_store,
    get_customer_login_rate_limiter,
    get_customer_session,
    get_cos_storage_service,
    get_filemaker_client,
    get_filemaker_odata_client,
    get_natural_query_conversation_store,
    get_natural_query_analytics_worker,
    get_rag_index_store,
    get_settings,
)
from app.services.filemaker_client import FileMakerAPIError, FileMakerClient
from app.services.cos_storage import COSStorageError, COSStorageService
from app.services.filemaker_odata_client import FileMakerODataClient
from app.services.natural_query_conversation_store import NaturalQueryConversationStore
from app.services.natural_query_analytics_worker import NaturalQueryAnalyticsWorker
from app.services.product_api import (
    PRODUCT_ASSET_LAYOUT,
    PRODUCT_LAYOUT,
    find_product_price,
    price_value,
)
from app.services.part_assets import (
    asset_fields as part_asset_fields,
    find_primary_part_asset,
)
from app.services.rag_index import RagIndexStore


router = APIRouter(prefix="/customer-chat", tags=["customer-chat"])
logger = logging.getLogger(__name__)
PART_LAYOUT = "Parts"
MAX_CUSTOMER_ATTACHMENT_BYTES = 12 * 1024 * 1024
CUSTOMER_CREDENTIALS_EMAIL_COOLDOWN_SECONDS = 60
CUSTOMER_ATTACHMENT_MEDIA_TYPES = {
    "application/pdf",
    "image/bmp",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
}

_PRICE_QUERY_TERMS = (
    "价格",
    "價格",
    "单价",
    "單價",
    "售价",
    "售價",
    "price",
    "unit price",
    "unit_price",
)
_SENSITIVE_FINANCIAL_QUERY_TERMS = (
    "成本",
    "报价",
    "報價",
    "金额",
    "金額",
    "货值",
    "貨值",
    "cost",
    "quotation",
)
_INTERNAL_QUERY_TERMS = (
    "供应商",
    "供應商",
    "厂商",
    "廠商",
    "采购",
    "採購",
    "利润",
    "利潤",
    "毛利",
    "订单",
    "訂單",
    "发料",
    "發料",
    "销售记录",
    "銷售紀錄",
    "内部备注",
    "內部備註",
    "supplier",
    "vendor",
    "purchase order",
    "order",
    "orders",
    "margin",
)
_OUT_OF_SCOPE_QUERY_TERMS = (
    "weather",
    "forecast",
    "天气",
    "天氣",
)
_GREETING_PROMPTS = {
    "hello",
    "hi",
    "hey",
    "你好",
    "您好",
}
_BASIC_LIST_PROMPTS = {
    "产品",
    "產品",
    "产品清单",
    "產品清單",
    "基础清单",
    "基礎清單",
    "产品列表",
    "產品列表",
    "所有产品",
    "所有產品",
    "全部产品",
    "全部產品",
    "查看产品清单",
    "查看產品清單",
    "查询产品清单",
    "查詢產品清單",
    "库存",
    "庫存",
    "查看库存",
    "查看庫存",
    "查询库存",
    "查詢庫存",
    "库存清单",
    "庫存清單",
    "产品库存",
    "產品庫存",
    "产品库存清单",
    "產品庫存清單",
    "所有产品库存",
    "所有產品庫存",
    "products",
    "productlist",
    "viewproductlist",
    "showproductlist",
    "allproducts",
    "showmeallproducts",
    "whatproductsdoyouhave",
    "whatproductsareavailable",
    "inventory",
    "viewinventory",
    "showinventory",
    "inventorylist",
    "productinventory",
}
_BASIC_PART_LIST_PROMPTS = {
    "零件",
    "零件清单",
    "零件清單",
    "零件列表",
    "所有零件",
    "全部零件",
    "查看零件清单",
    "查看零件清單",
    "查询零件清单",
    "查詢零件清單",
    "零件库存",
    "零件庫存",
    "零件库存清单",
    "零件庫存清單",
    "parts",
    "partlist",
    "viewpartlist",
    "viewpartslist",
    "showpartlist",
    "showpartslist",
    "allparts",
    "showmeallparts",
    "whatpartsdoyouhave",
    "whatpartsareavailable",
    "partinventory",
    "viewpartinventory",
}

_ORDER_CJK_TERMS = (
    "出库单",
    "出庫單",
    "出货单",
    "出貨單",
    "出货日期",
    "出貨日期",
    "订单",
    "訂單",
    "物流",
    "快递",
    "快遞",
    "运单",
    "運單",
    "发货",
    "發貨",
    "配送",
    "追踪",
    "追蹤",
)
_ORDER_ENGLISH_PATTERN = re.compile(
    r"\b(?:orders?|shipments?|shipping|tracking|deliveries|delivery|po)\b",
    re.IGNORECASE,
)
_ORDER_EXPLICIT_DATE_PATTERNS = (
    re.compile(r"(?<!\d)(?P<year>\d{4})[-/.](?P<month>\d{1,2})[-/.](?P<day>\d{1,2})(?!\d)"),
    re.compile(r"(?<!\d)(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日?"),
    re.compile(r"(?<!\d)(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{4})(?!\d)"),
    re.compile(r"(?<!\d)(?P<month>\d{1,2})月(?P<day>\d{1,2})日?"),
)


@dataclass(frozen=True)
class CustomerOrderQueryPlan:
    search: str = ""
    date_field: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    shipping_status: Literal["all", "shipped", "notShipped"] = "all"

    @property
    def filemaker_date_range(self) -> str | None:
        if self.start_date is None or self.end_date is None:
            return None
        return (
            f"{self.start_date.month}/{self.start_date.day}/{self.start_date.year}..."
            f"{self.end_date.month}/{self.end_date.day}/{self.end_date.year}"
        )


@router.post("/login", response_model=CustomerLoginResponse)
async def login_customer(
    body: CustomerLoginRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    rate_limiter: CustomerLoginRateLimiter = Depends(get_customer_login_rate_limiter),
    credential_store: CustomerCredentialStore = Depends(get_customer_credential_store),
    account_admin_store: CustomerAccountAdminStore = Depends(get_customer_account_admin_store),
) -> CustomerLoginResponse:
    if not settings.customer_chat_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "The customer portal is not enabled. Please contact your account representative."},
        )
    try:
        configured_accounts = load_customer_accounts(settings)
        if not settings.customer_chat_token_secret:
            raise CustomerAuthError("The customer portal configuration is incomplete")
    except CustomerAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "The customer portal is temporarily unavailable. Please contact your account representative."},
        ) from exc

    client_host = request.client.host if request.client else "unknown"
    login_identifier = body.username.strip()
    identifier_key = login_identifier.casefold()
    account_state, ambiguous_email = await account_admin_store.resolve_login_state(
        login_identifier
    )
    canonical_username = (
        str(account_state["username"]) if account_state else login_identifier
    )
    username_key = canonical_username.casefold()
    environment_account = configured_accounts.get(username_key)
    if environment_account and not account_state:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"message": "The customer portal is temporarily unavailable. Please try again later."},
        )
    password_hash_override = (
        await credential_store.get_password_hash(canonical_username)
        if account_state
        else None
    )
    password_hash = password_hash_override or (
        environment_account.password_hash if environment_account else ""
    )
    configured_account = (
        customer_account_from_admin_state(account_state, password_hash)
        if account_state and password_hash
        else None
    )
    limiter_key = f"{client_host}:{username_key if account_state else identifier_key}"
    retry_after = await rate_limiter.retry_after(
        limiter_key,
        max_attempts=settings.customer_chat_login_max_attempts,
        window_seconds=settings.customer_chat_login_window_seconds,
    )
    if retry_after:
        if account_state:
            await account_admin_store.record_login(
                str(account_state["username"]),
                success=False,
                reason="rate_limited",
                client_ip=client_host,
            )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"message": "Too many sign-in attempts. Please try again later."},
            headers={"Retry-After": str(retry_after)},
        )

    account = await asyncio.to_thread(
        authenticate_customer,
        "" if ambiguous_email else canonical_username,
        body.password,
        settings,
        password_hash_override=password_hash_override,
        account_override=configured_account,
    )
    login_failure_reason = (
        "ambiguous_email" if ambiguous_email else "invalid_credentials"
    )
    if account_state:
        if account and not account_state["enabled"]:
            account = None
            login_failure_reason = "account_disabled"
    if not account:
        if account_state:
            await account_admin_store.record_login(
                str(account_state["username"]),
                success=False,
                reason=login_failure_reason,
                client_ip=client_host,
            )
        await rate_limiter.record_failure(
            limiter_key,
            window_seconds=settings.customer_chat_login_window_seconds,
        )
        await audit_log.record(
            operator=OperatorContext(
                session_id="customer-login",
                account=body.username.strip() or "unknown",
                name="外部客户登录",
                privilege="external_customer",
            ),
            action_type="CUSTOMER_LOGIN",
            status="failed",
            request_payload={"clientHost": client_host},
            error_message=login_failure_reason,
        )
        if ambiguous_email:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": (
                        "This email is linked to multiple accounts. "
                        "Please contact your administrator."
                    )
                },
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "The username, email, or password is incorrect."},
        )

    await rate_limiter.clear(limiter_key)
    token, session = issue_customer_token(account, settings)
    await account_admin_store.record_login(
        account.username,
        success=True,
        reason="authenticated",
        client_ip=client_host,
    )
    await audit_log.record(
        operator=session.operator,
        action_type="CUSTOMER_LOGIN",
        status="success",
        request_payload={"clientHost": client_host},
        response_payload={"clientName": session.client_name, "expiresAt": session.expires_at},
    )
    return CustomerLoginResponse(
        token=token,
        expiresAt=session.expires_at,
        customer=_profile(session),
    )


@router.get("/me", response_model=CustomerProfile)
async def get_customer_profile(
    session: CustomerSession = Depends(get_customer_session),
) -> CustomerProfile:
    return _profile(session)


@router.post("/change-password", response_model=CustomerPasswordChangeResponse)
async def change_customer_password(
    body: CustomerPasswordChangeRequest,
    session: CustomerSession = Depends(get_customer_session),
    settings: Settings = Depends(get_settings),
    credential_store: CustomerCredentialStore = Depends(get_customer_credential_store),
    account_admin_store: CustomerAccountAdminStore = Depends(get_customer_account_admin_store),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> CustomerPasswordChangeResponse:
    if body.new_password != body.confirm_new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "The two new passwords do not match."},
        )
    if len(body.new_password) < 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "The new password must contain at least 12 characters."},
        )

    account_state = await account_admin_store.get_state(session.username)
    if not account_state:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Your account is no longer available."},
        )
    current_override_hash = await credential_store.get_password_hash(session.username)
    environment_account = load_customer_accounts(settings).get(session.username.casefold())
    current_password_hash = current_override_hash or (
        environment_account.password_hash if environment_account else ""
    )
    if not current_password_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"message": "Your account is no longer available."},
        )
    account = customer_account_from_admin_state(account_state, current_password_hash)
    old_password_valid = await asyncio.to_thread(
        verify_customer_password,
        body.old_password,
        account.password_hash,
    )
    if not old_password_valid:
        await audit_log.record(
            operator=session.operator,
            action_type="CUSTOMER_PASSWORD_CHANGE",
            status="failed",
            error_message="Current password did not match",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "The current password is incorrect."},
        )

    password_reused = await asyncio.to_thread(
        verify_customer_password,
        body.new_password,
        account.password_hash,
    )
    if password_reused:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "The new password must be different from the current password."},
        )

    new_password_hash = await asyncio.to_thread(hash_customer_password, body.new_password)
    changed = await credential_store.compare_and_set_password_hash(
        session.username,
        expected_override_hash=current_override_hash,
        new_password_hash=new_password_hash,
    )
    if not changed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "The password changed in another session. Please sign in again."},
        )

    updated_account = replace(
        account_with_password_hash(account, new_password_hash),
        can_view_price=session.can_view_price,
        is_admin=session.is_admin,
    )
    token, updated_session = issue_customer_token(updated_account, settings)
    await audit_log.record(
        operator=updated_session.operator,
        action_type="CUSTOMER_PASSWORD_CHANGE",
        status="success",
    )
    return CustomerPasswordChangeResponse(
        token=token,
        expiresAt=updated_session.expires_at,
        customer=_profile(updated_session),
        message="Your password has been changed.",
    )


@router.post(
    "/query",
    response_model=CustomerQueryResponse,
    response_model_exclude_unset=True,
)
async def query_customer_products(
    body: CustomerQueryRequest,
    request: Request,
    session: CustomerSession = Depends(get_customer_session),
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    odata_client: FileMakerODataClient = Depends(get_filemaker_odata_client),
    rag_store: RagIndexStore = Depends(get_rag_index_store),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    conversation_store: NaturalQueryConversationStore = Depends(get_natural_query_conversation_store),
    analytics_worker: NaturalQueryAnalyticsWorker = Depends(get_natural_query_analytics_worker),
    history_store: CustomerChatHistoryStore = Depends(get_customer_chat_history_store),
    settings: Settings = Depends(get_settings),
) -> CustomerQueryResponse:
    started_at = time.perf_counter()
    is_test = request.headers.get("X-QA-Test", "").strip().casefold() in {"1", "true", "yes"}
    channel = "regression_test" if is_test else request.headers.get("X-Client-Channel", "web")
    try:
        _validate_customer_sensitive_prompt(
            body.prompt,
            can_view_price=session.can_view_price,
        )
    except HTTPException as exc:
        await _record_customer_query_safe(
            history_store,
            session=session,
            body=body,
            started_at=started_at,
            status_value="blocked",
            http_status=exc.status_code,
            answer=_http_exception_message(exc),
            blocked_reason=_http_exception_code(exc),
            channel=channel,
            is_test=is_test,
        )
        raise

    asks_for_price = _customer_asks_for_price(body.prompt)
    exact_identifier = _customer_query_identifier(body.prompt)
    if asks_for_price and exact_identifier is None:
        response = CustomerQueryResponse(
            resultType="product",
            answer="Please provide a product number to view its unit price.",
            rows=[],
            foundCount=0,
            returnedCount=0,
            page=body.page,
            pageSize=body.page_size,
            totalPages=1,
            hasPrevious=False,
            hasNext=False,
            requiresClarification=True,
            clarificationQuestion="Which product number would you like a price for?",
            clarificationOptions=[
                "What is the unit price for MYB0196?",
                "What is the unit price for MYB0377-24?",
            ],
        )
        response.history_id = await _record_customer_query_safe(
            history_store,
            session=session,
            body=body,
            started_at=started_at,
            status_value="clarification",
            http_status=200,
            answer=response.answer,
            domain="product",
            result_type="product",
            channel=channel,
            is_test=is_test,
        )
        return response

    order_plan = _customer_order_query_plan(
        body.prompt,
        today=_customer_query_today(settings.natural_query_timezone if settings else "Asia/Shanghai"),
    )
    if order_plan is not None:
        try:
            response = await _query_customer_orders(
                plan=order_plan,
                body=body,
                session=session,
                filemaker=filemaker,
            )
        except HTTPException as exc:
            await _record_customer_query_safe(
                history_store,
                session=session,
                body=body,
                started_at=started_at,
                status_value="error",
                http_status=exc.status_code,
                answer=_http_exception_message(exc),
                blocked_reason=_http_exception_code(exc),
                domain="order",
                result_type="order",
                source_layout="@mayako",
                channel=channel,
                is_test=is_test,
            )
            raise
        response.history_id = await _record_customer_query_safe(
            history_store,
            session=session,
            body=body,
            started_at=started_at,
            status_value="success" if response.found_count > 0 else "no_result",
            http_status=200,
            answer=response.answer,
            domain="order",
            result_type="order",
            found_count=response.found_count,
            returned_count=response.returned_count,
            source_layout="@mayako",
            channel=channel,
            is_test=is_test,
        )
        return response

    try:
        _validate_customer_prompt(body.prompt, can_view_price=session.can_view_price)
    except HTTPException as exc:
        await _record_customer_query_safe(
            history_store,
            session=session,
            body=body,
            started_at=started_at,
            status_value="blocked" if exc.status_code == 403 else "error",
            http_status=exc.status_code,
            answer=_http_exception_message(exc),
            blocked_reason=_http_exception_code(exc),
            channel=channel,
            is_test=is_test,
        )
        raise
    query_prompt = _normalize_customer_prompt(body.prompt)
    identifier_domain = _customer_prompt_domain(body.prompt)
    if exact_identifier and identifier_domain is None:
        try:
            identifier_domain = await _resolve_customer_identifier_domain(
                filemaker,
                exact_identifier,
                customer_id=session.part_customer_id,
            )
        except FileMakerAPIError as exc:
            mapped = HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "message": "The search service is temporarily unavailable. Please try again later.",
                    "code": "query_service_unavailable",
                },
            )
            await _record_customer_query_safe(
                history_store,
                session=session,
                body=body,
                started_at=started_at,
                status_value="error",
                http_status=mapped.status_code,
                answer=_http_exception_message(mapped),
                blocked_reason=_http_exception_code(mapped),
                channel=channel,
                is_test=is_test,
            )
            raise mapped from exc

        if identifier_domain in {"ambiguous", "not_found"}:
            response = _customer_identifier_clarification(
                body,
                exact_identifier,
                matched_both=identifier_domain == "ambiguous",
                asks_for_price=asks_for_price,
            )
            response.history_id = await _record_customer_query_safe(
                history_store,
                session=session,
                body=body,
                started_at=started_at,
                status_value="clarification",
                http_status=200,
                answer=response.answer,
                domain="unknown",
                intent="lookup",
                channel=channel,
                is_test=is_test,
                response_meta={
                    "identifier": exact_identifier,
                    "identifierResolution": identifier_domain,
                },
            )
            return response

        query_prompt = (
            f"零件 {query_prompt}"
            if identifier_domain == "part"
            else f"产品 {query_prompt}"
        )
    try:
        result = await run_natural_language_query(
            body=NaturalLanguageQueryRequest(
                prompt=query_prompt,
                limit=body.page_size,
                offset=((body.page - 1) * body.page_size) + 1,
            ),
            filemaker=filemaker,
            odata_client=odata_client,
            rag_store=rag_store,
            audit_log=audit_log,
            conversation_store=conversation_store,
            analytics_worker=analytics_worker,
            operator=session.operator,
            settings=settings,
            enforced_product_client_id=session.part_customer_id,
            enforced_part_customer_id=session.part_customer_id,
        )
    except HTTPException as exc:
        if exc.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY:
            mapped = HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": _customer_query_validation_message(exc),
                    "code": "invalid_query",
                },
            )
        else:
            mapped = HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "message": "The search service is temporarily unavailable. Please try again later.",
                    "code": "query_service_unavailable",
                },
            )
        await _record_customer_query_safe(
            history_store,
            session=session,
            body=body,
            started_at=started_at,
            status_value="error",
            http_status=mapped.status_code,
            answer=_http_exception_message(mapped),
            blocked_reason=_http_exception_code(mapped),
            channel=channel,
            is_test=is_test,
        )
        raise mapped from exc
    result_type = "part" if result.plan.domain == "part" else "product"
    price_by_ref: dict[str, object] = {}
    if asks_for_price and result_type == "product" and session.can_view_price and result.rows:
        price_results = await asyncio.gather(*(
            find_product_price(
                filemaker,
                row.product_sku,
                str(row.raw.get("系統產品編號") or ""),
            )
            for row in result.rows
        ))
        price_by_ref = {
            row.record_id: price_value(
                price_result,
                row.product_sku,
                str(row.raw.get("系統產品編號") or ""),
            )
            for row, price_result in zip(result.rows, price_results, strict=True)
        }
    rows: list[CustomerProductResult] = []
    for row in result.rows:
        row_payload = {
            "entityType": result_type,
            "productRef": row.record_id,
            "productSku": row.product_sku,
            "productName": _customer_english_text(
                (
                    row.raw.get("part_name_en")
                    or row.raw.get("English Name")
                    or row.product_name
                )
                if result_type == "part"
                else row.product_name
            ),
            "modelName": (
                _customer_english_text(row.model_name)
                if session.can_view_details
                else ""
            ),
            "scale": _customer_english_text(row.scale) if session.can_view_details else "",
            "category": (
                _customer_english_text(row.category)
                if session.can_view_details
                else ""
            ),
            "stock": row.stock,
            "hasImage": bool(row.image_url) if session.can_view_details else False,
        }
        if asks_for_price and result_type == "product" and session.can_view_price:
            row_payload["price"] = price_by_ref.get(row.record_id)
        rows.append(CustomerProductResult(**row_payload))
    clarification_options = result.clarification_options
    if result.requires_clarification:
        clarification_options = [
            "View product list",
            "View part list",
            "View inventory",
            "Check inventory for MYB0377-24",
        ]
    total_pages = max(1, ceil(result.found_count / body.page_size))
    if result.requires_clarification:
        answer = "Please refine your search."
        clarification_question = "Search by product number, name, or model."
    else:
        answer = _customer_query_answer(
            result_type=result_type,
            found_count=result.found_count,
            returned_count=len(rows),
            page=body.page,
            total_pages=total_pages,
        )
        clarification_question = None
    if asks_for_price and result_type == "part":
        answer = (
            "Part pricing is not available in this portal. "
            "Please contact your account representative."
        )
    elif asks_for_price and result_type == "product" and rows:
        priced_rows = [row for row in rows if row.price not in {None, ""}]
        if len(priced_rows) == 1:
            answer = (
                f"The unit price for {priced_rows[0].product_sku} is "
                f"{_customer_price_text(priced_rows[0].price)}."
            )
        elif not priced_rows:
            answer = "A unit price is not available for this product."
    response = CustomerQueryResponse(
        resultType=result_type,
        answer=answer,
        rows=rows,
        foundCount=result.found_count,
        returnedCount=len(rows),
        page=body.page,
        pageSize=body.page_size,
        totalPages=total_pages,
        hasPrevious=body.page > 1,
        hasNext=body.page < total_pages,
        requiresClarification=result.requires_clarification,
        clarificationQuestion=clarification_question,
        clarificationOptions=clarification_options,
    )
    response.history_id = await _record_customer_query_safe(
        history_store,
        session=session,
        body=body,
        started_at=started_at,
        status_value=(
            "clarification"
            if response.requires_clarification
            else "success"
            if response.found_count > 0
            else "no_result"
        ),
        http_status=200,
        answer=response.answer,
        domain=result_type,
        result_type=result_type,
        found_count=response.found_count,
        returned_count=response.returned_count,
        source_layout="Parts" if result_type == "part" else "@products",
        channel=channel,
        is_test=is_test,
        response_meta={
            "priceRequested": asks_for_price,
            "priceReturned": any(row.price not in {None, ""} for row in rows),
        },
    )
    return response


@router.get("/admin/accounts", response_model=CustomerAccountAdminResponse)
async def get_customer_accounts_admin(
    session: CustomerSession = Depends(get_customer_session),
    account_admin_store: CustomerAccountAdminStore = Depends(get_customer_account_admin_store),
    settings: Settings = Depends(get_settings),
) -> CustomerAccountAdminResponse:
    _require_customer_admin(session)
    states = await account_admin_store.list_states()
    return CustomerAccountAdminResponse(
        accounts=[
            _customer_account_admin_item(state)
            for _, state in sorted(states.items())
        ],
        emailDeliveryEnabled=settings.customer_smtp_configured,
    )


@router.get(
    "/admin/accounts/email-logs",
    response_model=CustomerCredentialsEmailLogResponse,
)
async def get_customer_credentials_email_logs_admin(
    limit: int = Query(default=100, ge=1, le=200),
    session: CustomerSession = Depends(get_customer_session),
    account_admin_store: CustomerAccountAdminStore = Depends(get_customer_account_admin_store),
) -> CustomerCredentialsEmailLogResponse:
    _require_customer_admin(session)
    rows = await account_admin_store.list_credentials_email_events(limit=limit)
    return CustomerCredentialsEmailLogResponse(
        logs=[CustomerCredentialsEmailLogItem(**row) for row in rows],
    )


@router.post(
    "/admin/accounts",
    response_model=CustomerAccountAdminItem,
    status_code=status.HTTP_201_CREATED,
)
async def create_customer_account_admin(
    body: CustomerAccountAdminCreateRequest,
    session: CustomerSession = Depends(get_customer_session),
    account_admin_store: CustomerAccountAdminStore = Depends(get_customer_account_admin_store),
    credential_store: CustomerCredentialStore = Depends(get_customer_credential_store),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    settings: Settings = Depends(get_settings),
) -> CustomerAccountAdminItem:
    _require_customer_admin(session)
    if await account_admin_store.get_state(body.username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "A customer account with this username already exists."},
        )
    password_hash = await asyncio.to_thread(hash_customer_password, body.password)
    access_role = normalize_customer_access_role(
        body.access_role,
        is_admin=body.is_admin is True,
    )
    created = await account_admin_store.create_account(
        username=body.username,
        display_name=body.display_name,
        email=body.email,
        enabled=body.enabled,
        can_view_price=body.can_view_price is True,
        access_role=access_role,
        updated_by=session.username,
    )
    if not created:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "A customer account with this username already exists."},
        )
    try:
        await credential_store.set_password_hash(body.username, password_hash)
    except Exception:
        await account_admin_store.delete_account(
            body.username,
            updated_by=session.username,
        )
        raise
    credentials_email_sent: bool | None = None
    credentials_email_error = ""
    if body.send_credentials:
        await account_admin_store.claim_credentials_email(
            body.username,
            cooldown_seconds=CUSTOMER_CREDENTIALS_EMAIL_COOLDOWN_SECONDS,
        )
        try:
            await asyncio.to_thread(
                send_customer_credentials_email,
                settings,
                recipient_email=body.email,
                display_name=body.display_name,
                username=body.username.strip(),
                temporary_password=body.password,
            )
            credentials_email_sent = True
            await account_admin_store.complete_credentials_email(
                body.username,
                cooldown_seconds=CUSTOMER_CREDENTIALS_EMAIL_COOLDOWN_SECONDS,
            )
            await account_admin_store.record_credentials_email_event(
                body.username,
                recipient_email=body.email,
                status="success",
                message="Login credentials email sent.",
            )
        except CustomerEmailError as exc:
            credentials_email_sent = False
            credentials_email_error = str(exc)
            await account_admin_store.release_credentials_email(body.username)
            await account_admin_store.record_credentials_email_event(
                body.username,
                recipient_email=body.email,
                status="failed",
                message=credentials_email_error,
            )
        created = await account_admin_store.get_state(body.username) or created
    await audit_log.record(
        operator=session.operator,
        action_type="CUSTOMER_ACCOUNT_CREATE",
        target_table="customer_account_control",
        target_record_id=body.username.strip().casefold(),
        after_data=_customer_account_audit_data(created),
        status="success",
    )
    return _customer_account_admin_item(
        created,
        credentials_email_sent=credentials_email_sent,
        credentials_email_error=credentials_email_error,
    )


@router.post(
    "/admin/accounts/bulk-status",
    response_model=CustomerAccountBulkStatusResponse,
)
async def bulk_update_customer_account_status_admin(
    body: CustomerAccountBulkStatusRequest,
    session: CustomerSession = Depends(get_customer_session),
    account_admin_store: CustomerAccountAdminStore = Depends(get_customer_account_admin_store),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> CustomerAccountBulkStatusResponse:
    return await _bulk_update_customer_account_status(
        usernames=body.usernames,
        enabled=body.enabled,
        session=session,
        account_admin_store=account_admin_store,
        audit_log=audit_log,
    )


@router.post(
    "/admin/accounts/bulk-disable",
    response_model=CustomerAccountBulkDisableResponse,
)
async def bulk_disable_customer_accounts_admin(
    body: CustomerAccountBulkDisableRequest,
    session: CustomerSession = Depends(get_customer_session),
    account_admin_store: CustomerAccountAdminStore = Depends(get_customer_account_admin_store),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> CustomerAccountBulkDisableResponse:
    response = await _bulk_update_customer_account_status(
        usernames=body.usernames,
        enabled=False,
        session=session,
        account_admin_store=account_admin_store,
        audit_log=audit_log,
    )
    return CustomerAccountBulkDisableResponse(
        accounts=response.accounts,
        disabledCount=response.updated_count,
    )


async def _bulk_update_customer_account_status(
    *,
    usernames: list[str],
    enabled: bool,
    session: CustomerSession,
    account_admin_store: CustomerAccountAdminStore,
    audit_log: AuditLogStore,
) -> CustomerAccountBulkStatusResponse:
    _require_customer_admin(session)
    username_keys = list(dict.fromkeys(
        username.strip().casefold()
        for username in usernames
        if username.strip()
    ))
    if not username_keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Select at least one account."},
        )
    if session.username.casefold() in username_keys:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "You cannot change the status of the administrator account you are currently using."},
        )

    before_states: list[dict[str, object]] = []
    for username_key in username_keys:
        state = await account_admin_store.get_state(username_key)
        if not state:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": f"Customer account not found: {username_key}"},
            )
        before_states.append(state)

    changed_states = [
        state
        for state in before_states
        if bool(state["enabled"]) is not enabled
    ]
    updated_states: list[dict[str, object]] = []
    for before in changed_states:
        updated = await account_admin_store.update_account(
            str(before["username"]),
            enabled=enabled,
            access_role=str(before["accessRole"]),
            updated_by=session.username,
        )
        if updated:
            updated_states.append(updated)

    await audit_log.record(
        operator=session.operator,
        action_type=(
            "CUSTOMER_ACCOUNT_BULK_ENABLE"
            if enabled
            else "CUSTOMER_ACCOUNT_BULK_DISABLE"
        ),
        target_table="customer_account_control",
        target_record_id=",".join(username_keys),
        before_data={"accounts": [_customer_account_audit_data(state) for state in changed_states]},
        after_data={"accounts": [_customer_account_audit_data(state) for state in updated_states]},
        status="success",
    )
    return CustomerAccountBulkStatusResponse(
        accounts=[_customer_account_admin_item(state) for state in updated_states],
        updatedCount=len(updated_states),
        enabled=enabled,
    )


@router.patch("/admin/accounts/{username}", response_model=CustomerAccountAdminItem)
async def update_customer_account_admin(
    username: str,
    body: CustomerAccountAdminUpdateRequest,
    session: CustomerSession = Depends(get_customer_session),
    account_admin_store: CustomerAccountAdminStore = Depends(get_customer_account_admin_store),
    credential_store: CustomerCredentialStore = Depends(get_customer_credential_store),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    settings: Settings = Depends(get_settings),
) -> CustomerAccountAdminItem:
    _require_customer_admin(session)
    username_key = username.strip().casefold()
    before = await account_admin_store.get_state(username)
    if not before:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Customer account not found."},
        )
    if body.send_credentials and not body.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Generate a new temporary password before sending login details."},
        )
    email_value = body.email if body.email is not None else str(before.get("email") or "")
    if body.send_credentials and not email_value.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Add an email address before sending login details."},
        )
    next_enabled = body.enabled if body.enabled is not None else bool(before["enabled"])
    if username_key == session.username.casefold() and body.enabled is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "You cannot disable the administrator account you are currently using."},
        )
    access_role = normalize_customer_access_role(
        body.access_role if body.access_role is not None else before.get("accessRole"),
        is_admin=body.is_admin if body.is_admin is not None else bool(before["isAdmin"]),
    )
    if username_key == session.username.casefold() and access_role != "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "You cannot remove administrator permission from the account you are currently using."},
        )
    email_claimed = False
    if body.send_credentials:
        remaining = await account_admin_store.claim_credentials_email(
            username,
            cooldown_seconds=CUSTOMER_CREDENTIALS_EMAIL_COOLDOWN_SECONDS,
        )
        if remaining:
            await account_admin_store.record_credentials_email_event(
                username,
                recipient_email=email_value,
                status="blocked",
                message=f"Send blocked by {remaining}-second cooldown.",
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "message": f"Please wait {remaining} seconds before sending another login email.",
                    "code": "email_cooldown",
                    "cooldownSeconds": remaining,
                },
            )
        email_claimed = True
    try:
        updated = await account_admin_store.update_account(
            username,
            enabled=next_enabled,
            display_name=body.display_name,
            email=body.email,
            can_view_price=body.can_view_price,
            access_role=access_role,
            updated_by=session.username,
        )
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"message": "Customer account not found."},
            )
        if body.new_password:
            password_hash = await asyncio.to_thread(hash_customer_password, body.new_password)
            await credential_store.set_password_hash(username, password_hash)
    except Exception:
        if email_claimed:
            await account_admin_store.release_credentials_email(username)
        raise
    credentials_email_sent: bool | None = None
    credentials_email_error = ""
    if body.send_credentials and body.new_password:
        try:
            await asyncio.to_thread(
                send_customer_credentials_email,
                settings,
                recipient_email=str(updated["email"]),
                display_name=str(updated["displayName"]),
                username=str(updated["username"]),
                temporary_password=body.new_password,
            )
            credentials_email_sent = True
            await account_admin_store.complete_credentials_email(
                username,
                cooldown_seconds=CUSTOMER_CREDENTIALS_EMAIL_COOLDOWN_SECONDS,
            )
            await account_admin_store.record_credentials_email_event(
                username,
                recipient_email=str(updated["email"]),
                status="success",
                message="Login credentials email sent.",
            )
        except CustomerEmailError as exc:
            credentials_email_sent = False
            credentials_email_error = str(exc)
            await account_admin_store.release_credentials_email(username)
            await account_admin_store.record_credentials_email_event(
                username,
                recipient_email=str(updated["email"]),
                status="failed",
                message=credentials_email_error,
            )
        updated = await account_admin_store.get_state(username) or updated
    await audit_log.record(
        operator=session.operator,
        action_type="CUSTOMER_ACCOUNT_UPDATE",
        target_table="customer_account_control",
        target_record_id=username_key,
        before_data=_customer_account_audit_data(before),
        after_data={
            **_customer_account_audit_data(updated),
            "passwordReset": bool(body.new_password),
        },
        status="success",
    )
    return _customer_account_admin_item(
        updated,
        credentials_email_sent=credentials_email_sent,
        credentials_email_error=credentials_email_error,
    )


@router.delete("/admin/accounts/{username}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_customer_account_admin(
    username: str,
    session: CustomerSession = Depends(get_customer_session),
    account_admin_store: CustomerAccountAdminStore = Depends(get_customer_account_admin_store),
    credential_store: CustomerCredentialStore = Depends(get_customer_credential_store),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> Response:
    _require_customer_admin(session)
    username_key = username.strip().casefold()
    if username_key == session.username.casefold():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "You cannot delete the administrator account you are currently using."},
        )
    before = await account_admin_store.get_state(username)
    if not before:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Customer account not found."},
        )
    deleted = await account_admin_store.delete_account(
        username,
        updated_by=session.username,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Customer account not found."},
        )
    await credential_store.delete_password_hash(username)
    await audit_log.record(
        operator=session.operator,
        action_type="CUSTOMER_ACCOUNT_DELETE",
        target_table="customer_account_control",
        target_record_id=username_key,
        before_data=_customer_account_audit_data(before),
        after_data={"deleted": True},
        status="success",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/admin/history", response_model=CustomerChatHistoryResponse)
async def get_customer_chat_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, alias="pageSize", ge=1, le=200),
    domain: str = Query(default="", max_length=40),
    status_value: str = Query(default="", alias="status", max_length=40),
    query: str = Query(default="", alias="q", max_length=120),
    include_tests: bool = Query(default=False, alias="includeTests"),
    session: CustomerSession = Depends(get_customer_session),
    history_store: CustomerChatHistoryStore = Depends(get_customer_chat_history_store),
) -> CustomerChatHistoryResponse:
    _require_customer_admin(session)
    rows, total = await history_store.list_history(
        page=page,
        page_size=page_size,
        domain=domain.strip(),
        status=status_value.strip(),
        query=query.strip(),
        client_name=session.client_name,
        include_tests=include_tests,
    )
    return CustomerChatHistoryResponse(
        rows=[CustomerChatHistoryItem(**row) for row in rows],
        foundCount=total,
        returnedCount=len(rows),
        page=page,
        pageSize=page_size,
        totalPages=max(1, ceil(total / page_size)),
    )


@router.get("/admin/question-summary", response_model=CustomerChatQuestionSummaryResponse)
async def get_customer_chat_question_summary(
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=200),
    include_tests: bool = Query(default=False, alias="includeTests"),
    session: CustomerSession = Depends(get_customer_session),
    history_store: CustomerChatHistoryStore = Depends(get_customer_chat_history_store),
) -> CustomerChatQuestionSummaryResponse:
    _require_customer_admin(session)
    questions = await history_store.question_summary(
        days=days,
        limit=limit,
        client_name=session.client_name,
        include_tests=include_tests,
    )
    return CustomerChatQuestionSummaryResponse(
        days=days,
        questions=[CustomerChatQuestionSummaryItem(**item) for item in questions],
    )


async def _query_customer_orders(
    *,
    plan: CustomerOrderQueryPlan,
    body: CustomerQueryRequest,
    session: CustomerSession,
    filemaker: FileMakerClient,
) -> CustomerQueryResponse:
    if not session.can_view_orders:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Your account does not have permission to view orders.",
                "code": "order_permission",
            },
        )
    catalog = await find_customer_orders_for_chat(
        search=plan.search,
        date_field=plan.date_field,
        date_range=plan.filemaker_date_range,
        page=body.page,
        page_size=body.page_size,
        session=session,
        filemaker=filemaker,
        shipping_status=plan.shipping_status,
    )
    rows = [
        CustomerOrderResult(
            entityType="order",
            **order.model_dump(by_alias=True),
        )
        for order in catalog.rows
    ]
    answer = _customer_query_answer(
        result_type="order",
        found_count=catalog.found_count,
        returned_count=len(rows),
        page=body.page,
        total_pages=catalog.total_pages,
    )
    if plan.start_date and plan.end_date and plan.date_field:
        date_label = {
            "日期": "order date",
            "備好日期": "ready date",
            "出貨日期": "shipped date",
            "完成日期": "completed date",
            "收款日期": "payment date",
            "簽名日期": "signature date",
            "updated_at": "updated date",
        }.get(plan.date_field, "date")
        answer += (
            f" Filtered by {date_label} from {plan.start_date.isoformat()} "
            f"to {plan.end_date.isoformat()}."
        )
    if plan.shipping_status == "shipped":
        answer += " Filtered to orders with a shipped date."
    elif plan.shipping_status == "notShipped":
        answer += " Filtered to orders without a shipped date."
    return CustomerQueryResponse(
        resultType="order",
        answer=answer,
        rows=rows,
        foundCount=catalog.found_count,
        returnedCount=len(rows),
        page=body.page,
        pageSize=body.page_size,
        totalPages=catalog.total_pages,
        hasPrevious=body.page > 1,
        hasNext=body.page < catalog.total_pages,
        requiresClarification=False,
        clarificationQuestion=None,
        clarificationOptions=[],
    )


@router.get("/products/{record_id}/image")
async def get_customer_product_image(
    record_id: str,
    session: CustomerSession = Depends(get_customer_session),
    filemaker: FileMakerClient = Depends(get_filemaker_client),
) -> Response:
    _require_customer_detail_access(session)
    if not record_id.isdigit():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"message": "Image not found."})
    try:
        data = await filemaker.get_record(PRODUCT_LAYOUT, record_id)
    except FileMakerAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Image not found."},
        ) from exc
    record = data[0] if isinstance(data, list) and data else data if isinstance(data, dict) else None
    fields = record.get("fieldData", {}) if isinstance(record, dict) else {}
    if str(fields.get("id_client") or "").strip() != session.part_customer_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"message": "Image not found."})
    image_url = str(fields.get("檔案 1 | 容器") or "").strip()
    if not image_url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"message": "Image not found."})

    content, content_type = await _download_customer_attachment(filemaker, image_url)
    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/products/{record_id}/images/{asset_record_id}")
async def get_customer_product_asset_image(
    record_id: str,
    asset_record_id: str,
    session: CustomerSession = Depends(get_customer_session),
    filemaker: FileMakerClient = Depends(get_filemaker_client),
) -> Response:
    _require_customer_detail_access(session)
    if not record_id.isdigit() or not asset_record_id.isdigit():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"message": "Image not found."})
    try:
        product_data, asset_data = await asyncio.gather(
            filemaker.get_record(PRODUCT_LAYOUT, record_id),
            filemaker.get_record(PRODUCT_ASSET_LAYOUT, asset_record_id),
        )
    except FileMakerAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Image not found."},
        ) from exc

    product = _first_filemaker_record(product_data)
    asset = _first_filemaker_record(asset_data)
    product_fields = product.get("fieldData", {}) if product else {}
    asset_fields = asset.get("fieldData", {}) if asset else {}
    image_url = _customer_product_asset_url(
        record_id=record_id,
        client_id=session.part_customer_id,
        product_fields=product_fields,
        asset_fields=asset_fields,
    )
    content, content_type = await _download_customer_attachment(filemaker, image_url)
    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/parts/{record_id}/image")
async def get_customer_part_image(
    record_id: str,
    session: CustomerSession = Depends(get_customer_session),
    filemaker: FileMakerClient = Depends(get_filemaker_client),
    settings: Settings = Depends(get_settings),
    storage: COSStorageService = Depends(get_cos_storage_service),
) -> Response:
    _require_customer_detail_access(session)
    if not record_id.isdigit():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"message": "Image not found."})
    try:
        data = await filemaker.get_record(PART_LAYOUT, record_id)
    except FileMakerAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Image not found."},
        ) from exc
    record = data[0] if isinstance(data, list) and data else data if isinstance(data, dict) else None
    fields = record.get("fieldData", {}) if isinstance(record, dict) else {}
    part_number = str(fields.get("part_number") or "").strip()
    related_customer_code = str(fields.get("零件_客戶::客戶代號") or "").strip()
    if not part_number or related_customer_code != session.product_privilege:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"message": "Image not found."})

    try:
        scoped_records = await filemaker.find_records(
            PART_LAYOUT,
            query={
                "part_number": f"=={part_number}",
                "customer_id": f"=={session.part_customer_id}",
            },
            limit=100,
        )
    except FileMakerAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "Image not found."},
        ) from exc
    if not any(str(item.get("recordId") or "") == record_id for item in scoped_records["data"]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"message": "Image not found."})

    part_id = str(fields.get("part_id") or "").strip()
    if part_id:
        try:
            asset = await find_primary_part_asset(
                filemaker,
                settings,
                part_id=part_id,
                customer_visible_only=True,
            )
        except FileMakerAPIError:
            asset = None
        object_key = str(part_asset_fields(asset).get("object_key") or "").strip()
        try:
            asset_url, _expires_at = (
                await run_in_threadpool(storage.create_presigned_download, object_key)
                if object_key
                else ("", None)
            )
        except COSStorageError:
            asset_url = ""
        if asset_url:
            return RedirectResponse(
                asset_url,
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                headers={
                    "Cache-Control": "private, max-age=300",
                    "X-Content-Type-Options": "nosniff",
                },
            )

    image_url = str(fields.get("影像 | 容器") or fields.get("圖面 | 容器") or "").strip()
    if not image_url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"message": "Image not found."})
    content, content_type = await _download_customer_attachment(filemaker, image_url)
    return Response(
        content=content,
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _download_customer_attachment(filemaker: FileMakerClient, image_url: str) -> tuple[bytes, str]:
    source_host = urlparse(filemaker.settings.filemaker_host).hostname
    target_host = urlparse(image_url).hostname
    if not source_host or target_host != source_host:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"message": "Image not found."})
    token = await filemaker.get_token()
    async with httpx.AsyncClient(
        timeout=filemaker.settings.filemaker_timeout_seconds,
        verify=filemaker.settings.filemaker_ssl_verify,
        follow_redirects=True,
    ) as image_client:
        response = await image_client.get(image_url, headers={"Authorization": f"Bearer {token}"})
    if not response.is_success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": "The product image is temporarily unavailable."},
        )
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if (
        content_type not in CUSTOMER_ATTACHMENT_MEDIA_TYPES
        or len(response.content) > MAX_CUSTOMER_ATTACHMENT_BYTES
    ):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"message": "Unsupported product file."},
        )
    return response.content, content_type


def _first_filemaker_record(data: object) -> dict[str, object]:
    if isinstance(data, list):
        record = data[0] if data else None
    else:
        record = data
    return record if isinstance(record, dict) else {}


def _customer_product_asset_url(
    *,
    record_id: str,
    client_id: str,
    product_fields: dict[str, object],
    asset_fields: dict[str, object],
) -> str:
    allowed = (
        str(product_fields.get("id_client") or "").strip() == client_id
        and str(asset_fields.get("source_record_id") or "").strip() == record_id
        and str(asset_fields.get("id_client_snapshot") or "").strip() == client_id
        and str(asset_fields.get("asset_type") or "").strip() == "product_image"
        and str(asset_fields.get("visibility") or "").strip() == "customer"
        and str(asset_fields.get("migration_status") or "").strip() == "copied"
    )
    image_url = str(asset_fields.get("asset_file") or "").strip()
    if not allowed or not image_url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"message": "Image not found."})
    return image_url


def _profile(session: CustomerSession) -> CustomerProfile:
    return CustomerProfile(
        username=session.username,
        displayName=session.display_name,
        clientName=session.client_name,
        accessRole=session.access_role,
        canViewPrice=session.can_view_price,
        canViewOrders=session.can_view_orders,
        canViewDetails=session.can_view_details,
        isAdmin=session.is_admin,
    )


def _customer_account_admin_item(
    state: dict[str, object],
    *,
    credentials_email_sent: bool | None = None,
    credentials_email_error: str = "",
) -> CustomerAccountAdminItem:
    role = normalize_customer_access_role(
        state.get("accessRole"),
        is_admin=bool(state["isAdmin"]),
    )
    permissions = customer_access_permissions(role)
    return CustomerAccountAdminItem(
        username=str(state["username"]),
        displayName=str(state["displayName"]),
        email=str(state.get("email") or ""),
        clientName=str(state["clientName"]),
        productPrivilege=str(state["productPrivilege"]),
        partCustomerId=str(state["partCustomerId"]),
        shipmentCompanyId=str(state["shipmentCompanyId"]),
        enabled=bool(state["enabled"]),
        accessRole=role,
        canViewPrice=bool(state["canViewPrice"]),
        canViewOrders=permissions["canViewOrders"],
        canViewDetails=permissions["canViewDetails"],
        isAdmin=permissions["isAdmin"],
        lastLoginAt=state["lastLoginAt"],
        lastLoginStatus=str(state["lastLoginStatus"]),
        lastSuccessfulLoginAt=state["lastSuccessfulLoginAt"],
        lastFailedLoginAt=state["lastFailedLoginAt"],
        successfulLoginCount=int(state["successfulLoginCount"]),
        failedLoginCount=int(state["failedLoginCount"]),
        updatedAt=state["updatedAt"],
        updatedBy=str(state["updatedBy"]),
        credentialsEmailAvailableAt=state.get("credentialsEmailAvailableAt"),
        credentialsEmailSent=credentials_email_sent,
        credentialsEmailError=credentials_email_error,
    )


def _customer_account_audit_data(state: dict[str, object]) -> dict[str, object]:
    role = normalize_customer_access_role(
        state.get("accessRole"),
        is_admin=bool(state["isAdmin"]),
    )
    permissions = customer_access_permissions(role)
    return {
        "username": str(state["username"]),
        "displayName": str(state["displayName"]),
        "email": str(state.get("email") or ""),
        "clientName": str(state["clientName"]),
        "productPrivilege": str(state["productPrivilege"]),
        "partCustomerId": str(state["partCustomerId"]),
        "shipmentCompanyId": str(state["shipmentCompanyId"]),
        "enabled": bool(state["enabled"]),
        "accessRole": role,
        "canViewPrice": bool(state["canViewPrice"]),
        "canViewOrders": permissions["canViewOrders"],
        "canViewDetails": permissions["canViewDetails"],
        "isAdmin": permissions["isAdmin"],
    }


def _require_customer_admin(session: CustomerSession) -> None:
    if not session.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Administrator permission is required to view chat history.",
                "code": "admin_permission",
            },
        )


def _require_customer_detail_access(session: CustomerSession) -> None:
    if not session.can_view_details:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "This account is limited to inventory lookup.",
                "code": "inventory_only",
            },
        )


def _validate_customer_sensitive_prompt(prompt: str, *, can_view_price: bool) -> None:
    """Apply permission and sensitive-data rules before domain-specific routing."""
    normalized = " ".join(prompt.casefold().split())
    if _customer_asks_for_price(prompt) and not can_view_price:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Your account does not have permission to view prices.",
                "code": "price_permission",
            },
        )

    financial_text = re.sub(
        r"shipping\s+(?:cost|fee)|运费|運費|物流费用|物流費用|快递费用|快遞費用",
        " ",
        normalized,
        flags=re.IGNORECASE,
    )
    if any(term in financial_text for term in _SENSITIVE_FINANCIAL_QUERY_TERMS):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Costs and quotations are not available in this portal.",
                "code": "sensitive_financial",
            },
        )

    sensitive_internal_terms = (
        "供应商", "供應商", "厂商", "廠商", "采购", "採購", "利润", "利潤",
        "毛利", "内部备注", "內部備註", "supplier", "vendor", "purchase order", "margin",
    )
    if any(term in normalized for term in sensitive_internal_terms):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Supplier, purchasing, profit, and internal-note data are not available in this portal.",
                "code": "internal_data",
            },
        )


def _validate_customer_prompt(prompt: str, *, can_view_price: bool = False) -> None:
    """Reject queries outside the external inventory/basic-list policy."""
    _validate_customer_sensitive_prompt(prompt, can_view_price=can_view_price)
    normalized = " ".join(prompt.casefold().split())
    if any(term in normalized for term in _INTERNAL_QUERY_TERMS):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "This portal only provides approved product lists and inventory."},
        )
    compact = re.sub(r"[\s，。！？、；：,.!?;:]", "", normalized)
    if compact in _GREETING_PROMPTS or any(term in normalized for term in _OUT_OF_SCOPE_QUERY_TERMS):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": (
                    "Please ask about a product or part number, name, model, inventory, or date."
                )
            },
        )


def _customer_asks_for_price(prompt: str) -> bool:
    normalized = " ".join(prompt.casefold().split())
    return any(term in normalized for term in _PRICE_QUERY_TERMS)


def _customer_query_identifier(prompt: str) -> str | None:
    candidates = re.findall(
        r"(?<![A-Za-z0-9])([A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*)(?![A-Za-z0-9])",
        prompt,
    )
    for candidate in candidates:
        if len(candidate) >= 4 and re.search(r"[A-Za-z]", candidate) and re.search(r"\d", candidate):
            return candidate.upper()
    return None


def _customer_prompt_domain(prompt: str) -> Literal["product", "part"] | None:
    """Return only a domain the customer explicitly named."""
    normalized = " ".join(prompt.casefold().split())
    names_part = (
        any(term in normalized for term in ("零件", "配件", "备件", "備件", "part_number"))
        or bool(re.search(r"\b(?:parts?|spares?)\b", normalized))
    )
    names_product = (
        any(term in normalized for term in ("产品", "產品", "product_sku"))
        or bool(re.search(r"\b(?:products?|sku)\b", normalized))
    )
    if names_part == names_product:
        return None
    return "part" if names_part else "product"


async def _resolve_customer_identifier_domain(
    filemaker: FileMakerClient,
    identifier: str,
    *,
    customer_id: str,
) -> Literal["product", "part", "ambiguous", "not_found"]:
    """Find an unlabeled item number in both customer-scoped catalogs."""
    product_result, part_result = await asyncio.gather(
        filemaker.find_records(
            PRODUCT_LAYOUT,
            query={
                "product_sku": f"=={identifier}",
                "id_client": f"=={customer_id}",
            },
            limit=1,
        ),
        filemaker.find_records(
            PART_LAYOUT,
            query={
                "part_number": f"=={identifier}",
                "customer_id": f"=={customer_id}",
            },
            limit=1,
        ),
    )
    product_found = int(product_result.get("foundCount") or 0) > 0
    part_found = int(part_result.get("foundCount") or 0) > 0
    if product_found and part_found:
        return "ambiguous"
    if product_found:
        return "product"
    if part_found:
        return "part"
    return "not_found"


def _customer_identifier_clarification(
    body: CustomerQueryRequest,
    identifier: str,
    *,
    matched_both: bool,
    asks_for_price: bool,
) -> CustomerQueryResponse:
    if asks_for_price:
        options = [
            f"What is the unit price for product {identifier}?",
            f"What is the unit price for part {identifier}?",
        ]
    elif any(term in body.prompt.casefold() for term in ("库存", "庫存", "inventory", "stock")):
        options = [
            f"Check product inventory for {identifier}",
            f"Check part inventory for {identifier}",
        ]
    else:
        options = [
            f"Search product {identifier}",
            f"Search part {identifier}",
        ]
    answer = (
        f"{identifier} exists in both the product and part catalogs. "
        "Please choose which catalog you want to search."
        if matched_both
        else (
            f"I could not identify the catalog for {identifier}. "
            "Please tell me whether it is a product or a part."
        )
    )
    return CustomerQueryResponse(
        resultType="product",
        answer=answer,
        rows=[],
        foundCount=0,
        returnedCount=0,
        page=body.page,
        pageSize=body.page_size,
        totalPages=1,
        hasPrevious=False,
        hasNext=False,
        requiresClarification=True,
        clarificationQuestion=f"Is {identifier} a product or a part?",
        clarificationOptions=options,
    )


def _customer_price_text(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return str(value).strip() or "not available"


def _http_exception_message(exc: HTTPException) -> str:
    if isinstance(exc.detail, dict):
        return str(exc.detail.get("message") or "The request could not be completed.")
    return str(exc.detail or "The request could not be completed.")


def _http_exception_code(exc: HTTPException) -> str:
    if isinstance(exc.detail, dict):
        return str(exc.detail.get("code") or "")
    return ""


async def _record_customer_query_safe(
    history_store: CustomerChatHistoryStore,
    *,
    session: CustomerSession,
    body: CustomerQueryRequest,
    started_at: float,
    status_value: str,
    http_status: int,
    answer: str,
    blocked_reason: str = "",
    domain: str = "",
    intent: str = "",
    result_type: str = "",
    found_count: int = 0,
    returned_count: int = 0,
    source_layout: str = "",
    response_meta: dict[str, object] | None = None,
    channel: str = "web",
    is_test: bool = False,
) -> int | None:
    try:
        return await history_store.record(
            operator=session.operator,
            client_name=session.client_name,
            is_admin=session.is_admin,
            prompt=body.prompt,
            domain=domain,
            intent=intent,
            result_type=result_type,
            status=status_value,
            http_status=http_status,
            answer=answer,
            blocked_reason=blocked_reason,
            found_count=found_count,
            returned_count=returned_count,
            duration_ms=round((time.perf_counter() - started_at) * 1000),
            source_layout=source_layout,
            response_meta=response_meta,
            channel=channel,
            is_test=is_test,
        )
    except Exception:
        logger.exception("Unable to persist customer chat history")
        return None


def _customer_query_validation_message(exc: HTTPException) -> str:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    original_message = str(detail.get("message") or "")
    date_error_terms = (
        "日期查询字段",
        "新增/创建日期",
        "creation-date",
        "creation date",
        "created date",
    )
    if any(term in original_message.lower() for term in date_error_terms):
        return "Creation-date search is not available for this catalog."
    return "Try searching by product or part number, name, model, inventory, or date."


def _customer_order_search(prompt: str) -> str | None:
    """Compatibility wrapper used by focused prompt-normalization tests."""
    plan = _customer_order_query_plan(prompt)
    return None if plan is None else plan.search


def _customer_order_query_plan(
    prompt: str,
    *,
    today: date | None = None,
) -> CustomerOrderQueryPlan | None:
    """Recognize an approved order question and build deterministic filters."""
    normalized = " ".join(prompt.strip().split())
    folded = normalized.casefold()
    if not any(term in folded for term in _ORDER_CJK_TERMS) and not _ORDER_ENGLISH_PATTERN.search(folded):
        return None

    reference_date = today or _customer_query_today("Asia/Shanghai")
    start_date, end_date = _customer_order_date_range(normalized, reference_date)
    date_field = _customer_order_date_field(folded) if start_date and end_date else None
    is_not_shipped = bool(re.search(
        r"未出[货貨]|尚未出[货貨]|not\s+shipped|unshipped",
        folded,
        re.IGNORECASE,
    ))
    is_shipped = not is_not_shipped and bool(re.search(
        r"已(?:经|經)?出[货貨]|已[发發][货貨]|\bshipped\b",
        folded,
        re.IGNORECASE,
    ))
    shipping_status: Literal["all", "shipped", "notShipped"] = (
        "notShipped" if is_not_shipped else "shipped" if is_shipped else "all"
    )
    search = _strip_customer_order_dates(normalized) if start_date and end_date else normalized
    if start_date and end_date:
        search = re.sub(
            r"备好日期|備好日期|完成日期|收款日期|签名日期|簽名日期|更新日期|修改日期|"
            r"订单日期|訂單日期|出货日期|出貨日期|"
            r"\b(?:order|ready|completion|completed|payment|signature|updated|modified|shipped)\s+date\b",
            " ",
            search,
            flags=re.IGNORECASE,
        )

    search = re.sub(
        r"未出[货貨]|尚未出[货貨]|已(?:经|經)?出[货貨]|已[发發][货貨]|"
        r"\bnot\s+shipped\b|\bunshipped\b|\bshipped\b",
        " ",
        search,
        flags=re.IGNORECASE,
    )
    search = re.sub(
        r"出库单号|出庫單號|出货单号|出貨單號|出库单|出庫單|出货单|出貨單|"
        r"订单号|訂單號|订单|訂單|"
        r"物流单号|物流單號|物流|快递单号|快遞單號|快递|快遞|"
        r"运单号|運單號|运单|運單|发货|發貨|配送|追踪号|追蹤號|追踪|追蹤|"
        r"包装状态|包裝狀態|付款状态|付款狀態|订单分类|訂單分類|"
        r"订单概要|訂單概要|物流公司|快递公司|快遞公司|货运公司|貨運公司|"
        r"出货国家|出貨國家|国家|國家|"
        r"客户备注|客戶備註|备注|備註|客户名称|客戶名稱|客户代码|客戶代號|"
        r"产品编号|產品編號|客户SKU|客戶SKU|产品名称|產品名稱|产品|產品|"
        r"单号|單號|编号|編號|日期|费用|費用|运费|運費|金额|金額|多少钱|多少錢",
        " ",
        search,
        flags=re.IGNORECASE,
    )
    search = re.sub(
        r"\b(?:please|show|view|find|search|query|list|open|my|all|the|for|where|is|"
        r"status|details?|records?|history|orders?|shipments?|shipping|tracking|"
        r"deliveries|delivery|numbers?|cost|fee|date|between|from|to|and|"
        r"purchase|customer|client|product|sku|country|carrier|company|this|last|month|today|yesterday)\b",
        " ",
        search,
        flags=re.IGNORECASE,
    )
    search = re.sub(
        r"帮我|幫我|请|請|查询|查詢|查看|查找|搜索|显示|顯示|列出|所有|全部|我的|我|的|包含|含有|"
        r"从|從|自|到|至|之间|之間|范围|範圍|本月|这个月|這個月|上月|上个月|上個月|今天|今日|昨天",
        " ",
        search,
    )
    search = re.sub(r"[\s，。！？、；：,.!?;:]+", " ", search).strip()

    return CustomerOrderQueryPlan(
        search=search[:80],
        date_field=date_field,
        start_date=start_date,
        end_date=end_date,
        shipping_status=shipping_status,
    )


def _customer_order_date_range(value: str, today: date) -> tuple[date | None, date | None]:
    folded = value.casefold()
    if re.search(r"今天|今日|\btoday\b", folded):
        return today, today
    if re.search(r"昨天|\byesterday\b", folded):
        target = today - timedelta(days=1)
        return target, target
    if re.search(r"本月|这个月|這個月|\bthis\s+month\b", folded):
        return _month_range(today.year, today.month)
    if re.search(r"上月|上个月|上個月|\blast\s+month\b", folded):
        previous = today.replace(day=1) - timedelta(days=1)
        return _month_range(previous.year, previous.month)

    matches: list[tuple[int, int, date]] = []
    occupied: list[tuple[int, int]] = []
    for pattern in _ORDER_EXPLICIT_DATE_PATTERNS:
        for match in pattern.finditer(value):
            span = match.span()
            if any(span[0] < end and span[1] > start for start, end in occupied):
                continue
            year_text = match.groupdict().get("year")
            candidate = _safe_date(
                int(year_text) if year_text else today.year,
                int(match.group("month")),
                int(match.group("day")),
            )
            if candidate is not None:
                matches.append((span[0], span[1], candidate))
                occupied.append(span)
    matches.sort(key=lambda item: item[0])
    if matches:
        start = matches[0][2]
        end = matches[1][2] if len(matches) > 1 else start
        return (start, end) if start <= end else (end, start)

    month_match = re.search(r"(?<!\d)(\d{4})年(\d{1,2})月", value)
    if month_match is None:
        month_match = re.search(r"(?<!\d)(\d{4})[-/](\d{1,2})(?![-/]\d)", value)
    if month_match:
        return _month_range(int(month_match.group(1)), int(month_match.group(2)))
    month_without_year = re.search(r"(?<!\d)(\d{1,2})月(?:份)?", value)
    if month_without_year:
        return _month_range(today.year, int(month_without_year.group(1)))
    return None, None


def _customer_order_date_field(value: str) -> str:
    if re.search(r"备好|備好|ready", value, re.IGNORECASE):
        return "備好日期"
    if re.search(r"完成|complete", value, re.IGNORECASE):
        return "完成日期"
    if re.search(r"收款|payment", value, re.IGNORECASE):
        return "收款日期"
    if re.search(r"签名|簽名|signature", value, re.IGNORECASE):
        return "簽名日期"
    if re.search(r"更新|修改|updated|modified", value, re.IGNORECASE):
        return "updated_at"
    if re.search(r"订单日期|訂單日期|下单|下單|order\s+date", value, re.IGNORECASE):
        return "日期"
    if re.search(r"出货日期|出貨日期|shipped\s+date", value, re.IGNORECASE):
        return "出貨日期"
    return "日期"


def _strip_customer_order_dates(value: str) -> str:
    cleaned = value
    for pattern in _ORDER_EXPLICIT_DATE_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = re.sub(r"(?<!\d)\d{4}年\d{1,2}月", " ", cleaned)
    cleaned = re.sub(r"(?<!\d)\d{4}[-/]\d{1,2}(?![-/]\d)", " ", cleaned)
    cleaned = re.sub(r"(?<!\d)\d{1,2}月(?:份)?", " ", cleaned)
    return cleaned


def _month_range(year: int, month: int) -> tuple[date | None, date | None]:
    start = _safe_date(year, month, 1)
    if start is None:
        return None, None
    next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    return start, next_month - timedelta(days=1)


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _customer_query_today(timezone_name: str) -> date:
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("Asia/Shanghai")
    return datetime.now(timezone).date()


def _normalize_customer_prompt(prompt: str) -> str:
    """Turn supported broad list phrases into a safely scoped product listing."""
    sql_text = " ".join(prompt.strip().casefold().split())
    if re.search(r'\bselect\s+part_number\s+from\s+["“”]?零件["“”]?', sql_text):
        return "零件"
    if re.search(r'\bselect\s+product_sku\s+from\s+["“”]?(?:產品|产品)["“”]?', sql_text):
        return "产品"
    compact = re.sub(r"[\s，。！？、；：,.!?;:]", "", prompt.strip().casefold())
    inventory_match = re.fullmatch(
        r"(?:check|view|show|find)?inventory(?:for)?([a-z0-9][a-z0-9_-]*)",
        compact,
    )
    if inventory_match:
        return f"查询 {inventory_match.group(1).upper()} 库存"
    if compact in _BASIC_PART_LIST_PROMPTS:
        return "零件"
    return "产品" if compact in _BASIC_LIST_PROMPTS else prompt.strip()


def _customer_english_text(value: object) -> str:
    text = "" if value is None else str(value).strip()
    translations = {
        "零件包": "Parts kit",
        "成品": "Finished product",
        "整车": "Complete vehicle",
        "整車": "Complete vehicle",
        "配件": "Accessories",
    }
    if text in translations:
        return translations[text]
    if re.search(r"[\u3400-\u9fff]", text):
        return ""
    cleaned = re.sub(r"[\u3040-\u30ff]+", "", text)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _customer_query_answer(
    *,
    result_type: str,
    found_count: int,
    returned_count: int,
    page: int,
    total_pages: int,
) -> str:
    singular, plural = {
        "part": ("part", "parts"),
        "order": ("shipment record", "shipment records"),
    }.get(result_type, ("product", "products"))
    if found_count <= 0:
        return f"No matching {singular} was found in your available catalog."
    if returned_count <= 0:
        return (
            f"Found {found_count} matching {singular if found_count == 1 else plural}, "
            f"but page {page} has no results. Please use page {total_pages} or earlier."
        )
    return f"Found {found_count} matching {singular if found_count == 1 else plural}."
