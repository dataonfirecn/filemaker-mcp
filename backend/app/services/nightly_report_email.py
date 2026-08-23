from __future__ import annotations

import html
import re
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.core.config import Settings
from app.services.customer_email import CustomerEmailError, deliver_email_message


STATUS_LABELS = {
    "success": "正常",
    "warning": "需关注",
    "failed": "失败",
}

STATUS_COLORS = {
    "success": ("#147a4d", "#eaf7f0"),
    "warning": ("#9a650f", "#fff8e6"),
    "failed": ("#b42318", "#fff2ef"),
}


def nightly_report_recipients(settings: Settings) -> list[str]:
    recipients: list[str] = []
    seen: set[str] = set()
    for candidate in re.split(r"[,;\n]", settings.nightly_report_email_recipients):
        normalized = parseaddr(candidate.strip())[1].strip().casefold()
        if not _looks_like_email(normalized) or normalized in seen:
            continue
        recipients.append(normalized)
        seen.add(normalized)
    return recipients


def send_nightly_report_email(
    settings: Settings,
    *,
    recipient_email: str,
    report: dict[str, Any],
) -> None:
    if not settings.customer_smtp_configured:
        raise CustomerEmailError("SMTP is not configured.")
    recipient = parseaddr(recipient_email.strip())[1].strip().casefold()
    if not _looks_like_email(recipient):
        raise CustomerEmailError("The nightly report recipient is invalid.")

    status = str(report.get("status") or "warning")
    status_label = STATUS_LABELS.get(status, status)
    report_date = str(report.get("reportDate") or "")
    title = str(report.get("title") or "DMS 夜间报告")
    summary = str(report.get("summary") or "")
    report_url = settings.nightly_report_email_public_url.strip()
    brand = _report_brand(report)
    mail_kind = _report_mail_kind(report)
    task_kind = _report_task_kind(report)
    exceptions = list(report.get("exceptions") or [])[:5]

    message = EmailMessage()
    message["Subject"] = f"[{status_label}] {brand} {mail_kind} {report_date} · {title}"
    message["From"] = formataddr(
        (f"{brand} {mail_kind}", settings.customer_smtp_from_email.strip())
    )
    message["To"] = recipient
    plain_text_parts = [
        f"{brand} {mail_kind}：{title}",
        f"日期：{report_date}",
        f"状态：{status_label}",
        f"摘要：{summary}",
    ]
    if exceptions:
        plain_text_parts.extend(("", "需要关注：", _exception_plain_text(exceptions)))
    if report_url:
        plain_text_parts.extend(
            (
                "",
                f"打开报告并复制需关注内容：{_report_review_url(report_url, report)}",
            )
        )
    plain_text_parts.extend(("", f"本邮件由 {brand} {task_kind}任务自动发送。"))
    message.set_content("\n".join(plain_text_parts))
    message.add_alternative(
        build_nightly_report_email_html(report, report_url=report_url),
        subtype="html",
    )
    try:
        deliver_email_message(settings, message)
    except CustomerEmailError as exc:
        raise CustomerEmailError(
            f"The nightly report email could not be sent: {exc}"
        ) from exc


def build_nightly_report_email_html(
    report: dict[str, Any],
    *,
    report_url: str = "",
) -> str:
    status = str(report.get("status") or "warning")
    brand = _report_brand(report)
    mail_kind = _report_mail_kind(report)
    task_kind = _report_task_kind(report)
    kicker = "QUERY PROBE ALERT" if mail_kind == "自动巡检" else "NIGHTLY REPORT"
    status_label = STATUS_LABELS.get(status, status)
    status_color, status_background = STATUS_COLORS.get(
        status,
        STATUS_COLORS["warning"],
    )
    title = html.escape(str(report.get("title") or "DMS 夜间报告"))
    report_date = html.escape(str(report.get("reportDate") or ""))
    summary = html.escape(str(report.get("summary") or ""))
    completeness = html.escape(str(report.get("dataCompleteness") or 0))
    metrics = list(report.get("metrics") or [])[:6]
    exceptions = list(report.get("exceptions") or [])[:5]
    metric_rows = _metric_rows(metrics)
    exception_rows = _exception_rows(
        exceptions,
        report_url=report_url,
        report_id=str(report.get("id") or ""),
    )
    if not exceptions:
        attention_note = "本报告没有需要人工复核的事项。"
    elif report_url:
        attention_note = "下面的文字可直接选择复制；点击“打开并复制”会定位到报告中心的对应内容。"
    else:
        attention_note = "下面的文字可直接选择复制并转发给相关人员复核。"
    direct_report_url = _report_review_url(report_url, report)
    report_button = (
        f"""
        <tr><td style="padding:22px 28px 28px">
          <a href="{html.escape(direct_report_url, quote=True)}"
             style="display:inline-block;border-radius:8px;background:#0f766e;color:#ffffff;text-decoration:none;padding:11px 18px;font-size:13px;font-weight:700">
            打开 {html.escape(brand)} 报告中心
          </a>
        </td></tr>
        """
        if report_url
        else ""
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;background:#f3f6f6;color:#25313b;font-family:Arial,'PingFang SC','Microsoft YaHei',sans-serif">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f3f6f6">
    <tr><td align="center" style="padding:24px 12px">
      <table role="presentation" width="680" cellspacing="0" cellpadding="0" border="0"
             style="width:100%;max-width:680px;border:1px solid #dce5e5;border-radius:14px;background:#ffffff;overflow:hidden">
        <tr><td style="padding:28px;background:#0f766e;color:#ffffff">
          <div style="font-size:11px;font-weight:700;letter-spacing:.08em;opacity:.8">{html.escape(brand.upper())} {kicker} · {report_date}</div>
          <h1 style="margin:8px 0 9px;font-size:25px;line-height:1.3">{title}</h1>
          <p style="margin:0;font-size:13px;line-height:1.7;opacity:.9">{summary}</p>
          <span style="display:inline-block;margin-top:16px;border-radius:999px;background:{status_background};color:{status_color};padding:6px 11px;font-size:11px;font-weight:700">{html.escape(status_label)}</span>
        </td></tr>
        <tr><td style="padding:20px 28px 4px">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
            <tr>
              <td style="border:1px solid #e2e9e9;border-radius:9px;padding:13px">
                <div style="color:#718087;font-size:10px">数据完整度</div>
                <strong style="display:block;margin-top:4px;color:#173d40;font-size:20px">{completeness}%</strong>
              </td>
              <td width="10"></td>
              <td style="border:1px solid #e2e9e9;border-radius:9px;padding:13px">
                <div style="color:#718087;font-size:10px">需要关注</div>
                <strong style="display:block;margin-top:4px;color:#173d40;font-size:20px">{len(exceptions)} 项</strong>
              </td>
            </tr>
          </table>
        </td></tr>
        <tr><td style="padding:18px 28px 4px">
          <h2 style="margin:0 0 10px;color:#173d40;font-size:15px">核心指标</h2>
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">{metric_rows}</table>
        </td></tr>
        <tr><td style="padding:18px 28px 4px">
          <h2 style="margin:0 0 4px;color:#173d40;font-size:15px">需要关注</h2>
          <p style="margin:0 0 10px;color:#718087;font-size:10px;line-height:1.55">{attention_note}</p>
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">{exception_rows}</table>
        </td></tr>
        {report_button}
        <tr><td style="border-top:1px solid #e8eeee;padding:16px 28px;color:#87949a;font-size:10px;line-height:1.5">
          本邮件由 {html.escape(brand)} {html.escape(task_kind)}任务自动发送。完整HTML报告和历史记录保存在服务器报告中心。
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _metric_rows(metrics: Iterable[dict[str, Any]]) -> str:
    rows: list[str] = []
    for item in metrics:
        name = html.escape(str(item.get("metricName") or "指标"))
        value = html.escape(
            str(
                item.get("displayValue")
                or f"{item.get('metricValue', '-')}{item.get('unit', '')}"
            )
        )
        rows.append(
            f"""<tr><td style="border-bottom:1px solid #edf1f1;padding:9px 0;color:#66767d;font-size:11px">{name}</td>
            <td align="right" style="border-bottom:1px solid #edf1f1;padding:9px 0;color:#183f43;font-size:13px;font-weight:700">{value}</td></tr>"""
        )
    if not rows:
        return '<tr><td style="padding:14px;color:#87949a;font-size:11px;text-align:center">暂无结构化指标</td></tr>'
    return "".join(rows)


def _exception_rows(
    exceptions: Iterable[dict[str, Any]],
    *,
    report_url: str = "",
    report_id: str = "",
) -> str:
    rows: list[str] = []
    for item in exceptions:
        title = html.escape(str(item.get("title") or "待处理异常"))
        description = html.escape(str(item.get("description") or ""))
        impact = html.escape(str(item.get("impact") or ""))
        action = html.escape(str(item.get("suggestedAction") or ""))
        owner = html.escape(str(item.get("owner") or ""))
        detail = "<br>".join(
            part
            for part in (
                f"现象：{description}" if description else "",
                f"影响：{impact}" if impact else "",
                f"建议：{action}" if action else "",
                f"负责人：{owner}" if owner else "",
            )
            if part
        )
        attention_url = _report_review_url(
            report_url,
            {"id": report_id},
            attention_id=str(item.get("id") or ""),
        )
        copy_link = (
            f'<a href="{html.escape(attention_url, quote=True)}" '
            'style="float:right;margin-left:10px;border:1px solid #d2a85d;border-radius:6px;'
            'background:#ffffff;color:#805b18;text-decoration:none;padding:5px 8px;font-size:9px;font-weight:700">'
            "打开并复制</a>"
            if attention_url
            else ""
        )
        rows.append(
            f"""<tr><td style="border-left:3px solid #b7791f;border-bottom:8px solid #ffffff;background:#fff8e6;padding:10px 12px">
              {copy_link}<strong style="color:#553b11;font-size:11px">{title}</strong>
              {f'<div style="margin-top:4px;color:#725f3a;font-size:10px;line-height:1.55;user-select:all;-webkit-user-select:all">{detail}</div>' if detail else ''}
            </td></tr>"""
        )
    if not rows:
        return '<tr><td style="border-radius:8px;background:#eaf7f0;color:#147a4d;padding:13px;font-size:11px;text-align:center">没有未处理的重要异常</td></tr>'
    return "".join(rows)


def _exception_plain_text(exceptions: Iterable[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for index, item in enumerate(exceptions, start=1):
        lines = [f"{index}. {str(item.get('title') or '待处理异常')}"]
        for label, key in (
            ("现象", "description"),
            ("影响", "impact"),
            ("建议", "suggestedAction"),
            ("负责人", "owner"),
        ):
            value = str(item.get(key) or "").strip()
            if value:
                lines.append(f"{label}：{value}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _report_review_url(
    report_url: str,
    report: dict[str, Any],
    *,
    attention_id: str = "",
) -> str:
    if not report_url:
        return ""
    parts = urlsplit(report_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    report_id = str(report.get("id") or "").strip()
    if report_id:
        query["reportId"] = report_id
    if attention_id:
        query["attention"] = attention_id
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
    )


def _looks_like_email(value: str) -> bool:
    local, separator, domain = value.partition("@")
    return bool(local and separator and "." in domain and not any(char.isspace() for char in value))


def _report_brand(report: dict[str, Any]) -> str:
    return (
        "Stock Check"
        if str(report.get("reportType") or "") == "customer-chat-daily"
        else "DMS"
    )


def _report_mail_kind(report: dict[str, Any]) -> str:
    report_type = str(report.get("reportType") or "")
    return "自动巡检" if report_type.startswith("synthetic-query-probe") else "夜间报告"


def _report_task_kind(report: dict[str, Any]) -> str:
    report_type = str(report.get("reportType") or "")
    return "自动巡检" if report_type.startswith("synthetic-query-probe") else "夜间"
