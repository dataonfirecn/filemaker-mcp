from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class BomCalculationWriteLine(BaseModel):
    part_no: str = Field(alias="partNo", min_length=1, max_length=100)
    original_part_no: str = Field(alias="originalPartNo", min_length=1, max_length=100)
    rated_qty: Decimal = Field(alias="ratedQty", ge=0)
    quantity: Decimal = Field(ge=0)
    product_sku: str = Field(alias="productSku", min_length=1, max_length=100)
    product_qty: Decimal = Field(alias="productQty", gt=0)
    order_item_id: str = Field(alias="orderItemId", min_length=1, max_length=100)
    replacement_reason: str = Field(default="", alias="replacementReason", max_length=200)

    model_config = {"populate_by_name": True}

    @field_validator("rated_qty", "quantity", "product_qty")
    @classmethod
    def validate_finite_number(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("quantity must be finite")
        return value


class CreateBomCalculationRequest(BaseModel):
    request_id: str = Field(
        alias="requestId",
        min_length=8,
        max_length=80,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    lines: list[BomCalculationWriteLine] = Field(min_length=1, max_length=1000)

    model_config = {"populate_by_name": True}


class CreateBomCalculationResponse(BaseModel):
    ok: bool = True
    mode: str = "web-data-api"
    duplicate: bool = False
    request_id: str = Field(alias="requestId")
    order_id: str = Field(alias="orderId")
    bom_calculation_id: str = Field(alias="bomCalculationId")
    header_record_id: str = Field(alias="headerRecordId")
    detail_record_ids: list[str] = Field(default_factory=list, alias="detailRecordIds")
    nonrepeat_record_ids: list[str] = Field(
        default_factory=list,
        alias="nonrepeatRecordIds",
    )
    detail_count: int = Field(alias="detailCount")
    part_count: int = Field(alias="partCount")
    order_linked: bool = Field(alias="orderLinked")

    model_config = {"populate_by_name": True}
