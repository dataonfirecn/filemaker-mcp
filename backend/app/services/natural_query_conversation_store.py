from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from app.services.audit_log import OperatorContext


SYNTHETIC_QUERY_PRIVILEGE = "synthetic_monitor"


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
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS synthetic_query_probe_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slot_at TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'running',
                    question_count INTEGER NOT NULL DEFAULT 0,
                    issue_count INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    alert_status TEXT NOT NULL DEFAULT '',
                    alert_error TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_synthetic_query_probe_runs_slot
                ON synthetic_query_probe_runs(slot_at DESC);

                CREATE TABLE IF NOT EXISTS synthetic_query_probe_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    case_id TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    answer TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    severity TEXT NOT NULL DEFAULT 'info',
                    issue_category TEXT NOT NULL DEFAULT '',
                    issue_reason TEXT NOT NULL DEFAULT '',
                    domain TEXT NOT NULL DEFAULT '',
                    layout TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    found_count INTEGER NOT NULL DEFAULT 0,
                    returned_count INTEGER NOT NULL DEFAULT 0,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES synthetic_query_probe_runs(id) ON DELETE CASCADE,
                    UNIQUE(run_id, case_id)
                );

                CREATE INDEX IF NOT EXISTS idx_synthetic_query_probe_results_created
                ON synthetic_query_probe_results(created_at DESC);
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
                  AND c.operator_privilege != ?
                ORDER BY c.id ASC
                LIMIT ?
                """,
                (SYNTHETIC_QUERY_PRIVILEGE, limit),
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
                SELECT a.normalized_key,
                       MIN(a.canonical_question) AS canonical_question,
                       MIN(a.domain) AS domain,
                       MIN(a.intent) AS intent,
                       COUNT(*) AS count,
                       MAX(a.created_at) AS last_asked_at,
                       GROUP_CONCAT(a.prompt, '||') AS prompts
                FROM natural_query_question_analytics a
                JOIN natural_query_conversations c ON c.id = a.conversation_id
                WHERE a.is_meaningful = 1
                  AND a.created_at >= ?
                  AND c.operator_privilege != ?
                GROUP BY a.normalized_key
                ORDER BY count DESC, last_asked_at DESC
                LIMIT ?
                """,
                (cutoff_iso, SYNTHETIC_QUERY_PRIVILEGE, limit),
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
                       status, answer, found_count, returned_count, rag_hit_count,
                       duration_ms, warnings_json, error_message, created_at
                FROM natural_query_conversations
                WHERE created_at >= ? AND created_at < ?
                  AND operator_privilege != ?
                ORDER BY created_at DESC
                """,
                (start_at, end_at, SYNTHETIC_QUERY_PRIVILEGE),
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
                JOIN natural_query_conversations c ON c.id = a.conversation_id
                WHERE a.is_meaningful = 1
                  AND a.created_at >= ? AND a.created_at < ?
                  AND c.operator_privilege != ?
                GROUP BY a.normalized_key
                HAVING COUNT(DISTINCT a.prompt) > 1
                ORDER BY variants DESC, count DESC
                LIMIT ?
                """,
                (start_at, end_at, SYNTHETIC_QUERY_PRIVILEGE, max(1, limit)),
            )
            alias_rows = await alias_cursor.fetchall()

        statuses: dict[str, int] = {}
        errors: dict[str, int] = {}
        warnings: dict[str, int] = {}
        failed_examples: list[dict[str, Any]] = []
        zero_result_examples: list[dict[str, Any]] = []
        poor_answer_examples: list[dict[str, Any]] = []
        failed_or_clarification_count = 0
        zero_result_count = 0
        empty_answer_count = 0
        warning_conversation_count = 0
        direct_answer_count = 0
        poor_answer_count = 0
        total_duration = 0
        for row in conversations:
            status = str(row["status"] or "unknown")
            answer = str(row["answer"] or "").strip()
            found_count = int(row["found_count"] or 0)
            statuses[status] = statuses.get(status, 0) + 1
            total_duration += int(row["duration_ms"] or 0)
            error = str(row["error_message"] or "").strip()
            if error:
                errors[error] = errors.get(error, 0) + 1
            row_warnings = self._json_list(row["warnings_json"])
            for warning in row_warnings:
                warnings[warning] = warnings.get(warning, 0) + 1
            if row_warnings:
                warning_conversation_count += 1
            if status == "success" and answer:
                direct_answer_count += 1
            if not answer:
                empty_answer_count += 1
            if status in {"error", "failed", "clarification"}:
                failed_or_clarification_count += 1
            if status in {"error", "failed", "clarification"} and len(failed_examples) < limit:
                failed_examples.append(
                    {
                        "prompt": str(row["prompt"] or ""),
                        "interpretedPrompt": str(row["interpreted_prompt"] or ""),
                        "status": status,
                        "answer": _summary_text(answer),
                        "error": error,
                        "createdAt": str(row["created_at"] or ""),
                    }
                )
            if (
                status == "success"
                and found_count == 0
            ):
                zero_result_count += 1
                if len(zero_result_examples) < limit:
                    zero_result_examples.append(
                        {
                            "prompt": str(row["prompt"] or ""),
                            "interpretedPrompt": str(row["interpreted_prompt"] or ""),
                            "answer": _summary_text(answer),
                            "domain": str(row["domain"] or ""),
                            "layout": str(row["layout"] or ""),
                        }
                    )

            issue = _poor_answer_issue(
                status=status,
                answer=answer,
                found_count=found_count,
                error=error,
                warnings=row_warnings,
            )
            if issue is not None:
                poor_answer_count += 1
                if len(poor_answer_examples) < limit:
                    poor_answer_examples.append(
                        {
                            "prompt": str(row["prompt"] or ""),
                            "interpretedPrompt": str(row["interpreted_prompt"] or ""),
                            "answer": _summary_text(answer),
                            "status": status,
                            "createdAt": str(row["created_at"] or ""),
                            **issue,
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
            "directAnswerCount": direct_answer_count,
            "directAnswerRate": round(direct_answer_count * 100 / len(conversations), 1)
            if conversations
            else 0,
            "failedOrClarificationCount": failed_or_clarification_count,
            "zeroResultCount": zero_result_count,
            "emptyAnswerCount": empty_answer_count,
            "warningConversationCount": warning_conversation_count,
            "poorAnswerCount": poor_answer_count,
            "averageDurationMs": round(total_duration / len(conversations))
            if conversations
            else 0,
            "statuses": statuses,
            "errors": sorted(errors.items(), key=lambda item: (-item[1], item[0]))[:limit],
            "warnings": sorted(warnings.items(), key=lambda item: (-item[1], item[0]))[:limit],
            "failedExamples": failed_examples,
            "zeroResultExamples": zero_result_examples,
            "poorAnswerExamples": poor_answer_examples,
            "aliases": aliases,
        }

    async def claim_synthetic_probe_run(self, *, slot_at: str) -> int | None:
        """Atomically claim a scheduled probe slot, preventing restart duplicates."""
        async with aiosqlite.connect(self.database_path) as db:
            cursor = await db.execute(
                """
                INSERT OR IGNORE INTO synthetic_query_probe_runs (
                    slot_at, status, started_at
                ) VALUES (?, 'running', ?)
                """,
                (slot_at, utc_iso()),
            )
            await db.commit()
            if cursor.rowcount != 1:
                return None
            return int(cursor.lastrowid)

    async def record_synthetic_probe_result(
        self,
        *,
        run_id: int,
        case_id: str,
        prompt: str,
        answer: str = "",
        status: str,
        severity: str = "info",
        issue_category: str = "",
        issue_reason: str = "",
        domain: str = "",
        layout: str = "",
        source: str = "",
        found_count: int = 0,
        returned_count: int = 0,
        duration_ms: int = 0,
    ) -> None:
        await self._execute(
            """
            INSERT INTO synthetic_query_probe_results (
                run_id, case_id, prompt, answer, status, severity,
                issue_category, issue_reason, domain, layout, source,
                found_count, returned_count, duration_ms, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, case_id) DO UPDATE SET
                prompt = excluded.prompt,
                answer = excluded.answer,
                status = excluded.status,
                severity = excluded.severity,
                issue_category = excluded.issue_category,
                issue_reason = excluded.issue_reason,
                domain = excluded.domain,
                layout = excluded.layout,
                source = excluded.source,
                found_count = excluded.found_count,
                returned_count = excluded.returned_count,
                duration_ms = excluded.duration_ms,
                created_at = excluded.created_at
            """,
            (
                run_id,
                case_id,
                prompt,
                answer,
                status,
                severity,
                issue_category,
                issue_reason,
                domain,
                layout,
                source,
                found_count,
                returned_count,
                duration_ms,
                utc_iso(),
            ),
        )

    async def finish_synthetic_probe_run(
        self,
        *,
        run_id: int,
        status: str,
        question_count: int,
        issue_count: int,
        error: str = "",
    ) -> None:
        await self._execute(
            """
            UPDATE synthetic_query_probe_runs
            SET status = ?, question_count = ?, issue_count = ?,
                completed_at = ?, error = ?
            WHERE id = ?
            """,
            (
                status,
                question_count,
                issue_count,
                utc_iso(),
                error[:1000],
                run_id,
            ),
        )

    async def record_synthetic_probe_alert(
        self,
        *,
        run_id: int,
        status: str,
        error: str = "",
    ) -> None:
        await self._execute(
            """
            UPDATE synthetic_query_probe_runs
            SET alert_status = ?, alert_error = ?
            WHERE id = ?
            """,
            (status, error[:1000], run_id),
        )

    async def synthetic_probe_summary(
        self,
        *,
        start_at: str,
        end_at: str,
        limit: int = 20,
        run_id: int | None = None,
    ) -> dict[str, Any]:
        conditions = ["r.created_at >= ?", "r.created_at < ?"]
        params: list[Any] = [start_at, end_at]
        if run_id is not None:
            conditions.append("r.run_id = ?")
            params.append(run_id)
        where = " AND ".join(conditions)
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                f"""
                SELECT r.*, p.slot_at
                FROM synthetic_query_probe_results r
                JOIN synthetic_query_probe_runs p ON p.id = r.run_id
                WHERE {where}
                ORDER BY r.created_at DESC, r.id DESC
                """,
                params,
            )
            rows = await cursor.fetchall()
            run_cursor = await db.execute(
                f"""
                SELECT COUNT(DISTINCT r.run_id) AS count
                FROM synthetic_query_probe_results r
                WHERE {where}
                """,
                params,
            )
            run_row = await run_cursor.fetchone()

        statuses: dict[str, int] = {}
        total_duration = 0
        issues: list[dict[str, Any]] = []
        for row in rows:
            result_status = str(row["status"] or "unknown")
            statuses[result_status] = statuses.get(result_status, 0) + 1
            total_duration += int(row["duration_ms"] or 0)
            if result_status == "passed" or len(issues) >= max(1, limit):
                continue
            issues.append(
                {
                    "caseId": str(row["case_id"] or ""),
                    "prompt": str(row["prompt"] or ""),
                    "answer": _summary_text(str(row["answer"] or "")),
                    "status": result_status,
                    "severity": str(row["severity"] or "warning"),
                    "category": str(row["issue_category"] or "自动巡检异常"),
                    "reason": str(row["issue_reason"] or "需要人工复核。"),
                    "domain": str(row["domain"] or ""),
                    "layout": str(row["layout"] or ""),
                    "source": str(row["source"] or ""),
                    "foundCount": int(row["found_count"] or 0),
                    "returnedCount": int(row["returned_count"] or 0),
                    "durationMs": int(row["duration_ms"] or 0),
                    "slotAt": str(row["slot_at"] or ""),
                    "createdAt": str(row["created_at"] or ""),
                }
            )
        total = len(rows)
        issue_count = total - statuses.get("passed", 0)
        return {
            "runCount": int(run_row["count"] if run_row else 0),
            "total": total,
            "passedCount": statuses.get("passed", 0),
            "issueCount": issue_count,
            "passRate": round(statuses.get("passed", 0) * 100 / total, 1)
            if total
            else 0,
            "averageDurationMs": round(total_duration / total) if total else 0,
            "statuses": statuses,
            "issues": issues,
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


def _summary_text(value: str, *, limit: int = 500) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _poor_answer_issue(
    *,
    status: str,
    answer: str,
    found_count: int,
    error: str,
    warnings: list[str],
) -> dict[str, str] | None:
    if status in {"error", "failed"}:
        return {
            "category": "系统错误",
            "severity": "critical",
            "reason": error or "查询执行失败，未生成有效回答。",
            "suggestedAction": "检查查询、FileMaker 或模型服务日志后重试。",
        }
    if status == "clarification":
        return {
            "category": "需要澄清",
            "severity": "warning",
            "reason": error or answer or "系统要求用户补充查询条件。",
            "suggestedAction": "检查字段语义和别名，减少不必要的追问。",
        }
    if not answer:
        return {
            "category": "空回答",
            "severity": "critical",
            "reason": "请求已结束，但没有保存任何回答内容。",
            "suggestedAction": "检查回答组装与保存流程。",
        }
    if status == "success" and found_count == 0:
        return {
            "category": "零结果待复核",
            "severity": "warning",
            "reason": answer or "查询没有匹配到记录。",
            "suggestedAction": "核对源数据，并检查字段映射、别名和查询条件。",
        }
    if warnings:
        return {
            "category": "回答警告",
            "severity": "warning",
            "reason": "；".join(warnings),
            "suggestedAction": "核对缺失字段及回答中的降级说明。",
        }
    return None
