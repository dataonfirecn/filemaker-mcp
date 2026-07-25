from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from app.services.audit_log import OperatorContext


class CustomerChatHistoryStore:
    """PostgreSQL-backed customer chat history and question aggregates."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self._pool: asyncpg.Pool | None = None
        self._memory_rows: list[dict[str, Any]] = []
        self._memory_next_id = 1

    async def init(self) -> None:
        if self.database_url.startswith("memory://"):
            return
        self._pool = await asyncpg.create_pool(self.database_url, min_size=1, max_size=5)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS customer_chat_history (
                    id BIGSERIAL PRIMARY KEY,
                    request_id UUID NOT NULL UNIQUE,
                    session_id TEXT NOT NULL,
                    operator_account TEXT NOT NULL,
                    operator_name TEXT NOT NULL,
                    client_name TEXT NOT NULL,
                    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
                    channel TEXT NOT NULL DEFAULT 'web',
                    prompt TEXT NOT NULL,
                    normalized_key TEXT NOT NULL,
                    domain TEXT NOT NULL DEFAULT '',
                    intent TEXT NOT NULL DEFAULT '',
                    result_type TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    http_status INTEGER NOT NULL,
                    blocked_reason TEXT NOT NULL DEFAULT '',
                    answer TEXT NOT NULL DEFAULT '',
                    found_count INTEGER NOT NULL DEFAULT 0,
                    returned_count INTEGER NOT NULL DEFAULT 0,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    source_layout TEXT NOT NULL DEFAULT '',
                    response_meta JSONB NOT NULL DEFAULT '{}'::jsonb,
                    is_test BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS idx_customer_chat_history_created_at
                    ON customer_chat_history (created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_customer_chat_history_account
                    ON customer_chat_history (operator_account, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_customer_chat_history_status
                    ON customer_chat_history (status, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_customer_chat_history_normalized
                    ON customer_chat_history (normalized_key, created_at DESC);

                CREATE TABLE IF NOT EXISTS customer_chat_question_summary (
                    normalized_key TEXT NOT NULL,
                    domain TEXT NOT NULL DEFAULT '',
                    canonical_question TEXT NOT NULL,
                    intent TEXT NOT NULL DEFAULT '',
                    total_count BIGINT NOT NULL DEFAULT 0,
                    success_count BIGINT NOT NULL DEFAULT 0,
                    no_result_count BIGINT NOT NULL DEFAULT 0,
                    clarification_count BIGINT NOT NULL DEFAULT 0,
                    blocked_count BIGINT NOT NULL DEFAULT 0,
                    error_count BIGINT NOT NULL DEFAULT 0,
                    test_count BIGINT NOT NULL DEFAULT 0,
                    last_status TEXT NOT NULL DEFAULT '',
                    last_asked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (normalized_key, domain)
                );
                CREATE INDEX IF NOT EXISTS idx_customer_chat_question_summary_count
                    ON customer_chat_question_summary (total_count DESC, last_asked_at DESC);
                """
            )

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def record(
        self,
        *,
        operator: OperatorContext,
        client_name: str,
        is_admin: bool,
        prompt: str,
        domain: str = "",
        intent: str = "",
        result_type: str = "",
        status: str,
        http_status: int,
        answer: str = "",
        blocked_reason: str = "",
        found_count: int = 0,
        returned_count: int = 0,
        duration_ms: int = 0,
        source_layout: str = "",
        response_meta: dict[str, Any] | None = None,
        channel: str = "web",
        is_test: bool = False,
        request_id: str | None = None,
    ) -> int:
        normalized_key = normalize_customer_question(prompt)
        resolved_domain = domain or infer_customer_question_domain(prompt)
        resolved_intent = intent or infer_customer_question_intent(prompt)
        resolved_request_id = request_id or str(uuid.uuid4())
        canonical_question = canonical_customer_question(prompt)
        safe_channel = channel if channel in {"web", "mobile", "api", "regression_test"} else "api"
        row = {
            "requestId": resolved_request_id,
            "sessionId": operator.session_id,
            "operatorAccount": operator.account,
            "operatorName": operator.name,
            "clientName": client_name,
            "isAdmin": is_admin,
            "channel": safe_channel,
            "prompt": prompt,
            "normalizedKey": normalized_key,
            "domain": resolved_domain,
            "intent": resolved_intent,
            "resultType": result_type,
            "status": status,
            "httpStatus": http_status,
            "blockedReason": blocked_reason,
            "answer": answer,
            "foundCount": max(0, int(found_count or 0)),
            "returnedCount": max(0, int(returned_count or 0)),
            "durationMs": max(0, int(duration_ms or 0)),
            "sourceLayout": source_layout,
            "responseMeta": response_meta or {},
            "isTest": bool(is_test),
            "createdAt": datetime.now(timezone.utc),
        }
        if self.database_url.startswith("memory://"):
            row["id"] = self._memory_next_id
            self._memory_next_id += 1
            self._memory_rows.append(row)
            return int(row["id"])

        if not self._pool:
            raise RuntimeError("Customer chat history store is not initialized")
        async with self._pool.acquire() as conn, conn.transaction():
            history_id = await conn.fetchval(
                """
                INSERT INTO customer_chat_history (
                    request_id, session_id, operator_account, operator_name,
                    client_name, is_admin, channel, prompt, normalized_key,
                    domain, intent, result_type, status, http_status,
                    blocked_reason, answer, found_count, returned_count,
                    duration_ms, source_layout, response_meta, is_test
                )
                VALUES (
                    $1::uuid, $2, $3, $4, $5, $6, $7, $8, $9,
                    $10, $11, $12, $13, $14, $15, $16, $17, $18,
                    $19, $20, $21::jsonb, $22
                )
                RETURNING id
                """,
                resolved_request_id,
                operator.session_id,
                operator.account,
                operator.name,
                client_name,
                is_admin,
                safe_channel,
                prompt,
                normalized_key,
                resolved_domain,
                resolved_intent,
                result_type,
                status,
                http_status,
                blocked_reason,
                answer,
                row["foundCount"],
                row["returnedCount"],
                row["durationMs"],
                source_layout,
                json.dumps(response_meta or {}, ensure_ascii=False, default=str),
                is_test,
            )
            await conn.execute(
                """
                INSERT INTO customer_chat_question_summary (
                    normalized_key, domain, canonical_question, intent,
                    total_count, success_count, no_result_count,
                    clarification_count, blocked_count, error_count,
                    test_count, last_status, last_asked_at
                )
                VALUES (
                    $1, $2, $3, $4, 1,
                    CASE WHEN $5 = 'success' THEN 1 ELSE 0 END,
                    CASE WHEN $5 = 'no_result' THEN 1 ELSE 0 END,
                    CASE WHEN $5 = 'clarification' THEN 1 ELSE 0 END,
                    CASE WHEN $5 = 'blocked' THEN 1 ELSE 0 END,
                    CASE WHEN $5 = 'error' THEN 1 ELSE 0 END,
                    CASE WHEN $6 THEN 1 ELSE 0 END,
                    $5, now()
                )
                ON CONFLICT (normalized_key, domain) DO UPDATE SET
                    canonical_question = EXCLUDED.canonical_question,
                    intent = EXCLUDED.intent,
                    total_count = customer_chat_question_summary.total_count + 1,
                    success_count = customer_chat_question_summary.success_count + EXCLUDED.success_count,
                    no_result_count = customer_chat_question_summary.no_result_count + EXCLUDED.no_result_count,
                    clarification_count = customer_chat_question_summary.clarification_count + EXCLUDED.clarification_count,
                    blocked_count = customer_chat_question_summary.blocked_count + EXCLUDED.blocked_count,
                    error_count = customer_chat_question_summary.error_count + EXCLUDED.error_count,
                    test_count = customer_chat_question_summary.test_count + EXCLUDED.test_count,
                    last_status = EXCLUDED.last_status,
                    last_asked_at = EXCLUDED.last_asked_at
                """,
                normalized_key,
                resolved_domain,
                canonical_question,
                resolved_intent,
                status,
                is_test,
            )
        return int(history_id)

    async def list_history(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        domain: str = "",
        status: str = "",
        query: str = "",
        include_tests: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        if self.database_url.startswith("memory://"):
            rows = [row for row in self._memory_rows if include_tests or not row["isTest"]]
            if domain:
                rows = [row for row in rows if row["domain"] == domain]
            if status:
                rows = [row for row in rows if row["status"] == status]
            if query:
                lowered = query.casefold()
                rows = [row for row in rows if lowered in row["prompt"].casefold()]
            rows.sort(key=lambda item: item["createdAt"], reverse=True)
            total = len(rows)
            start = (page - 1) * page_size
            return rows[start:start + page_size], total

        if not self._pool:
            raise RuntimeError("Customer chat history store is not initialized")
        async with self._pool.acquire() as conn:
            total = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM customer_chat_history
                WHERE ($1 = '' OR domain = $1)
                  AND ($2 = '' OR status = $2)
                  AND ($3 = '' OR prompt ILIKE '%' || $3 || '%')
                  AND ($4 OR NOT is_test)
                """,
                domain,
                status,
                query,
                include_tests,
            )
            records = await conn.fetch(
                """
                SELECT id, request_id, session_id, operator_account, operator_name,
                       client_name, is_admin, channel, prompt, normalized_key,
                       domain, intent, result_type, status, http_status,
                       blocked_reason, answer, found_count, returned_count,
                       duration_ms, source_layout, is_test, created_at
                FROM customer_chat_history
                WHERE ($1 = '' OR domain = $1)
                  AND ($2 = '' OR status = $2)
                  AND ($3 = '' OR prompt ILIKE '%' || $3 || '%')
                  AND ($4 OR NOT is_test)
                ORDER BY created_at DESC, id DESC
                LIMIT $5 OFFSET $6
                """,
                domain,
                status,
                query,
                include_tests,
                page_size,
                (page - 1) * page_size,
            )
        return [_history_record_to_dict(record) for record in records], int(total or 0)

    async def question_summary(
        self,
        *,
        days: int = 30,
        limit: int = 50,
        include_tests: bool = False,
    ) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
        if self.database_url.startswith("memory://"):
            grouped: dict[tuple[str, str], dict[str, Any]] = {}
            for row in self._memory_rows:
                if row["createdAt"] < cutoff or (row["isTest"] and not include_tests):
                    continue
                key = (row["normalizedKey"], row["domain"])
                item = grouped.setdefault(
                    key,
                    {
                        "normalizedKey": key[0],
                        "canonicalQuestion": row["prompt"],
                        "domain": key[1],
                        "intent": row["intent"],
                        "totalCount": 0,
                        "successCount": 0,
                        "noResultCount": 0,
                        "clarificationCount": 0,
                        "blockedCount": 0,
                        "errorCount": 0,
                        "lastAskedAt": row["createdAt"],
                    },
                )
                item["totalCount"] += 1
                counter = {
                    "success": "successCount",
                    "no_result": "noResultCount",
                    "clarification": "clarificationCount",
                    "blocked": "blockedCount",
                    "error": "errorCount",
                }.get(row["status"])
                if counter:
                    item[counter] += 1
                item["lastAskedAt"] = max(item["lastAskedAt"], row["createdAt"])
            return sorted(
                grouped.values(),
                key=lambda item: (item["totalCount"], item["lastAskedAt"]),
                reverse=True,
            )[:limit]

        if not self._pool:
            raise RuntimeError("Customer chat history store is not initialized")
        async with self._pool.acquire() as conn:
            records = await conn.fetch(
                """
                SELECT normalized_key,
                       MIN(prompt) AS canonical_question,
                       MIN(domain) AS domain,
                       MIN(intent) AS intent,
                       COUNT(*) AS total_count,
                       COUNT(*) FILTER (WHERE status = 'success') AS success_count,
                       COUNT(*) FILTER (WHERE status = 'no_result') AS no_result_count,
                       COUNT(*) FILTER (WHERE status = 'clarification') AS clarification_count,
                       COUNT(*) FILTER (WHERE status = 'blocked') AS blocked_count,
                       COUNT(*) FILTER (WHERE status = 'error') AS error_count,
                       MAX(created_at) AS last_asked_at
                FROM customer_chat_history
                WHERE created_at >= $1
                  AND ($2 OR NOT is_test)
                GROUP BY normalized_key, domain
                ORDER BY total_count DESC, last_asked_at DESC
                LIMIT $3
                """,
                cutoff,
                include_tests,
                limit,
            )
        return [_summary_record_to_dict(record) for record in records]


def canonical_customer_question(prompt: str) -> str:
    return re.sub(r"\s+", " ", prompt.strip())[:240] or "Empty question"


def normalize_customer_question(prompt: str) -> str:
    text = canonical_customer_question(prompt).casefold()
    text = re.sub(r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}\b", "{date}", text)
    text = re.sub(
        r"(?<![a-z0-9])(?=[a-z0-9_-]{4,40}(?![a-z0-9_-]))(?=[a-z0-9_-]*[a-z])(?=[a-z0-9_-]*\d)[a-z0-9]+(?:[-_][a-z0-9]+)*(?![a-z0-9])",
        "{id}",
        text,
    )
    text = re.sub(r"\b\d{6,}\b", "{number}", text)
    text = re.sub(r"[\s,，。.!！?？;；:：'\"“”‘’（）()【】\[\]{}<>《》、/_-]+", "", text)
    return text[:240] or "empty"


def infer_customer_question_domain(prompt: str) -> str:
    lowered = prompt.casefold()
    if any(term in lowered for term in ("出库", "出庫", "出货", "出貨", "订单", "訂單", "shipping", "tracking")):
        return "order"
    if any(term in lowered for term in ("零件", "part")):
        return "part"
    if any(term in lowered for term in ("产品", "產品", "product", "sku", "inventory", "库存", "庫存")):
        return "product"
    return "unknown"


def infer_customer_question_intent(prompt: str) -> str:
    lowered = prompt.casefold()
    if any(term in lowered for term in ("价格", "價格", "单价", "單價", "price")):
        return "price"
    if any(term in lowered for term in ("库存", "庫存", "inventory", "stock")):
        return "inventory"
    if any(term in lowered for term in ("追踪", "追蹤", "tracking")):
        return "tracking"
    if any(term in lowered for term in ("未出货", "未出貨", "unshipped", "not shipped")):
        return "shipping_status"
    if any(term in lowered for term in ("日期", "date", "today", "昨天", "本月")):
        return "date_range"
    return "lookup"


def _history_record_to_dict(record: asyncpg.Record) -> dict[str, Any]:
    return {
        "id": int(record["id"]),
        "requestId": str(record["request_id"]),
        "sessionId": str(record["session_id"]),
        "operatorAccount": str(record["operator_account"]),
        "operatorName": str(record["operator_name"]),
        "clientName": str(record["client_name"]),
        "isAdmin": bool(record["is_admin"]),
        "channel": str(record["channel"]),
        "prompt": str(record["prompt"]),
        "normalizedKey": str(record["normalized_key"]),
        "domain": str(record["domain"]),
        "intent": str(record["intent"]),
        "resultType": str(record["result_type"]),
        "status": str(record["status"]),
        "httpStatus": int(record["http_status"]),
        "blockedReason": str(record["blocked_reason"]),
        "answer": str(record["answer"]),
        "foundCount": int(record["found_count"]),
        "returnedCount": int(record["returned_count"]),
        "durationMs": int(record["duration_ms"]),
        "sourceLayout": str(record["source_layout"]),
        "isTest": bool(record["is_test"]),
        "createdAt": record["created_at"],
    }


def _summary_record_to_dict(record: asyncpg.Record) -> dict[str, Any]:
    return {
        "normalizedKey": str(record["normalized_key"]),
        "canonicalQuestion": str(record["canonical_question"]),
        "domain": str(record["domain"]),
        "intent": str(record["intent"]),
        "totalCount": int(record["total_count"]),
        "successCount": int(record["success_count"]),
        "noResultCount": int(record["no_result_count"]),
        "clarificationCount": int(record["clarification_count"]),
        "blockedCount": int(record["blocked_count"]),
        "errorCount": int(record["error_count"]),
        "lastAskedAt": record["last_asked_at"],
    }
