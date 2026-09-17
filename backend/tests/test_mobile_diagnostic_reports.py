from datetime import datetime

import pytest

from app.api import mobile_app, webviewer
from app.core.config import Settings
from app.services.audit_log import AuditLogStore, OperatorContext


def _operator(account: str = "warehouse.user") -> OperatorContext:
    return OperatorContext(
        session_id="session-1",
        account=account,
        name="仓库测试员",
        privilege="倉庫_組員",
    )


@pytest.mark.asyncio
async def test_mobile_diagnostic_report_is_redacted_saved_and_queryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = AuditLogStore("memory://mobile-diagnostics")
    await store.init()
    monkeypatch.setattr(
        mobile_app,
        "send_mobile_diagnostic_email",
        lambda *args, **kwargs: "admin@example.com",
    )

    response = await mobile_app.email_mobile_diagnostic_report(
        mobile_app.MobileDiagnosticEmailRequest(
            reportId="report-1",
            draftId="draft-1",
            documentNumber="NB261438",
            event="receipt_submission_failed",
            report=(
                "HTTP 403\n"
                "Authorization: Bearer secret-token\n"
                "URL: https://example.com/report?signature=secret"
            ),
        ),
        app_build="12",
        app_version="1.0.0",
        operator=_operator(),
        settings=Settings(),
        audit_log=store,
    )

    assert response.status == "sent"
    assert isinstance(response.sent_at, datetime)
    result = await webviewer.list_mobile_diagnostic_reports(
        page=1,
        page_size=20,
        query="NB261438",
        email_status="sent",
        _access={"canManageAccounts": True},
        audit_log=store,
    )
    assert result.total == 1
    assert result.items[0].app_build == "12"
    detail = await webviewer.get_mobile_diagnostic_report(
        result.items[0].id,
        _access={"canManageAccounts": True},
        audit_log=store,
    )
    assert "secret-token" not in detail.report
    assert "signature=secret" not in detail.report
    assert "<已隐藏>" in detail.report
    assert "<查询参数已隐藏>" in detail.report


@pytest.mark.asyncio
async def test_mobile_diagnostic_report_keeps_failed_email_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = AuditLogStore("memory://mobile-diagnostics-failed")
    await store.init()

    def fail_delivery(*args, **kwargs):
        raise mobile_app.MobileDiagnosticEmailError("SMTP unavailable")

    monkeypatch.setattr(mobile_app, "send_mobile_diagnostic_email", fail_delivery)

    with pytest.raises(mobile_app.HTTPException) as raised:
        await mobile_app.email_mobile_diagnostic_report(
            mobile_app.MobileDiagnosticEmailRequest(
                reportId="report-failed",
                draftId="draft-2",
                documentNumber="NB261439",
                event="receipt_submission_failed",
                report="HTTP 500",
            ),
            app_build="12",
            app_version="1.0.0",
            operator=_operator("warehouse.failed"),
            settings=Settings(),
            audit_log=store,
        )

    assert raised.value.status_code == 503
    result = await store.list_mobile_diagnostic_reports(email_status="failed")
    assert result["total"] == 1
    assert result["items"][0]["emailError"] == "SMTP unavailable"

