from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class QualityScanResolveRequest(BaseModel):
    code: str = Field(min_length=2, max_length=500)

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip()


class CreateQualityInspectionRequest(BaseModel):
    arrival_batch_id: str = Field(
        alias="arrivalBatchID",
        min_length=1,
        max_length=160,
    )

    model_config = {"populate_by_name": True}


class QualityArrivalBatch(BaseModel):
    id: str
    purchase_line_id: str = Field(alias="purchaseLineID")
    arrival_date: str = Field(alias="arrivalDate")
    arrival_quantity: int = Field(alias="arrivalQuantity")
    returned_quantity: int = Field(alias="returnedQuantity")
    warehoused_quantity: int = Field(alias="warehousedQuantity")
    qc_status: str = Field(alias="qcStatus")
    nb_number: str = Field(alias="nbNumber")
    pt_number: str = Field(alias="ptNumber")
    inspection_id: str | None = Field(default=None, alias="inspectionID")

    model_config = {"populate_by_name": True}


class QualityScanResolution(BaseModel):
    resource_type: str = Field(default="purchase_arrival", alias="resourceType")
    purchase_line_id: str = Field(alias="purchaseLineID")
    purchase_order_number: str = Field(alias="purchaseOrderNumber")
    part_number: str = Field(alias="partNumber")
    part_name: str = Field(alias="partName")
    supplier_name: str = Field(alias="supplierName")
    arrivals: list[QualityArrivalBatch]

    model_config = {"populate_by_name": True}


class QualitySpecVersion(BaseModel):
    id: str
    version: str
    approved_by: str = Field(alias="approvedBy")
    effective_at: str = Field(alias="effectiveAt")

    model_config = {"populate_by_name": True}


class QualityCheckItem(BaseModel):
    id: str
    code: str
    title: str
    instructions: str
    input_type: str = Field(alias="inputType")
    unit: str = ""
    target_value: float | None = Field(default=None, alias="targetValue")
    lower_limit: float | None = Field(default=None, alias="lowerLimit")
    upper_limit: float | None = Field(default=None, alias="upperLimit")
    required: bool = True
    sample_count: int = Field(default=1, alias="sampleCount")
    standard_text: str | None = Field(default=None, alias="standardText")
    result_kind: str | None = Field(default=None, alias="resultKind")

    model_config = {"populate_by_name": True}


class QualityInspection(BaseModel):
    id: str
    arrival_batch_id: str = Field(alias="arrivalBatchID")
    status: str
    inspection_method: str = Field(alias="inspectionMethod")
    sample_quantity: int = Field(alias="sampleQuantity")
    spec_version: QualitySpecVersion = Field(alias="specVersion")
    check_items: list[QualityCheckItem] = Field(alias="checkItems")

    model_config = {"populate_by_name": True}


class QualityInspectionAdminListItem(BaseModel):
    id: str
    purchase_line_id: str = Field(alias="purchaseLineID")
    arrival_batch_id: str = Field(alias="arrivalBatchID")
    inspection_round: int = Field(alias="inspectionRound")
    purchase_order_number: str = Field(alias="purchaseOrderNumber")
    nb_number: str = Field(alias="nbNumber")
    part_number: str = Field(alias="partNumber")
    part_name: str = Field(alias="partName")
    supplier_name: str = Field(alias="supplierName")
    arrival_date: str = Field(alias="arrivalDate")
    arrival_quantity: int = Field(alias="arrivalQuantity")
    available_quantity: int = Field(alias="availableQuantity")
    inspection_method: str = Field(alias="inspectionMethod")
    sample_quantity: int = Field(alias="sampleQuantity")
    status: str
    conclusion: str
    operator_account: str = Field(alias="operatorAccount")
    operator_name: str = Field(alias="operatorName")
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")

    model_config = {"populate_by_name": True}


class QualityInspectionEvent(BaseModel):
    event_id: str = Field(alias="eventId")
    inspection_id: str = Field(alias="inspectionID")
    event_type: str = Field(alias="eventType")
    from_status: str = Field(alias="fromStatus")
    to_status: str = Field(alias="toStatus")
    operator_account: str = Field(alias="operatorAccount")
    operator_name: str = Field(alias="operatorName")
    operator_privilege: str = Field(alias="operatorPrivilege")
    session_id: str = Field(alias="sessionId")
    payload: dict
    created_at: str = Field(alias="createdAt")

    model_config = {"populate_by_name": True}


class QualityInspectionAdminDetail(QualityInspectionAdminListItem):
    idempotency_key: str = Field(alias="idempotencyKey")
    returned_quantity: int = Field(alias="returnedQuantity")
    warehoused_quantity: int = Field(alias="warehousedQuantity")
    spec_version: QualitySpecVersion = Field(alias="specVersion")
    check_items: list[QualityCheckItem] = Field(alias="checkItems")
    source_snapshot: dict = Field(alias="sourceSnapshot")
    request_payload: dict = Field(alias="requestPayload")
    operator_privilege: str = Field(alias="operatorPrivilege")
    session_id: str = Field(alias="sessionId")
    events: list[QualityInspectionEvent]


class QualityInspectionAdminListResponse(BaseModel):
    items: list[QualityInspectionAdminListItem]
    total: int
    page: int
    page_size: int = Field(alias="pageSize")
    total_pages: int = Field(alias="totalPages")

    model_config = {"populate_by_name": True}
