from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import aiosqlite


REPORT_STATUSES = {"success", "warning", "failed"}
EXCEPTION_SEVERITIES = {"info", "warning", "critical"}


class NightlyReportNotFoundError(LookupError):
    pass


class NightlyReportStore:
    """Persist searchable report metadata and immutable HTML/JSON artifacts."""

    def __init__(self, database_path: str, reports_directory: str) -> None:
        self.database_path = database_path
        self.reports_directory = Path(reports_directory)

    async def init(self) -> None:
        if self.database_path.startswith("memory://"):
            return
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self.reports_directory.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.database_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS nightly_reports (
                    id TEXT PRIMARY KEY,
                    report_date TEXT NOT NULL,
                    report_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    keywords TEXT NOT NULL DEFAULT '',
                    search_text TEXT NOT NULL DEFAULT '',
                    html_path TEXT NOT NULL,
                    json_path TEXT NOT NULL,
                    data_completeness REAL NOT NULL DEFAULT 100,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(report_type, report_date)
                );

                CREATE INDEX IF NOT EXISTS idx_nightly_reports_date
                ON nightly_reports(report_date DESC, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_nightly_reports_status
                ON nightly_reports(status, report_date DESC);

                CREATE INDEX IF NOT EXISTS idx_nightly_reports_type
                ON nightly_reports(report_type, report_date DESC);

                CREATE TABLE IF NOT EXISTS nightly_report_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_id TEXT NOT NULL,
                    metric_code TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    metric_value REAL,
                    display_value TEXT NOT NULL DEFAULT '',
                    previous_value REAL,
                    target_value REAL,
                    unit TEXT NOT NULL DEFAULT '',
                    severity TEXT NOT NULL DEFAULT 'info',
                    department TEXT NOT NULL DEFAULT '',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(report_id) REFERENCES nightly_reports(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_nightly_report_metrics_report
                ON nightly_report_metrics(report_id, sort_order, id);

                CREATE TABLE IF NOT EXISTS nightly_report_exceptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_id TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT '',
                    severity TEXT NOT NULL DEFAULT 'warning',
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    impact TEXT NOT NULL DEFAULT '',
                    suggested_action TEXT NOT NULL DEFAULT '',
                    owner TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'open',
                    FOREIGN KEY(report_id) REFERENCES nightly_reports(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_nightly_report_exceptions_report
                ON nightly_report_exceptions(report_id, severity, id);

                CREATE TABLE IF NOT EXISTS nightly_report_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_id TEXT NOT NULL,
                    channel TEXT NOT NULL DEFAULT 'email',
                    recipient TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    last_attempt_at TEXT NOT NULL,
                    sent_at TEXT,
                    error TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(report_id) REFERENCES nightly_reports(id) ON DELETE CASCADE,
                    UNIQUE(report_id, channel, recipient)
                );

                CREATE INDEX IF NOT EXISTS idx_nightly_report_deliveries_report
                ON nightly_report_deliveries(report_id, status, recipient);
                """
            )
            await db.commit()

    async def publish(
        self,
        *,
        report_type: str,
        report_date: date | str,
        title: str,
        status: str,
        summary: str,
        html: str,
        metrics: Iterable[dict[str, Any]] = (),
        exceptions: Iterable[dict[str, Any]] = (),
        keywords: Iterable[str] = (),
        data_completeness: float = 100,
        started_at: datetime | str | None = None,
        completed_at: datetime | str | None = None,
    ) -> dict[str, Any]:
        if self.database_path.startswith("memory://"):
            raise RuntimeError("Nightly reports require a persistent SQLite database")
        if status not in REPORT_STATUSES:
            raise ValueError(f"Unsupported report status: {status}")

        report_date_text = (
            report_date.isoformat() if isinstance(report_date, date) else str(report_date)
        )
        safe_type = _slug(report_type)
        report_id = f"{safe_type}-{report_date_text}"
        metric_rows = [_normalize_metric(item) for item in metrics]
        exception_rows = [_normalize_exception(item) for item in exceptions]
        keyword_text = " ".join(str(item).strip() for item in keywords if str(item).strip())
        now = datetime.now(timezone.utc).isoformat()
        started_text = _timestamp(started_at, fallback=now)
        completed_text = _timestamp(completed_at, fallback=now)

        report_directory = (
            self.reports_directory
            / report_date_text[:4]
            / report_date_text[5:7]
            / report_date_text[8:10]
            / report_id
        )
        report_directory.mkdir(parents=True, exist_ok=True)
        html_path = report_directory / "index.html"
        json_path = report_directory / "report.json"
        payload = {
            "id": report_id,
            "reportDate": report_date_text,
            "reportType": report_type,
            "title": title,
            "status": status,
            "summary": summary,
            "keywords": keyword_text,
            "dataCompleteness": _bounded_percentage(data_completeness),
            "startedAt": started_text,
            "completedAt": completed_text,
            "metrics": metric_rows,
            "exceptions": exception_rows,
        }
        _atomic_write(html_path, html)
        _atomic_write(
            json_path,
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        )

        exception_search = " ".join(
            " ".join(
                (
                    item["title"],
                    item["description"],
                    item["impact"],
                    item["suggestedAction"],
                )
            )
            for item in exception_rows
        )
        search_text = " ".join((title, summary, keyword_text, exception_search)).casefold()

        async with aiosqlite.connect(self.database_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute(
                """
                INSERT INTO nightly_reports (
                    id, report_date, report_type, title, status, summary,
                    keywords, search_text, html_path, json_path,
                    data_completeness, started_at, completed_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(report_type, report_date) DO UPDATE SET
                    id = excluded.id,
                    title = excluded.title,
                    status = excluded.status,
                    summary = excluded.summary,
                    keywords = excluded.keywords,
                    search_text = excluded.search_text,
                    html_path = excluded.html_path,
                    json_path = excluded.json_path,
                    data_completeness = excluded.data_completeness,
                    started_at = excluded.started_at,
                    completed_at = excluded.completed_at,
                    updated_at = excluded.updated_at
                """,
                (
                    report_id,
                    report_date_text,
                    report_type,
                    title,
                    status,
                    summary,
                    keyword_text,
                    search_text,
                    str(html_path),
                    str(json_path),
                    _bounded_percentage(data_completeness),
                    started_text,
                    completed_text,
                    now,
                    now,
                ),
            )
            await db.execute(
                "DELETE FROM nightly_report_metrics WHERE report_id = ?",
                (report_id,),
            )
            await db.execute(
                "DELETE FROM nightly_report_exceptions WHERE report_id = ?",
                (report_id,),
            )
            await db.executemany(
                """
                INSERT INTO nightly_report_metrics (
                    report_id, metric_code, metric_name, metric_value,
                    display_value, previous_value, target_value, unit,
                    severity, department, sort_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        report_id,
                        item["metricCode"],
                        item["metricName"],
                        item["metricValue"],
                        item["displayValue"],
                        item["previousValue"],
                        item["targetValue"],
                        item["unit"],
                        item["severity"],
                        item["department"],
                        item["sortOrder"],
                    )
                    for item in metric_rows
                ],
            )
            await db.executemany(
                """
                INSERT INTO nightly_report_exceptions (
                    report_id, category, severity, title, description,
                    impact, suggested_action, owner, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        report_id,
                        item["category"],
                        item["severity"],
                        item["title"],
                        item["description"],
                        item["impact"],
                        item["suggestedAction"],
                        item["owner"],
                        item["status"],
                    )
                    for item in exception_rows
                ],
            )
            await db.commit()
        return await self.get_report(report_id)

    async def list_reports(
        self,
        *,
        query: str = "",
        status: str = "",
        report_type: str = "",
        date_from: str = "",
        date_to: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        conditions: list[str] = []
        params: list[Any] = []
        if query.strip():
            conditions.append("r.search_text LIKE ? ESCAPE '\\'")
            params.append(f"%{_like_pattern(query.casefold().strip())}%")
        if status.strip():
            conditions.append("r.status = ?")
            params.append(status.strip())
        if report_type.strip():
            conditions.append("r.report_type = ?")
            params.append(report_type.strip())
        if date_from.strip():
            conditions.append("r.report_date >= ?")
            params.append(date_from.strip())
        if date_to.strip():
            conditions.append("r.report_date <= ?")
            params.append(date_to.strip())
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        page = max(1, page)
        page_size = min(100, max(1, page_size))
        offset = (page - 1) * page_size

        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            total_cursor = await db.execute(
                f"SELECT COUNT(*) AS total FROM nightly_reports r {where}",
                params,
            )
            total_row = await total_cursor.fetchone()
            cursor = await db.execute(
                f"""
                SELECT r.*,
                    (SELECT COUNT(*) FROM nightly_report_metrics m
                     WHERE m.report_id = r.id) AS metric_count,
                    (SELECT COUNT(*) FROM nightly_report_exceptions e
                     WHERE e.report_id = r.id) AS exception_count
                FROM nightly_reports r
                {where}
                ORDER BY r.report_date DESC, r.created_at DESC, r.title ASC
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            )
            rows = await cursor.fetchall()
            type_cursor = await db.execute(
                """
                SELECT report_type, COUNT(*) AS count
                FROM nightly_reports
                GROUP BY report_type
                ORDER BY report_type
                """
            )
            type_rows = await type_cursor.fetchall()
        total = int(total_row["total"] if total_row else 0)
        return {
            "items": [_report_summary(row) for row in rows],
            "total": total,
            "page": page,
            "pageSize": page_size,
            "totalPages": max(1, (total + page_size - 1) // page_size),
            "reportTypes": [
                {"value": row["report_type"], "count": int(row["count"])}
                for row in type_rows
            ],
        }

    async def get_report(self, report_id: str) -> dict[str, Any]:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT r.*,
                    (SELECT COUNT(*) FROM nightly_report_metrics m
                     WHERE m.report_id = r.id) AS metric_count,
                    (SELECT COUNT(*) FROM nightly_report_exceptions e
                     WHERE e.report_id = r.id) AS exception_count
                FROM nightly_reports r
                WHERE r.id = ?
                """,
                (report_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                raise NightlyReportNotFoundError(report_id)
            metric_cursor = await db.execute(
                """
                SELECT * FROM nightly_report_metrics
                WHERE report_id = ?
                ORDER BY sort_order, id
                """,
                (report_id,),
            )
            exception_cursor = await db.execute(
                """
                SELECT * FROM nightly_report_exceptions
                WHERE report_id = ?
                ORDER BY CASE severity
                    WHEN 'critical' THEN 0
                    WHEN 'warning' THEN 1
                    ELSE 2 END, id
                """,
                (report_id,),
            )
            metric_rows = await metric_cursor.fetchall()
            exception_rows = await exception_cursor.fetchall()
        return {
            **_report_summary(row),
            "metrics": [_metric_payload(item) for item in metric_rows],
            "exceptions": [_exception_payload(item) for item in exception_rows],
        }

    async def read_html(self, report_id: str) -> str:
        report = await self.get_report(report_id)
        root = self.reports_directory.resolve()
        target = Path(str(report["htmlPath"])).resolve()
        if not target.is_relative_to(root) or target.name != "index.html":
            raise NightlyReportNotFoundError(report_id)
        try:
            return target.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise NightlyReportNotFoundError(report_id) from exc

    async def delivery_was_sent(
        self,
        report_id: str,
        recipient: str,
        *,
        channel: str = "email",
    ) -> bool:
        async with aiosqlite.connect(self.database_path) as db:
            cursor = await db.execute(
                """
                SELECT 1
                FROM nightly_report_deliveries
                WHERE report_id = ? AND channel = ? AND recipient = ?
                  AND status = 'sent'
                LIMIT 1
                """,
                (report_id, channel, recipient.strip().casefold()),
            )
            return await cursor.fetchone() is not None

    async def record_delivery_attempt(
        self,
        report_id: str,
        recipient: str,
        *,
        status: str,
        error: str = "",
        channel: str = "email",
    ) -> None:
        if status not in {"sending", "sent", "failed"}:
            raise ValueError(f"Unsupported delivery status: {status}")
        now = datetime.now(timezone.utc).isoformat()
        sent_at = now if status == "sent" else None
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute(
                """
                INSERT INTO nightly_report_deliveries (
                    report_id, channel, recipient, status, attempt_count,
                    last_attempt_at, sent_at, error
                ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                ON CONFLICT(report_id, channel, recipient) DO UPDATE SET
                    status = excluded.status,
                    attempt_count = nightly_report_deliveries.attempt_count + 1,
                    last_attempt_at = excluded.last_attempt_at,
                    sent_at = COALESCE(excluded.sent_at, nightly_report_deliveries.sent_at),
                    error = excluded.error
                """,
                (
                    report_id,
                    channel,
                    recipient.strip().casefold(),
                    status,
                    now,
                    sent_at,
                    error[:1000],
                ),
            )
            await db.commit()

    async def list_deliveries(self, report_id: str) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT channel, recipient, status, attempt_count,
                       last_attempt_at, sent_at, error
                FROM nightly_report_deliveries
                WHERE report_id = ?
                ORDER BY channel, recipient
                """,
                (report_id,),
            )
            rows = await cursor.fetchall()
        return [
            {
                "channel": row["channel"],
                "recipient": row["recipient"],
                "status": row["status"],
                "attemptCount": int(row["attempt_count"]),
                "lastAttemptAt": row["last_attempt_at"],
                "sentAt": row["sent_at"],
                "error": row["error"],
            }
            for row in rows
        ]

    async def dashboard(self, *, days: int = 14) -> dict[str, Any]:
        days = min(90, max(1, days))
        async with aiosqlite.connect(self.database_path) as db:
            db.row_factory = aiosqlite.Row
            latest_cursor = await db.execute(
                "SELECT MAX(report_date) AS report_date FROM nightly_reports"
            )
            latest_row = await latest_cursor.fetchone()
            latest_date = str(latest_row["report_date"] or "") if latest_row else ""
            if not latest_date:
                return {
                    "hasReports": False,
                    "latestDate": "",
                    "overallStatus": "success",
                    "reportCount": 0,
                    "successCount": 0,
                    "warningCount": 0,
                    "failedCount": 0,
                    "dataCompleteness": 0,
                    "latestReports": [],
                    "metrics": [],
                    "exceptions": [],
                    "trends": [],
                }
            report_cursor = await db.execute(
                """
                SELECT r.*,
                    (SELECT COUNT(*) FROM nightly_report_metrics m
                     WHERE m.report_id = r.id) AS metric_count,
                    (SELECT COUNT(*) FROM nightly_report_exceptions e
                     WHERE e.report_id = r.id) AS exception_count
                FROM nightly_reports r
                JOIN (
                    SELECT report_type, MAX(report_date) AS report_date
                    FROM nightly_reports
                    GROUP BY report_type
                ) latest
                  ON latest.report_type = r.report_type
                 AND latest.report_date = r.report_date
                ORDER BY CASE status
                    WHEN 'failed' THEN 0
                    WHEN 'warning' THEN 1
                    ELSE 2 END, title
                """
            )
            report_rows = await report_cursor.fetchall()
            metric_cursor = await db.execute(
                """
                SELECT m.*, r.report_type, r.title AS report_title
                FROM nightly_report_metrics m
                JOIN nightly_reports r ON r.id = m.report_id
                JOIN (
                    SELECT report_type, MAX(report_date) AS report_date
                    FROM nightly_reports
                    GROUP BY report_type
                ) latest
                  ON latest.report_type = r.report_type
                 AND latest.report_date = r.report_date
                ORDER BY CASE m.severity
                    WHEN 'critical' THEN 0
                    WHEN 'warning' THEN 1
                    ELSE 2 END, m.sort_order, m.id
                LIMIT 8
                """
            )
            exception_cursor = await db.execute(
                """
                SELECT e.*, r.report_type, r.title AS report_title
                FROM nightly_report_exceptions e
                JOIN nightly_reports r ON r.id = e.report_id
                JOIN (
                    SELECT report_type, MAX(report_date) AS report_date
                    FROM nightly_reports
                    GROUP BY report_type
                ) latest
                  ON latest.report_type = r.report_type
                 AND latest.report_date = r.report_date
                WHERE e.status != 'closed'
                ORDER BY CASE e.severity
                    WHEN 'critical' THEN 0
                    WHEN 'warning' THEN 1
                    ELSE 2 END, e.id
                LIMIT 6
                """
            )
            trend_cursor = await db.execute(
                """
                SELECT report_date,
                    COUNT(*) AS report_count,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_count,
                    SUM(CASE WHEN status = 'warning' THEN 1 ELSE 0 END) AS warning_count,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
                    AVG(data_completeness) AS data_completeness
                FROM nightly_reports
                GROUP BY report_date
                ORDER BY report_date DESC
                LIMIT ?
                """,
                (days,),
            )
            metric_rows = await metric_cursor.fetchall()
            exception_rows = await exception_cursor.fetchall()
            trend_rows = list(reversed(await trend_cursor.fetchall()))

        statuses = [str(row["status"]) for row in report_rows]
        overall_status = (
            "failed" if "failed" in statuses else "warning" if "warning" in statuses else "success"
        )
        completeness = (
            sum(float(row["data_completeness"]) for row in report_rows) / len(report_rows)
            if report_rows
            else 0
        )
        return {
            "hasReports": True,
            "latestDate": latest_date,
            "overallStatus": overall_status,
            "reportCount": len(report_rows),
            "successCount": statuses.count("success"),
            "warningCount": statuses.count("warning"),
            "failedCount": statuses.count("failed"),
            "dataCompleteness": round(completeness, 1),
            "latestReports": [_report_summary(row) for row in report_rows],
            "metrics": [
                {
                    **_metric_payload(row),
                    "reportType": row["report_type"],
                    "reportTitle": row["report_title"],
                }
                for row in metric_rows
            ],
            "exceptions": [
                {
                    **_exception_payload(row),
                    "reportType": row["report_type"],
                    "reportTitle": row["report_title"],
                }
                for row in exception_rows
            ],
            "trends": [
                {
                    "reportDate": row["report_date"],
                    "reportCount": int(row["report_count"]),
                    "successCount": int(row["success_count"] or 0),
                    "warningCount": int(row["warning_count"] or 0),
                    "failedCount": int(row["failed_count"] or 0),
                    "dataCompleteness": round(float(row["data_completeness"] or 0), 1),
                }
                for row in trend_rows
            ],
        }


def _normalize_metric(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("metricValue", item.get("value"))
    numeric_value = float(value) if value is not None else None
    unit = str(item.get("unit") or "")
    display_value = str(item.get("displayValue") or "")
    if not display_value and numeric_value is not None:
        display_value = f"{numeric_value:g}{unit}"
    severity = str(item.get("severity") or "info")
    if severity not in EXCEPTION_SEVERITIES:
        severity = "info"
    return {
        "metricCode": str(item.get("metricCode") or item.get("code") or "metric"),
        "metricName": str(item.get("metricName") or item.get("name") or "指标"),
        "metricValue": numeric_value,
        "displayValue": display_value,
        "previousValue": _optional_float(item.get("previousValue")),
        "targetValue": _optional_float(item.get("targetValue")),
        "unit": unit,
        "severity": severity,
        "department": str(item.get("department") or ""),
        "sortOrder": int(item.get("sortOrder") or 0),
    }


def _normalize_exception(item: dict[str, Any]) -> dict[str, str]:
    severity = str(item.get("severity") or "warning")
    if severity not in EXCEPTION_SEVERITIES:
        severity = "warning"
    return {
        "category": str(item.get("category") or ""),
        "severity": severity,
        "title": str(item.get("title") or "待处理异常"),
        "description": str(item.get("description") or ""),
        "impact": str(item.get("impact") or ""),
        "suggestedAction": str(item.get("suggestedAction") or ""),
        "owner": str(item.get("owner") or ""),
        "status": str(item.get("status") or "open"),
    }


def _report_summary(row: aiosqlite.Row) -> dict[str, Any]:
    keys = set(row.keys())
    return {
        "id": row["id"],
        "reportDate": row["report_date"],
        "reportType": row["report_type"],
        "title": row["title"],
        "status": row["status"],
        "summary": row["summary"],
        "keywords": row["keywords"],
        "htmlPath": row["html_path"],
        "dataCompleteness": float(row["data_completeness"]),
        "startedAt": row["started_at"],
        "completedAt": row["completed_at"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "metricCount": int(row["metric_count"]) if "metric_count" in keys else 0,
        "exceptionCount": int(row["exception_count"]) if "exception_count" in keys else 0,
    }


def _metric_payload(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "metricCode": row["metric_code"],
        "metricName": row["metric_name"],
        "metricValue": row["metric_value"],
        "displayValue": row["display_value"],
        "previousValue": row["previous_value"],
        "targetValue": row["target_value"],
        "unit": row["unit"],
        "severity": row["severity"],
        "department": row["department"],
        "sortOrder": int(row["sort_order"]),
    }


def _exception_payload(row: aiosqlite.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "category": row["category"],
        "severity": row["severity"],
        "title": row["title"],
        "description": row["description"],
        "impact": row["impact"],
        "suggestedAction": row["suggested_action"],
        "owner": row["owner"],
        "status": row["status"],
    }


def _atomic_write(target: Path, content: str) -> None:
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, target)


def _timestamp(value: datetime | str | None, *, fallback: str) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or fallback)


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None and value != "" else None


def _bounded_percentage(value: float) -> float:
    return round(min(100.0, max(0.0, float(value))), 2)


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_-]+", "-", value.strip().lower()).strip("-")
    return normalized or "report"


def _like_pattern(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
