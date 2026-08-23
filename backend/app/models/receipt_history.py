from __future__ import annotations

from pydantic import BaseModel, Field


class ReceiptHistoryPhoto(BaseModel):
    attachment_id: str = Field(alias="attachmentId")
    draft_id: str = Field(alias="draftId")
    scope: str
    source: str
    filename: str
    mime_type: str = Field(alias="mimeType")
    file_size: int = Field(alias="fileSize")
    status: str
    uploaded_at: str = Field(alias="uploadedAt")
    operator_account: str = Field(alias="operatorAccount")
    url: str

    model_config = {"populate_by_name": True}


class ReceiptHistoryInventoryMovement(BaseModel):
    record_key: str = Field(alias="recordKey")
    receipt_id: str = Field(alias="receiptId")
    line_id: str = Field(alias="lineId")
    product_sku: str = Field(alias="productSku")
    date: str
    batch_number: str = Field(alias="batchNumber")
    description: str
    inbound_quantity: float = Field(alias="inboundQuantity")
    outbound_quantity: float = Field(alias="outboundQuantity")
    operator: str

    model_config = {"populate_by_name": True}


class ReceiptHistoryEntry(BaseModel):
    receipt_id: str = Field(alias="receiptId")
    status: str
    quantity: float
    received_at: str = Field(alias="receivedAt")
    received_by: str = Field(alias="receivedBy")
    created_by: str = Field(alias="createdBy")
    modified_at: str = Field(alias="modifiedAt")
    modified_by: str = Field(alias="modifiedBy")
    traceable: bool
    inventory_movements: list[ReceiptHistoryInventoryMovement] = Field(
        alias="inventoryMovements"
    )

    model_config = {"populate_by_name": True}


class ReceiptHistoryLine(BaseModel):
    line_id: str = Field(alias="lineId")
    order_id: str = Field(alias="orderId")
    document_number: str = Field(alias="documentNumber")
    pi_number: str = Field(alias="piNumber")
    customer_po: str = Field(alias="customerPo")
    customer: str
    sales_owner: str = Field(alias="salesOwner")
    product_sku: str = Field(alias="productSku")
    product_name: str = Field(alias="productName")
    english_name: str = Field(alias="englishName")
    main_image_url: str = Field(alias="mainImageUrl")
    order_reference_quantity: float = Field(alias="orderReferenceQuantity")
    current_received_quantity: float = Field(alias="currentReceivedQuantity")
    current_stock: float = Field(alias="currentStock")
    packaging_status: str = Field(alias="packagingStatus")
    packaging_operator: str = Field(alias="packagingOperator")
    source_created_at: str = Field(alias="sourceCreatedAt")
    source_updated_at: str = Field(alias="sourceUpdatedAt")

    model_config = {"populate_by_name": True}


class ReceiptHistorySummary(BaseModel):
    receipt_count: int = Field(alias="receiptCount")
    completed_receipt_count: int = Field(alias="completedReceiptCount")
    official_received_quantity: float = Field(alias="officialReceivedQuantity")
    order_reference_quantity: float = Field(alias="orderReferenceQuantity")
    difference_from_order: float = Field(alias="differenceFromOrder")
    inventory_movement_count: int = Field(alias="inventoryMovementCount")
    photo_count: int = Field(alias="photoCount")
    fully_traceable: bool = Field(alias="fullyTraceable")

    model_config = {"populate_by_name": True}


class ReceiptHistoryResponse(BaseModel):
    line: ReceiptHistoryLine
    summary: ReceiptHistorySummary
    receipts: list[ReceiptHistoryEntry]
    photos: list[ReceiptHistoryPhoto]
    read_only: bool = Field(default=True, alias="readOnly")

    model_config = {"populate_by_name": True}
