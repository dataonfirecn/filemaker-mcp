from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ProductPhotoPresignRequest(BaseModel):
    session_id: str = Field(
        alias="sessionId",
        min_length=8,
        max_length=80,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(alias="mimeType", min_length=1, max_length=100)
    file_size: int = Field(alias="fileSize", gt=0)
    sha256: str = Field(min_length=64, max_length=64)
    source: Literal["camera"] = "camera"

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


class ProductPhotoPresignResponse(BaseModel):
    upload_id: str = Field(alias="uploadId")
    object_key: str = Field(alias="objectKey")
    slot: int
    upload_url: str = Field(alias="uploadUrl")
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str]
    expires_at: datetime = Field(alias="expiresAt")

    model_config = {"populate_by_name": True}


class ProductPhotoCompleteRequest(BaseModel):
    etag: str = Field(min_length=1, max_length=255)
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


class ProductPhotoUploadResponse(BaseModel):
    upload_id: str = Field(alias="uploadId")
    product_sku: str = Field(alias="productSku")
    object_key: str = Field(alias="objectKey")
    slot: int
    status: str
    asset_record_id: str | None = Field(default=None, alias="assetRecordId")
    last_error: str | None = Field(default=None, alias="lastError")
    created_at: datetime = Field(alias="createdAt")
    uploaded_at: datetime | None = Field(default=None, alias="uploadedAt")
    synced_at: datetime | None = Field(default=None, alias="syncedAt")

    model_config = {"populate_by_name": True}
