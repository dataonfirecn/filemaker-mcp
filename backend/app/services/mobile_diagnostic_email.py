from __future__ import annotations

from email.message import EmailMessage
from email.utils import formataddr, parseaddr
import re

from app.core.config import Settings
from app.services.audit_log import OperatorContext
from app.services.customer_email import CustomerEmailError, deliver_email_message


class MobileDiagnosticEmailError(RuntimeError):
    pass


def send_mobile_diagnostic_email(
    settings: Settings,
    *,
    operator: OperatorContext,
    report_id: str,
    draft_id: str,
    document_number: str,
    event: str,
    report: str,
) -> str:
    if not settings.ios_pda_diagnostic_email_enabled:
        raise MobileDiagnosticEmailError("PDA diagnostic email is disabled.")
    if not settings.customer_smtp_configured:
        raise MobileDiagnosticEmailError("SMTP is not configured.")

    recipient = parseaddr(
        settings.ios_pda_diagnostic_email_recipient.strip()
    )[1].strip().casefold()
    if not _looks_like_email(recipient):
        raise MobileDiagnosticEmailError(
            "PDA diagnostic email recipient is invalid."
        )

    safe_report = redact_diagnostic_report(report)
    subject_document = _subject_value(document_number, fallback="未知单据")
    subject_event = _subject_value(event, fallback="unknown_error")
    message = EmailMessage()
    message["Subject"] = (
        f"[StarRC PDA 错误] {subject_document} · {subject_event}"
    )
    message["From"] = formataddr(
        ("StarRC PDA 错误报告", settings.customer_smtp_from_email.strip())
    )
    message["To"] = recipient
    message.set_content(
        "\n".join(
            [
                "StarRC PDA 错误报告",
                "",
                f"操作员：{operator.name} ({operator.account})",
                f"报告 ID：{report_id}",
                f"草稿 ID：{draft_id}",
                f"单据编号：{document_number or '<空>'}",
                f"错误事件：{event}",
                "",
                "以下内容由 iPad 端生成，已隐藏密码、Token、签名和临时凭证：",
                "",
                safe_report,
            ]
        )
    )
    message.add_attachment(
        safe_report.encode("utf-8"),
        maintype="text",
        subtype="plain",
        filename=f"starrc-pda-error-{_filename_value(report_id)}.txt",
    )
    try:
        deliver_email_message(settings, message)
    except CustomerEmailError as exc:
        raise MobileDiagnosticEmailError(
            "PDA diagnostic email could not be sent."
        ) from exc
    return recipient


def redact_diagnostic_report(report: str) -> str:
    value = report.replace("\x00", "")
    sensitive_line = re.compile(
        r"(?im)^(\s*(?:authorization|bearer|token|password|secret|credential|signature|cookie)[^:\n]*:)\s*.*$"
    )
    value = sensitive_line.sub(r"\1 <已隐藏>", value)
    value = re.sub(
        r"(?i)\bBearer\s+[A-Za-z0-9._~+\-/=]+",
        "Bearer <已隐藏>",
        value,
    )
    # Presigned COS and other temporary URLs must never be forwarded by email.
    value = re.sub(
        r"(https?://[^\s?]+)\?[^\s]+",
        r"\1?<查询参数已隐藏>",
        value,
    )
    return value


def _subject_value(value: str, *, fallback: str) -> str:
    normalized = " ".join(value.split())[:80]
    return normalized or fallback


def _filename_value(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]", "-", value)[:80]
    return normalized or "report"


def _looks_like_email(value: str) -> bool:
    local, separator, domain = value.partition("@")
    return bool(
        local
        and separator
        and "." in domain
        and not any(character.isspace() for character in value)
    )
