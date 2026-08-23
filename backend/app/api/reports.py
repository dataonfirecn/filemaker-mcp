from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse

from app.models.reports import (
    ReportDashboardResponse,
    ReportDetail,
    ReportListResponse,
)
from app.services.dependencies import (
    get_nightly_report_store,
    get_webviewer_session_context,
)
from app.services.nightly_report_store import (
    NightlyReportNotFoundError,
    NightlyReportStore,
)


router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_model=ReportListResponse)
async def list_reports(
    q: str = Query(default="", max_length=160),
    status_filter: str = Query(default="", alias="status", max_length=20),
    report_type: str = Query(default="", alias="reportType", max_length=80),
    date_from: date | None = Query(default=None, alias="dateFrom"),
    date_to: date | None = Query(default=None, alias="dateTo"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=100),
    _session: dict = Depends(get_webviewer_session_context),
    store: NightlyReportStore = Depends(get_nightly_report_store),
) -> ReportListResponse:
    if status_filter and status_filter not in {"success", "warning", "failed"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "不支持的报告状态。"},
        )
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "开始日期不能晚于结束日期。"},
        )
    payload = await store.list_reports(
        query=q,
        status=status_filter,
        report_type=report_type,
        date_from=date_from.isoformat() if date_from else "",
        date_to=date_to.isoformat() if date_to else "",
        page=page,
        page_size=page_size,
    )
    return ReportListResponse.model_validate(payload)


@router.get("/dashboard", response_model=ReportDashboardResponse)
async def get_report_dashboard(
    days: int = Query(default=14, ge=1, le=90),
    _session: dict = Depends(get_webviewer_session_context),
    store: NightlyReportStore = Depends(get_nightly_report_store),
) -> ReportDashboardResponse:
    return ReportDashboardResponse.model_validate(await store.dashboard(days=days))


@router.get("/{report_id}", response_model=ReportDetail)
async def get_report(
    report_id: str,
    _session: dict = Depends(get_webviewer_session_context),
    store: NightlyReportStore = Depends(get_nightly_report_store),
) -> ReportDetail:
    try:
        payload = await store.get_report(report_id)
    except NightlyReportNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "找不到这份报告。"},
        ) from exc
    return ReportDetail.model_validate(payload)


@router.get("/{report_id}/html", response_class=HTMLResponse)
async def get_report_html(
    report_id: str,
    _session: dict = Depends(get_webviewer_session_context),
    store: NightlyReportStore = Depends(get_nightly_report_store),
) -> HTMLResponse:
    try:
        content = await store.read_html(report_id)
    except NightlyReportNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"message": "报告HTML文件不存在。"},
        ) from exc
    return HTMLResponse(
        content=content,
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
                "font-src 'none'; frame-ancestors 'self'"
            ),
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )
