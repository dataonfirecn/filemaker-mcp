from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from app.services.audit_log import OperatorContext


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class NaturalQueryConversation:
    id: int
    session_id: str
    operator_account: str
    operator_name: str
    prompt: str
    interpreted_prompt: str | None
    layout: str | None
    domain: str | None
    source: str | None
    status: str
    found_count: int
    returned_count: int
    warnings: list[str]
    duration_ms: int
    created_at: str


@dataclass
class NaturalQueryQuestionCandidate:
    id: int
    prompt: str
    interpreted_prompt: str | None
    layout: str | None
    domain: str | None
    intent: str | None
    status: str
    created_at: str


@dataclass
class NaturalQueryTopQuestion:
    canonical_question: str
    normalized_key: str
    domain: str
    intent: str
    count: int
    example_prompts: list[str]
    last_asked_at: str


class NaturalQueryConversationStore:
    def __init__(self, database_path: str):
        self.database_path = database_path

    async def init(self) -> None:
        db_path = Path(self.database_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS natural_query_conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    operator_account TEXT NOT NULL,
                    operator_name TEXT NOT NULL,
                    operator_privilege TEXT NOT NULL DEFAULT '',
                    prompt TEXT NOT NULL,
                    interpreted_prompt TEXT,
                    llm_json TEXT NOT NULL DEFAULT '{}',
                    layout TEXT,
                    domain TEXT,
                    intent TEXT,
                    source TEXT,
                    query_json TEXT NOT NULL DEFAULT '[]',
                    sort_json TEXT NOT NULL DEFAULT '[]',
                    filters_json TEXT NOT NULL DEFAULT '{}',
                    date_range_json TEXT,
                    semantic_profile_json TEXT NOT NULL DEFAULT '{}',
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    answer TEXT,
                    found_count INTEGER NOT NULL DEFAULT 0,
                    returned_count INTEGER NOT NULL DEFAULT 0,
                    rag_hit_count INTEGER NOT NULL DEFAULT 0,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_natural_query_conversations_created_at
                ON natural_query_conversations(created_at DESC)
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_natural_query_conversations_layout
                ON natural_query_conversations(layout)
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS natural_query_question_analytics (
                    conversation_id INTEGER PRIMARY KEY,
                    prompt TEXT NOT NULL,
                    canonical_question TEXT NOT NULL,
                    normalized_key TEXT NOT NULL,
                    domain TEXT NOT NULL DEFAULT '',
                    intent TEXT NOT NULL DEFAULT '',
                    is_meaningful INTEGER NOT NULL DEFAULT 0,
                    reason TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    analyzed_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_natural_query_question_analytics_key
                ON natural_query_question_analytics(normalized_key)
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_natural_query_question_analytics_created_at
                ON natural_query_question_analytics(created_at DESC)
                """
            )
            await db.commit()

    async def record(
        self,
        *,
        operator: OperatorContext,
        prompt: str,
        interpreted_prompt: str | None = None,
        llm: dict[str, Any] | None = None,
        layout: str | None = None,
        domain: str | None = None,
        intent: str | None = None,
        source: str | None = None,
        query: Any = None,
        sort: Any = None,
        filters: Any = None,
        date_range: Any = None,
        semantic_profile: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
        answer: str | None = None,
        found_count: int = 0,
        returned_count: int = 0,
        rag_hit_count: int = 0,
        duration_ms: int = 0,
        status: str = "success",
        error_message: str | None = None,
    ) -> int:
        async with aiosqlite.connect(self.database_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO natural_query_conversations (
                    session_id, operator_account, operator_name, operator_privilege,
                    prompt, interpreted_prompt, llm_json,
                    layout, domain, intent, source,
                    query_json, sort_json, filters_json, date_range_json,
                    semantic_profile_json, warnings_json, answer,
                    found_count, returned_count, rag_hit_count,
                    duration_ms, status, error_message, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operator.session_id,
                    operator.account,
                    operator.name,
                    operator.privilege,
                    prompt,
                    interpreted_prompt,
                    self._json(llm or {}),
                    layout,
                    domain,
                    intent,
                    source,
                    self._json(query or []),
                    self._json(sort or []),
                    self._json(filters or {}),
                    self._json(date_range) if date_range is not None else None,
                    self._json(_summarize_semantic_profile(semantic_profile or {})),
                    self._json(warnings or []),
                    answer,
                    found_count,
                    returned_count,
                    rag_hit_count,
                    duration_ms,
                    status,
                    error_message,
                    utc_iso(),
                ),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def list_recent(self, *, limit: int = 50) -> list[NaturalQueryConversation]:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT *
                FROM natural_query_conversations
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = await cursor.fetchall()
        return [self._row_to_conversation(row) for row in rows]

    async def list_unanalyzed_question_candidates(self, *, limit: int = 100) -> list[NaturalQueryQuestionCandidate]:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT c.id, c.prompt, c.interpreted_prompt, c.layout, c.domain,
                       c.intent, c.status, c.created_at
                FROM natural_query_conversations c
                LEFT JOIN natural_query_question_analytics a ON a.conversation_id = c.id
                WHERE a.conversation_id IS NULL
                  AND TRIM(c.prompt) != ''
                ORDER BY c.id ASC
                LIMIT ?
                """,
                (limit,),
            )
            rows = await cursor.fetchall()
        return [
            NaturalQueryQuestionCandidate(
                id=int(row["id"]),
                prompt=str(row["prompt"]),
                interpreted_prompt=row["interpreted_prompt"],
                layout=row["layout"],
                domain=row["domain"],
                intent=row["intent"],
                status=str(row["status"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    async def upsert_question_analytics(
        self,
        *,
        conversation_id: int,
        prompt: str,
        canonical_question: str,
        normalized_key: str,
        domain: str = "",
        intent: str = "",
        is_meaningful: bool,
        reason: str = "",
        source: str = "",
        model: str = "",
        created_at: str,
    ) -> None:
        await self._execute(
            """
            INSERT INTO natural_query_question_analytics (
                conversation_id, prompt, canonical_question, normalized_key,
                domain, intent, is_meaningful, reason, source, model,
                analyzed_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                prompt = excluded.prompt,
                canonical_question = excluded.canonical_question,
                normalized_key = excluded.normalized_key,
                domain = excluded.domain,
                intent = excluded.intent,
                is_meaningful = excluded.is_meaningful,
                reason = excluded.reason,
                source = excluded.source,
                model = excluded.model,
                analyzed_at = excluded.analyzed_at,
                created_at = excluded.created_at
            """,
            (
                conversation_id,
                prompt,
                canonical_question,
                normalized_key,
                domain,
                intent,
                1 if is_meaningful else 0,
                reason,
                source,
                model,
                utc_iso(),
                created_at,
            ),
        )

    async def top_questions(self, *, days: int = 30, limit: int = 20) -> list[NaturalQueryTopQuestion]:
        cutoff_iso = (datetime.now(timezone.utc) - timedelta(days=max(1, days))).replace(microsecond=0).isoformat()
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT normalized_key,
                       MIN(canonical_question) AS canonical_question,
                       MIN(domain) AS domain,
                       MIN(intent) AS intent,
                       COUNT(*) AS count,
                       MAX(created_at) AS last_asked_at,
                       GROUP_CONCAT(prompt, '||') AS prompts
                FROM natural_query_question_analytics
                WHERE is_meaningful = 1
                  AND created_at >= ?
                GROUP BY normalized_key
                ORDER BY count DESC, last_asked_at DESC
                LIMIT ?
                """,
                (cutoff_iso, limit),
            )
            rows = await cursor.fetchall()
        return [self._row_to_top_question(row) for row in rows]

    async def quality_summary(
        self,
        *,
        start_at: str,
        end_at: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Return read-only failure, warning and alias statistics for a time window."""
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT id, prompt, interpreted_prompt, layout, domain, intent,
                       status, found_count, returned_count, rag_hit_count,
                       duration_ms, warnings_json, error_message, created_at
                FROM natural_query_conversations
                WHERE created_at >= ? AND created_at < ?
                ORDER BY created_at DESC
                """,
                (start_at, end_at),
            )
            conversations = await cursor.fetchall()
            alias_cursor = await db.execute(
                """
                SELECT a.normalized_key,
                       MIN(a.canonical_question) AS canonical_question,
                       COUNT(*) AS count,
                       COUNT(DISTINCT a.prompt) AS variants,
                       GROUP_CONCAT(DISTINCT a.prompt) AS prompts
                FROM natural_query_question_analytics a
                WHERE a.is_meaningful = 1
                  AND a.created_at >= ? AND a.created_at < ?
                GROUP BY a.normalized_key
                HAVING COUNT(DISTINCT a.prompt) > 1
                ORDER BY variants DESC, count DESC
                LIMIT ?
                """,
                (start_at, end_at, max(1, limit)),
            )
            alias_rows = await alias_cursor.fetchall()

        statuses: dict[str, int] = {}
        errors: dict[str, int] = {}
        warnings: dict[str, int] = {}
        failed_examples: list[dict[str, Any]] = []
        zero_result_examples: list[dict[str, Any]] = []
        total_duration = 0
        for row in conversations:
            status = str(row["status"] or "unknown")
            statuses[status] = statuses.get(status, 0) + 1
            total_duration += int(row["duration_ms"] or 0)
            error = str(row["error_message"] or "").strip()
            if error:
                errors[error] = errors.get(error, 0) + 1
            row_warnings = self._json_list(row["warnings_json"])
            for warning in row_warnings:
                warnings[warning] = warnings.get(warning, 0) + 1
            if status in {"error", "failed", "clarification"} and len(failed_examples) < limit:
                failed_examples.append(
                    {
                        "prompt": str(row["prompt"] or ""),
                        "interpretedPrompt": str(row["interpreted_prompt"] or ""),
                        "status": status,
                        "error": error,
                        "createdAt": str(row["created_at"] or ""),
                    }
                )
            if (
                status == "success"
                and int(row["found_count"] or 0) == 0
                and len(zero_result_examples) < limit
            ):
                zero_result_examples.append(
                    {
                        "prompt": str(row["prompt"] or ""),
                        "interpretedPrompt": str(row["interpreted_prompt"] or ""),
                        "domain": str(row["domain"] or ""),
                        "layout": str(row["layout"] or ""),
                    }
                )

        aliases = []
        for row in alias_rows:
            prompts = [
                value.strip()
                for value in str(row["prompts"] or "").split(",")
                if value.strip()
            ]
            aliases.append(
                {
                    "canonicalQuestion": str(row["canonical_question"] or ""),
                    "normalizedKey": str(row["normalized_key"] or ""),
                    "count": int(row["count"] or 0),
                    "variants": int(row["variants"] or 0),
                    "prompts": prompts[:5],
                }
            )
        return {
            "total": len(conversations),
            "averageDurationMs": round(total_duration / len(conversations))
            if conversations
            else 0,
            "statuses": statuses,
            "errors": sorted(errors.items(), key=lambda item: (-item[1], item[0]))[:limit],
            "warnings": sorted(warnings.items(), key=lambda item: (-item[1], item[0]))[:limit],
            "failedExamples": failed_examples,
            "zeroResultExamples": zero_result_examples,
            "aliases": aliases,
        }

    async def _execute(self, statement: str, params: tuple[Any, ...]) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(statement, params)
            await db.commit()

    def _row_to_conversation(self, row: aiosqlite.Row) -> NaturalQueryConversation:
        return NaturalQueryConversation(
            id=int(row["id"]),
            session_id=str(row["session_id"]),
            operator_account=str(row["operator_account"]),
            operator_name=str(row["operator_name"]),
            prompt=str(row["prompt"]),
            interpreted_prompt=row["interpreted_prompt"],
            layout=row["layout"],
            domain=row["domain"],
            source=row["source"],
            status=str(row["status"]),
            found_count=int(row["found_count"] or 0),
            returned_count=int(row["returned_count"] or 0),
            warnings=self._json_list(row["warnings_json"]),
            duration_ms=int(row["duration_ms"] or 0),
            created_at=str(row["created_at"]),
        )

    def _json(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)

    def _json_list(self, value: str | None) -> list[str]:
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []
        return [str(item) for item in parsed]

    def _row_to_top_question(self, row: aiosqlite.Row) -> NaturalQueryTopQuestion:
        prompts = []
        seen = set()
        for prompt in str(row["prompts"] or "").split("||"):
            prompt = prompt.strip()
            if prompt and prompt not in seen:
                seen.add(prompt)
                prompts.append(prompt)
            if len(prompts) >= 5:
                break
        return NaturalQueryTopQuestion(
            canonical_question=str(row["canonical_question"] or ""),
            normalized_key=str(row["normalized_key"] or ""),
            domain=str(row["domain"] or ""),
            intent=str(row["intent"] or ""),
            count=int(row["count"] or 0),
            example_prompts=prompts,
            last_asked_at=str(row["last_asked_at"] or ""),
        )


def _summarize_semantic_profile(profile: dict[str, Any]) -> dict[str, Any]:
    concepts = profile.get("concepts") if isinstance(profile.get("concepts"), dict) else {}
    return {
        "schemaVersion": profile.get("schemaVersion"),
        "source": profile.get("source"),
        "sampleRecordCount": profile.get("sampleRecordCount"),
        "fieldCount": len(profile.get("fields") or {}),
        "concepts": concepts,
    }
