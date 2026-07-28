from fastapi import APIRouter, Depends, HTTPException, status

import asyncio

from app.core.config import Settings
from app.models.webviewer_admin import (
    WebViewerAccountAdminItem,
    WebViewerAccountAdminResponse,
    WebViewerAccountAdminUpdateRequest,
    WebViewerAccountRegisterRequest,
    WebViewerPrivilegeSetAdminItem,
    WebViewerPrivilegeSetAdminUpdateRequest,
    WebViewerSendAdminCredentialsRequest,
)
from app.models.webviewer import WebViewerSessionRequest, WebViewerSessionResponse
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.customer_chat_auth import CustomerLoginRateLimiter
from app.services.customer_email import (
    CustomerEmailError,
    send_admin_credentials_email,
)
from app.services.part_permission_catalog import permission_catalog
from app.services.dependencies import (
    get_audit_log_store,
    get_operator_context,
    get_settings,
    get_webviewer_access,
    get_webviewer_account_access_store,
    get_webviewer_session_context,
)
from app.services.webviewer_account_access import WebViewerAccountAccessStore
from app.services.webviewer_session import (
    WebViewerSessionError,
    create_mock_context,
    issue_session_token,
    verify_external_context,
)
from app.services.webviewer_remote_auth import authenticate_webviewer_remote

router = APIRouter(prefix="/webviewer", tags=["webviewer"])
remote_login_limiter = CustomerLoginRateLimiter()


@router.post("/session", response_model=WebViewerSessionResponse)
async def create_webviewer_session(
    body: WebViewerSessionRequest,
    settings: Settings = Depends(get_settings),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
    account_access: WebViewerAccountAccessStore = Depends(get_webviewer_account_access_store),
) -> WebViewerSessionResponse:
    if not isinstance(account_access, WebViewerAccountAccessStore):
        # Keep direct service-level calls (used by tests and maintenance scripts)
        # independent from FastAPI's dependency injection container.
        account_access = WebViewerAccountAccessStore("memory://direct-webviewer-session")
        await account_access.init()
    if body.ctx and body.sig:
        try:
            context = verify_external_context(body.ctx, body.sig, settings)
        except WebViewerSessionError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": str(exc)},
            ) from exc
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
        account = authenticate_webviewer_remote(
            body.username,
            body.password.get_secret_value(),
            settings,
        )
        if not account:
            await remote_login_limiter.record_failure(
                limiter_key,
                window_seconds=settings.webviewer_remote_login_window_seconds,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"message": "用户名或密码不正确"},
            )
        await remote_login_limiter.clear(limiter_key)
        context = create_mock_context(
            operator_account=account.username,
            operator_name=account.display_name,
            operator_privilege=account.privilege_set,
            persistent_id=account.username,
            product_sku=body.product_sku,
            order_id=body.order_id,
            bom_calc_id=body.bom_calc_id,
            customer_id=body.customer_id,
            customer_name=body.customer_name,
            currency=body.currency,
        )
    elif body.mock and settings.webviewer_allow_mock_context:
        operator = body.operator
        context = create_mock_context(
            operator_account=operator.account if operator else "mock.operator",
            operator_name=operator.name if operator else "本地测试操作员",
            operator_privilege=operator.privilege if operator else "mock",
            product_sku=body.product_sku,
            order_id=body.order_id,
            bom_calc_id=body.bom_calc_id,
            customer_id=body.customer_id,
            customer_name=body.customer_name,
            currency=body.currency,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Signed ctx/sig is required"},
        )

    context_operator = context.get("operator") or {}
    account_state = await account_access.observe_account(
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
            detail={"message": "此 StarRC 账号或其 FileMaker 权限集已停用。"},
        )
    context["access"] = dict(account_state["permissions"])
    context["partPermissions"] = dict(account_state["partPermissions"])
    token, session_payload = issue_session_token(context, settings)
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
        request_payload=body.model_dump(by_alias=True),
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
    updated = await store.update_account(
        username,
        enabled=body.enabled,
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
            detail={"message": "找不到此 FileMaker 权限集。"},
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


@router.post(
    "/admin/accounts/send-credentials",
    status_code=status.HTTP_200_OK,
)
async def send_admin_credentials(
    body: WebViewerSendAdminCredentialsRequest,
    operator: OperatorContext = Depends(get_operator_context),
    settings: Settings = Depends(get_settings),
    audit_log: AuditLogStore = Depends(get_audit_log_store),
) -> dict:
    """Email the StarRC admin backend credentials to a trusted recipient.

    The credentials are the deployed FileMaker Data API account
    (``FILEMAKER_USERNAME`` / ``FILEMAKER_PASSWORD``); the webviewer admin
    account store does not keep passwords locally.
    """
    username = settings.filemaker_username.strip()
    password = settings.filemaker_password
    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "后端未配置 FileMaker 管理员账号，无法发送。"},
        )
    try:
        await asyncio.to_thread(
            send_admin_credentials_email,
            settings,
            recipient_email=body.recipient_email,
            username=username,
            password=password,
        )
    except CustomerEmailError as exc:
        await audit_log.record(
            operator=operator,
            action_type="WEBVIEWER_ADMIN_CREDENTIALS_EMAIL",
            status="failure",
            request_payload={"recipientEmail": body.recipient_email},
            response_payload={"error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"message": f"邮件发送失败：{exc}"},
        ) from exc
    await audit_log.record(
        operator=operator,
        action_type="WEBVIEWER_ADMIN_CREDENTIALS_EMAIL",
        status="success",
        request_payload={"recipientEmail": body.recipient_email},
    )
    return {"ok": True, "recipient": body.recipient_email}
