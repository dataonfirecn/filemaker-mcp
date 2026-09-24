from datetime import datetime

from typing import Literal

from pydantic import BaseModel, Field, SecretStr


class WebViewerPermissions(BaseModel):
    can_view_price: bool = Field(alias="canViewPrice")
    can_manage_accounts: bool = Field(alias="canManageAccounts")
    can_view_products: bool = Field(alias="canViewProducts")
    can_approve_products: bool = Field(default=False, alias="canApproveProducts")
    can_view_orders: bool = Field(alias="canViewOrders")
    can_view_quality: bool = Field(default=False, alias="canViewQuality")
    can_add_completed_receipts: bool = Field(alias="canAddCompletedReceipts")
    can_view_inventory: bool = Field(alias="canViewInventory")
    can_view_bom: bool = Field(alias="canViewBom")
    can_use_natural_query: bool = Field(alias="canUseNaturalQuery")
    can_manage_rag: bool = Field(alias="canManageRag")
    can_merge_orders: bool = Field(alias="canMergeOrders")

    model_config = {"populate_by_name": True}


class WebViewerAccountAdminItem(BaseModel):
    username: str
    display_name: str = Field(alias="displayName")
    filemaker_privilege_set: str = Field(alias="filemakerPrivilegeSet")
    enabled: bool
    mobile_only: bool = Field(default=False, alias="mobileOnly")
    has_password: bool = Field(default=False, alias="hasPassword")
    permissions: WebViewerPermissions
    part_permissions: dict[str, bool] = Field(
        default_factory=dict,
        alias="partPermissions",
    )
    inherits_privilege_set: bool = Field(alias="inheritsPrivilegeSet")
    inherits_part_permissions: bool = Field(alias="inheritsPartPermissions")
    origin: str
    last_seen_at: datetime | None = Field(alias="lastSeenAt")
    updated_at: datetime = Field(alias="updatedAt")
    updated_by: str = Field(alias="updatedBy")

    model_config = {"populate_by_name": True}


class WebViewerPrivilegeSetAdminItem(BaseModel):
    name: str
    enabled: bool
    permissions: WebViewerPermissions
    part_permissions: dict[str, bool] = Field(
        default_factory=dict,
        alias="partPermissions",
    )
    account_count: int = Field(alias="accountCount")
    updated_at: datetime = Field(alias="updatedAt")
    updated_by: str = Field(alias="updatedBy")

    model_config = {"populate_by_name": True}


class WebViewerAccountAdminResponse(BaseModel):
    accounts: list[WebViewerAccountAdminItem]
    privilege_sets: list[WebViewerPrivilegeSetAdminItem] = Field(alias="privilegeSets")

    model_config = {"populate_by_name": True}


class WebViewerAccountRegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    display_name: str = Field(alias="displayName", min_length=1, max_length=120)
    filemaker_privilege_set: str = Field(
        alias="filemakerPrivilegeSet",
        min_length=1,
        max_length=160,
    )
    enabled: bool = True
    mobile_only: bool = Field(default=False, alias="mobileOnly")
    password: SecretStr = Field(min_length=8, max_length=128)
    permissions: WebViewerPermissions | None = None
    part_permissions: dict[str, bool] | None = Field(
        default=None,
        alias="partPermissions",
    )
    inherit_privilege_set: bool = Field(default=True, alias="inheritPrivilegeSet")
    inherit_part_permissions: bool = Field(
        default=True,
        alias="inheritPartPermissions",
    )

    model_config = {"populate_by_name": True}


class WebViewerAccountAdminUpdateRequest(BaseModel):
    display_name: str | None = Field(
        default=None,
        alias="displayName",
        min_length=1,
        max_length=120,
    )
    filemaker_privilege_set: str | None = Field(
        default=None,
        alias="filemakerPrivilegeSet",
        min_length=1,
        max_length=160,
    )
    enabled: bool
    mobile_only: bool | None = Field(default=None, alias="mobileOnly")
    password: SecretStr | None = Field(default=None, min_length=8, max_length=128)
    permissions: WebViewerPermissions
    part_permissions: dict[str, bool] | None = Field(
        default=None,
        alias="partPermissions",
    )
    inherit_privilege_set: bool = Field(default=False, alias="inheritPrivilegeSet")
    inherit_part_permissions: bool = Field(
        default=False,
        alias="inheritPartPermissions",
    )

    model_config = {"populate_by_name": True}


class WebViewerPrivilegeSetAdminUpdateRequest(BaseModel):
    enabled: bool
    permissions: WebViewerPermissions
    part_permissions: dict[str, bool] | None = Field(
        default=None,
        alias="partPermissions",
    )

    model_config = {"populate_by_name": True}


class LlmProviderOption(BaseModel):
    id: Literal["deepseek", "lm_studio"]
    label: str
    model: str
    base_url: str = Field(alias="baseUrl")
    configured: bool
    active: bool

    model_config = {"populate_by_name": True}


class LlmProviderStatusResponse(BaseModel):
    enabled: bool
    active_provider: Literal["deepseek", "lm_studio"] = Field(alias="activeProvider")
    updated_at: datetime | None = Field(alias="updatedAt")
    updated_by: str = Field(alias="updatedBy")
    providers: list[LlmProviderOption]

    model_config = {"populate_by_name": True}


class LlmProviderSwitchRequest(BaseModel):
    provider: Literal["deepseek", "lm_studio"]


class MobileDiagnosticReportListItem(BaseModel):
    id: int
    report_id: str = Field(alias="reportId")
    operator_account: str = Field(alias="operatorAccount")
    operator_name: str = Field(alias="operatorName")
    operator_privilege: str = Field(alias="operatorPrivilege")
    draft_id: str = Field(alias="draftId")
    document_number: str = Field(alias="documentNumber")
    event: str
    app_build: str = Field(alias="appBuild")
    app_version: str = Field(alias="appVersion")
    email_status: str = Field(alias="emailStatus")
    email_error: str | None = Field(alias="emailError")
    received_at: datetime = Field(alias="receivedAt")
    updated_at: datetime = Field(alias="updatedAt")
    emailed_at: datetime | None = Field(alias="emailedAt")

    model_config = {"populate_by_name": True}


class MobileDiagnosticReportDetail(MobileDiagnosticReportListItem):
    session_id: str = Field(alias="sessionId")
    report: str


class MobileDiagnosticReportListResponse(BaseModel):
    items: list[MobileDiagnosticReportListItem]
    total: int
    page: int
    page_size: int = Field(alias="pageSize")
    total_pages: int = Field(alias="totalPages")

    model_config = {"populate_by_name": True}
