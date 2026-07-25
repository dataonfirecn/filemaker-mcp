import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any

from app.core.config import Settings
from app.services.audit_log import OperatorContext
from app.services.customer_access import (
    customer_access_permissions,
    normalize_customer_access_role,
)
from app.services.customer_account_admin_store import CustomerAccountAdminStore
from app.services.customer_credential_store import CustomerCredentialStore


PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 600_000
INSECURE_SECRET_PLACEHOLDERS = {"", "change-me", "changeme", "secret"}


class CustomerAuthError(ValueError):
    pass


@dataclass(frozen=True)
class CustomerAccount:
    username: str
    display_name: str
    client_name: str
    product_privilege: str
    part_customer_id: str
    password_hash: str
    email: str = ""
    shipment_company_id: str = ""
    can_view_price: bool = False
    is_admin: bool = False
    access_role: str = ""

    def __post_init__(self) -> None:
        role = normalize_customer_access_role(
            self.access_role,
            can_view_price=self.can_view_price,
            is_admin=self.is_admin,
        )
        permissions = customer_access_permissions(role)
        object.__setattr__(self, "access_role", role)
        object.__setattr__(self, "can_view_price", permissions["canViewPrice"])
        object.__setattr__(self, "is_admin", permissions["isAdmin"])

    @property
    def can_view_orders(self) -> bool:
        return customer_access_permissions(self.access_role)["canViewOrders"]

    @property
    def can_view_details(self) -> bool:
        return customer_access_permissions(self.access_role)["canViewDetails"]


@dataclass(frozen=True)
class CustomerSession:
    session_id: str
    username: str
    display_name: str
    client_name: str
    product_privilege: str
    part_customer_id: str
    expires_at: int
    shipment_company_id: str = ""
    can_view_price: bool = False
    is_admin: bool = False
    access_role: str = ""

    def __post_init__(self) -> None:
        role = normalize_customer_access_role(
            self.access_role,
            can_view_price=self.can_view_price,
            is_admin=self.is_admin,
        )
        permissions = customer_access_permissions(role)
        object.__setattr__(self, "access_role", role)
        object.__setattr__(self, "can_view_price", permissions["canViewPrice"])
        object.__setattr__(self, "is_admin", permissions["isAdmin"])

    @property
    def can_view_orders(self) -> bool:
        return customer_access_permissions(self.access_role)["canViewOrders"]

    @property
    def can_view_details(self) -> bool:
        return customer_access_permissions(self.access_role)["canViewDetails"]

    @property
    def operator(self) -> OperatorContext:
        return OperatorContext(
            session_id=self.session_id,
            account=self.username,
            name=self.display_name,
            privilege="external_customer",
            persistent_id=self.client_name,
        )


def customer_account_from_admin_state(
    state: dict[str, Any],
    password_hash: str,
) -> CustomerAccount:
    return CustomerAccount(
        username=str(state["username"]),
        display_name=str(state["displayName"]),
        client_name=str(state["clientName"]),
        product_privilege=str(state["productPrivilege"]),
        part_customer_id=str(state["partCustomerId"]),
        shipment_company_id=str(state["shipmentCompanyId"]),
        password_hash=password_hash,
        email=str(state.get("email") or ""),
        can_view_price=bool(state["canViewPrice"]),
        is_admin=bool(state["isAdmin"]),
        access_role=str(state.get("accessRole") or ""),
    )


class CustomerLoginRateLimiter:
    def __init__(self) -> None:
        self._attempts: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()

    async def retry_after(self, key: str, *, max_attempts: int, window_seconds: int) -> int:
        now = time.monotonic()
        async with self._lock:
            attempts = self._active_attempts(key, now, window_seconds)
            if len(attempts) < max(1, max_attempts):
                return 0
            return max(1, int(window_seconds - (now - attempts[0])))

    async def record_failure(self, key: str, *, window_seconds: int) -> None:
        now = time.monotonic()
        async with self._lock:
            attempts = self._active_attempts(key, now, window_seconds)
            attempts.append(now)
            self._attempts[key] = attempts

    async def clear(self, key: str) -> None:
        async with self._lock:
            self._attempts.pop(key, None)

    def _active_attempts(self, key: str, now: float, window_seconds: int) -> list[float]:
        cutoff = now - max(1, window_seconds)
        attempts = [item for item in self._attempts.get(key, []) if item > cutoff]
        if attempts:
            self._attempts[key] = attempts
        else:
            self._attempts.pop(key, None)
        return attempts


def hash_customer_password(password: str, *, iterations: int = PASSWORD_ITERATIONS) -> str:
    if not password:
        raise ValueError("Password cannot be empty")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{PASSWORD_SCHEME}${iterations}${salt.hex()}${digest.hex()}"


def verify_customer_password(password: str, encoded: str) -> bool:
    try:
        scheme, iteration_text, salt_hex, digest_hex = encoded.split("$", 3)
        if scheme != PASSWORD_SCHEME:
            return False
        iterations = int(iteration_text)
        if iterations < 100_000 or iterations > 2_000_000:
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (TypeError, ValueError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def load_customer_accounts(settings: Settings) -> dict[str, CustomerAccount]:
    try:
        raw = json.loads(settings.customer_chat_accounts_json or "[]")
    except json.JSONDecodeError as exc:
        raise CustomerAuthError("CUSTOMER_CHAT_ACCOUNTS_JSON is not valid JSON") from exc
    if not isinstance(raw, list):
        raise CustomerAuthError("CUSTOMER_CHAT_ACCOUNTS_JSON must be an account array")

    accounts: dict[str, CustomerAccount] = {}
    for item in raw:
        if not isinstance(item, dict) or item.get("enabled") is False:
            continue
        username = str(item.get("username") or "").strip()
        display_name = str(item.get("displayName") or username).strip()
        client_name = str(item.get("clientName") or item.get("client") or "").strip()
        product_privilege = str(item.get("productPrivilege") or "").strip()
        part_customer_id = str(item.get("partCustomerId") or "").strip()
        shipment_company_id = str(item.get("shipmentCompanyId") or "").strip()
        email = str(item.get("email") or "").strip()
        can_view_price = item.get("canViewPrice") is True
        is_admin = item.get("isAdmin") is True
        access_role = normalize_customer_access_role(
            item.get("accessRole"),
            can_view_price=can_view_price,
            is_admin=is_admin,
        )
        password_hash = str(item.get("passwordHash") or "").strip()
        if not username or not client_name or not product_privilege or not part_customer_id or not password_hash:
            raise CustomerAuthError(
                "Each external account requires username, clientName, productPrivilege, "
                "partCustomerId, and passwordHash"
            )
        key = username.casefold()
        if key in accounts:
            raise CustomerAuthError(f"Duplicate external account: {username}")
        accounts[key] = CustomerAccount(
            username=username,
            display_name=display_name or username,
            client_name=client_name,
            product_privilege=product_privilege,
            part_customer_id=part_customer_id,
            password_hash=password_hash,
            email=email,
            shipment_company_id=shipment_company_id,
            can_view_price=can_view_price,
            is_admin=is_admin,
            access_role=access_role,
        )
    return accounts


def account_with_password_hash(
    account: CustomerAccount,
    password_hash_override: str | None,
) -> CustomerAccount:
    if not password_hash_override:
        return account
    return replace(account, password_hash=password_hash_override)


def authenticate_customer(
    username: str,
    password: str,
    settings: Settings,
    *,
    password_hash_override: str | None = None,
    account_override: CustomerAccount | None = None,
) -> CustomerAccount | None:
    account = account_override
    if account is None:
        accounts = load_customer_accounts(settings)
        account = accounts.get(username.strip().casefold())
    # Unknown users still perform a deliberately expensive hash check to reduce timing leakage.
    if account:
        account = account_with_password_hash(account, password_hash_override)
    password_hash = account.password_hash if account else _dummy_password_hash()
    valid = verify_customer_password(password, password_hash)
    return account if account and valid else None


def issue_customer_token(account: CustomerAccount, settings: Settings) -> tuple[str, CustomerSession]:
    now = int(time.time())
    payload = {
        "typ": "customer",
        "sessionId": str(uuid.uuid4()),
        "username": account.username,
        "displayName": account.display_name,
        "clientName": account.client_name,
        "productPrivilege": account.product_privilege,
        "partCustomerId": account.part_customer_id,
        "shipmentCompanyId": account.shipment_company_id,
        "canViewPrice": account.can_view_price,
        "canViewOrders": account.can_view_orders,
        "canViewDetails": account.can_view_details,
        "isAdmin": account.is_admin,
        "accessRole": account.access_role,
        "authVersion": _account_auth_version(account),
        "iat": now,
        "exp": now + settings.customer_chat_session_ttl_seconds,
    }
    encoded = _b64encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    token = f"{encoded}.{_sign(encoded, settings.customer_chat_token_secret)}"
    return token, _session_from_payload(payload)


def verify_customer_token(
    token: str,
    settings: Settings,
    *,
    password_hash_override: str | None = None,
    account_override: CustomerAccount | None = None,
) -> CustomerSession:
    if not settings.customer_chat_enabled or not settings.customer_chat_token_secret:
        raise CustomerAuthError("The customer portal is not enabled")
    try:
        encoded, signature = token.split(".", 1)
    except ValueError as exc:
        raise CustomerAuthError("Invalid sign-in credentials") from exc
    expected = _sign(encoded, settings.customer_chat_token_secret)
    if not hmac.compare_digest(expected, signature):
        raise CustomerAuthError("Invalid sign-in credentials")
    try:
        payload = json.loads(_b64decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CustomerAuthError("Invalid sign-in credentials") from exc
    if payload.get("typ") != "customer":
        raise CustomerAuthError("Invalid sign-in credentials")
    if int(payload.get("exp") or 0) <= int(time.time()):
        raise CustomerAuthError("Your session has expired. Please sign in again")
    session = _session_from_payload(payload)
    if (
        not session.username
        or not session.client_name
        or not session.product_privilege
        or not session.part_customer_id
    ):
        raise CustomerAuthError("Invalid sign-in credentials")
    if account_override is None:
        accounts = load_customer_accounts(settings)
        account = accounts.get(session.username.casefold())
        if account:
            account = account_with_password_hash(account, password_hash_override)
    else:
        account = account_override
    if (
        not account
        or account.client_name != session.client_name
        or account.product_privilege != session.product_privilege
        or account.part_customer_id != session.part_customer_id
        or account.shipment_company_id != session.shipment_company_id
        or account.can_view_price != session.can_view_price
        or account.is_admin != session.is_admin
        or account.access_role != session.access_role
        or not hmac.compare_digest(
            str(payload.get("authVersion") or ""),
            _account_auth_version(account),
        )
    ):
        raise CustomerAuthError("The customer account has changed. Please sign in again")
    return session


async def verify_customer_token_with_store(
    token: str,
    settings: Settings,
    credential_store: CustomerCredentialStore,
    account_admin_store: CustomerAccountAdminStore,
) -> CustomerSession:
    username = _token_username(token, settings)
    state = await account_admin_store.get_state(username)
    if not state or not state["enabled"]:
        raise CustomerAuthError("The customer account is disabled")
    configured_account = load_customer_accounts(settings).get(username.casefold())
    password_hash_override = await credential_store.get_password_hash(username)
    password_hash = password_hash_override or (
        configured_account.password_hash if configured_account else ""
    )
    if not password_hash:
        raise CustomerAuthError("The customer account has changed. Please sign in again")
    account = customer_account_from_admin_state(state, password_hash)
    return verify_customer_token(
        token,
        settings,
        account_override=account,
    )


def validate_customer_chat_configuration(settings: Settings) -> list[str]:
    if not settings.customer_chat_enabled:
        return []
    problems: list[str] = []
    secret = settings.customer_chat_token_secret.strip()
    if len(secret) < 32 or secret.lower() in INSECURE_SECRET_PLACEHOLDERS:
        problems.append("CUSTOMER_CHAT_TOKEN_SECRET must be a random secret of at least 32 characters.")
    try:
        accounts = load_customer_accounts(settings)
    except CustomerAuthError as exc:
        problems.append(str(exc))
    else:
        if not accounts:
            problems.append("CUSTOMER_CHAT_ENABLED=true requires at least one external customer account.")
        for account in accounts.values():
            if not _valid_password_hash(account.password_hash):
                problems.append(f"External account {account.username} has an invalid or insufficient passwordHash.")
    return problems


def _valid_password_hash(value: str) -> bool:
    try:
        scheme, iteration_text, salt_hex, digest_hex = value.split("$", 3)
        return (
            scheme == PASSWORD_SCHEME
            and int(iteration_text) >= 100_000
            and len(bytes.fromhex(salt_hex)) >= 16
            and len(bytes.fromhex(digest_hex)) == 32
        )
    except (TypeError, ValueError):
        return False


def _session_from_payload(payload: dict[str, Any]) -> CustomerSession:
    return CustomerSession(
        session_id=str(payload.get("sessionId") or ""),
        username=str(payload.get("username") or ""),
        display_name=str(payload.get("displayName") or payload.get("username") or ""),
        client_name=str(payload.get("clientName") or ""),
        product_privilege=str(payload.get("productPrivilege") or ""),
        part_customer_id=str(payload.get("partCustomerId") or ""),
        expires_at=int(payload.get("exp") or 0),
        shipment_company_id=str(payload.get("shipmentCompanyId") or ""),
        can_view_price=payload.get("canViewPrice") is True,
        is_admin=payload.get("isAdmin") is True,
        access_role=str(payload.get("accessRole") or ""),
    )


def _account_auth_version(account: CustomerAccount) -> str:
    value = (
        f"{account.username.casefold()}\0{account.client_name}\0"
        f"{account.product_privilege}\0{account.part_customer_id}\0"
        f"{account.shipment_company_id}\0{account.can_view_price}\0{account.is_admin}\0"
        f"{account.access_role}\0"
        f"{account.password_hash}"
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _dummy_password_hash() -> str:
    # A stable valid hash is intentional: it equalizes work without allocating a new salt per failure.
    return (
        "pbkdf2_sha256$600000$3a29a251a37b6e68e2440d69f26d650d$"
        "10b261b903659f4f2d5948df87bcf087aa2b4045e074c86f9aa012e28141c9da"
    )


def _token_username(token: str, settings: Settings) -> str:
    if not settings.customer_chat_enabled or not settings.customer_chat_token_secret:
        raise CustomerAuthError("The customer portal is not enabled")
    try:
        encoded, signature = token.split(".", 1)
    except ValueError as exc:
        raise CustomerAuthError("Invalid sign-in credentials") from exc
    expected = _sign(encoded, settings.customer_chat_token_secret)
    if not hmac.compare_digest(expected, signature):
        raise CustomerAuthError("Invalid sign-in credentials")
    try:
        payload = json.loads(_b64decode(encoded).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CustomerAuthError("Invalid sign-in credentials") from exc
    if payload.get("typ") != "customer" or int(payload.get("exp") or 0) <= int(time.time()):
        raise CustomerAuthError("Invalid sign-in credentials")
    username = str(payload.get("username") or "").strip()
    if not username:
        raise CustomerAuthError("Invalid sign-in credentials")
    return username


def _sign(value: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))
