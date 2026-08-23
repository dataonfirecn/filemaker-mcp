from datetime import datetime

from pydantic import BaseModel, Field


class WebViewerPermissions(BaseModel):
    can_view_price: bool = Field(alias="canViewPrice")
    can_manage_accounts: bool = Field(alias="canManageAccounts")
    can_view_products: bool = Field(alias="canViewProducts")
    can_view_orders: bool = Field(alias="canViewOrders")
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


class WebViewerSendAdminCredentialsRequest(BaseModel):
    recipient_email: str = Field(alias="recipientEmail", min_length=3, max_length=320)

    model_config = {"populate_by_name": True}
