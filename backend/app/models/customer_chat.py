from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CustomerLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class CustomerProfile(BaseModel):
    username: str
    display_name: str = Field(alias="displayName")
    company_name: str = Field(alias="companyName")
    client_name: str = Field(alias="clientName")
    access_role: Literal["admin", "manager", "team", "agent"] = Field(alias="accessRole")
    can_view_price: bool = Field(default=False, alias="canViewPrice")
    can_view_orders: bool = Field(default=True, alias="canViewOrders")
    can_view_details: bool = Field(default=True, alias="canViewDetails")
    is_admin: bool = Field(default=False, alias="isAdmin")

    model_config = {"populate_by_name": True}


class CustomerLoginResponse(BaseModel):
    token: str
    expires_at: int = Field(alias="expiresAt")
    customer: CustomerProfile

    model_config = {"populate_by_name": True}


class CustomerPasswordChangeRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=200, alias="oldPassword")
    new_password: str = Field(min_length=1, max_length=200, alias="newPassword")
    confirm_new_password: str = Field(
        min_length=1,
        max_length=200,
        alias="confirmNewPassword",
    )

    model_config = {"populate_by_name": True}


class CustomerPasswordChangeResponse(CustomerLoginResponse):
    message: str


class CustomerQueryRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=240)
    page: int = Field(default=1, ge=1, le=10_000)
    pageSize: int = Field(default=20, ge=1, le=50)

    model_config = {"populate_by_name": True}

    @property
    def page_size(self) -> int:
        return self.pageSize


class CustomerProductResult(BaseModel):
    entity_type: Literal["product", "part"] = Field(alias="entityType")
    product_ref: str = Field(alias="productRef")
    product_sku: str = Field(default="", alias="productSku")
    product_name: str = Field(default="", alias="productName")
    model_name: str = Field(default="", alias="modelName")
    scale: str = ""
    category: str = ""
    stock: float | int | str | None = None
    sold_total: float | int | str | None = Field(default=None, alias="soldTotal")
    has_image: bool = Field(default=False, alias="hasImage")
    price: float | int | str | None = None

    # Keep the external response boundary strict. Adding an internal field to the
    # constructor must fail instead of being silently serialized to customers.
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class CustomerOrderResult(BaseModel):
    entity_type: Literal["order"] = Field(alias="entityType")
    order_ref: str = Field(alias="orderRef")
    client_name: str = Field(default="", alias="clientName")
    order_number: str = Field(default="", alias="orderNumber")
    order_amount: float | int | str | None = Field(default=None, alias="orderAmount")
    shipping_company: str = Field(default="", alias="shippingCompany")
    tracking_number: str = Field(default="", alias="trackingNumber")
    shipping_cost: float | int | str | None = Field(default=None, alias="shippingCost")
    shipped_date: str = Field(default="", alias="shippedDate")
    shipping_status: str = Field(default="", alias="shippingStatus")
    remarks: str = ""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class CustomerQueryResponse(BaseModel):
    result_type: Literal["product", "part", "order"] = Field(alias="resultType")
    answer: str
    rows: list[CustomerProductResult | CustomerOrderResult] = Field(default_factory=list)
    found_count: int = Field(alias="foundCount")
    returned_count: int = Field(alias="returnedCount")
    page: int
    page_size: int = Field(alias="pageSize")
    total_pages: int = Field(alias="totalPages")
    has_previous: bool = Field(alias="hasPrevious")
    has_next: bool = Field(alias="hasNext")
    requires_clarification: bool = Field(default=False, alias="requiresClarification")
    clarification_question: str | None = Field(default=None, alias="clarificationQuestion")
    clarification_options: list[str] = Field(default_factory=list, alias="clarificationOptions")
    history_id: int | None = Field(default=None, alias="historyId")

    model_config = {"populate_by_name": True}
