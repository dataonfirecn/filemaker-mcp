from typing import Any

from pydantic import BaseModel, Field


class FileMakerRow(BaseModel):
    record_id: str = Field(alias="recordId")
    mod_id: str | None = Field(default=None, alias="modId")
    fields: dict[str, Any]

    model_config = {"populate_by_name": True}


class ProductInfo(BaseModel):
    product_sku: str = Field(alias="productSku")
    product_name: str = Field(default="", alias="productName")
    product_name_cn: str = Field(default="", alias="productNameCn")
    raw: dict[str, Any]

    model_config = {"populate_by_name": True}


class ProductBomRow(BaseModel):
    record_id: str = Field(alias="recordId")
    product_sku: str = Field(alias="productSku")
    part_no: str = Field(default="", alias="partNo")
    part_name: str = Field(default="", alias="partName")
    required_qty: float | int | str | None = Field(default=None, alias="requiredQty")
    cost_qty: float | int | str | None = Field(default=None, alias="costQty")
    change_type: str = Field(default="", alias="changeType")
    change_status: str = Field(default="", alias="changeStatus")
    raw: dict[str, Any]

    model_config = {"populate_by_name": True}


class ProductBomResponse(BaseModel):
    product: ProductInfo | None
    rows: list[ProductBomRow]
    found_count: int = Field(alias="foundCount")
    returned_count: int = Field(alias="returnedCount")

    model_config = {"populate_by_name": True}


class IssueRowsResponse(BaseModel):
    layout: str
    rows: list[FileMakerRow]
    found_count: int = Field(alias="foundCount")
    returned_count: int = Field(alias="returnedCount")

    model_config = {"populate_by_name": True}


class ReadOnlyActionRequest(BaseModel):
    product_sku: str | None = Field(default=None, alias="productSku")
    order_id: str | None = Field(default=None, alias="orderId")
    bom_calc_id: str | None = Field(default=None, alias="bomCalcId")
    change_batch_id: str | None = Field(default=None, alias="changeBatchId")
    change_item_id: str | None = Field(default=None, alias="changeItemId")
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class BomCalculationPreviewRequest(BaseModel):
    product_sku: str = Field(alias="productSku")
    generate_qty: float = Field(alias="generateQty", gt=0)

    model_config = {"populate_by_name": True}


class BomCalculationLine(BaseModel):
    line_no: int = Field(alias="lineNo")
    source_bom_record_id: str = Field(default="", alias="sourceBomRecordId")
    part_no: str = Field(alias="partNo")
    part_name: str = Field(default="", alias="partName")
    bom_qty: float = Field(alias="bomQty")
    stock_snapshot: float | None = Field(default=None, alias="stockSnapshot")
    calculated_qty: float = Field(alias="calculatedQty")
    actual_qty: float | None = Field(default=None, alias="actualQty")
    warehouse: str = ""
    position1: str = ""
    position2: str = ""
    issue_time: str = Field(default="", alias="issueTime")
    raw: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class BomCalculationPreviewResponse(BaseModel):
    calculation_id: str = Field(alias="calculationId")
    created_at: str = Field(alias="createdAt")
    status: str
    product: ProductInfo | None
    generate_qty: float = Field(alias="generateQty")
    lines: list[BomCalculationLine]

    model_config = {"populate_by_name": True}


class PartInfo(BaseModel):
    part_no: str = Field(alias="partNo")
    part_name: str = Field(default="", alias="partName")
    stock_snapshot: float | None = Field(default=None, alias="stockSnapshot")
    warehouse: str = ""
    position1: str = ""
    position2: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class PartSearchResponse(BaseModel):
    rows: list[PartInfo]
    found_count: int = Field(alias="foundCount")
    returned_count: int = Field(alias="returnedCount")

    model_config = {"populate_by_name": True}


class KitIssueField(BaseModel):
    source: str
    label: str
    role: str
    result: str = ""


class KitIssueRow(BaseModel):
    record_id: str = Field(alias="recordId")
    mod_id: str | None = Field(default=None, alias="modId")
    line_no: int = Field(alias="lineNo")
    order_no: str = Field(default="", alias="orderNo")
    order_date: str = Field(default="", alias="orderDate")
    customer: str = ""
    product_sku: str = Field(default="", alias="productSku")
    product_name_cn: str = Field(default="", alias="productNameCn")
    product_qty: float | int | str | None = Field(default=None, alias="productQty")
    part_no: str = Field(default="", alias="partNo")
    part_name: str = Field(default="", alias="partName")
    warehouse_division: str = Field(default="", alias="warehouseDivision")
    product_warehouse_division: str = Field(default="", alias="productWarehouseDivision")
    position1: str = ""
    position2: str = ""
    rated_qty: float | int | str | None = Field(default=None, alias="ratedQty")
    stock_qty: float | int | str | None = Field(default=None, alias="stockQty")
    quantity: float | int | str | None = None
    shipping_qty: float | int | str | None = Field(default=None, alias="shippingQty")
    actual_qty: float | int | str | None = Field(default=None, alias="actualQty")
    order_summary_cn: str = Field(default="", alias="orderSummaryCn")
    production_receipt_status: str = Field(default="", alias="productionReceiptStatus")
    outbound_id: str = Field(default="", alias="outboundId")
    issue_time: str = Field(default="", alias="issueTime")
    batch_price: float | int | str | None = Field(default=None, alias="batchPrice")
    return_qty: float | int | str | None = Field(default=None, alias="returnQty")
    raw: dict[str, Any]

    model_config = {"populate_by_name": True}


class KitIssueRecordsResponse(BaseModel):
    layout: str
    rows: list[KitIssueRow]
    found_count: int = Field(alias="foundCount")
    returned_count: int = Field(alias="returnedCount")
    page: int
    page_size: int = Field(alias="pageSize")
    total_pages: int = Field(alias="totalPages")
    order_no: str = Field(default="", alias="orderNo")
    fields: list[KitIssueField]

    model_config = {"populate_by_name": True}


class ConfirmBomDocumentRequest(BaseModel):
    calculation_id: str = Field(alias="calculationId")
    product: ProductInfo
    generate_qty: float = Field(alias="generateQty", gt=0)
    lines: list[BomCalculationLine]

    model_config = {"populate_by_name": True}


class BomDocumentResponse(BaseModel):
    id: str
    document_no: str = Field(alias="documentNo")
    product_sku: str = Field(alias="productSku")
    product_name: str = Field(alias="productName")
    product_name_cn: str = Field(alias="productNameCn")
    generate_qty: float = Field(alias="generateQty")
    status: str
    operator_account: str = Field(alias="operatorAccount")
    operator_name: str = Field(alias="operatorName")
    operator_privilege: str = Field(default="", alias="operatorPrivilege")
    line_count: int = Field(alias="lineCount")
    created_at: str = Field(alias="createdAt")
    lines: list[dict[str, Any]]

    model_config = {"populate_by_name": True}
