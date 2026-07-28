import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from app.core.config import Settings


class COSStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class COSPresignedUpload:
    object_key: str
    upload_url: str
    headers: dict[str, str]
    expires_at: datetime


@dataclass(frozen=True)
class COSObjectMetadata:
    content_length: int
    content_type: str
    etag: str


class COSStorageService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: Any | None = None

    @property
    def configured(self) -> bool:
        return self.settings.cos_configured

    def create_object_key(
        self,
        *,
        draft_id: str,
        shipment_id: str,
        attachment_id: str,
        mime_type: str,
        now: datetime | None = None,
    ) -> str:
        timestamp = now or datetime.now(timezone.utc)
        safe_shipment_id = _safe_segment(shipment_id)
        safe_draft_id = _safe_segment(draft_id)
        extension = _extension_for_mime_type(mime_type)
        return str(
            PurePosixPath(
                "starrc",
                "receipts",
                f"{timestamp:%Y}",
                f"{timestamp:%m}",
                safe_shipment_id,
                safe_draft_id,
                f"{attachment_id}.{extension}",
            )
        )

    def create_part_asset_object_key(
        self,
        *,
        draft_id: str,
        upload_id: str,
        mime_type: str,
        original_filename: str = "",
        now: datetime | None = None,
    ) -> str:
        timestamp = now or datetime.now(timezone.utc)
        extension = _asset_extension(mime_type, original_filename)
        return str(
            PurePosixPath(
                "starrc",
                "parts",
                "original",
                f"{timestamp:%Y}",
                f"{timestamp:%m}",
                _safe_segment(draft_id),
                f"{_safe_segment(upload_id)}.{extension}",
            )
        )

    def create_migrated_part_asset_object_key(
        self,
        *,
        part_id: str,
        asset_id: str,
        mime_type: str,
        original_filename: str = "",
    ) -> str:
        extension = _asset_extension(mime_type, original_filename)
        return str(
            PurePosixPath(
                "starrc",
                "parts",
                "original",
                "migration",
                _safe_segment(part_id),
                f"{_safe_segment(asset_id)}.{extension}",
            )
        )

    def create_presigned_upload(
        self,
        *,
        object_key: str,
        content_type: str,
    ) -> COSPresignedUpload:
        client = self._require_client()
        ttl = self.settings.cos_presign_ttl_seconds
        headers = {"Content-Type": content_type}
        try:
            upload_url = client.get_presigned_url(
                Bucket=self.settings.cos_bucket,
                Key=object_key,
                Method="PUT",
                Expired=ttl,
                Headers=headers,
                SignHost=True,
            )
        except Exception as exc:
            raise COSStorageError("Unable to create COS upload URL") from exc
        return COSPresignedUpload(
            object_key=object_key,
            upload_url=upload_url,
            headers=headers,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl),
        )

    def head_object(self, object_key: str) -> COSObjectMetadata:
        client = self._require_client()
        try:
            response = client.head_object(
                Bucket=self.settings.cos_bucket,
                Key=object_key,
            )
        except Exception as exc:
            raise COSStorageError("Uploaded COS object could not be verified") from exc
        return COSObjectMetadata(
            content_length=int(response.get("Content-Length") or 0),
            content_type=str(response.get("Content-Type") or "")
            .split(";", 1)[0]
            .strip()
            .lower(),
            etag=str(response.get("ETag") or "").strip('"'),
        )

    def put_object(
        self,
        *,
        object_key: str,
        content: bytes,
        content_type: str,
    ) -> str:
        client = self._require_client()
        try:
            response = client.put_object(
                Bucket=self.settings.cos_bucket,
                Key=object_key,
                Body=content,
                ContentType=content_type,
            )
        except Exception as exc:
            raise COSStorageError("Unable to upload COS object") from exc
        return str(response.get("ETag") or "").strip('"')

    def create_presigned_download(self, object_key: str) -> tuple[str, datetime]:
        client = self._require_client()
        ttl = self.settings.cos_presign_ttl_seconds
        try:
            url = client.get_presigned_url(
                Bucket=self.settings.cos_bucket,
                Key=object_key,
                Method="GET",
                Expired=ttl,
                SignHost=True,
            )
        except Exception as exc:
            raise COSStorageError("Unable to create COS download URL") from exc
        return url, datetime.now(timezone.utc) + timedelta(seconds=ttl)

    def _require_client(self):
        if not self.configured:
            raise COSStorageError("COS storage is not configured")
        if self._client is None:
            try:
                from qcloud_cos import CosConfig, CosS3Client
            except ImportError as exc:
                raise COSStorageError("Tencent COS SDK is not installed") from exc

            config = CosConfig(
                Region=self.settings.cos_region,
                SecretId=self.settings.cos_secret_id,
                SecretKey=self.settings.cos_secret_key,
                Scheme="https",
            )
            self._client = CosS3Client(config)
        return self._client


def new_attachment_id() -> str:
    return f"att_{uuid.uuid4().hex}"


def _safe_segment(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    while ".." in normalized:
        normalized = normalized.replace("..", "-")
    normalized = normalized.strip(".-")
    return normalized[:120] or uuid.uuid4().hex


def _extension_for_mime_type(mime_type: str) -> str:
    return {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/heic": "heic",
        "image/heif": "heif",
    }.get(mime_type.lower(), "bin")


def _asset_extension(mime_type: str, original_filename: str) -> str:
    known = {
        "application/pdf": "pdf",
        "image/bmp": "bmp",
        "image/gif": "gif",
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/heic": "heic",
        "image/heif": "heif",
    }.get(mime_type.lower())
    if known:
        return known
    suffix = Path(original_filename).suffix.lower().lstrip(".")
    safe_suffix = re.sub(r"[^a-z0-9]+", "", suffix)
    return safe_suffix[:12] or "bin"
