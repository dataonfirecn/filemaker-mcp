from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


AttachmentSource = Literal["camera", "photo_library"]
AttachmentStatus = Literal["PENDING", "UPLOADED", "BOUND", "FAILED", "ORPHAN"]


class AttachmentPresignRequest(BaseModel):
    shipment_id: str = Field(alias="shipmentId", min_length=1, max_length=160)
    pi_number: str = Field(alias="piNumber", min_length=1, max_length=160)
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(alias="mimeType", min_length=1, max_length=100)
    file_size: int = Field(alias="fileSize", gt=0)
    sha256: str = Field(min_length=64, max_length=64)
    source: AttachmentSource
    line_id: str | None = Field(default=None, alias="lineId", max_length=160)

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


class AttachmentPresignResponse(BaseModel):
    attachment_id: str = Field(alias="attachmentId")
    object_key: str = Field(alias="objectKey")
    upload_url: str = Field(alias="uploadUrl")
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str]
    expires_at: datetime = Field(alias="expiresAt")

    model_config = {"populate_by_name": True}


class AttachmentCompleteRequest(BaseModel):
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


class AttachmentResponse(BaseModel):
    attachment_id: str = Field(alias="attachmentId")
    draft_id: str = Field(alias="draftId")
    shipment_id: str = Field(alias="shipmentId")
    pi_number: str = Field(alias="piNumber")
    line_id: str | None = Field(default=None, alias="lineId")
    object_key: str = Field(alias="objectKey")
    mime_type: str = Field(alias="mimeType")
    file_size: int = Field(alias="fileSize")
    sha256: str
    etag: str | None = None
    source: AttachmentSource
    status: AttachmentStatus
    created_at: datetime = Field(alias="createdAt")
    uploaded_at: datetime | None = Field(default=None, alias="uploadedAt")

    model_config = {"populate_by_name": True}


class AttachmentDownloadResponse(BaseModel):
    download_url: str = Field(alias="downloadUrl")
    expires_at: datetime = Field(alias="expiresAt")

    model_config = {"populate_by_name": True}
