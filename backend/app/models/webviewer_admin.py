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
    permissions: WebViewerPermissions
    inherits_privilege_set: bool = Field(alias="inheritsPrivilegeSet")
    origin: str
    last_seen_at: datetime | None = Field(alias="lastSeenAt")
    updated_at: datetime = Field(alias="updatedAt")
    updated_by: str = Field(alias="updatedBy")

    model_config = {"populate_by_name": True}


class WebViewerPrivilegeSetAdminItem(BaseModel):
    name: str
    enabled: bool
    permissions: WebViewerPermissions
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

    model_config = {"populate_by_name": True}


class WebViewerAccountAdminUpdateRequest(BaseModel):
    enabled: bool
    permissions: WebViewerPermissions
    inherit_privilege_set: bool = Field(default=False, alias="inheritPrivilegeSet")

    model_config = {"populate_by_name": True}


class WebViewerPrivilegeSetAdminUpdateRequest(BaseModel):
    enabled: bool
    permissions: WebViewerPermissions

    model_config = {"populate_by_name": True}


class WebViewerSendAdminCredentialsRequest(BaseModel):
    recipient_email: str = Field(alias="recipientEmail", min_length=3, max_length=320)

    model_config = {"populate_by_name": True}
