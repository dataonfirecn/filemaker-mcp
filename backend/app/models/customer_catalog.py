from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CustomerCatalogProduct(BaseModel):
    product_ref: str = Field(alias="productRef")
    product_sku: str = Field(default="", alias="productSku")
    product_name: str = Field(default="", alias="productName")
    model_name: str = Field(default="", alias="modelName")
    scale: str = ""
    category: str = ""
    stock: float | int | str | None = None
    bom_count: float | int | str | None = Field(default=None, alias="bomCount")
    has_image: bool = Field(default=False, alias="hasImage")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class CustomerProductDetailItem(CustomerCatalogProduct):
    sold_total: float | int | str | None = Field(default=None, alias="soldTotal")
    price: float | int | str | None = None
    stock_value: float | int | str | None = Field(default=None, alias="stockValue")
    prepaid_stock: float | int | str | None = Field(default=None, alias="prepaidStock")
    production_calculation: float | int | str | None = Field(
        default=None,
        alias="productionCalculation",
    )


class CustomerProductImage(BaseModel):
    asset_ref: str = Field(alias="assetRef")
    filename: str = ""
    title: str = ""
    sort_order: int = Field(default=0, alias="sortOrder")
    is_primary: bool = Field(default=False, alias="isPrimary")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class CustomerCatalogPart(BaseModel):
    part_ref: str = Field(alias="partRef")
    part_number: str = Field(default="", alias="partNumber")
    part_name: str = Field(default="", alias="partName")
    stock: float | int | str | None = None
    safety_stock: float | int | str | None = Field(default=None, alias="safetyStock")
    turnover: str = ""
    created: str = ""
    status: str = ""
    has_image: bool = Field(default=False, alias="hasImage")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class CustomerCatalogPage(BaseModel):
    found_count: int = Field(alias="foundCount")
    returned_count: int = Field(alias="returnedCount")
    page: int
    page_size: int = Field(alias="pageSize")
    total_pages: int = Field(alias="totalPages")
    query: str = ""
    sort_by: str = Field(alias="sortBy")
    sort_order: Literal["asc", "desc"] = Field(alias="sortOrder")

    model_config = {"populate_by_name": True}


class CustomerProductListResponse(CustomerCatalogPage):
    rows: list[CustomerCatalogProduct] = Field(default_factory=list)


class CustomerPartListResponse(CustomerCatalogPage):
    rows: list[CustomerCatalogPart] = Field(default_factory=list)


class CustomerCatalogOrder(BaseModel):
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


class CustomerOrderListResponse(CustomerCatalogPage):
    rows: list[CustomerCatalogOrder] = Field(default_factory=list)


class CustomerOrderSummaryResponse(BaseModel):
    order_amount_total: float | None = Field(default=None, alias="orderAmountTotal")
    order_count: int = Field(default=0, alias="orderCount")
    shipped_count: int = Field(default=0, alias="shippedCount")
    not_shipped_count: int = Field(default=0, alias="notShippedCount")
    month: str = ""
    shipping_status: Literal["all", "shipped", "notShipped"] = Field(
        default="all",
        alias="shippingStatus",
    )

    model_config = {"populate_by_name": True}


class CustomerBomLine(BaseModel):
    line_ref: str = Field(alias="lineRef")
    part_number: str = Field(default="", alias="partNumber")
    client_part_number: str = Field(default="", alias="clientPartNumber")
    part_name: str = Field(default="", alias="partName")
    bom_quantity: float | int | str | None = Field(default=None, alias="bomQuantity")
    required_quantity: float | int | str | None = Field(default=None, alias="requiredQuantity")
    stock: float | int | str | None = None
    status: str = ""
    spare_part_number: str = Field(default="", alias="sparePartNumber")
    spare_stock: float | int | str | None = Field(default=None, alias="spareStock")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class CustomerRelatedProduct(BaseModel):
    product_ref: str = Field(alias="productRef")
    product_sku: str = Field(default="", alias="productSku")
    product_name: str = Field(default="", alias="productName")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class CustomerProductDetailResponse(BaseModel):
    product: CustomerProductDetailItem
    images: list[CustomerProductImage] = Field(default_factory=list)
    image_count: int = Field(default=0, alias="imageCount")
    bom: list[CustomerBomLine] = Field(default_factory=list)
    bom_found_count: int = Field(default=0, alias="bomFoundCount")
    bom_returned_count: int = Field(default=0, alias="bomReturnedCount")
    bom_truncated: bool = Field(default=False, alias="bomTruncated")
    warnings: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class CustomerPartDetailResponse(BaseModel):
    part: CustomerCatalogPart
    related_products: list[CustomerRelatedProduct] = Field(default_factory=list, alias="relatedProducts")

    model_config = ConfigDict(populate_by_name=True)
