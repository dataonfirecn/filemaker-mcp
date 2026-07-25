from typing import Any

from pydantic import BaseModel, Field, SecretStr


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
    customer_id: str = Field(default="", alias="customerId")
    customer_name: str = Field(default="", alias="customerName")
    currency: str = ""
    username: str = ""
    password: SecretStr | None = None

    model_config = {"populate_by_name": True}


class WebViewerSessionResponse(BaseModel):
    token: str
    session_id: str = Field(alias="sessionId")
    context: dict[str, Any]
    read_only: bool = Field(alias="readOnly")
    bom_write_enabled: bool = Field(default=False, alias="bomWriteEnabled")

    model_config = {"populate_by_name": True}
