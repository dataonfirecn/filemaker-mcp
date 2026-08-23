from __future__ import annotations

import asyncio
import html
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, time as datetime_time, timedelta, timezone
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException

from app.api.natural_language_query import run_natural_language_query
from app.core.config import Settings
from app.models.natural_language_query import (
    NaturalLanguageQueryRequest,
    NaturalLanguageQueryResponse,
)
from app.services.audit_log import AuditLogStore, OperatorContext
from app.services.customer_email import CustomerEmailError
from app.services.filemaker_client import FileMakerClient
from app.services.filemaker_odata_client import FileMakerODataClient
from app.services.natural_query_conversation_store import (
    SYNTHETIC_QUERY_PRIVILEGE,
    NaturalQueryConversationStore,
)
from app.services.nightly_report_email import (
    nightly_report_recipients,
    send_nightly_report_email,
)
from app.services.nightly_report_store import NightlyReportStore
from app.services.rag_index import RagIndexStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyntheticQueryCase:
    case_id: str
    prompt: str
    expected_domain: str
    expected_layout: str
    allow_zero_results: bool = True
    expected_sources: tuple[str, ...] = ()


_PRODUCT_DATE_PROMPTS = (
    "今天新增的产品有哪些",
    "昨天新增了哪些产品",
    "近7天新增的产品有哪些",
    "最近30天创建的产品有哪些",
)
_PART_DATE_PROMPTS = (
    "今天新增的零件有哪些",
    "昨天新增了哪些零件",
    "近7天新增的零件有哪些",
    "最近30天创建的零件有哪些",
)
_PURCHASE_PROMPTS = (
    "今天采购的零件有哪些",
    "昨天采购了哪些零件",
    "近7天采购的零件有哪些",
    "最近30天采购的零件有哪些",
)
_MOST_SOLD_PROMPTS = (
    "销量最高的前5个 SKU",
    "列出最畅销的前5个产品",
    "哪些产品累计销量最高，显示前5个",
)
_LEAST_SOLD_PROMPTS = (
    "销量最低的后5个 SKU",
    "列出最滞销的后5个产品",
    "哪些产品非零累计销量最低，显示后5个",
)


class SyntheticQueryMonitor:
    """Exercise the real read-only natural-query path on a fixed interval."""

    def __init__(
        self,
        *,
        store: NaturalQueryConversationStore,
        settings: Settings,
        reports: NightlyReportStore,
        filemaker: FileMakerClient,
        odata_client: FileMakerODataClient,
        rag_store: RagIndexStore,
        audit_log: AuditLogStore,
        rng: random.Random | random.SystemRandom | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.reports = reports
        self.filemaker = filemaker
        self.odata_client = odata_client
        self.rag_store = rag_store
        self.audit_log = audit_log
        self.rng = rng or random.SystemRandom()
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    def start(self) -> None:
        if not self.settings.synthetic_query_monitor_enabled or self._task:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="synthetic-query-monitor")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop_event.set()
        try:
            await self._task
        finally:
            self._task = None

    async def run_now(self, *, now: datetime | None = None) -> dict[str, Any] | None:
        local_now = now or datetime.now(self._timezone())
        slot_at = _interval_slot(
            local_now,
            interval_minutes=self.settings.synthetic_query_monitor_interval_minutes,
        )
        run_id = await self.store.claim_synthetic_probe_run(
            slot_at=slot_at.isoformat()
        )
        if run_id is None:
            return None

        cases = await self._select_cases()
        results: list[dict[str, Any]] = []
        try:
            for case in cases:
                result = await self._execute_case(case, run_id=run_id)
                results.append(result)
                await self.store.record_synthetic_probe_result(
                    run_id=run_id,
                    **result,
                )
        except Exception as exc:
            await self.store.finish_synthetic_probe_run(
                run_id=run_id,
                status="failed",
                question_count=len(results),
                issue_count=sum(item["status"] != "passed" for item in results),
                error=str(exc),
            )
            logger.exception("Synthetic query monitor run failed")
            raise

        issue_count = sum(item["status"] != "passed" for item in results)
        run_status = "warning" if issue_count else "success"
        await self.store.finish_synthetic_probe_run(
            run_id=run_id,
            status=run_status,
            question_count=len(results),
            issue_count=issue_count,
        )
        daily_report = await self._publish_daily_report(local_now)
        if issue_count:
            await self._send_issue_alert(
                run_id=run_id,
                slot_at=slot_at,
                results=results,
            )
        logger.info(
            "Synthetic query probe complete: slot=%s questions=%s issues=%s",
            slot_at.isoformat(),
            len(results),
            issue_count,
        )
        return {
            "runId": run_id,
            "slotAt": slot_at.isoformat(),
            "questionCount": len(results),
            "issueCount": issue_count,
            "status": run_status,
            "reportId": daily_report["id"],
            "results": results,
        }

    async def _run(self) -> None:
        logger.info(
            "Synthetic query monitor started: every %s minutes, %s questions per run",
            self.settings.synthetic_query_monitor_interval_minutes,
            self.settings.synthetic_query_monitor_questions_per_run,
        )
        while not self._stop_event.is_set():
            try:
                await self.run_now()
            except Exception:
                logger.exception("Synthetic query monitor scheduler failed")
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=max(
                        5.0,
                        self.settings.synthetic_query_monitor_poll_interval_seconds,
                    ),
                )
            except TimeoutError:
                pass
        logger.info("Synthetic query monitor stopped")

    async def _select_cases(self) -> list[SyntheticQueryCase]:
        product_ids, part_ids = await self._sample_identifiers()
        cases = [
            SyntheticQueryCase(
                "product-recent",
                self.rng.choice(_PRODUCT_DATE_PROMPTS),
                "product",
                "@products",
            ),
            SyntheticQueryCase(
                "part-recent",
                self.rng.choice(_PART_DATE_PROMPTS),
                "part",
                "Parts",
            ),
            SyntheticQueryCase(
                "part-purchase",
                self.rng.choice(_PURCHASE_PROMPTS),
                "part",
                "採購單資料",
                expected_sources=("odata-live",),
            ),
            SyntheticQueryCase(
                "product-most-sold",
                self.rng.choice(_MOST_SOLD_PROMPTS),
                "product",
                "@products_rank",
            ),
            SyntheticQueryCase(
                "product-least-sold",
                self.rng.choice(_LEAST_SOLD_PROMPTS),
                "product",
                "@products_rank",
            ),
        ]
        if product_ids:
            product_id = self.rng.choice(product_ids)
            cases.extend(
                (
                    SyntheticQueryCase(
                        "product-exact",
                        self.rng.choice(
                            (
                                f"查询产品 {product_id}",
                                f"帮我查产品编号 {product_id}",
                                f"显示产品 {product_id} 的资料",
                            )
                        ),
                        "product",
                        "@products",
                        allow_zero_results=False,
                        expected_sources=(
                            ("odata-live",)
                            if self.settings.filemaker_odata_enabled
                            else ("filemaker",)
                        ),
                    ),
                    SyntheticQueryCase(
                        "product-inventory",
                        self.rng.choice(
                            (
                                f"产品 {product_id} 当前库存有多少",
                                f"查询产品 {product_id} 的库存",
                                f"{product_id} 这个产品还有多少现货",
                            )
                        ),
                        "product",
                        "@products",
                        allow_zero_results=False,
                        expected_sources=(
                            ("odata-live",)
                            if self.settings.filemaker_odata_enabled
                            else ("filemaker",)
                        ),
                    ),
                )
            )
        if part_ids:
            part_id = self.rng.choice(part_ids)
            cases.extend(
                (
                    SyntheticQueryCase(
                        "part-exact",
                        self.rng.choice(
                            (
                                f"查询零件 {part_id}",
                                f"帮我查零件编号 {part_id}",
                                f"显示零件 {part_id} 的资料",
                            )
                        ),
                        "part",
                        "Parts",
                        allow_zero_results=False,
                        expected_sources=(
                            ("odata-live",)
                            if self.settings.filemaker_odata_enabled
                            else ("filemaker",)
                        ),
                    ),
                    SyntheticQueryCase(
                        "part-inventory",
                        self.rng.choice(
                            (
                                f"零件 {part_id} 当前库存有多少",
                                f"查询零件 {part_id} 的库存",
                                f"{part_id} 这个零件还有多少现货",
                            )
                        ),
                        "part",
                        "Parts",
                        allow_zero_results=False,
                        expected_sources=(
                            ("odata-live",)
                            if self.settings.filemaker_odata_enabled
                            else ("filemaker",)
                        ),
                    ),
                )
            )

        count = min(
            len(cases),
            max(1, self.settings.synthetic_query_monitor_questions_per_run),
        )
        return self.rng.sample(cases, count)

    async def _sample_identifiers(self) -> tuple[list[str], list[str]]:
        async def sample(layout: str, fields: tuple[str, ...]) -> list[str]:
            try:
                result = await self.filemaker.find_records(
                    layout,
                    query=None,
                    limit=20,
                    offset=1,
                )
            except Exception:
                logger.exception("Unable to sample identifiers for probe layout %s", layout)
                return []
            values: list[str] = []
            for record in result.get("data") or []:
                field_data = record.get("fieldData") if isinstance(record, dict) else None
                if not isinstance(field_data, dict):
                    continue
                value = next(
                    (
                        str(field_data.get(field) or "").strip()
                        for field in fields
                        if str(field_data.get(field) or "").strip()
                    ),
                    "",
                )
                if value and value not in values:
                    values.append(value)
            return values

        product_ids, part_ids = await asyncio.gather(
            sample("@products", ("product_sku", "系統產品編號")),
            sample("Parts", ("part_number", "零件ID")),
        )
        return product_ids, part_ids

    async def _execute_case(
        self,
        case: SyntheticQueryCase,
        *,
        run_id: int,
    ) -> dict[str, Any]:
        started_at = time.perf_counter()
        operator = OperatorContext(
            session_id=f"synthetic-monitor:{run_id}",
            account="synthetic-monitor",
            name="DMS 自动问答巡检",
            privilege=SYNTHETIC_QUERY_PRIVILEGE,
            permissions={
                "canViewPrice": False,
                "canManageAccounts": False,
                "canViewProducts": True,
                "canViewOrders": True,
                "canViewInventory": True,
                "canViewBom": True,
                "canUseNaturalQuery": True,
                "canManageRag": False,
                "canMergeOrders": False,
            },
            part_permissions={"part.procurement.purchaseHistory.read": True},
        )
        try:
            response = await asyncio.wait_for(
                run_natural_language_query(
                    body=NaturalLanguageQueryRequest(prompt=case.prompt, limit=10),
                    filemaker=self.filemaker,
                    odata_client=self.odata_client,
                    rag_store=self.rag_store,
                    audit_log=self.audit_log,
                    conversation_store=self.store,
                    analytics_worker=None,  # Synthetic prompts never enter user analytics.
                    operator=operator,
                    settings=self.settings,
                    enforced_product_client_id="",
                    enforced_part_customer_id="",
                ),
                timeout=self.settings.synthetic_query_monitor_timeout_seconds,
            )
        except TimeoutError:
            duration_ms = _duration_ms(started_at)
            return _result_payload(
                case,
                status="failed",
                severity="critical",
                issue_category="查询超时",
                issue_reason=(
                    f"超过 {self.settings.synthetic_query_monitor_timeout_seconds:g} 秒仍未完成。"
                ),
                duration_ms=duration_ms,
            )
        except HTTPException as exc:
            return _result_payload(
                case,
                status="failed",
                severity="critical",
                issue_category="查询接口错误",
                issue_reason=f"HTTP {exc.status_code}：{_http_exception_detail(exc)}",
                duration_ms=_duration_ms(started_at),
            )
        except Exception as exc:
            return _result_payload(
                case,
                status="failed",
                severity="critical",
                issue_category="系统错误",
                issue_reason=str(exc) or type(exc).__name__,
                duration_ms=_duration_ms(started_at),
            )
        return _evaluate_response(
            case,
            response,
            duration_ms=_duration_ms(started_at),
            slow_threshold_ms=self.settings.synthetic_query_monitor_slow_ms,
        )

    async def _publish_daily_report(self, now: datetime) -> dict[str, Any]:
        local_start = datetime.combine(now.date(), datetime_time.min, tzinfo=self._timezone())
        summary = await self.store.synthetic_probe_summary(
            start_at=local_start.astimezone(timezone.utc).isoformat(),
            end_at=(local_start + timedelta(days=1)).astimezone(timezone.utc).isoformat(),
            limit=30,
        )
        status = "warning" if summary["issueCount"] else "success"
        exceptions = [_probe_exception(item) for item in summary["issues"]]
        return await self.reports.publish(
            report_type="synthetic-query-probe",
            report_date=now.date(),
            title="DMS 自动问答巡检",
            status=status,
            summary=(
                f"今日已执行 {summary['runCount']} 轮、随机测试 {summary['total']} 题；"
                f"通过 {summary['passedCount']} 题，发现 {summary['issueCount']} 个问题，"
                f"通过率 {summary['passRate']:g}%。"
            ),
            html=_probe_report_html(now=now, summary=summary),
            metrics=(
                _metric("probe_runs", "巡检轮次", summary["runCount"], 1),
                _metric("probe_questions", "随机问题", summary["total"], 2),
                _metric("probe_passed", "通过", summary["passedCount"], 3),
                _metric(
                    "probe_issues",
                    "发现问题",
                    summary["issueCount"],
                    4,
                    severity="warning" if summary["issueCount"] else "info",
                ),
                _metric(
                    "probe_pass_rate",
                    "通过率",
                    summary["passRate"],
                    5,
                    display_value=f"{summary['passRate']:g}%",
                    unit="%",
                ),
                _metric(
                    "probe_average_duration",
                    "平均耗时",
                    summary["averageDurationMs"],
                    6,
                    unit=" ms",
                ),
            ),
            exceptions=exceptions,
            keywords=("自动巡检", "模拟提问", "GPU", "FileMaker", "问答质量"),
            data_completeness=100,
            completed_at=now,
        )

    async def _send_issue_alert(
        self,
        *,
        run_id: int,
        slot_at: datetime,
        results: list[dict[str, Any]],
    ) -> None:
        if not self.settings.synthetic_query_monitor_email_on_issue:
            return
        recipients = nightly_report_recipients(self.settings)
        if not self.settings.nightly_report_email_enabled or not recipients:
            logger.warning("Synthetic query issues found but alert email is not configured")
            await self.store.record_synthetic_probe_alert(
                run_id=run_id,
                status="disabled",
                error="Email is disabled or no valid recipient is configured.",
            )
            return
        issues = [item for item in results if item["status"] != "passed"]
        report = {
            "id": f"synthetic-query-probe-alert-{run_id}",
            "reportDate": slot_at.strftime("%Y-%m-%d %H:%M"),
            "reportType": "synthetic-query-probe-alert",
            "title": "DMS 自动问答巡检发现问题",
            "status": "failed" if any(item["status"] == "failed" for item in issues) else "warning",
            "summary": (
                f"本轮随机测试 {len(results)} 题，发现 {len(issues)} 个问题；"
                "模拟提问与真实用户统计已分开。"
            ),
            "dataCompleteness": 100,
            "metrics": [
                _metric("probe_questions", "本轮问题", len(results), 1),
                _metric("probe_issues", "发现问题", len(issues), 2, severity="critical"),
            ],
            "exceptions": [_probe_exception(item) for item in issues],
        }
        errors: list[str] = []
        for recipient in recipients:
            sent = False
            for attempt in range(1, self.settings.nightly_report_email_max_attempts + 1):
                try:
                    await asyncio.to_thread(
                        send_nightly_report_email,
                        self.settings,
                        recipient_email=recipient,
                        report=report,
                    )
                except CustomerEmailError as exc:
                    if attempt >= self.settings.nightly_report_email_max_attempts:
                        errors.append(f"{recipient}: {exc}")
                    else:
                        await asyncio.sleep(min(4.0, float(2 ** (attempt - 1))))
                else:
                    sent = True
                    break
            if not sent:
                logger.error("Synthetic query alert email failed for %s", recipient)
        await self.store.record_synthetic_probe_alert(
            run_id=run_id,
            status="failed" if errors else "sent",
            error="; ".join(errors),
        )

    def _timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.settings.nightly_maintenance_timezone)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")


def _evaluate_response(
    case: SyntheticQueryCase,
    response: NaturalLanguageQueryResponse,
    *,
    duration_ms: int,
    slow_threshold_ms: int,
) -> dict[str, Any]:
    issues: list[tuple[str, str, str]] = []
    if not response.answer.strip():
        issues.append(("critical", "空回答", "查询完成，但没有返回回答文本。"))
    if response.requires_clarification:
        issues.append(
            (
                "warning",
                "不必要的澄清",
                response.clarification_question or "已限定范围的巡检问题仍要求补充条件。",
            )
        )
    if response.plan.domain != case.expected_domain:
        issues.append(
            (
                "warning",
                "领域识别错误",
                f"预期 {case.expected_domain}，实际 {response.plan.domain}。",
            )
        )
    if response.layout != case.expected_layout:
        issues.append(
            (
                "warning",
                "数据布局错误",
                f"预期 {case.expected_layout}，实际 {response.layout or '空'}。",
            )
        )
    if case.expected_sources and response.source not in case.expected_sources:
        issues.append(
            (
                "warning",
                "数据源降级",
                f"预期数据源 {' / '.join(case.expected_sources)}，实际使用 {response.source or '未知数据源'}。",
            )
        )
    if not case.allow_zero_results and response.found_count <= 0:
        issues.append(
            (
                "warning",
                "已知记录零结果",
                "问题使用了刚从 FileMaker 抽取的有效编号，但自然语言查询返回零结果。",
            )
        )
    if response.plan.warnings:
        issues.append(("warning", "回答警告", "；".join(response.plan.warnings)))
    if duration_ms > slow_threshold_ms:
        issues.append(
            (
                "warning",
                "响应过慢",
                f"耗时 {duration_ms} ms，超过 {slow_threshold_ms} ms 阈值。",
            )
        )

    if not issues:
        return _result_payload(
            case,
            status="passed",
            answer=response.answer,
            domain=response.plan.domain,
            layout=response.layout,
            source=response.source,
            found_count=response.found_count,
            returned_count=response.returned_count,
            duration_ms=duration_ms,
        )
    severity = "critical" if any(item[0] == "critical" for item in issues) else "warning"
    return _result_payload(
        case,
        status="failed" if severity == "critical" else "warning",
        severity=severity,
        issue_category="、".join(dict.fromkeys(item[1] for item in issues)),
        issue_reason="；".join(item[2] for item in issues),
        answer=response.answer,
        domain=response.plan.domain,
        layout=response.layout,
        source=response.source,
        found_count=response.found_count,
        returned_count=response.returned_count,
        duration_ms=duration_ms,
    )


def _result_payload(
    case: SyntheticQueryCase,
    *,
    status: str,
    severity: str = "info",
    issue_category: str = "",
    issue_reason: str = "",
    answer: str = "",
    domain: str = "",
    layout: str = "",
    source: str = "",
    found_count: int = 0,
    returned_count: int = 0,
    duration_ms: int = 0,
) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "prompt": case.prompt,
        "answer": answer[:2000],
        "status": status,
        "severity": severity,
        "issue_category": issue_category,
        "issue_reason": issue_reason[:2000],
        "domain": domain,
        "layout": layout,
        "source": source,
        "found_count": found_count,
        "returned_count": returned_count,
        "duration_ms": duration_ms,
    }


def _probe_exception(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": item.get("category") or item.get("issue_category") or "自动巡检异常",
        "severity": item.get("severity") or "warning",
        "title": item.get("prompt") or "未命名巡检问题",
        "description": (
            f"系统回答：{item.get('answer') or '（无有效回答）'}；"
            f"判定原因：{item.get('reason') or item.get('issue_reason') or '需要人工复核。'}；"
            f"耗时：{item.get('durationMs', item.get('duration_ms', 0))} ms"
        ),
        "impact": "自动巡检未能得到符合预期的可靠回答，可能影响真实用户查询。",
        "suggestedAction": "检查模型、查询计划、FileMaker/OData 数据源和对应服务日志后复测。",
        "owner": "数据与AI运营",
    }


def _metric(
    code: str,
    name: str,
    value: int | float,
    sort_order: int,
    *,
    severity: str = "info",
    display_value: str = "",
    unit: str = "",
) -> dict[str, Any]:
    return {
        "metricCode": code,
        "metricName": name,
        "metricValue": value,
        "displayValue": display_value,
        "unit": unit,
        "severity": severity,
        "sortOrder": sort_order,
    }


def _probe_report_html(*, now: datetime, summary: dict[str, Any]) -> str:
    issue_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['slotAt'])}</td>"
        f"<td>{html.escape(item['category'])}</td>"
        f"<td>{html.escape(item['prompt'])}</td>"
        f"<td>{html.escape(item['answer'] or '（无有效回答）')}</td>"
        f"<td>{html.escape(item['reason'])}</td>"
        f"<td>{item['durationMs']} ms</td>"
        "</tr>"
        for item in summary["issues"]
    ) or '<tr><td colspan="6" class="empty">今天的自动巡检尚未发现问题。</td></tr>'
    status = "需关注" if summary["issueCount"] else "正常"
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>DMS 自动问答巡检</title><style>
body{{margin:0;background:#f4f7f7;color:#25313b;font-family:Arial,'PingFang SC','Microsoft YaHei',sans-serif}}
main{{width:min(1180px,calc(100% - 32px));margin:24px auto}}header{{padding:28px;border-radius:18px;background:#0f766e;color:white}}
h1{{margin:8px 0}}.metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0}}
.metric,section{{padding:18px;border:1px solid #dce5e5;border-radius:14px;background:white}}.metric span{{display:block;color:#65747e;font-size:12px}}
.metric strong{{display:block;margin-top:5px;font-size:22px}}table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{padding:10px;border-bottom:1px solid #e8eeee;text-align:left;vertical-align:top}}
th{{background:#f1f7f6}}.table{{overflow:auto}}.empty{{color:#819096;text-align:center}}
</style></head><body><main><header><small>DMS QUERY PROBE · {now.date().isoformat()}</small>
<h1>DMS 自动问答巡检</h1><p>每 {summary.get('intervalMinutes', 60)} 分钟随机提问，模拟数据与真实用户统计分开。</p><strong>{status}</strong></header>
<div class="metrics"><div class="metric"><span>巡检轮次</span><strong>{summary['runCount']}</strong></div>
<div class="metric"><span>随机问题</span><strong>{summary['total']}</strong></div><div class="metric"><span>通过率</span><strong>{summary['passRate']:g}%</strong></div>
<div class="metric"><span>发现问题</span><strong>{summary['issueCount']}</strong></div><div class="metric"><span>平均耗时</span><strong>{summary['averageDurationMs']} ms</strong></div></div>
<section><h2>异常明细</h2><div class="table"><table><thead><tr><th>执行时段</th><th>分类</th><th>随机问题</th><th>系统回答</th><th>判定原因</th><th>耗时</th></tr></thead><tbody>{issue_rows}</tbody></table></div></section>
</main></body></html>"""


def _interval_slot(now: datetime, *, interval_minutes: int) -> datetime:
    interval = max(1, interval_minutes)
    local_midnight = datetime.combine(now.date(), datetime_time.min, tzinfo=now.tzinfo)
    elapsed_minutes = now.hour * 60 + now.minute
    return local_midnight + timedelta(minutes=(elapsed_minutes // interval) * interval)


def _duration_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


def _http_exception_detail(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        return str(detail.get("message") or detail)
    return str(detail)
