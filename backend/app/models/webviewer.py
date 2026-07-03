from typing import Any

from pydantic import BaseModel, Field


class MockOperator(BaseModel):
    account: str = "mock.operator"
    name: str = "本地测试操作员"
    privilege: str = "mock"


class WebViewerSessionRequest(BaseModel):
    ctx: str | None = None
    sig: str | None = None
    mock: bool = False
    operator: MockOperator | None = None
    product_sku: str = Field(default="", alias="productSku")
    order_id: str = Field(default="", alias="orderId")
    bom_calc_id: str = Field(default="", alias="bomCalcId")

    model_config = {"populate_by_name": True}


class WebViewerSessionResponse(BaseModel):
    token: str
    session_id: str = Field(alias="sessionId")
    context: dict[str, Any]
    read_only: bool = Field(alias="readOnly")

    model_config = {"populate_by_name": True}
