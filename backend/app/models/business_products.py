from typing import Any

from pydantic import BaseModel, Field


class BusinessProductFilters(BaseModel):
    category: str = ""
    model: str = ""
    audit: str = ""
    client: str = ""


class BusinessProductFieldGroup(BaseModel):
    name: str
    fields: dict[str, Any] = Field(default_factory=dict)


class BusinessProductPortalGroup(BaseModel):
    name: str
    rows: list[dict[str, Any]] = Field(default_factory=list)


class BusinessProductRow(BaseModel):
    record_id: str = Field(alias="recordId")
    mod_id: str | None = Field(default=None, alias="modId")
    product_sku: str = Field(default="", alias="productSku")
    system_product_sku: str = Field(default="", alias="systemProductSku")
    product_name: str = Field(default="", alias="productName")
    product_name_cn: str = Field(default="", alias="productNameCn")
    image_url: str = Field(default="", alias="imageUrl")
    selected_file_url: str = Field(default="", alias="selectedFileUrl")
    qr_code_url: str = Field(default="", alias="qrCodeUrl")
    model_name: str = Field(default="", alias="modelName")
    scale: str = ""
    category: str = ""
    audit_status: str = Field(default="", alias="auditStatus")
    image_status: str = Field(default="", alias="imageStatus")
    stock: float | int | str | None = None
    stock_usd: float | int | str | None = Field(default=None, alias="stockUsd")
    prepaid_stock_usd: float | int | str | None = Field(default=None, alias="prepaidStockUsd")
    bom_count: float | int | str | None = Field(default=None, alias="bomCount")
    order_qty: float | int | str | None = Field(default=None, alias="orderQty")
    sold_total: float | int | str | None = Field(default=None, alias="soldTotal")
    bom_date: str = Field(default="", alias="bomDate")
    vendor: str = ""
    client: str = ""
    customer: str = ""
    privilege: str = ""
    category1: str = ""
    category2: str = ""
    category3: str = ""
    label_spec: str = Field(default="", alias="labelSpec")
    packaging_hours: float | int | str | None = Field(default=None, alias="packagingHours")
    package_check: str = Field(default="", alias="packageCheck")
    dms_status: str = Field(default="", alias="dmsStatus")
    raw: dict[str, Any] = Field(default_factory=dict)
    main_fields: dict[str, Any] = Field(default_factory=dict, alias="mainFields")
    related_field_groups: list[BusinessProductFieldGroup] = Field(
        default_factory=list,
        alias="relatedFieldGroups",
    )
    portals: list[BusinessProductPortalGroup] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class BusinessProductsResponse(BaseModel):
    layout: str
    rows: list[BusinessProductRow]
    found_count: int = Field(alias="foundCount")
    returned_count: int = Field(alias="returnedCount")
    page: int
    page_size: int = Field(alias="pageSize")
    total_pages: int = Field(alias="totalPages")
    query: str = ""
    filters: BusinessProductFilters

    model_config = {"populate_by_name": True}


class BusinessProductDetailResponse(BaseModel):
    layout: str
    product: BusinessProductRow

    model_config = {"populate_by_name": True}
