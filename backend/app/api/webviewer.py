from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

import asyncio

from app.core.config import Settings
from app.models.webviewer_admin import (
    WebViewerAccountAdminItem,
    WebViewerAccountAdminResponse,
    WebViewerAccountAdminUpdateRequest,
    WebViewerAccountRegisterRequest,
    LlmProviderStatusResponse,
    LlmProviderSwitchRequest,
    MobileDiagnosticReportDetail,
    MobileDiagnosticReportListResponse,
    WebViewerPrivilegeSetAdminItem,
    WebViewerPrivilegeSetAdminUpdateRequest,
)
from app.models.webviewer import (
    WebViewerCurrentSessionResponse,
    WebViewerCurrentUser,
    WebViewerSessionRequest,
    WebViewerSessionResponse,
)
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.customer_chat_auth import (
    CustomerLoginRateLimiter,
    hash_customer_password,
)
from app.services.part_permission_catalog import permission_catalog
from app.services.service_directory import api_service_directory
from app.services.dependencies import (
    get_audit_log_store,
    get_llm_provider_manager,
    get_operator_context,
    get_settings,
    get_webviewer_access,
    get_webviewer_account_access_store,
    get_webviewer_session_context,
)
from app.services.webviewer_account_access import WebViewerAccountAccessStore
from app.services.llm_provider_manager import (
    LlmProviderConfigurationError,
    LlmProviderManager,
)
from app.services.webviewer_session import (
    WebViewerSessionError,
    create_mock_context,
    issue_session_token,
    verify_external_context,
)
from app.services.webviewer_remote_auth import (
    authenticate_webviewer_remote,
    is_webviewer_physical_pda_request,
    is_webviewer_mobile_request,
    webviewer_device_class,
    webviewer_remote_request_allowed,
)

router = APIRouter(prefix="/webviewer", tags=["webviewer"])
remote_login_limiter = CustomerLoginRateLimiter()


@router.post("/session", response_model=WebViewerSessionResponse)
async def create_webviewer_session(
    body: WebViewerSessionRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    account_access: WebViewerAccountAccessStore = Depends(get_webviewer_account_access_store),
) -> WebViewerSessionResponse:
    if not isinstance(account_access, WebViewerAccountAccessStore):
        # Keep direct service-level calls (used by tests and maintenance scripts)
        # independent from FastAPI's dependency injection container.
        account_access = WebViewerAccountAccessStore("memory://direct-webviewer-session")
        await account_access.init()
    client_channel = request.headers.get("X-Client-Channel", "")
    device_class = request.headers.get("X-Device-Class", "")
    physical_pda_request = is_webviewer_physical_pda_request(
        client_channel=client_channel,
        device_class=device_class,
    )
    web_account_state: dict | None = None
    if body.ctx and body.sig:
        if physical_pda_request:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"message": "物理设备必须使用员工账号和密码登录。"},
            )
        try:
            context = verify_external_context(body.ctx, body.sig, settings)
        except WebViewerSessionError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": str(exc)},
            ) from exc
        context["authenticationMethod"] = "signedContext"
    elif settings.webviewer_remote_access_enabled and body.username and body.password:
        limiter_key = body.username.strip().casefold()
        retry_after = await remote_login_limiter.retry_after(
            limiter_key,
            max_attempts=settings.webviewer_remote_login_max_attempts,
            window_seconds=settings.webviewer_remote_login_window_seconds,
        )
        if retry_after:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"message": "登录尝试过多，请稍后再试", "retryAfter": retry_after},
                headers={"Retry-After": str(retry_after)},
            )
        password = body.password.get_secret_value()
        web_account_state = await account_access.authenticate_account(
            body.username,
            password,
        )
        environment_account = authenticate_webviewer_remote(
            body.username,
            password,
            settings,
        )
        if not web_account_state and not environment_account:
            await remote_login_limiter.record_failure(
                limiter_key,
                window_seconds=settings.webviewer_remote_login_window_seconds,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": "用户名或密码不正确"},
            )
        if environment_account and not webviewer_remote_request_allowed(
            environment_account,
            client_channel=request.headers.get("X-Client-Channel", ""),
            user_agent=request.headers.get("User-Agent", ""),
        ):
            await remote_login_limiter.clear(limiter_key)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"message": "该账号仅允许通过指定的 PDA 应用登录"},
            )
        await remote_login_limiter.clear(limiter_key)
        if not web_account_state and environment_account:
            web_account_state = await account_access.register_account(
                username=environment_account.username,
                display_name=environment_account.display_name,
                privilege_set=environment_account.privilege_set,
                origin="environment",
                seen=False,
                password_hash=environment_account.password_hash,
            )
        if not web_account_state:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": "用户名或密码不正确"},
            )
        context = create_mock_context(
            operator_account=str(web_account_state["username"]),
            operator_name=str(web_account_state["displayName"]),
            operator_privilege=str(web_account_state["filemakerPrivilegeSet"]),
            persistent_id=str(web_account_state["username"]),
            product_sku=body.product_sku,
            order_id=body.order_id,
            line_id=body.line_id,
            bom_calc_id=body.bom_calc_id,
            customer_id=body.customer_id,
            customer_name=body.customer_name,
            currency=body.currency,
        )
        context["authenticationMethod"] = "webPassword"
    elif body.mock:
        if physical_pda_request:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"message": "物理设备必须使用员工账号和密码登录。"},
            )
        if not settings.webviewer_allow_mock_context:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "Signed ctx/sig is required"},
            )
        operator = body.operator
        context = create_mock_context(
            operator_account=operator.account if operator else "mock.operator",
            operator_name=operator.name if operator else "本地测试操作员",
            operator_privilege=operator.privilege if operator else "mock",
            product_sku=body.product_sku,
            order_id=body.order_id,
            line_id=body.line_id,
            bom_calc_id=body.bom_calc_id,
            customer_id=body.customer_id,
            customer_name=body.customer_name,
            currency=body.currency,
        )
        context["authenticationMethod"] = "mock"
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Signed ctx/sig is required"},
        )

    context_operator = context.get("operator") or {}
    account_state = web_account_state or await account_access.observe_account(
        username=str(context_operator.get("account") or "unknown"),
        display_name=str(
            context_operator.get("name")
            or context_operator.get("account")
            or "unknown"
        ),
        privilege_set=str(context_operator.get("privilege") or "unknown"),
    )
    if not account_state["enabled"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "此 Web 账号或其角色已停用。"},
        )
    if account_state["mobileOnly"] and not is_webviewer_mobile_request(
        client_channel=request.headers.get("X-Client-Channel", ""),
        user_agent=request.headers.get("User-Agent", ""),
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"message": "此账号仅允许通过移动端登录。"},
        )
    context["access"] = dict(account_state["permissions"])
    context["partPermissions"] = dict(account_state["partPermissions"])
    context["deviceClass"] = webviewer_device_class(
        client_channel=client_channel,
        device_class=device_class,
    )
    client_channel = client_channel.strip().lower()
    session_ttl_seconds = (
        settings.ios_pda_session_ttl_seconds
        if client_channel == "ios-pda"
        else settings.webviewer_session_ttl_seconds
    )
    token, session_payload = issue_session_token(
        context,
        settings,
        ttl_seconds=session_ttl_seconds,
    )
    session_id = session_payload["sessionId"]
    operator = session_payload.get("operator") or {}
    await audit_log.record(
        operator=OperatorContext(
            session_id=session_id,
            account=str(operator.get("account") or "unknown"),
            name=str(operator.get("name") or "unknown"),
            privilege=str(operator.get("privilege") or ""),
        ),
        action_type="WEBVIEWER_SESSION_START",
        status="success",
        product_sku=session_payload.get("productSku") or None,
        order_id=session_payload.get("orderId") or None,
        bom_calc_id=session_payload.get("bomCalcId") or None,
        request_payload={
            "mock": body.mock,
            "remoteLogin": bool(body.username),
            "hasSignedContext": bool(body.ctx and body.sig),
            "clientChannel": client_channel or "web",
            "deviceClass": context["deviceClass"],
            "authenticationMethod": context["authenticationMethod"],
            "sessionTtlSeconds": session_ttl_seconds,
        },
        response_payload={
            "sessionId": session_id,
            "readOnly": settings.filemaker_read_only,
            "bomWriteEnabled": settings.filemaker_bom_write_enabled,
        },
    )
    return WebViewerSessionResponse(
        token=token,
        sessionId=session_id,
        context=session_payload,
        readOnly=settings.filemaker_read_only,
        bomWriteEnabled=settings.filemaker_bom_write_enabled,
    )


@router.get("/session/me", response_model=WebViewerCurrentSessionResponse)
async def get_current_webviewer_session(
    session_context: dict = Depends(get_webviewer_session_context),
) -> WebViewerCurrentSessionResponse:
    operator = session_context.get("operator") or {}
    username = str(operator.get("account") or "unknown")
    return WebViewerCurrentSessionResponse(
        sessionId=str(session_context.get("sessionId") or ""),
        user=WebViewerCurrentUser(
            username=username,
            displayName=str(operator.get("name") or username),
            filemakerPrivilegeSet=str(operator.get("privilege") or "unknown"),
        ),
        permissions={
            str(key): bool(value)
            for key, value in (session_context.get("access") or {}).items()
        },
        partPermissions={
            str(key): bool(value)
            for key, value in (
                session_context.get("partPermissions") or {}
            ).items()
        },
    )


@router.get("/admin/accounts", response_model=WebViewerAccountAdminResponse)
async def list_webviewer_accounts(
    _access: dict[str, bool] = Depends(get_webviewer_access),
    store: WebViewerAccountAccessStore = Depends(get_webviewer_account_access_store),
) -> WebViewerAccountAdminResponse:
    return WebViewerAccountAdminResponse(
        accounts=await store.list_accounts(),
        privilegeSets=await store.list_privilege_sets(),
    )


@router.get(
    "/admin/part-permission-catalog",
    response_model=dict,
)
async def get_part_permission_catalog(
    _access: dict[str, bool] = Depends(get_webviewer_access),
) -> dict:
    return permission_catalog()


@router.get(
    "/admin/service-directory",
    response_model=dict,
)
async def get_service_directory(
    _access: dict[str, bool] = Depends(get_webviewer_access),
) -> dict:
    return api_service_directory()


@router.get(
    "/admin/mobile-diagnostic-reports",
    response_model=MobileDiagnosticReportListResponse,
)
async def list_mobile_diagnostic_reports(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
    query: str = Query(default="", alias="q", max_length=160),
    email_status: str = Query(default="", alias="emailStatus", max_length=40),
    _access: dict[str, bool] = Depends(get_webviewer_access),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> MobileDiagnosticReportListResponse:
    payload = await audit_log.list_mobile_diagnostic_reports(
        limit=page_size,
        offset=(page - 1) * page_size,
        query=query,
        email_status=email_status,
    )
    total = int(payload["total"])
    return MobileDiagnosticReportListResponse(
        items=payload["items"],
        total=total,
        page=page,
        pageSize=page_size,
        totalPages=max(1, (total + page_size - 1) // page_size),
    )


@router.get(
    "/admin/mobile-diagnostic-reports/{report_row_id}",
    response_model=MobileDiagnosticReportDetail,
)
async def get_mobile_diagnostic_report(
    report_row_id: int,
    _access: dict[str, bool] = Depends(get_webviewer_access),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> MobileDiagnosticReportDetail:
    report = await audit_log.get_mobile_diagnostic_report(report_row_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "找不到这份 PDA 错误报告。"},
        )
    return MobileDiagnosticReportDetail.model_validate(report)


@router.get(
    "/admin/llm-provider",
    response_model=LlmProviderStatusResponse,
)
async def get_llm_provider_status(
    _access: dict[str, bool] = Depends(get_webviewer_access),
    manager: LlmProviderManager = Depends(get_llm_provider_manager),
) -> LlmProviderStatusResponse:
    return LlmProviderStatusResponse.model_validate(manager.status())


@router.post(
    "/admin/llm-provider/switch",
    response_model=LlmProviderStatusResponse,
)
async def switch_llm_provider(
    body: LlmProviderSwitchRequest,
    operator: OperatorContext = Depends(get_operator_context),
    manager: LlmProviderManager = Depends(get_llm_provider_manager),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> LlmProviderStatusResponse:
    before = manager.status()
    try:
        after = await manager.switch(body.provider, updated_by=operator.account)
    except LlmProviderConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc)},
        ) from exc
    await audit_log.record(
        operator=operator,
        action_type="LLM_PROVIDER_SWITCH",
        status="success",
        before_data={"activeProvider": before["activeProvider"]},
        after_data={"activeProvider": after["activeProvider"]},
    )
    return LlmProviderStatusResponse.model_validate(after)


@router.get(
    "/admin/accounts/{username}",
    response_model=WebViewerAccountAdminItem,
)
async def get_webviewer_account(
    username: str,
    _access: dict[str, bool] = Depends(get_webviewer_access),
    store: WebViewerAccountAccessStore = Depends(get_webviewer_account_access_store),
) -> WebViewerAccountAdminItem:
    account = await store.get_account(username)
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "找不到此账号。"},
        )
    return WebViewerAccountAdminItem.model_validate(account)


@router.post(
    "/admin/accounts",
    response_model=WebViewerAccountAdminItem,
    status_code=status.HTTP_201_CREATED,
)
async def register_webviewer_account(
    body: WebViewerAccountRegisterRequest,
    operator: OperatorContext = Depends(get_operator_context),
    store: WebViewerAccountAccessStore = Depends(get_webviewer_account_access_store),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> WebViewerAccountAdminItem:
    if await store.get_account(body.username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "此账号已经存在。"},
        )
    account = await store.register_account(
        username=body.username,
        display_name=body.display_name,
        privilege_set=body.filemaker_privilege_set,
        origin="admin",
        seen=False,
        updated_by=operator.account,
    )
    password_hash = await asyncio.to_thread(
        hash_customer_password,
        body.password.get_secret_value(),
    )
    account = await store.set_password_hash(
        body.username,
        password_hash,
        updated_by=operator.account,
    )
    if not account:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "账号创建后无法保存密码。"},
        )
    requested_permissions = (
        body.permissions.model_dump(by_alias=True)
        if body.permissions is not None
        else account["permissions"]
    )
    requested_part_permissions = (
        body.part_permissions
        if body.part_permissions is not None
        else account["partPermissions"]
    )
    account = await store.update_account(
        body.username,
        enabled=body.enabled,
        mobile_only=body.mobile_only,
        permissions=requested_permissions,
        part_permissions=requested_part_permissions,
        inherit_privilege_set=body.inherit_privilege_set,
        inherit_part_permissions=body.inherit_part_permissions,
        updated_by=operator.account,
    )
    if not account:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "账号创建后无法写入权限设置。"},
        )
    await audit_log.record(
        operator=operator,
        action_type="WEBVIEWER_ACCOUNT_REGISTER",
        status="success",
        request_payload={
            "username": body.username,
            "displayName": body.display_name,
            "role": body.filemaker_privilege_set,
            "enabled": body.enabled,
            "mobileOnly": body.mobile_only,
        },
        response_payload={
            "username": account["username"],
            "filemakerPrivilegeSet": account["filemakerPrivilegeSet"],
        },
    )
    return WebViewerAccountAdminItem.model_validate(account)


@router.patch(
    "/admin/accounts/{username}",
    response_model=WebViewerAccountAdminItem,
)
async def update_webviewer_account(
    username: str,
    body: WebViewerAccountAdminUpdateRequest,
    session_context: dict = Depends(get_webviewer_session_context),
    operator: OperatorContext = Depends(get_operator_context),
    store: WebViewerAccountAccessStore = Depends(get_webviewer_account_access_store),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> WebViewerAccountAdminItem:
    current_username = str((session_context.get("operator") or {}).get("account") or "")
    permissions = body.permissions.model_dump(by_alias=True)
    before = await store.get_account(username)
    if not before:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "找不到此账号。"},
        )
    if username.casefold() == current_username.casefold():
        target_privilege_name = (
            body.filemaker_privilege_set or before["filemakerPrivilegeSet"]
        )
        target_privilege = next(
            (
                item
                for item in await store.list_privilege_sets()
                if item["name"].casefold() == target_privilege_name.casefold()
            ),
            None,
        )
        inherited_admin_access = bool(
            target_privilege
            and target_privilege["enabled"]
            and target_privilege["permissions"]["canManageAccounts"]
        )
        retains_admin_access = (
            inherited_admin_access
            if body.inherit_privilege_set
            else bool(
                target_privilege
                and target_privilege["enabled"]
                and permissions["canManageAccounts"]
            )
        )
        if not body.enabled or not retains_admin_access:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "不能停用当前管理员或移除自己的账号管理权限。"},
            )
        if body.mobile_only:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"message": "不能将当前登录的管理员改为仅移动端账号。"},
            )
    updated = await store.update_account(
        username,
        enabled=body.enabled,
        mobile_only=body.mobile_only,
        permissions=permissions,
        part_permissions=body.part_permissions,
        inherit_privilege_set=body.inherit_privilege_set,
        inherit_part_permissions=body.inherit_part_permissions,
        display_name=body.display_name,
        privilege_set=body.filemaker_privilege_set,
        updated_by=operator.account,
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if body.password is not None:
        password_hash = await asyncio.to_thread(
            hash_customer_password,
            body.password.get_secret_value(),
        )
        updated = await store.set_password_hash(
            username,
            password_hash,
            updated_by=operator.account,
        )
        if not updated:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await audit_log.record(
        operator=operator,
        action_type="WEBVIEWER_ACCOUNT_POLICY_UPDATE",
        status="success",
        before_data=before,
        after_data=updated,
    )
    return WebViewerAccountAdminItem.model_validate(updated)


@router.delete(
    "/admin/accounts/{username}",
    status_code=status.HTTP_200_OK,
)
async def delete_webviewer_account(
    username: str,
    session_context: dict = Depends(get_webviewer_session_context),
    operator: OperatorContext = Depends(get_operator_context),
    store: WebViewerAccountAccessStore = Depends(get_webviewer_account_access_store),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> dict:
    current_username = str((session_context.get("operator") or {}).get("account") or "")
    if username.casefold() == current_username.casefold():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "不能删除当前登录的管理员账号。"},
        )
    deleted = await store.delete_account(username)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "找不到此账号。"},
        )
    await audit_log.record(
        operator=operator,
        action_type="WEBVIEWER_ACCOUNT_DELETE",
        status="success",
        before_data=deleted,
        response_payload={
            "username": deleted["username"],
            "origin": deleted["origin"],
        },
    )
    return {
        "ok": True,
        "username": deleted["username"],
        "willResync": deleted["origin"] == "filemaker",
    }


@router.patch(
    "/admin/privilege-sets/{privilege_set}",
    response_model=WebViewerPrivilegeSetAdminItem,
)
async def update_webviewer_privilege_set(
    privilege_set: str,
    body: WebViewerPrivilegeSetAdminUpdateRequest,
    session_context: dict = Depends(get_webviewer_session_context),
    operator: OperatorContext = Depends(get_operator_context),
    store: WebViewerAccountAccessStore = Depends(get_webviewer_account_access_store),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> WebViewerPrivilegeSetAdminItem:
    current_privilege = str((session_context.get("operator") or {}).get("privilege") or "")
    permissions = body.permissions.model_dump(by_alias=True)
    if privilege_set.casefold() == current_privilege.casefold() and (
        not body.enabled or not permissions["canManageAccounts"]
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "不能停用当前管理员所属权限集或移除其账号管理权限。"},
        )
    before = next(
        (
            item
            for item in await store.list_privilege_sets()
            if item["name"].casefold() == privilege_set.casefold()
        ),
        None,
    )
    if not before:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "找不到此账号角色。"},
        )
    updated = await store.update_privilege_set(
        privilege_set,
        enabled=body.enabled,
        permissions=permissions,
        part_permissions=body.part_permissions,
        updated_by=operator.account,
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await audit_log.record(
        operator=operator,
        action_type="WEBVIEWER_PRIVILEGE_SET_POLICY_UPDATE",
        status="success",
        before_data=before,
        after_data=updated,
    )
    return WebViewerPrivilegeSetAdminItem.model_validate(updated)
