from __future__ import annotations

from pydantic import BaseModel, Field


class ReportMetric(BaseModel):
    metric_code: str = Field(alias="metricCode")
    metric_name: str = Field(alias="metricName")
    metric_value: float | None = Field(alias="metricValue")
    display_value: str = Field(alias="displayValue")
    previous_value: float | None = Field(alias="previousValue")
    target_value: float | None = Field(alias="targetValue")
    unit: str
    severity: str
    department: str
    sort_order: int = Field(alias="sortOrder")

    model_config = {"populate_by_name": True}


class ReportException(BaseModel):
    id: int
    category: str
    severity: str
    title: str
    description: str
    impact: str
    suggested_action: str = Field(alias="suggestedAction")
    owner: str
    status: str
    report_type: str | None = Field(default=None, alias="reportType")
    report_title: str | None = Field(default=None, alias="reportTitle")

    model_config = {"populate_by_name": True}


class ReportSummary(BaseModel):
    id: str
    report_date: str = Field(alias="reportDate")
    report_type: str = Field(alias="reportType")
    title: str
    status: str
    summary: str
    keywords: str
    data_completeness: float = Field(alias="dataCompleteness")
    started_at: str = Field(alias="startedAt")
    completed_at: str = Field(alias="completedAt")
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")
    metric_count: int = Field(alias="metricCount")
    exception_count: int = Field(alias="exceptionCount")

    model_config = {"populate_by_name": True}


class ReportDetail(ReportSummary):
    metrics: list[ReportMetric] = Field(default_factory=list)
    exceptions: list[ReportException] = Field(default_factory=list)


class ReportTypeOption(BaseModel):
    value: str
    count: int


class ReportListResponse(BaseModel):
    items: list[ReportSummary] = Field(default_factory=list)
    total: int
    page: int
    page_size: int = Field(alias="pageSize")
    total_pages: int = Field(alias="totalPages")
    report_types: list[ReportTypeOption] = Field(alias="reportTypes")

    model_config = {"populate_by_name": True}


class DashboardMetric(ReportMetric):
    report_type: str = Field(alias="reportType")
    report_title: str = Field(alias="reportTitle")


class DashboardTrend(BaseModel):
    report_date: str = Field(alias="reportDate")
    report_count: int = Field(alias="reportCount")
    success_count: int = Field(alias="successCount")
    warning_count: int = Field(alias="warningCount")
    failed_count: int = Field(alias="failedCount")
    data_completeness: float = Field(alias="dataCompleteness")

    model_config = {"populate_by_name": True}


class ReportDashboardResponse(BaseModel):
    has_reports: bool = Field(alias="hasReports")
    latest_date: str = Field(alias="latestDate")
    overall_status: str = Field(alias="overallStatus")
    report_count: int = Field(alias="reportCount")
    success_count: int = Field(alias="successCount")
    warning_count: int = Field(alias="warningCount")
    failed_count: int = Field(alias="failedCount")
    data_completeness: float = Field(alias="dataCompleteness")
    latest_reports: list[ReportSummary] = Field(alias="latestReports")
    metrics: list[DashboardMetric]
    exceptions: list[ReportException]
    trends: list[DashboardTrend]

    model_config = {"populate_by_name": True}
