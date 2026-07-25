from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import aiosqlite


class CustomerCredentialStore:
    """Persistent password overrides for customer portal accounts.

    Account scope and permissions remain controlled by the production environment.
    Only a salted password hash is stored here so users can rotate credentials
    without requiring a container restart or exposing the host env file.
    """

    def __init__(self, database_path: str):
        self.database_path = database_path

    async def init(self) -> None:
        db_path = Path(self.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS customer_credential (
                    username_key TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            await db.commit()

    async def get_password_hash(self, username: str) -> str | None:
        async with aiosqlite.connect(self.database_path) as db:
            cursor = await db.execute(
                "SELECT password_hash FROM customer_credential WHERE username_key = ?",
                (username.strip().casefold(),),
            )
            row = await cursor.fetchone()
        return str(row[0]) if row else None

    async def set_password_hash(self, username: str, password_hash: str) -> None:
        username_key = username.strip().casefold()
        updated_at = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                INSERT INTO customer_credential (
                    username_key, password_hash, updated_at
                )
                VALUES (?, ?, ?)
                ON CONFLICT (username_key) DO UPDATE
                SET password_hash = excluded.password_hash,
                    updated_at = excluded.updated_at
                """,
                (username_key, password_hash, updated_at),
            )
            await db.commit()

    async def delete_password_hash(self, username: str) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                "DELETE FROM customer_credential WHERE username_key = ?",
                (username.strip().casefold(),),
            )
            await db.commit()

    async def compare_and_set_password_hash(
        self,
        username: str,
        *,
        expected_override_hash: str | None,
        new_password_hash: str,
    ) -> bool:
        username_key = username.strip().casefold()
        updated_at = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            if expected_override_hash is None:
                cursor = await db.execute(
                    """
                    INSERT OR IGNORE INTO customer_credential (
                        username_key, password_hash, updated_at
                    )
                    VALUES (?, ?, ?)
                    """,
                    (username_key, new_password_hash, updated_at),
                )
            else:
                cursor = await db.execute(
                    """
                    UPDATE customer_credential
                    SET password_hash = ?, updated_at = ?
                    WHERE username_key = ? AND password_hash = ?
                    """,
                    (
                        new_password_hash,
                        updated_at,
                        username_key,
                        expected_override_hash,
                    ),
                )
            changed = cursor.rowcount == 1
            await db.commit()
        return changed
