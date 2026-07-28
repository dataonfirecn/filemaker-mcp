from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CustomerChatHistoryItem(BaseModel):
    id: int
    request_id: str = Field(alias="requestId")
    session_id: str = Field(alias="sessionId")
    operator_account: str = Field(alias="operatorAccount")
    operator_name: str = Field(alias="operatorName")
    client_name: str = Field(alias="clientName")
    is_admin: bool = Field(alias="isAdmin")
    channel: str
    prompt: str
    normalized_key: str = Field(alias="normalizedKey")
    domain: str
    intent: str
    result_type: str = Field(alias="resultType")
    status: str
    http_status: int = Field(alias="httpStatus")
    blocked_reason: str = Field(alias="blockedReason")
    answer: str
    found_count: int = Field(alias="foundCount")
    returned_count: int = Field(alias="returnedCount")
    duration_ms: int = Field(alias="durationMs")
    source_layout: str = Field(alias="sourceLayout")
    is_test: bool = Field(alias="isTest")
    created_at: datetime = Field(alias="createdAt")

    model_config = {"populate_by_name": True}


class CustomerChatHistoryResponse(BaseModel):
    rows: list[CustomerChatHistoryItem]
    found_count: int = Field(alias="foundCount")
    returned_count: int = Field(alias="returnedCount")
    page: int
    page_size: int = Field(alias="pageSize")
    total_pages: int = Field(alias="totalPages")

    model_config = {"populate_by_name": True}


class CustomerChatQuestionSummaryItem(BaseModel):
    normalized_key: str = Field(alias="normalizedKey")
    canonical_question: str = Field(alias="canonicalQuestion")
    domain: str
    intent: str
    total_count: int = Field(alias="totalCount")
    success_count: int = Field(alias="successCount")
    no_result_count: int = Field(alias="noResultCount")
    clarification_count: int = Field(alias="clarificationCount")
    blocked_count: int = Field(alias="blockedCount")
    error_count: int = Field(alias="errorCount")
    last_asked_at: datetime = Field(alias="lastAskedAt")

    model_config = {"populate_by_name": True}


class CustomerChatQuestionSummaryResponse(BaseModel):
    days: int
    questions: list[CustomerChatQuestionSummaryItem]

    model_config = {"populate_by_name": True}


class CustomerAccountAdminItem(BaseModel):
    username: str
    display_name: str = Field(alias="displayName")
    email: str
    client_name: str = Field(alias="clientName")
    product_privilege: str = Field(alias="productPrivilege")
    part_customer_id: str = Field(alias="partCustomerId")
    shipment_company_id: str = Field(alias="shipmentCompanyId")
    enabled: bool
    access_role: Literal["admin", "manager", "team", "agent"] = Field(alias="accessRole")
    can_view_price: bool = Field(alias="canViewPrice")
    can_view_orders: bool = Field(alias="canViewOrders")
    can_view_details: bool = Field(alias="canViewDetails")
    is_admin: bool = Field(alias="isAdmin")
    last_login_at: datetime | None = Field(alias="lastLoginAt")
    last_login_status: str = Field(alias="lastLoginStatus")
    last_successful_login_at: datetime | None = Field(alias="lastSuccessfulLoginAt")
    last_failed_login_at: datetime | None = Field(alias="lastFailedLoginAt")
    successful_login_count: int = Field(alias="successfulLoginCount")
    failed_login_count: int = Field(alias="failedLoginCount")
    updated_at: datetime = Field(alias="updatedAt")
    updated_by: str = Field(alias="updatedBy")
    credentials_email_available_at: datetime | None = Field(
        default=None,
        alias="credentialsEmailAvailableAt",
    )
    credentials_email_sent: bool | None = Field(default=None, alias="credentialsEmailSent")
    credentials_email_error: str = Field(default="", alias="credentialsEmailError")

    model_config = {"populate_by_name": True}


class CustomerAccountAdminResponse(BaseModel):
    accounts: list[CustomerAccountAdminItem]
    email_delivery_enabled: bool = Field(alias="emailDeliveryEnabled")

    model_config = {"populate_by_name": True}


class CustomerCredentialsEmailLogItem(BaseModel):
    id: int
    username: str
    recipient_email: str = Field(alias="recipientEmail")
    status: Literal["success", "failed", "blocked"]
    message: str
    created_at: datetime = Field(alias="createdAt")

    model_config = {"populate_by_name": True}


class CustomerCredentialsEmailLogResponse(BaseModel):
    logs: list[CustomerCredentialsEmailLogItem]

    model_config = {"populate_by_name": True}


class CustomerAccountAdminCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    display_name: str = Field(alias="displayName", min_length=1, max_length=120)
    email: str = Field(
        min_length=5,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    password: str = Field(min_length=12, max_length=256)
    enabled: bool = True
    send_credentials: bool = Field(default=False, alias="sendCredentials")
    access_role: Literal["admin", "manager", "team", "agent"] | None = Field(
        default=None,
        alias="accessRole",
    )
    can_view_price: bool | None = Field(default=None, alias="canViewPrice")
    is_admin: bool | None = Field(default=None, alias="isAdmin")

    model_config = {"populate_by_name": True}


class CustomerAccountAdminUpdateRequest(BaseModel):
    display_name: str | None = Field(
        default=None,
        alias="displayName",
        min_length=1,
        max_length=120,
    )
    email: str | None = Field(
        default=None,
        min_length=5,
        max_length=254,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    )
    enabled: bool | None = None
    send_credentials: bool = Field(default=False, alias="sendCredentials")
    access_role: Literal["admin", "manager", "team", "agent"] | None = Field(
        default=None,
        alias="accessRole",
    )
    can_view_price: bool | None = Field(default=None, alias="canViewPrice")
    is_admin: bool | None = Field(default=None, alias="isAdmin")
    new_password: str | None = Field(
        default=None,
        alias="newPassword",
        min_length=12,
        max_length=256,
    )

    model_config = {"populate_by_name": True}


class CustomerAccountBulkDisableRequest(BaseModel):
    usernames: list[str] = Field(min_length=1, max_length=200)


class CustomerAccountBulkDisableResponse(BaseModel):
    accounts: list[CustomerAccountAdminItem]
    disabled_count: int = Field(alias="disabledCount")

    model_config = {"populate_by_name": True}


class CustomerAccountBulkStatusRequest(BaseModel):
    usernames: list[str] = Field(min_length=1, max_length=200)
    enabled: bool


class CustomerAccountBulkStatusResponse(BaseModel):
    accounts: list[CustomerAccountAdminItem]
    updated_count: int = Field(alias="updatedCount")
    enabled: bool

    model_config = {"populate_by_name": True}
