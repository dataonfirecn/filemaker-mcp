from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any

import asyncpg

from app.services.customer_access import (
    MAYAKO_CLIENT_NAME,
    MAYAKO_PART_CUSTOMER_ID,
    MAYAKO_PRODUCT_PRIVILEGE,
    MAYAKO_SHIPMENT_COMPANY_ID,
    customer_access_permissions,
    normalize_customer_access_role,
)


class CustomerAccountAdminStore:
    """Persistent customer accounts, runtime controls, and login history."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self._pool: asyncpg.Pool | None = None
        self._memory: dict[str, dict[str, Any]] = {}
        self._memory_events: list[dict[str, Any]] = []
        self._memory_email_events: list[dict[str, Any]] = []

    async def init(self, accounts: dict[str, Any]) -> None:
        if self.database_url.startswith("memory://"):
            for key, account in accounts.items():
                self._memory.setdefault(key, self._new_memory_state(account))
            return

        self._pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=5)
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS customer_account_control (
                    username_key TEXT PRIMARY KEY,
                    username TEXT NOT NULL DEFAULT '',
                    display_name TEXT NOT NULL DEFAULT '',
                    email TEXT NOT NULL DEFAULT '',
                    client_name TEXT NOT NULL DEFAULT '',
                    product_privilege TEXT NOT NULL DEFAULT '',
                    part_customer_id TEXT NOT NULL DEFAULT '',
                    shipment_company_id TEXT NOT NULL DEFAULT '',
                    enabled BOOLEAN NOT NULL DEFAULT TRUE,
                    can_view_price BOOLEAN NOT NULL DEFAULT FALSE,
                    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
                    access_role TEXT NOT NULL DEFAULT '',
                    deleted BOOLEAN NOT NULL DEFAULT FALSE,
                    last_login_at TIMESTAMPTZ,
                    last_login_status TEXT NOT NULL DEFAULT '',
                    last_successful_login_at TIMESTAMPTZ,
                    last_failed_login_at TIMESTAMPTZ,
                    successful_login_count BIGINT NOT NULL DEFAULT 0,
                    failed_login_count BIGINT NOT NULL DEFAULT 0,
                    credentials_email_available_at TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_by TEXT NOT NULL DEFAULT 'system'
                );
                ALTER TABLE customer_account_control
                    ADD COLUMN IF NOT EXISTS username TEXT NOT NULL DEFAULT '',
                    ADD COLUMN IF NOT EXISTS display_name TEXT NOT NULL DEFAULT '',
                    ADD COLUMN IF NOT EXISTS email TEXT NOT NULL DEFAULT '',
                    ADD COLUMN IF NOT EXISTS client_name TEXT NOT NULL DEFAULT '',
                    ADD COLUMN IF NOT EXISTS product_privilege TEXT NOT NULL DEFAULT '',
                    ADD COLUMN IF NOT EXISTS part_customer_id TEXT NOT NULL DEFAULT '',
                    ADD COLUMN IF NOT EXISTS shipment_company_id TEXT NOT NULL DEFAULT '',
                    ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE,
                    ADD COLUMN IF NOT EXISTS access_role TEXT NOT NULL DEFAULT '',
                    ADD COLUMN IF NOT EXISTS deleted BOOLEAN NOT NULL DEFAULT FALSE,
                    ADD COLUMN IF NOT EXISTS credentials_email_available_at TIMESTAMPTZ;
                CREATE TABLE IF NOT EXISTS customer_account_login_event (
                    id BIGSERIAL PRIMARY KEY,
                    username_key TEXT NOT NULL REFERENCES customer_account_control(username_key),
                    success BOOLEAN NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    client_ip TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS idx_customer_account_login_event_account
                    ON customer_account_login_event (username_key, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_customer_account_login_event_created
                    ON customer_account_login_event (created_at DESC);
                CREATE TABLE IF NOT EXISTS customer_account_email_event (
                    id BIGSERIAL PRIMARY KEY,
                    username_key TEXT NOT NULL REFERENCES customer_account_control(username_key),
                    username TEXT NOT NULL DEFAULT '',
                    recipient_email TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS idx_customer_account_email_event_created
                    ON customer_account_email_event (created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_customer_account_email_event_account
                    ON customer_account_email_event (username_key, created_at DESC);
                """
            )
            for key, account in accounts.items():
                await conn.execute(
                    """
                    INSERT INTO customer_account_control (
                        username_key, username, display_name, email, client_name,
                        product_privilege, part_customer_id, shipment_company_id,
                        enabled, can_view_price, is_admin, access_role, updated_by
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, TRUE, $9, $10, $11, 'environment')
                    ON CONFLICT (username_key) DO UPDATE
                    SET username = CASE
                            WHEN customer_account_control.username = '' THEN EXCLUDED.username
                            ELSE customer_account_control.username
                        END,
                        display_name = CASE
                            WHEN customer_account_control.display_name = '' THEN EXCLUDED.display_name
                            ELSE customer_account_control.display_name
                        END,
                        email = CASE
                            WHEN customer_account_control.email = '' THEN EXCLUDED.email
                            ELSE customer_account_control.email
                        END,
                        client_name = CASE
                            WHEN customer_account_control.client_name = '' THEN EXCLUDED.client_name
                            ELSE customer_account_control.client_name
                        END,
                        product_privilege = CASE
                            WHEN customer_account_control.product_privilege = '' THEN EXCLUDED.product_privilege
                            ELSE customer_account_control.product_privilege
                        END,
                        part_customer_id = CASE
                            WHEN customer_account_control.part_customer_id = '' THEN EXCLUDED.part_customer_id
                            ELSE customer_account_control.part_customer_id
                        END,
                        shipment_company_id = CASE
                            WHEN customer_account_control.username = '' THEN EXCLUDED.shipment_company_id
                            ELSE customer_account_control.shipment_company_id
                        END,
                        is_admin = CASE
                            WHEN customer_account_control.username = '' THEN EXCLUDED.is_admin
                            ELSE customer_account_control.is_admin
                        END,
                        access_role = CASE
                            WHEN customer_account_control.access_role = '' THEN EXCLUDED.access_role
                            ELSE customer_account_control.access_role
                        END
                    """,
                    key,
                    account.username,
                    account.display_name,
                    account.email,
                    account.client_name,
                    account.product_privilege,
                    account.part_customer_id,
                    account.shipment_company_id,
                    bool(account.can_view_price),
                    bool(account.is_admin),
                    account.access_role,
                )

            await conn.execute(
                """
                UPDATE customer_account_control
                SET access_role = CASE
                        WHEN is_admin THEN 'admin'
                        ELSE 'team'
                    END
                WHERE access_role NOT IN ('admin', 'manager', 'team', 'agent');

                UPDATE customer_account_control
                SET is_admin = access_role = 'admin';
                """
            )
            await conn.execute(
                """
                UPDATE customer_account_control
                SET client_name = $1,
                    product_privilege = $2,
                    part_customer_id = $3,
                    shipment_company_id = $4
                """,
                MAYAKO_CLIENT_NAME,
                MAYAKO_PRODUCT_PRIVILEGE,
                MAYAKO_PART_CUSTOMER_ID,
                MAYAKO_SHIPMENT_COMPANY_ID,
            )

            # Preserve login information that was written before this table existed.
            await conn.execute(
                """
                WITH login_stats AS (
                    SELECT lower(operator_account) AS username_key,
                           MAX(created_at) AS last_login_at,
                           MAX(created_at) FILTER (WHERE status = 'success') AS last_successful_login_at,
                           MAX(created_at) FILTER (WHERE status = 'failed') AS last_failed_login_at,
                           COUNT(*) FILTER (WHERE status = 'success') AS successful_login_count,
                           COUNT(*) FILTER (WHERE status = 'failed') AS failed_login_count
                    FROM audit_log
                    WHERE action_type = 'CUSTOMER_LOGIN'
                    GROUP BY lower(operator_account)
                )
                UPDATE customer_account_control AS control
                SET last_login_at = GREATEST(control.last_login_at, stats.last_login_at),
                    last_successful_login_at = GREATEST(
                        control.last_successful_login_at, stats.last_successful_login_at
                    ),
                    last_failed_login_at = GREATEST(
                        control.last_failed_login_at, stats.last_failed_login_at
                    ),
                    successful_login_count = GREATEST(
                        control.successful_login_count, stats.successful_login_count
                    ),
                    failed_login_count = GREATEST(
                        control.failed_login_count, stats.failed_login_count
                    ),
                    last_login_status = CASE
                        WHEN stats.last_successful_login_at = stats.last_login_at THEN 'success'
                        ELSE 'failed'
                    END
                FROM login_stats AS stats
                WHERE control.username_key = stats.username_key
                """
            )

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def get_state(self, username: str) -> dict[str, Any] | None:
        key = username.strip().casefold()
        if self.database_url.startswith("memory://"):
            state = self._memory.get(key)
            return dict(state) if state and not state["deleted"] else None
        if not self._pool:
            raise RuntimeError("Customer account admin store is not initialized")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM customer_account_control
                WHERE username_key = $1 AND deleted = FALSE
                """,
                key,
            )
        return _account_state_dict(row) if row else None

    async def resolve_login_state(
        self,
        identifier: str,
    ) -> tuple[dict[str, Any] | None, bool]:
        """Resolve a username first, then a case-insensitive email.

        The boolean result indicates that the email belongs to multiple active
        account records, in which case no account is returned.
        """
        key = identifier.strip().casefold()
        if not key:
            return None, False

        username_state = await self.get_state(identifier)
        if username_state:
            return username_state, False

        if self.database_url.startswith("memory://"):
            matches = [
                dict(state)
                for state in self._memory.values()
                if not state["deleted"]
                and str(state.get("email") or "").strip().casefold() == key
                and key
            ]
        else:
            if not self._pool:
                raise RuntimeError("Customer account admin store is not initialized")
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT *
                    FROM customer_account_control
                    WHERE deleted = FALSE
                      AND email <> ''
                      AND lower(email) = $1
                    ORDER BY username_key
                    LIMIT 2
                    """,
                    key,
                )
            matches = [_account_state_dict(row) for row in rows]

        if len(matches) == 1:
            return matches[0], False
        return None, len(matches) > 1

    async def list_states(self) -> dict[str, dict[str, Any]]:
        if self.database_url.startswith("memory://"):
            return {
                key: dict(value)
                for key, value in self._memory.items()
                if not value["deleted"]
            }
        if not self._pool:
            raise RuntimeError("Customer account admin store is not initialized")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT *
                FROM customer_account_control
                WHERE deleted = FALSE
                ORDER BY username_key
                """
            )
        return {str(row["username_key"]): _account_state_dict(row) for row in rows}

    async def create_account(
        self,
        *,
        username: str,
        display_name: str,
        email: str,
        enabled: bool,
        updated_by: str,
        can_view_price: bool = False,
        is_admin: bool = False,
        access_role: str = "",
    ) -> dict[str, Any] | None:
        key = username.strip().casefold()
        now = datetime.now(timezone.utc)
        role = normalize_customer_access_role(
            access_role,
            is_admin=is_admin,
        )
        permissions = customer_access_permissions(role)
        if self.database_url.startswith("memory://"):
            existing = self._memory.get(key)
            if existing and not existing["deleted"]:
                return None
            if existing:
                existing.update(
                    username=username.strip(),
                    displayName=display_name.strip(),
                    email=email.strip().casefold(),
                    clientName=MAYAKO_CLIENT_NAME,
                    productPrivilege=MAYAKO_PRODUCT_PRIVILEGE,
                    partCustomerId=MAYAKO_PART_CUSTOMER_ID,
                    shipmentCompanyId=MAYAKO_SHIPMENT_COMPANY_ID,
                    enabled=bool(enabled),
                    canViewPrice=bool(can_view_price),
                    isAdmin=permissions["isAdmin"],
                    accessRole=role,
                    deleted=False,
                    credentialsEmailAvailableAt=None,
                    updatedAt=now,
                    updatedBy=updated_by,
                )
                return dict(existing)
            state = {
                "usernameKey": key,
                "username": username.strip(),
                "displayName": display_name.strip(),
                "email": email.strip().casefold(),
                "clientName": MAYAKO_CLIENT_NAME,
                "productPrivilege": MAYAKO_PRODUCT_PRIVILEGE,
                "partCustomerId": MAYAKO_PART_CUSTOMER_ID,
                "shipmentCompanyId": MAYAKO_SHIPMENT_COMPANY_ID,
                "enabled": bool(enabled),
                "canViewPrice": bool(can_view_price),
                "isAdmin": permissions["isAdmin"],
                "accessRole": role,
                "deleted": False,
                "lastLoginAt": None,
                "lastLoginStatus": "",
                "lastSuccessfulLoginAt": None,
                "lastFailedLoginAt": None,
                "successfulLoginCount": 0,
                "failedLoginCount": 0,
                "credentialsEmailAvailableAt": None,
                "updatedAt": now,
                "updatedBy": updated_by,
            }
            self._memory[key] = state
            return dict(state)

        if not self._pool:
            raise RuntimeError("Customer account admin store is not initialized")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO customer_account_control (
                    username_key, username, display_name, email, client_name,
                    product_privilege, part_customer_id, shipment_company_id,
                    enabled, can_view_price, is_admin, access_role,
                    deleted, updated_at, updated_by
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, FALSE, now(), $13)
                ON CONFLICT (username_key) DO UPDATE
                SET username = EXCLUDED.username,
                    display_name = EXCLUDED.display_name,
                    email = EXCLUDED.email,
                    client_name = EXCLUDED.client_name,
                    product_privilege = EXCLUDED.product_privilege,
                    part_customer_id = EXCLUDED.part_customer_id,
                    shipment_company_id = EXCLUDED.shipment_company_id,
                    enabled = EXCLUDED.enabled,
                    can_view_price = EXCLUDED.can_view_price,
                    is_admin = EXCLUDED.is_admin,
                    access_role = EXCLUDED.access_role,
                    deleted = FALSE,
                    credentials_email_available_at = NULL,
                    updated_at = now(),
                    updated_by = EXCLUDED.updated_by
                WHERE customer_account_control.deleted = TRUE
                RETURNING *
                """,
                key,
                username.strip(),
                display_name.strip(),
                email.strip().casefold(),
                MAYAKO_CLIENT_NAME,
                MAYAKO_PRODUCT_PRIVILEGE,
                MAYAKO_PART_CUSTOMER_ID,
                MAYAKO_SHIPMENT_COMPANY_ID,
                bool(enabled),
                bool(can_view_price),
                permissions["isAdmin"],
                role,
                updated_by,
            )
        return _account_state_dict(row) if row else None

    async def update_account(
        self,
        username: str,
        *,
        enabled: bool,
        updated_by: str,
        can_view_price: bool | None = None,
        display_name: str | None = None,
        email: str | None = None,
        is_admin: bool | None = None,
        access_role: str | None = None,
    ) -> dict[str, Any] | None:
        key = username.strip().casefold()
        now = datetime.now(timezone.utc)
        before = await self.get_state(username)
        if not before:
            return None
        current_role = normalize_customer_access_role(
            before.get("accessRole"),
            is_admin=bool(before["isAdmin"]),
        )
        role = normalize_customer_access_role(
            access_role if access_role is not None else current_role,
            is_admin=bool(is_admin) if is_admin is not None else bool(before["isAdmin"]),
        )
        if access_role is None and is_admin is not None:
            role = normalize_customer_access_role(
                "",
                is_admin=bool(is_admin),
            )
        price_access = (
            bool(can_view_price)
            if can_view_price is not None
            else bool(before["canViewPrice"])
        )
        permissions = customer_access_permissions(role)
        if self.database_url.startswith("memory://"):
            state = self._memory.get(key)
            if not state or state["deleted"]:
                return None
            state.update(
                enabled=bool(enabled),
                canViewPrice=price_access,
                isAdmin=permissions["isAdmin"],
                accessRole=role,
                updatedAt=now,
                updatedBy=updated_by,
            )
            if display_name is not None:
                state["displayName"] = display_name.strip()
            if email is not None:
                state["email"] = email.strip().casefold()
            state["clientName"] = MAYAKO_CLIENT_NAME
            state["productPrivilege"] = MAYAKO_PRODUCT_PRIVILEGE
            state["partCustomerId"] = MAYAKO_PART_CUSTOMER_ID
            state["shipmentCompanyId"] = MAYAKO_SHIPMENT_COMPANY_ID
            return dict(state)

        if not self._pool:
            raise RuntimeError("Customer account admin store is not initialized")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE customer_account_control
                SET enabled = $2,
                    can_view_price = $3,
                    display_name = COALESCE($4, display_name),
                    email = COALESCE($5, email),
                    client_name = $6,
                    product_privilege = $7,
                    part_customer_id = $8,
                    shipment_company_id = $9,
                    is_admin = $10,
                    access_role = $11,
                    updated_at = now(),
                    updated_by = $12
                WHERE username_key = $1 AND deleted = FALSE
                RETURNING *
                """,
                key,
                bool(enabled),
                price_access,
                display_name.strip() if display_name is not None else None,
                email.strip().casefold() if email is not None else None,
                MAYAKO_CLIENT_NAME,
                MAYAKO_PRODUCT_PRIVILEGE,
                MAYAKO_PART_CUSTOMER_ID,
                MAYAKO_SHIPMENT_COMPANY_ID,
                permissions["isAdmin"],
                role,
                updated_by,
            )
        return _account_state_dict(row) if row else None

    async def delete_account(
        self,
        username: str,
        *,
        updated_by: str,
    ) -> dict[str, Any] | None:
        key = username.strip().casefold()
        now = datetime.now(timezone.utc)
        if self.database_url.startswith("memory://"):
            state = self._memory.get(key)
            if not state or state["deleted"]:
                return None
            state.update(
                enabled=False,
                deleted=True,
                updatedAt=now,
                updatedBy=updated_by,
            )
            return dict(state)

        if not self._pool:
            raise RuntimeError("Customer account admin store is not initialized")
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE customer_account_control
                SET enabled = FALSE,
                    deleted = TRUE,
                    updated_at = now(),
                    updated_by = $2
                WHERE username_key = $1 AND deleted = FALSE
                RETURNING *
                """,
                key,
                updated_by,
            )
        return _account_state_dict(row) if row else None

    async def record_login(
        self,
        username: str,
        *,
        success: bool,
        reason: str,
        client_ip: str,
    ) -> None:
        key = username.strip().casefold()
        now = datetime.now(timezone.utc)
        if self.database_url.startswith("memory://"):
            state = self._memory.get(key)
            if not state or state["deleted"]:
                return
            state["lastLoginAt"] = now
            state["lastLoginStatus"] = "success" if success else "failed"
            counter = "successfulLoginCount" if success else "failedLoginCount"
            state[counter] = int(state[counter]) + 1
            state["lastSuccessfulLoginAt" if success else "lastFailedLoginAt"] = now
            self._memory_events.append({
                "usernameKey": key,
                "success": success,
                "reason": reason,
                "clientIp": client_ip,
                "createdAt": now,
            })
            return

        if not self._pool:
            raise RuntimeError("Customer account admin store is not initialized")
        async with self._pool.acquire() as conn, conn.transaction():
            updated = await conn.execute(
                """
                UPDATE customer_account_control
                SET last_login_at = now(),
                    last_login_status = CASE WHEN $2 THEN 'success' ELSE 'failed' END,
                    last_successful_login_at = CASE WHEN $2 THEN now() ELSE last_successful_login_at END,
                    last_failed_login_at = CASE WHEN $2 THEN last_failed_login_at ELSE now() END,
                    successful_login_count = successful_login_count + CASE WHEN $2 THEN 1 ELSE 0 END,
                    failed_login_count = failed_login_count + CASE WHEN $2 THEN 0 ELSE 1 END
                WHERE username_key = $1 AND deleted = FALSE
                """,
                key,
                success,
            )
            if updated == "UPDATE 0":
                return
            await conn.execute(
                """
                INSERT INTO customer_account_login_event (
                    username_key, success, reason, client_ip
                )
                VALUES ($1, $2, $3, $4)
                """,
                key,
                success,
                reason[:80],
                client_ip[:120],
            )

    async def claim_credentials_email(
        self,
        username: str,
        *,
        cooldown_seconds: int = 60,
    ) -> int:
        """Reserve an email send, returning zero or the remaining cooldown seconds."""
        key = username.strip().casefold()
        now = datetime.now(timezone.utc)
        available_at = now + timedelta(seconds=max(1, cooldown_seconds))
        if self.database_url.startswith("memory://"):
            state = self._memory.get(key)
            if not state or state["deleted"]:
                raise KeyError(username)
            current = state.get("credentialsEmailAvailableAt")
            if current and current > now:
                return max(1, math.ceil((current - now).total_seconds()))
            state["credentialsEmailAvailableAt"] = available_at
            return 0

        if not self._pool:
            raise RuntimeError("Customer account admin store is not initialized")
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """
                UPDATE customer_account_control
                SET credentials_email_available_at = $2
                WHERE username_key = $1
                  AND deleted = FALSE
                  AND (
                      credentials_email_available_at IS NULL
                      OR credentials_email_available_at <= now()
                  )
                RETURNING credentials_email_available_at
                """,
                key,
                available_at,
            )
            if row:
                return 0
            current = await conn.fetchval(
                """
                SELECT credentials_email_available_at
                FROM customer_account_control
                WHERE username_key = $1 AND deleted = FALSE
                """,
                key,
            )
        if current is None:
            raise KeyError(username)
        return max(
            1,
            math.ceil((current - datetime.now(timezone.utc)).total_seconds()),
        )

    async def release_credentials_email(self, username: str) -> None:
        """Release a reservation after a failed delivery so a retry is possible."""
        key = username.strip().casefold()
        if self.database_url.startswith("memory://"):
            state = self._memory.get(key)
            if state and not state["deleted"]:
                state["credentialsEmailAvailableAt"] = None
            return
        if not self._pool:
            raise RuntimeError("Customer account admin store is not initialized")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE customer_account_control
                SET credentials_email_available_at = NULL
                WHERE username_key = $1 AND deleted = FALSE
                """,
                key,
            )

    async def complete_credentials_email(
        self,
        username: str,
        *,
        cooldown_seconds: int = 60,
    ) -> None:
        """Start a full cooldown after the SMTP server confirms delivery."""
        key = username.strip().casefold()
        available_at = datetime.now(timezone.utc) + timedelta(
            seconds=max(1, cooldown_seconds),
        )
        if self.database_url.startswith("memory://"):
            state = self._memory.get(key)
            if not state or state["deleted"]:
                raise KeyError(username)
            state["credentialsEmailAvailableAt"] = available_at
            return
        if not self._pool:
            raise RuntimeError("Customer account admin store is not initialized")
        async with self._pool.acquire() as conn:
            updated = await conn.execute(
                """
                UPDATE customer_account_control
                SET credentials_email_available_at = $2
                WHERE username_key = $1 AND deleted = FALSE
                """,
                key,
                available_at,
            )
        if updated == "UPDATE 0":
            raise KeyError(username)

    async def record_credentials_email_event(
        self,
        username: str,
        *,
        recipient_email: str,
        status: str,
        message: str = "",
    ) -> None:
        key = username.strip().casefold()
        now = datetime.now(timezone.utc)
        normalized_status = status if status in {"success", "failed", "blocked"} else "failed"
        if self.database_url.startswith("memory://"):
            state = self._memory.get(key)
            if not state:
                return
            self._memory_email_events.append({
                "id": len(self._memory_email_events) + 1,
                "username": str(state["username"]),
                "recipientEmail": recipient_email.strip().casefold(),
                "status": normalized_status,
                "message": message[:500],
                "createdAt": now,
            })
            return
        if not self._pool:
            raise RuntimeError("Customer account admin store is not initialized")
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO customer_account_email_event (
                    username_key, username, recipient_email, status, message
                )
                SELECT username_key, username, $2, $3, $4
                FROM customer_account_control
                WHERE username_key = $1
                """,
                key,
                recipient_email.strip().casefold(),
                normalized_status,
                message[:500],
            )

    async def list_credentials_email_events(
        self,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        bounded_limit = min(max(1, limit), 200)
        if self.database_url.startswith("memory://"):
            return [
                dict(event)
                for event in reversed(self._memory_email_events[-bounded_limit:])
            ]
        if not self._pool:
            raise RuntimeError("Customer account admin store is not initialized")
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, username, recipient_email, status, message, created_at
                FROM customer_account_email_event
                ORDER BY created_at DESC, id DESC
                LIMIT $1
                """,
                bounded_limit,
            )
        return [{
            "id": int(row["id"]),
            "username": str(row["username"]),
            "recipientEmail": str(row["recipient_email"]),
            "status": str(row["status"]),
            "message": str(row["message"]),
            "createdAt": row["created_at"],
        } for row in rows]

    @staticmethod
    def _new_memory_state(account: Any) -> dict[str, Any]:
        return {
            "usernameKey": account.username.strip().casefold(),
            "username": account.username,
            "displayName": account.display_name,
            "email": account.email,
            "clientName": MAYAKO_CLIENT_NAME,
            "productPrivilege": MAYAKO_PRODUCT_PRIVILEGE,
            "partCustomerId": MAYAKO_PART_CUSTOMER_ID,
            "shipmentCompanyId": MAYAKO_SHIPMENT_COMPANY_ID,
            "enabled": True,
            "canViewPrice": bool(account.can_view_price),
            "isAdmin": bool(account.is_admin),
            "accessRole": account.access_role,
            "deleted": False,
            "lastLoginAt": None,
            "lastLoginStatus": "",
            "lastSuccessfulLoginAt": None,
            "lastFailedLoginAt": None,
            "successfulLoginCount": 0,
            "failedLoginCount": 0,
            "credentialsEmailAvailableAt": None,
            "updatedAt": datetime.now(timezone.utc),
            "updatedBy": "environment",
        }


def _account_state_dict(row: asyncpg.Record) -> dict[str, Any]:
    return {
        "usernameKey": str(row["username_key"]),
        "username": str(row["username"]),
        "displayName": str(row["display_name"]),
        "email": str(row["email"]),
        "clientName": str(row["client_name"]),
        "productPrivilege": str(row["product_privilege"]),
        "partCustomerId": str(row["part_customer_id"]),
        "shipmentCompanyId": str(row["shipment_company_id"]),
        "enabled": bool(row["enabled"]),
        "canViewPrice": bool(row["can_view_price"]),
        "isAdmin": bool(row["is_admin"]),
        "accessRole": normalize_customer_access_role(
            row["access_role"],
            is_admin=bool(row["is_admin"]),
        ),
        "deleted": bool(row["deleted"]),
        "lastLoginAt": row["last_login_at"],
        "lastLoginStatus": str(row["last_login_status"]),
        "lastSuccessfulLoginAt": row["last_successful_login_at"],
        "lastFailedLoginAt": row["last_failed_login_at"],
        "successfulLoginCount": int(row["successful_login_count"]),
        "failedLoginCount": int(row["failed_login_count"]),
        "credentialsEmailAvailableAt": row["credentials_email_available_at"],
        "updatedAt": row["updated_at"],
        "updatedBy": str(row["updated_by"]),
    }
