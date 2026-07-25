from pydantic import BaseModel, Field


class InventoryTransactionRow(BaseModel):
    record_id: str = Field(alias="recordId")
    date: str
    year: int
    movement_type: str = Field(alias="type")
    order_batch_no: str = Field(alias="orderBatchNo")
    description: str = ""
    inbound_qty: float = Field(alias="inboundQty")
    outbound_qty: float = Field(alias="outboundQty")
    signed_qty: float = Field(alias="signedQty")
    balance: float
    operator: str = ""

    model_config = {"populate_by_name": True}


class InventoryTrendPoint(BaseModel):
    date: str
    balance: float


class InventorySummary(BaseModel):
    current_stock: float = Field(alias="currentStock")
    inbound_total: float = Field(alias="inboundTotal")
    outbound_total: float = Field(alias="outboundTotal")
    net_change: float = Field(alias="netChange")

    model_config = {"populate_by_name": True}


class ProductInventoryResponse(BaseModel):
    product_sku: str = Field(alias="productSku")
    layout: str
    rows: list[InventoryTransactionRow]
    trend: list[InventoryTrendPoint]
    summary: InventorySummary
    found_count: int = Field(alias="foundCount")
    returned_count: int = Field(alias="returnedCount")
    read_only: bool = Field(default=True, alias="readOnly")

    model_config = {"populate_by_name": True}
