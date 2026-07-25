from pydantic import BaseModel, Field


class MaterialIdGenerationRequest(BaseModel):
    material: str = Field(default="", max_length=80)
    customer: str = Field(default="", max_length=80)
    serial: str = Field(default="", max_length=20)
    manufacture: str = Field(default="", max_length=80)
    color: str = Field(default="", max_length=80)
    other: str = Field(default="", max_length=120)
    script_part_number: str = Field(
        default="",
        alias="scriptPartNumber",
        max_length=320,
    )

    model_config = {"populate_by_name": True}


class MaterialIdGenerationResponse(BaseModel):
    part_number: str = Field(alias="partNumber")
    serial: str
    prefix: str
    auto_serial: bool = Field(alias="autoSerial")
    exists: bool
    script_part_number: str = Field(alias="scriptPartNumber")
    matches_script: bool | None = Field(alias="matchesScript")
    scanned_count: int = Field(alias="scannedCount")
    algorithm_version: str = Field(alias="algorithmVersion")
    explanation: list[str]

    model_config = {"populate_by_name": True}


class MaterialIdOption(BaseModel):
    code: str
    label: str


class MaterialIdOptionsResponse(BaseModel):
    materials: list[MaterialIdOption]
    customers: list[MaterialIdOption]
    manufactures: list[MaterialIdOption]
    colors: list[MaterialIdOption]
    others: list[MaterialIdOption]

    model_config = {"populate_by_name": True}


class RelatedPartOption(BaseModel):
    part_number: str = Field(alias="partNumber")
    internal_name: str = Field(alias="internalName")
    external_name: str = Field(alias="externalName")

    model_config = {"populate_by_name": True}


class RelatedPartSearchResponse(BaseModel):
    items: list[RelatedPartOption]
    found_count: int = Field(alias="foundCount")

    model_config = {"populate_by_name": True}
