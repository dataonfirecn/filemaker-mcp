from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import asyncpg

from app.services.part_permission_catalog import (
    default_part_permissions_for_privilege_set,
    normalize_part_permissions,
)
from app.services.rag_semantic_registry import RagSemanticRegistry


PERMISSION_KEYS = (
    "canViewPrice",
    "canManageAccounts",
    "canViewProducts",
    "canViewOrders",
    "canViewInventory",
    "canViewBom",
    "canUseNaturalQuery",
    "canManageRag",
    "canMergeOrders",
)

STANDARD_PERMISSIONS = {
    "canViewPrice": False,
    "canManageAccounts": False,
    "canViewProducts": True,
    "canViewOrders": True,
    "canViewInventory": True,
    "canViewBom": True,
    "canUseNaturalQuery": True,
    "canManageRag": False,
    "canMergeOrders": False,
}

FULL_PERMISSIONS = {key: True for key in PERMISSION_KEYS}
CONFIG_POLICY_OWNERS = {
    "system",
    "configuration",
    "filemaker-security-audit",
}


def default_permissions_for_privilege_set(privilege_set: str) -> dict[str, bool]:
    normalized = privilege_set.strip().casefold()
    if normalized in {
        "[full access]",
        "full access",
        "[完全访问权限]",
        "完全访问权限",
        "[完全存取權限]",
        "完全存取權限",
        "mock",
    }:
        return dict(FULL_PERMISSIONS)
    return dict(STANDARD_PERMISSIONS)


def load_privilege_set_policies(path: str) -> list[dict[str, Any]]:
    policy_path = Path(path).expanduser()
    if not policy_path.exists():
        return []
    payload = json.loads(policy_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("WebViewer privilege-set policy must be a JSON object")
    templates = payload.get("templates") or {}
    entries = payload.get("privilegeSets") or []
    if not isinstance(templates, dict) or not isinstance(entries, list):
        raise ValueError(
            "WebViewer privilege-set policy requires templates and privilegeSets"
        )

    policies: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Each WebViewer privilege-set policy must be an object")
        name = str(entry.get("name") or "").strip()
        if not name:
            raise ValueError("Each WebViewer privilege-set policy requires a name")
        key = name.casefold()
        if key in seen:
            raise ValueError(f"Duplicate WebViewer privilege-set policy: {name}")
        seen.add(key)

        template_name = str(entry.get("template") or "").strip()
        template = templates.get(template_name) if template_name else {}
        if template_name and not isinstance(template, dict):
            raise ValueError(
                f"Unknown WebViewer privilege-set template {template_name!r} for {name}"
            )
        baseline = normalize_permissions(template or STANDARD_PERMISSIONS)
        policies.append(
            {
                "name": name,
                "enabled": bool(entry.get("enabled", True)),
                "permissions": normalize_permissions(
                    entry.get("permissions") or {},
                    fallback=baseline,
                ),
            }
        )
    return policies


def normalize_permissions(value: Any, *, fallback: dict[str, bool] | None = None) -> dict[str, bool]:
    source = _json_object(value)
    baseline = fallback or STANDARD_PERMISSIONS
    return {
        key: bool(source[key]) if key in source else bool(baseline.get(key, False))
        for key in PERMISSION_KEYS
    }


def sanitize_price_data(
    value: Any,
    *,
    semantic_registry: RagSemanticRegistry | None = None,
) -> Any:
    """Remove financial fields from arbitrary FileMaker-shaped response data."""
    if isinstance(value, list):
        cleaned: list[Any] = []
        for item in value:
            if isinstance(item, dict) and _is_finance_descriptor(
                item,
                semantic_registry=semantic_registry,
            ):
                continue
            cleaned.append(
                sanitize_price_data(
                    item,
                    semantic_registry=semantic_registry,
                )
            )
        return cleaned
    if not isinstance(value, dict):
        return value

    cleaned_dict: dict[str, Any] = {}
    for key, item in value.items():
        if _is_price_key(key, semantic_registry=semantic_registry):
            continue
        cleaned_dict[key] = sanitize_price_data(
            item,
            semantic_registry=semantic_registry,
        )
    return cleaned_dict


def _is_finance_descriptor(
    value: dict[str, Any],
    *,
    semantic_registry: RagSemanticRegistry | None = None,
) -> bool:
    if str(value.get("role") or "").strip().casefold() == "finance":
        return True
    return any(
        _is_price_key(
            str(value.get(key) or ""),
            semantic_registry=semantic_registry,
        )
        for key in ("source", "label", "field", "fieldName")
    )


def _is_price_key(
    key: str,
    *,
    semantic_registry: RagSemanticRegistry | None = None,
) -> bool:
    if semantic_registry is not None:
        explicit = semantic_registry.price_restriction_for_field(key)
        if explicit is not None:
            return explicit
    normalized = "".join(character for character in key.casefold() if character.isalnum())
    if normalized.startswith(("canviewprice", "pricepermission")):
        return False
    english_terms = (
        "price",
        "unitprice",
        "batchprice",
        "retailprice",
        "sellingprice",
        "saleprice",
        "wholesaleprice",
        "quotation",
        "quoteamount",
        "amount",
        "cost",
        "margin",
        "profit",
        "orderamount",
        "totalamount",
        "stockusd",
        "prepaidstockusd",
    )
    cjk_terms = (
        "价格",
        "價格",
        "单价",
        "單價",
        "售价",
        "售價",
        "成本",
        "金额",
        "金額",
        "报价",
        "報價",
        "利润",
        "利潤",
        "货值",
        "貨值",
        "批次价格",
        "批次價格",
    )
    return any(term in normalized for term in english_terms + cjk_terms)


class WebViewerAccountAccessStore:
    """Persistent StarRC account policies keyed to FileMaker privilege-set names."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self._pool: asyncpg.Pool | None = None
        self._memory_privilege_sets: dict[str, dict[str, Any]] = {}
        self._memory_accounts: dict[str, dict[str, Any]] = {}

    async def init(
        self,
        seed_accounts: Iterable[dict[str, str]] = (),
        seed_privilege_sets: Iterable[dict[str, Any]] = (),
    ) -> None:
        privilege_set_policies = list(seed_privilege_sets)
        if self.database_url.startswith("memory://"):
            for item in privilege_set_policies:
                await self._seed_privilege_set(item)
            for item in seed_accounts:
                await self.register_account(
                    username=item["username"],
                    display_name=item.get("displayName") or item["username"],
                    privilege_set=item.get("privilegeSet") or "internal_remote",
                    origin="environment",
                    seen=False,
                )
            return

        self._pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=5)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS webviewer_privilege_set_control (
                    privilege_set_key TEXT PRIMARY KEY,
                    privilege_set_name TEXT NOT NULL,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    permissions JSONB NOT NULL DEFAULT '{}'::jsonb,
                    part_permissions JSONB NOT NULL DEFAULT '{}'::jsonb,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_by TEXT NOT NULL DEFAULT 'system'
                );
                CREATE TABLE IF NOT EXISTS webviewer_account_control (
                    username_key TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    filemaker_privilege_set TEXT NOT NULL DEFAULT '',
                    privilege_set_key TEXT NOT NULL DEFAULT '',
                    enabled_override BOOLEAN,
                    permission_overrides JSONB NOT NULL DEFAULT '{}'::jsonb,
                    part_permission_overrides JSONB NOT NULL DEFAULT '{}'::jsonb,
                    origin TEXT NOT NULL DEFAULT 'filemaker',
                    last_seen_at TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_by TEXT NOT NULL DEFAULT 'system'
                );
                CREATE INDEX IF NOT EXISTS idx_webviewer_account_privilege_set
                    ON webviewer_account_control (privilege_set_key, username_key);
                """
            )
            await conn.execute(
                """
                ALTER TABLE webviewer_privilege_set_control
                    ADD COLUMN IF NOT EXISTS part_permissions JSONB
                    NOT NULL DEFAULT '{}'::jsonb;
                ALTER TABLE webviewer_account_control
                    ADD COLUMN IF NOT EXISTS part_permission_overrides JSONB
                    NOT NULL DEFAULT '{}'::jsonb;
                """
            )
            empty_part_policy_rows = await conn.fetch(
                """
                SELECT privilege_set_key, privilege_set_name
                FROM webviewer_privilege_set_control
                WHERE part_permissions = '{}'::jsonb
                """
            )
            for row in empty_part_policy_rows:
                await conn.execute(
                    """
                    UPDATE webviewer_privilege_set_control
                    SET part_permissions = $2::jsonb
                    WHERE privilege_set_key = $1
                      AND part_permissions = '{}'::jsonb
                    """,
                    str(row["privilege_set_key"]),
                    json.dumps(
                        default_part_permissions_for_privilege_set(
                            str(row["privilege_set_name"])
                        )
                    ),
                )
        for item in privilege_set_policies:
            await self._seed_privilege_set(item)
        for item in seed_accounts:
            await self.register_account(
                username=item["username"],
                display_name=item.get("displayName") or item["username"],
                privilege_set=item.get("privilegeSet") or "internal_remote",
                origin="environment",
                seen=False,
            )

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def observe_account(
        self,
        *,
        username: str,
        display_name: str,
        privilege_set: str,
    ) -> dict[str, Any]:
        return await self.register_account(
            username=username,
            display_name=display_name,
            privilege_set=privilege_set,
            origin="filemaker",
            seen=True,
        )

    async def register_account(
        self,
        *,
        username: str,
        display_name: str,
        privilege_set: str,
        origin: str,
        seen: bool,
        updated_by: str = "system",
    ) -> dict[str, Any]:
        normalized_username = username.strip()
        normalized_privilege = privilege_set.strip() or "unknown"
        username_key = normalized_username.casefold()
        privilege_key = normalized_privilege.casefold()
        if not normalized_username:
            raise ValueError("username is required")

        await self._ensure_privilege_set(normalized_privilege, updated_by=updated_by)
        now = datetime.now(timezone.utc)
        if self.database_url.startswith("memory://"):
            existing = self._memory_accounts.get(username_key)
            if existing:
                existing.setdefault("partPermissionOverrides", {})
                existing.update(
                    username=normalized_username,
                    displayName=display_name.strip() or normalized_username,
                    filemakerPrivilegeSet=normalized_privilege,
                    privilegeSetKey=privilege_key,
                    lastSeenAt=now if seen else existing.get("lastSeenAt"),
                )
                if seen:
                    existing["origin"] = "filemaker"
            else:
                self._memory_accounts[username_key] = {
                    "usernameKey": username_key,
                    "username": normalized_username,
                    "displayName": display_name.strip() or normalized_username,
                    "filemakerPrivilegeSet": normalized_privilege,
                    "privilegeSetKey": privilege_key,
                    "enabledOverride": None,
                    "permissionOverrides": {},
                    "partPermissionOverrides": {},
                    "origin": origin,
                    "lastSeenAt": now if seen else None,
                    "updatedAt": now,
                    "updatedBy": updated_by,
                }
            return self._effective_account(self._memory_accounts[username_key])

        if not self._pool:
            raise RuntimeError("WebViewer account access store is not initialized")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO webviewer_account_control (
                    username_key, username, display_name, filemaker_privilege_set,
                    privilege_set_key, origin, last_seen_at, updated_by
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (username_key) DO UPDATE
                SET username = EXCLUDED.username,
                    display_name = EXCLUDED.display_name,
                    filemaker_privilege_set = EXCLUDED.filemaker_privilege_set,
                    privilege_set_key = EXCLUDED.privilege_set_key,
                    origin = CASE
                        WHEN EXCLUDED.last_seen_at IS NOT NULL THEN 'filemaker'
                        ELSE webviewer_account_control.origin
                    END,
                    last_seen_at = COALESCE(EXCLUDED.last_seen_at, webviewer_account_control.last_seen_at)
                """,
                username_key,
                normalized_username,
                display_name.strip() or normalized_username,
                normalized_privilege,
                privilege_key,
                origin,
                now if seen else None,
                updated_by,
            )
        state = await self.get_account(normalized_username)
        if not state:
            raise RuntimeError("Unable to read the registered WebViewer account")
        return state

    async def get_account(self, username: str) -> dict[str, Any] | None:
        key = username.strip().casefold()
        if self.database_url.startswith("memory://"):
            row = self._memory_accounts.get(key)
            return self._effective_account(row) if row else None
        if not self._pool:
            raise RuntimeError("WebViewer account access store is not initialized")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT account.*, privilege.enabled AS privilege_enabled,
                       privilege.permissions AS privilege_permissions,
                       privilege.part_permissions AS privilege_part_permissions
                FROM webviewer_account_control AS account
                JOIN webviewer_privilege_set_control AS privilege
                  ON privilege.privilege_set_key = account.privilege_set_key
                WHERE account.username_key = $1
                """,
                key,
            )
        return self._postgres_account(row) if row else None

    async def list_accounts(self) -> list[dict[str, Any]]:
        if self.database_url.startswith("memory://"):
            return [
                self._effective_account(row)
                for _, row in sorted(self._memory_accounts.items())
            ]
        if not self._pool:
            raise RuntimeError("WebViewer account access store is not initialized")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT account.*, privilege.enabled AS privilege_enabled,
                       privilege.permissions AS privilege_permissions,
                       privilege.part_permissions AS privilege_part_permissions
                FROM webviewer_account_control AS account
                JOIN webviewer_privilege_set_control AS privilege
                  ON privilege.privilege_set_key = account.privilege_set_key
                ORDER BY account.filemaker_privilege_set, account.username
                """
            )
        return [self._postgres_account(row) for row in rows]

    async def list_privilege_sets(self) -> list[dict[str, Any]]:
        if self.database_url.startswith("memory://"):
            return [
                self._public_privilege_set(row)
                for _, row in sorted(self._memory_privilege_sets.items())
            ]
        if not self._pool:
            raise RuntimeError("WebViewer account access store is not initialized")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT privilege.*,
                       COUNT(account.username_key) AS account_count
                FROM webviewer_privilege_set_control AS privilege
                LEFT JOIN webviewer_account_control AS account
                  ON account.privilege_set_key = privilege.privilege_set_key
                GROUP BY privilege.privilege_set_key
                ORDER BY privilege.privilege_set_name
                """
            )
        return [
            {
                "name": str(row["privilege_set_name"]),
                "enabled": bool(row["enabled"]),
                "permissions": normalize_permissions(row["permissions"]),
                "partPermissions": normalize_part_permissions(
                    row["part_permissions"]
                ),
                "accountCount": int(row["account_count"]),
                "updatedAt": row["updated_at"],
                "updatedBy": str(row["updated_by"]),
            }
            for row in rows
        ]

    async def update_account(
        self,
        username: str,
        *,
        enabled: bool,
        permissions: dict[str, bool],
        updated_by: str,
        part_permissions: dict[str, bool] | None = None,
        inherit_privilege_set: bool = False,
        inherit_part_permissions: bool = False,
        display_name: str | None = None,
        privilege_set: str | None = None,
    ) -> dict[str, Any] | None:
        key = username.strip().casefold()
        normalized_permissions = normalize_permissions(permissions)
        current = await self.get_account(username)
        if not current:
            return None
        normalized_part_permissions = normalize_part_permissions(
            part_permissions
            if part_permissions is not None
            else current["partPermissions"]
        )
        target_display_name = (
            display_name.strip()
            if display_name is not None and display_name.strip()
            else current["displayName"]
        )
        target_privilege_set = (
            privilege_set.strip()
            if privilege_set is not None and privilege_set.strip()
            else current["filemakerPrivilegeSet"]
        )
        target_privilege_key = target_privilege_set.casefold()
        await self._ensure_privilege_set(target_privilege_set, updated_by=updated_by)

        if self.database_url.startswith("memory://"):
            row = self._memory_accounts.get(key)
            if not row:
                return None
            privilege = self._memory_privilege_sets[target_privilege_key]
            privilege_permissions = normalize_permissions(privilege["permissions"])
            privilege_part_permissions = normalize_part_permissions(
                privilege.get("partPermissions")
            )
            permission_overrides = (
                {}
                if inherit_privilege_set
                else {
                    permission_key: value
                    for permission_key, value in normalized_permissions.items()
                    if value != privilege_permissions[permission_key]
                }
            )
            part_permission_overrides = (
                {}
                if inherit_part_permissions
                else {
                    permission_key: value
                    for permission_key, value in normalized_part_permissions.items()
                    if value != privilege_part_permissions[permission_key]
                }
            )
            enabled_override = _enabled_override(
                requested_enabled=enabled,
                privilege_enabled=bool(privilege["enabled"]),
                inherit_privilege_set=inherit_privilege_set,
            )
            row["displayName"] = target_display_name
            row["filemakerPrivilegeSet"] = target_privilege_set
            row["privilegeSetKey"] = target_privilege_key
            row["enabledOverride"] = enabled_override
            row["permissionOverrides"] = permission_overrides
            row["partPermissionOverrides"] = part_permission_overrides
            row["updatedAt"] = datetime.now(timezone.utc)
            row["updatedBy"] = updated_by
            return self._effective_account(row)

        if not self._pool:
            raise RuntimeError("WebViewer account access store is not initialized")
        async with self._pool.acquire() as conn:
            privilege = await conn.fetchrow(
                """
                SELECT enabled, permissions, part_permissions
                FROM webviewer_privilege_set_control
                WHERE privilege_set_key = $1
                """,
                target_privilege_key,
            )
            if not privilege:
                return None
            privilege_permissions = normalize_permissions(privilege["permissions"])
            privilege_part_permissions = normalize_part_permissions(
                privilege["part_permissions"]
            )
            permission_overrides = (
                {}
                if inherit_privilege_set
                else {
                    permission_key: value
                    for permission_key, value in normalized_permissions.items()
                    if value != privilege_permissions[permission_key]
                }
            )
            part_permission_overrides = (
                {}
                if inherit_part_permissions
                else {
                    permission_key: value
                    for permission_key, value in normalized_part_permissions.items()
                    if value != privilege_part_permissions[permission_key]
                }
            )
            enabled_override = _enabled_override(
                requested_enabled=enabled,
                privilege_enabled=bool(privilege["enabled"]),
                inherit_privilege_set=inherit_privilege_set,
            )
            result = await conn.execute(
                """
                UPDATE webviewer_account_control
                SET display_name = $2,
                    filemaker_privilege_set = $3,
                    privilege_set_key = $4,
                    enabled_override = $5,
                    permission_overrides = $6::jsonb,
                    part_permission_overrides = $7::jsonb,
                    updated_at = now(),
                    updated_by = $8
                WHERE username_key = $1
                """,
                key,
                target_display_name,
                target_privilege_set,
                target_privilege_key,
                enabled_override,
                json.dumps(permission_overrides),
                json.dumps(part_permission_overrides),
                updated_by,
            )
        if result == "UPDATE 0":
            return None
        return await self.get_account(username)

    async def delete_account(self, username: str) -> dict[str, Any] | None:
        key = username.strip().casefold()
        current = await self.get_account(username)
        if not current:
            return None
        if self.database_url.startswith("memory://"):
            self._memory_accounts.pop(key, None)
            return current
        if not self._pool:
            raise RuntimeError("WebViewer account access store is not initialized")
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM webviewer_account_control WHERE username_key = $1",
                key,
            )
        return current if result != "DELETE 0" else None

    async def update_privilege_set(
        self,
        privilege_set: str,
        *,
        enabled: bool,
        permissions: dict[str, bool],
        updated_by: str,
        part_permissions: dict[str, bool] | None = None,
    ) -> dict[str, Any] | None:
        key = privilege_set.strip().casefold()
        normalized_permissions = normalize_permissions(permissions)
        current_sets = await self.list_privilege_sets()
        current = next(
            (item for item in current_sets if item["name"].casefold() == key),
            None,
        )
        if not current:
            return None
        normalized_part_permissions = normalize_part_permissions(
            part_permissions
            if part_permissions is not None
            else current["partPermissions"]
        )
        if self.database_url.startswith("memory://"):
            row = self._memory_privilege_sets.get(key)
            row["enabled"] = bool(enabled)
            row["permissions"] = normalized_permissions
            row["partPermissions"] = normalized_part_permissions
            row["updatedAt"] = datetime.now(timezone.utc)
            row["updatedBy"] = updated_by
            return self._public_privilege_set(row)

        if not self._pool:
            raise RuntimeError("WebViewer account access store is not initialized")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE webviewer_privilege_set_control
                SET enabled = $2,
                    permissions = $3::jsonb,
                    part_permissions = $4::jsonb,
                    updated_at = now(),
                    updated_by = $5
                WHERE privilege_set_key = $1
                RETURNING *
                """,
                key,
                bool(enabled),
                json.dumps(normalized_permissions),
                json.dumps(normalized_part_permissions),
                updated_by,
            )
        if not row:
            return None
        accounts = await self.list_accounts()
        return {
            "name": str(row["privilege_set_name"]),
            "enabled": bool(row["enabled"]),
            "permissions": normalize_permissions(row["permissions"]),
            "partPermissions": normalize_part_permissions(row["part_permissions"]),
            "accountCount": sum(
                account["filemakerPrivilegeSet"].casefold() == key for account in accounts
            ),
            "updatedAt": row["updated_at"],
            "updatedBy": str(row["updated_by"]),
        }

    async def _ensure_privilege_set(self, privilege_set: str, *, updated_by: str) -> None:
        key = privilege_set.casefold()
        defaults = default_permissions_for_privilege_set(privilege_set)
        part_defaults = default_part_permissions_for_privilege_set(privilege_set)
        now = datetime.now(timezone.utc)
        if self.database_url.startswith("memory://"):
            self._memory_privilege_sets.setdefault(
                key,
                {
                    "name": privilege_set,
                    "enabled": True,
                    "permissions": defaults,
                    "partPermissions": part_defaults,
                    "accountCount": 0,
                    "updatedAt": now,
                    "updatedBy": updated_by,
                },
            )
            return
        if not self._pool:
            raise RuntimeError("WebViewer account access store is not initialized")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO webviewer_privilege_set_control (
                    privilege_set_key, privilege_set_name, enabled, permissions,
                    part_permissions, updated_by
                )
                VALUES ($1, $2, TRUE, $3::jsonb, $4::jsonb, $5)
                ON CONFLICT (privilege_set_key) DO UPDATE
                SET privilege_set_name = EXCLUDED.privilege_set_name
                """,
                key,
                privilege_set,
                json.dumps(defaults),
                json.dumps(part_defaults),
                updated_by,
            )

    async def _seed_privilege_set(self, item: dict[str, Any]) -> None:
        name = str(item.get("name") or "").strip()
        if not name:
            raise ValueError("Seeded privilege set requires a name")
        key = name.casefold()
        enabled = bool(item.get("enabled", True))
        permissions = normalize_permissions(item.get("permissions") or {})
        part_permissions = normalize_part_permissions(
            item.get("partPermissions")
            or default_part_permissions_for_privilege_set(name)
        )
        now = datetime.now(timezone.utc)
        if self.database_url.startswith("memory://"):
            existing = self._memory_privilege_sets.get(key)
            if (
                existing
                and str(existing.get("updatedBy") or "") not in CONFIG_POLICY_OWNERS
            ):
                return
            self._memory_privilege_sets[key] = {
                "name": name,
                "enabled": enabled,
                "permissions": permissions,
                "partPermissions": part_permissions,
                "accountCount": int((existing or {}).get("accountCount") or 0),
                "updatedAt": now,
                "updatedBy": "filemaker-security-audit",
            }
            return

        if not self._pool:
            raise RuntimeError("WebViewer account access store is not initialized")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO webviewer_privilege_set_control (
                    privilege_set_key, privilege_set_name, enabled, permissions,
                    part_permissions,
                    updated_at, updated_by
                )
                VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, now(), 'filemaker-security-audit')
                ON CONFLICT (privilege_set_key) DO UPDATE
                SET privilege_set_name = EXCLUDED.privilege_set_name,
                    enabled = EXCLUDED.enabled,
                    permissions = EXCLUDED.permissions,
                    part_permissions = EXCLUDED.part_permissions,
                    updated_at = now(),
                    updated_by = EXCLUDED.updated_by
                WHERE webviewer_privilege_set_control.updated_by = ANY($6::text[])
                """,
                key,
                name,
                enabled,
                json.dumps(permissions),
                json.dumps(part_permissions),
                sorted(CONFIG_POLICY_OWNERS),
            )

    def _effective_account(self, row: dict[str, Any]) -> dict[str, Any]:
        privilege = self._memory_privilege_sets[row["privilegeSetKey"]]
        privilege_permissions = normalize_permissions(privilege["permissions"])
        overrides = _json_object(row.get("permissionOverrides"))
        effective = {
            key: bool(overrides[key]) if key in overrides else privilege_permissions[key]
            for key in PERMISSION_KEYS
        }
        privilege_part_permissions = normalize_part_permissions(
            privilege.get("partPermissions")
        )
        part_overrides = _json_object(row.get("partPermissionOverrides"))
        effective_part_permissions = {
            key: (
                bool(part_overrides[key])
                if key in part_overrides
                else privilege_part_permissions[key]
            )
            for key in privilege_part_permissions
        }
        enabled_override = row.get("enabledOverride")
        return {
            "username": row["username"],
            "displayName": row["displayName"],
            "filemakerPrivilegeSet": row["filemakerPrivilegeSet"],
            "enabled": bool(privilege["enabled"]) and enabled_override is not False,
            "permissions": effective,
            "partPermissions": effective_part_permissions,
            "inheritsPrivilegeSet": enabled_override is None and not overrides,
            "inheritsPartPermissions": not part_overrides,
            "origin": row["origin"],
            "lastSeenAt": row.get("lastSeenAt"),
            "updatedAt": row["updatedAt"],
            "updatedBy": row["updatedBy"],
        }

    def _postgres_account(self, row: asyncpg.Record) -> dict[str, Any]:
        privilege_permissions = normalize_permissions(row["privilege_permissions"])
        overrides = _json_object(row["permission_overrides"])
        effective = {
            key: bool(overrides[key]) if key in overrides else privilege_permissions[key]
            for key in PERMISSION_KEYS
        }
        privilege_part_permissions = normalize_part_permissions(
            row["privilege_part_permissions"]
        )
        part_overrides = _json_object(row["part_permission_overrides"])
        effective_part_permissions = {
            key: (
                bool(part_overrides[key])
                if key in part_overrides
                else privilege_part_permissions[key]
            )
            for key in privilege_part_permissions
        }
        enabled_override = row["enabled_override"]
        return {
            "username": str(row["username"]),
            "displayName": str(row["display_name"]),
            "filemakerPrivilegeSet": str(row["filemaker_privilege_set"]),
            "enabled": bool(row["privilege_enabled"]) and enabled_override is not False,
            "permissions": effective,
            "partPermissions": effective_part_permissions,
            "inheritsPrivilegeSet": enabled_override is None and not overrides,
            "inheritsPartPermissions": not part_overrides,
            "origin": str(row["origin"]),
            "lastSeenAt": row["last_seen_at"],
            "updatedAt": row["updated_at"],
            "updatedBy": str(row["updated_by"]),
        }

    def _public_privilege_set(self, row: dict[str, Any]) -> dict[str, Any]:
        key = str(row["name"]).casefold()
        return {
            "name": row["name"],
            "enabled": bool(row["enabled"]),
            "permissions": normalize_permissions(row["permissions"]),
            "partPermissions": normalize_part_permissions(
                row.get("partPermissions")
            ),
            "accountCount": sum(
                account["privilegeSetKey"] == key
                for account in self._memory_accounts.values()
            ),
            "updatedAt": row["updatedAt"],
            "updatedBy": row["updatedBy"],
        }


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _enabled_override(
    *,
    requested_enabled: bool,
    privilege_enabled: bool,
    inherit_privilege_set: bool,
) -> bool | None:
    # Permission inheritance does not prevent an individual account from being
    # disabled. A disabled privilege set remains authoritative.
    if requested_enabled == privilege_enabled:
        return None
    if inherit_privilege_set and not privilege_enabled:
        return None
    return False if privilege_enabled else None
