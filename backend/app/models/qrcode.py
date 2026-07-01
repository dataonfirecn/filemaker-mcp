from typing import Literal

from pydantic import BaseModel, Field


class QRCodeGenerateRequest(BaseModel):
    data: str | None = None
    token: str | None = None
    format: Literal["png", "svg"] = "png"
    box_size: int = Field(default=10, ge=2, le=40, alias="boxSize")
    border: int = Field(default=4, ge=0, le=10)
    fill_color: str = Field(default="black", alias="fillColor")
    back_color: str = Field(default="white", alias="backColor")

    model_config = {"populate_by_name": True}
