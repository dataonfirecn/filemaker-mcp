from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


PartAssetSource = Literal["file_picker", "camera", "migration", "ai"]
PartAssetVisibility = Literal["internal", "customer", "vendor"]
PartAssetUploadStatus = Literal["PENDING", "UPLOADED", "BOUND", "FAILED", "ORPHAN"]


class PartAssetPresignRequest(BaseModel):
    draft_id: str = Field(alias="draftId", min_length=8, max_length=120)
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(alias="mimeType", min_length=1, max_length=120)
    file_size: int = Field(alias="fileSize", gt=0)
    sha256: str = Field(min_length=64, max_length=64)
    asset_type: str = Field(default="part_image", alias="assetType", min_length=1, max_length=80)
    asset_role: str = Field(default="primary", alias="assetRole", min_length=1, max_length=80)
    visibility: PartAssetVisibility = "customer"
    source: PartAssetSource = "file_picker"

    model_config = {"populate_by_name": True}

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        normalized = value.strip().lower()
        if any(character not in "0123456789abcdef" for character in normalized):
            raise ValueError("sha256 must be a 64-character hexadecimal digest")
        return normalized

    @field_validator("mime_type")
    @classmethod
    def normalize_mime_type(cls, value: str) -> str:
        return value.strip().lower()


class PartAssetPresignResponse(BaseModel):
    upload_id: str = Field(alias="uploadId")
    object_key: str = Field(alias="objectKey")
    upload_url: str = Field(alias="uploadUrl")
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str]
    expires_at: datetime = Field(alias="expiresAt")

    model_config = {"populate_by_name": True}


class PartAssetCompleteRequest(BaseModel):
    etag: str = Field(default="", max_length=255)
    file_size: int = Field(alias="fileSize", gt=0)
    sha256: str = Field(min_length=64, max_length=64)

    model_config = {"populate_by_name": True}

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        normalized = value.strip().lower()
        if any(character not in "0123456789abcdef" for character in normalized):
            raise ValueError("sha256 must be a 64-character hexadecimal digest")
        return normalized


class PartAssetBindRequest(BaseModel):
    part_id: str = Field(alias="partId", min_length=1, max_length=320)
    part_number: str = Field(alias="partNumber", min_length=1, max_length=320)
    part_record_id: str = Field(alias="partRecordId", min_length=1, max_length=80)

    model_config = {"populate_by_name": True}


class PartAssetResponse(BaseModel):
    upload_id: str = Field(alias="uploadId")
    asset_id: str = Field(default="", alias="assetId")
    asset_record_id: str = Field(default="", alias="assetRecordId")
    object_key: str = Field(alias="objectKey")
    filename: str
    mime_type: str = Field(alias="mimeType")
    file_size: int = Field(alias="fileSize")
    sha256: str
    asset_type: str = Field(alias="assetType")
    asset_role: str = Field(alias="assetRole")
    visibility: PartAssetVisibility
    status: PartAssetUploadStatus
    public_url: str = Field(default="", alias="publicUrl")
    created_at: datetime = Field(alias="createdAt")
    uploaded_at: datetime | None = Field(default=None, alias="uploadedAt")

    model_config = {"populate_by_name": True}
