from pydantic import AliasChoices, BaseModel, Field

from app.models.material_ids import MaterialIdOptionsResponse


class PartCreationOption(BaseModel):
    code: str
    label: str


class PartVendorOption(BaseModel):
    vendor_id: str = Field(alias="vendorId")
    vendor_number: str = Field(alias="vendorNumber")
    vendor_name: str = Field(alias="vendorName")
    status: str
    selectable: bool

    model_config = {"populate_by_name": True}


class PartVendorSearchResponse(BaseModel):
    items: list[PartVendorOption]
    found_count: int = Field(alias="foundCount")

    model_config = {"populate_by_name": True}


class PartCreationDefaults(BaseModel):
    department_division: str = Field(alias="departmentDivision")
    statistics_category: str = Field(alias="statisticsCategory")
    machining_category: str = Field(alias="machiningCategory")

    model_config = {"populate_by_name": True}


class PartCreationOptionsResponse(BaseModel):
    warehouse_divisions: list[PartCreationOption] = Field(alias="warehouseDivisions")
    material_categories: list[PartCreationOption] = Field(alias="materialCategories")
    machining_categories: list[PartCreationOption] = Field(alias="machiningCategories")
    department_divisions: list[PartCreationOption] = Field(alias="departmentDivisions")
    statistics_categories: list[PartCreationOption] = Field(alias="statisticsCategories")
    use_departments: list[PartCreationOption] = Field(alias="useDepartments")
    lifecycle_statuses: list[PartCreationOption] = Field(alias="lifecycleStatuses")
    part_categories: list[PartCreationOption] = Field(alias="partCategories")
    material_properties: list[PartCreationOption] = Field(alias="materialProperties")
    warehouse_codes: list[PartCreationOption] = Field(alias="warehouseCodes")
    material_sizes: list[PartCreationOption] = Field(alias="materialSizes")
    exclusive_customers: list[PartCreationOption] = Field(alias="exclusiveCustomers")
    generator: MaterialIdOptionsResponse
    defaults: PartCreationDefaults
    asset_uploads_enabled: bool = Field(default=False, alias="assetUploadsEnabled")

    model_config = {"populate_by_name": True}


class PartCreationRequest(BaseModel):
    part_number: str = Field(alias="partNumber", max_length=320)
    internal_name: str = Field(alias="internalName", max_length=2000)
    external_name: str = Field(alias="externalName", max_length=2000)
    inventory_notice: bool = Field(default=False, alias="inventoryNotice")
    warehouse_division: str = Field(alias="warehouseDivision", max_length=80)
    machining_category: str = Field(default="", alias="machiningCategory", max_length=80)
    statistics_category: str = Field(default="", alias="statisticsCategory", max_length=80)
    use_department: str = Field(default="", alias="useDepartment", max_length=120)
    lifecycle_status: str = Field(default="", alias="lifecycleStatus", max_length=80)
    vendor_id: str = Field(default="", alias="vendorId", max_length=80)
    vendor_number: str = Field(default="", alias="vendorNumber", max_length=160)
    vendor_name: str = Field(default="", alias="vendorName", max_length=240)
    material_category: str = Field(alias="materialCategory", max_length=80)
    department_division: str = Field(default="", alias="departmentDivision", max_length=80)
    part_category: str = Field(default="", alias="partCategory", max_length=120)
    material_properties: str = Field(default="", alias="materialProperties", max_length=120)
    material_spec: str = Field(default="", alias="materialSpec", max_length=500)
    warehouse_code: str = Field(default="", alias="warehouseCode", max_length=120)
    location_primary: str = Field(default="", alias="locationPrimary", max_length=160)
    location_secondary: str = Field(default="", alias="locationSecondary", max_length=160)
    weight_grams: str = Field(default="", alias="weightGrams", max_length=80)
    material_size: str = Field(default="", alias="materialSize", max_length=200)
    customer_code: str = Field(
        default="",
        validation_alias=AliasChoices("customerCode", "customerId"),
        serialization_alias="customerCode",
        max_length=120,
    )
    customer_name: str = Field(default="", alias="customerName", max_length=240)
    customer_part_number: str = Field(
        default="",
        alias="customerPartNumber",
        max_length=240,
    )
    photo_name: str = Field(default="", alias="photoName", max_length=240)
    photo_mime_type: str = Field(default="", alias="photoMimeType", max_length=80)
    photo_base64: str = Field(default="", alias="photoBase64")
    photo_upload_id: str = Field(default="", alias="photoUploadId", max_length=80)

    model_config = {"populate_by_name": True}


class PartValidationResponse(BaseModel):
    valid: bool
    errors: dict[str, str]
    warnings: list[str]


class PartCreationResponse(BaseModel):
    ok: bool = True
    record_id: str = Field(alias="recordId")
    part_id: str = Field(alias="partId")
    part_number: str = Field(alias="partNumber")
    photo_uploaded: bool = Field(alias="photoUploaded")
    photo_asset_id: str = Field(default="", alias="photoAssetId")
    warnings: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}
