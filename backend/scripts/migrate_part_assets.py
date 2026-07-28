"""Migrate non-barcode @零件 containers to COS and PartAssets.

The source layout is always read-only. The script defaults to a dry run and
requires --commit before it uploads to COS or writes PartAssets.

Barcode/label-generation containers deliberately remain in @零件:

* qrcode_image
* barcode_image
* 發料收料標籤貼紙
* 零件標籤貼紙
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import mimetypes
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote, urlparse

import httpx


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.services.cos_storage import COSStorageError, COSStorageService  # noqa: E402
from app.services.filemaker_client import (  # noqa: E402
    FileMakerAPIError,
    FileMakerClient,
)


SOURCE_LAYOUT = "@零件"
TARGET_LAYOUT = "PartAssets"
MIGRATION_ACTOR = "codex_part_asset_migration"
DEFAULT_BATCH_SIZE = 100
DEFAULT_MAX_FILE_BYTES = 100 * 1024 * 1024

EXCLUDED_BARCODE_FIELDS = frozenset(
    {
        "qrcode_image",
        "barcode_image",
        "發料收料標籤貼紙",
        "零件標籤貼紙",
    }
)


@dataclass(frozen=True)
class AssetSpec:
    source_field: str
    asset_type: str
    asset_role: str
    sort_order: int
    is_primary: int = 0
    visibility: str = "internal"


ASSET_SPECS = (
    AssetSpec("影像 | 容器", "part_image", "primary", 1, 1, "customer"),
    AssetSpec("影像 | 容器2", "part_image", "gallery", 2, 0, "customer"),
    AssetSpec("零件照片3", "part_image", "gallery", 3, 0, "customer"),
    AssetSpec("影像 | 容器3", "part_image", "gallery", 4, 0, "customer"),
    AssetSpec("零件照片4", "part_image", "gallery", 5, 0, "customer"),
    AssetSpec("影像 | 容器4", "part_image", "gallery", 6, 0, "customer"),
    AssetSpec("影像 | 容器5", "part_image", "gallery", 7, 0, "customer"),
    AssetSpec("圖面 | 容器", "drawing_2d", "primary", 1, 1, "customer"),
    AssetSpec("打樣2D | 容器", "drawing_2d", "sample", 10),
    AssetSpec("打樣圖面", "drawing_2d", "sample", 11),
    AssetSpec("打樣圖面 | 容器", "drawing_2d", "sample", 12),
    AssetSpec("外加工圖面", "drawing_2d", "outsourcing", 20),
    AssetSpec("檔案2D", "cad_2d", "source", 1),
    AssetSpec("檔案3D", "cad_3d", "source", 1),
    AssetSpec("雷雕照片", "process_file", "laser_photo", 1),
    AssetSpec("雷雕檔", "process_file", "laser_source", 2),
    AssetSpec("雷雕美工檔", "process_file", "laser_artwork", 3),
    AssetSpec("雷雕製具", "process_file", "laser_fixture", 4),
    AssetSpec("雷雕製具2", "process_file", "laser_fixture", 5),
    AssetSpec("雷雕製具3", "process_file", "laser_fixture", 6),
    AssetSpec("印刷logo", "process_file", "print_logo", 10),
    AssetSpec("印刷車殼", "process_file", "print_body", 11),
    AssetSpec("外紙箱", "package", "outer_carton", 1),
    AssetSpec("彩盒", "package", "color_box", 2),
    AssetSpec("說明書", "document", "manual", 1),
    AssetSpec("貼紙", "document", "sticker_artwork", 2),
)

REQUIRED_SOURCE_FIELDS = {
    "part_id",
    "part_number",
    *(spec.source_field for spec in ASSET_SPECS),
}
REQUIRED_TARGET_FIELDS = {
    "id_asset",
    "part_id_fk",
    "part_number_snapshot",
    "asset_type",
    "asset_role",
    "visibility",
    "legacy_source_field",
    "source_record_id",
    "source_mod_id",
    "original_filename",
    "mime_type",
    "migration_key",
    "migration_status",
    "storage_provider",
    "cos_bucket",
    "cos_region",
    "object_key",
    "etag",
    "sha256",
    "file_size",
    "status",
    "source_kind",
    "created_by",
    "updated_by",
    "sort_order",
    "is_primary",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offset", type=int, default=1)
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum source records to scan; 0 scans every part.",
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--failure-report",
        type=Path,
        help="Write the final JSON summary, including failed asset details, here.",
    )
    args = parser.parse_args()
    if args.offset < 1:
        parser.error("--offset must be at least 1")
    if args.limit < 0:
        parser.error("--limit cannot be negative")
    if not 1 <= args.batch_size <= 500:
        parser.error("--batch-size must be between 1 and 500")
    if not 1 <= args.concurrency <= 8:
        parser.error("--concurrency must be between 1 and 8")
    if args.max_file_bytes < 1:
        parser.error("--max-file-bytes must be positive")
    return args


def _text(value: Any) -> str:
    return str(value or "").strip()


def _container_url(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("url", "data", "value"):
            candidate = _text(value.get(key))
            if candidate:
                return candidate
    return ""


def _migration_key(source_record_id: str, source_field: str) -> str:
    return f"{SOURCE_LAYOUT}:{source_record_id}:{source_field}"


def _asset_id(migration_key: str) -> str:
    return f"legacy_{hashlib.sha256(migration_key.encode()).hexdigest()[:28]}"


def _failure_reason(error: str) -> str:
    normalized = error.lower()
    if "http 401" in normalized:
        return "source_http_401"
    if "http 404" in normalized:
        return "source_http_404"
    if "does not belong to the filemaker host" in normalized:
        return "external_container_host"
    if "over " in normalized or "exceeds " in normalized:
        return "over_size_limit"
    return "other"


def _filename_from_response(url: str, headers: Mapping[str, str]) -> str:
    disposition = headers.get("content-disposition", "")
    utf8_match = re.search(
        r"filename\*=UTF-8''([^;]+)",
        disposition,
        flags=re.IGNORECASE,
    )
    if utf8_match:
        return Path(unquote(utf8_match.group(1))).name
    plain_match = re.search(r'filename="?([^";]+)', disposition, flags=re.IGNORECASE)
    if plain_match:
        return Path(plain_match.group(1).strip()).name
    return Path(unquote(urlparse(url).path)).name or "part-asset.bin"


def _content_type(
    declared: str,
    filename: str,
    content: bytes,
) -> str:
    normalized = declared.split(";", 1)[0].strip().lower()
    if normalized and normalized not in {
        "application/octet-stream",
        "binary/octet-stream",
    }:
        return normalized
    signatures = (
        (b"\xff\xd8\xff", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"GIF87a", "image/gif"),
        (b"GIF89a", "image/gif"),
        (b"%PDF-", "application/pdf"),
        (b"BM", "image/bmp"),
    )
    for signature, mime_type in signatures:
        if content.startswith(signature):
            return mime_type
    if (
        len(content) >= 12
        and content.startswith(b"RIFF")
        and content[8:12] == b"WEBP"
    ):
        return "image/webp"
    guessed, _encoding = mimetypes.guess_type(filename)
    return guessed or normalized or "application/octet-stream"


def _validate_same_filemaker_host(filemaker_host: str, container_url: str) -> None:
    source = urlparse(filemaker_host)
    target = urlparse(container_url)
    if (
        not source.hostname
        or target.hostname != source.hostname
        or target.scheme not in {"http", "https"}
    ):
        raise RuntimeError("Container URL does not belong to the FileMaker host")


async def _validate_layouts(
    client: FileMakerClient,
    *,
    require_target: bool,
) -> None:
    source_fields = {
        item.get("name") for item in await client.get_layout_fields(SOURCE_LAYOUT)
    }
    missing_source = sorted(REQUIRED_SOURCE_FIELDS - source_fields)
    if missing_source:
        raise RuntimeError(f"Source layout is missing fields: {missing_source}")
    container_fields = {
        str(item.get("name") or "")
        for item in await client.get_layout_fields(SOURCE_LAYOUT)
        if str(item.get("result") or "").lower() == "container"
    }
    selected_fields = {spec.source_field for spec in ASSET_SPECS}
    unexpected = sorted(
        container_fields - selected_fields - EXCLUDED_BARCODE_FIELDS
    )
    if unexpected:
        raise RuntimeError(
            "Unclassified container fields found; update ASSET_SPECS or "
            f"EXCLUDED_BARCODE_FIELDS before migration: {unexpected}"
        )
    if not require_target:
        return
    target_fields = {
        item.get("name") for item in await client.get_layout_fields(TARGET_LAYOUT)
    }
    missing_target = sorted(REQUIRED_TARGET_FIELDS - target_fields)
    if missing_target:
        raise RuntimeError(f"Target layout is missing fields: {missing_target}")


async def _source_records(
    client: FileMakerClient,
    *,
    offset: int,
    limit: int,
    batch_size: int,
):
    scanned = 0
    next_offset = offset
    while limit == 0 or scanned < limit:
        requested = batch_size if limit == 0 else min(batch_size, limit - scanned)
        result = await client.find_records(
            SOURCE_LAYOUT,
            limit=requested,
            offset=next_offset,
        )
        rows = result.get("data") or []
        if not rows:
            break
        for row in rows:
            yield row
        scanned += len(rows)
        next_offset += len(rows)
        if len(rows) < requested:
            break


async def _target_index(client: FileMakerClient) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    offset = 1
    while True:
        result = await client.find_records(TARGET_LAYOUT, limit=500, offset=offset)
        rows = result.get("data") or []
        if not rows:
            break
        for row in rows:
            key = _text((row.get("fieldData") or {}).get("migration_key"))
            if key:
                index[key] = row
        offset += len(rows)
        if len(rows) < 500:
            break
    return index


async def _download(
    client: FileMakerClient,
    transfer: httpx.AsyncClient,
    url: str,
    *,
    max_file_bytes: int,
) -> tuple[bytes, str, str]:
    _validate_same_filemaker_host(client.settings.filemaker_host, url)
    response_status: int | None = None
    response_headers: dict[str, str] = {}
    content: bytes | None = None
    last_error: Exception | None = None
    for attempt in range(3):
        token = await client.get_token()
        try:
            async with transfer.stream(
                "GET",
                url,
                headers={"Authorization": f"Bearer {token}"},
            ) as response:
                response_status = response.status_code
                response_headers = dict(response.headers)
                if response.status_code in {408, 429, 500, 502, 503, 504}:
                    pass
                elif not response.is_success:
                    break
                else:
                    try:
                        advertised_size = int(
                            response.headers.get("content-length") or 0
                        )
                    except ValueError:
                        advertised_size = 0
                    if advertised_size > max_file_bytes:
                        raise RuntimeError(
                            f"Container is {advertised_size} bytes, "
                            f"over {max_file_bytes}"
                        )
                    buffer = bytearray()
                    async for chunk in response.aiter_bytes():
                        buffer.extend(chunk)
                        if len(buffer) > max_file_bytes:
                            raise RuntimeError(
                                f"Container exceeds {max_file_bytes} bytes"
                            )
                    content = bytes(buffer)
                    break
        except httpx.RequestError as exc:
            last_error = exc
        if attempt < 2:
            await asyncio.sleep(0.5 * (2**attempt))
    if content is None and response_status is None:
        raise RuntimeError(f"Container download failed: {last_error}")
    if content is None:
        raise RuntimeError(f"Container download failed: HTTP {response_status}")
    filename = _filename_from_response(url, response_headers)
    content_type = _content_type(
        response_headers.get("content-type", ""),
        filename,
        content,
    )
    return content, content_type, filename


async def _copy_asset(
    *,
    client: FileMakerClient,
    storage: COSStorageService,
    transfer: httpx.AsyncClient,
    source_record: dict[str, Any],
    spec: AssetSpec,
    url: str,
    existing: dict[str, Any] | None,
    max_file_bytes: int,
) -> tuple[str, dict[str, Any] | None]:
    source_record_id = _text(source_record.get("recordId"))
    source_mod_id = _text(source_record.get("modId"))
    source_fields = source_record.get("fieldData") or {}
    migration_key = _migration_key(source_record_id, spec.source_field)
    existing_fields = existing.get("fieldData") or {} if existing else {}
    if (
        existing
        and _text(existing_fields.get("migration_status")) == "copied"
        and _text(existing_fields.get("status")) == "READY"
        and _text(existing_fields.get("object_key"))
    ):
        return "skipped_existing", existing

    part_id = _text(source_fields.get("part_id"))
    if not part_id:
        raise RuntimeError("Source part has no part_id")
    content, content_type, filename = await _download(
        client,
        transfer,
        url,
        max_file_bytes=max_file_bytes,
    )
    content_sha256 = hashlib.sha256(content).hexdigest()
    asset_id = _asset_id(migration_key)
    object_key = storage.create_migrated_part_asset_object_key(
        part_id=part_id,
        asset_id=asset_id,
        mime_type=content_type,
        original_filename=filename,
    )
    etag = await asyncio.to_thread(
        storage.put_object,
        object_key=object_key,
        content=content,
        content_type=content_type,
    )
    metadata = await asyncio.to_thread(storage.head_object, object_key)
    if metadata.content_length != len(content):
        raise RuntimeError("COS object size verification failed")

    payload = {
        "id_asset": asset_id,
        "part_id_fk": part_id,
        "part_number_snapshot": _text(source_fields.get("part_number")),
        "asset_type": spec.asset_type,
        "asset_role": spec.asset_role,
        "visibility": spec.visibility,
        "legacy_source_field": spec.source_field,
        "source_record_id": source_record_id,
        "source_mod_id": source_mod_id,
        "original_filename": filename,
        "mime_type": content_type,
        "migration_key": migration_key,
        "migration_status": "copied",
        "storage_provider": "cos",
        "cos_bucket": storage.settings.cos_bucket,
        "cos_region": storage.settings.cos_region,
        "object_key": object_key,
        "etag": etag or metadata.etag,
        "sha256": content_sha256,
        "file_size": len(content),
        "status": "READY",
        "source_kind": "migration",
        "created_by": MIGRATION_ACTOR,
        "updated_by": MIGRATION_ACTOR,
        "sort_order": spec.sort_order,
        "is_primary": spec.is_primary,
    }
    if existing:
        target_record_id = _text(existing.get("recordId"))
        await client.update_record(TARGET_LAYOUT, target_record_id, payload)
    else:
        created = await client.create_record(TARGET_LAYOUT, payload)
        target_record_id = _text(created.get("recordId"))
    if not target_record_id:
        raise RuntimeError("PartAssets did not return a recordId")
    return "copied", {
        "recordId": target_record_id,
        "fieldData": payload,
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    client = FileMakerClient(settings)
    storage = COSStorageService(settings)
    summary: dict[str, Any] = {
        "mode": "commit" if args.commit else "dry-run",
        "sourceLayout": SOURCE_LAYOUT,
        "targetLayout": TARGET_LAYOUT,
        "excludedBarcodeFields": sorted(EXCLUDED_BARCODE_FIELDS),
        "sourcePartsScanned": 0,
        "partsMissingPartId": 0,
        "candidateAssets": 0,
        "candidateByField": {},
        "copied": 0,
        "skippedExisting": 0,
        "failed": 0,
        "failureByReason": {},
        "failureDetails": [],
    }
    try:
        await _validate_layouts(client, require_target=args.commit)
        if args.commit and not storage.configured:
            raise RuntimeError("COS storage is not configured")
        target_index = await _target_index(client) if args.commit else {}
        timeout = httpx.Timeout(
            max(60.0, settings.filemaker_timeout_seconds),
            connect=settings.filemaker_timeout_seconds,
        )
        async with httpx.AsyncClient(
            timeout=timeout,
            verify=settings.filemaker_ssl_verify,
            follow_redirects=True,
        ) as transfer:
            semaphore = asyncio.Semaphore(args.concurrency)
            pending: set[asyncio.Task[None]] = set()

            async def process(
                source_record: dict[str, Any],
                spec: AssetSpec,
                url: str,
            ) -> None:
                key = _migration_key(_text(source_record.get("recordId")), spec.source_field)
                async with semaphore:
                    try:
                        outcome, target = await _copy_asset(
                            client=client,
                            storage=storage,
                            transfer=transfer,
                            source_record=source_record,
                            spec=spec,
                            url=url,
                            existing=target_index.get(key),
                            max_file_bytes=args.max_file_bytes,
                        )
                    except (
                        COSStorageError,
                        FileMakerAPIError,
                        httpx.HTTPError,
                        RuntimeError,
                    ) as exc:
                        error = str(exc)
                        reason = _failure_reason(error)
                        summary["failed"] += 1
                        by_reason = summary["failureByReason"]
                        by_reason[reason] = by_reason.get(reason, 0) + 1
                        source_fields = source_record.get("fieldData") or {}
                        summary["failureDetails"].append(
                            {
                                "recordId": _text(source_record.get("recordId")),
                                "partId": _text(source_fields.get("part_id")),
                                "partNumber": _text(
                                    source_fields.get("part_number")
                                ),
                                "field": spec.source_field,
                                "reason": reason,
                                "error": error,
                            }
                        )
                        print(
                            f"ERROR recordId={_text(source_record.get('recordId'))} "
                            f"field={spec.source_field}: {exc}",
                            file=sys.stderr,
                            flush=True,
                        )
                        return
                    if outcome == "copied":
                        summary["copied"] += 1
                        if target:
                            target_index[key] = target
                    else:
                        summary["skippedExisting"] += 1

            async for record in _source_records(
                client,
                offset=args.offset,
                limit=args.limit,
                batch_size=args.batch_size,
            ):
                summary["sourcePartsScanned"] += 1
                fields = record.get("fieldData") or {}
                if not _text(fields.get("part_id")):
                    summary["partsMissingPartId"] += 1
                for spec in ASSET_SPECS:
                    url = _container_url(fields.get(spec.source_field))
                    if not url:
                        continue
                    summary["candidateAssets"] += 1
                    by_field = summary["candidateByField"]
                    by_field[spec.source_field] = by_field.get(spec.source_field, 0) + 1
                    if args.verbose:
                        print(
                            f"candidate recordId={_text(record.get('recordId'))} "
                            f"field={spec.source_field} type={spec.asset_type}"
                        )
                    if not args.commit:
                        continue
                    pending.add(asyncio.create_task(process(record, spec, url)))
                    if len(pending) >= args.concurrency * 2:
                        _, pending = await asyncio.wait(
                            pending,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                progress_interval = 250 if args.commit else 5000
                if summary["sourcePartsScanned"] % progress_interval == 0:
                    print(
                        "progress "
                        + json.dumps(
                            {
                                "parts": summary["sourcePartsScanned"],
                                "candidates": summary["candidateAssets"],
                                "copied": summary["copied"],
                                "skipped": summary["skippedExisting"],
                                "failed": summary["failed"],
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
            if pending:
                await asyncio.gather(*pending)
        return summary
    finally:
        await client.close()


def main() -> None:
    args = parse_args()
    summary = asyncio.run(run(args))
    if args.failure_report:
        args.failure_report.parent.mkdir(parents=True, exist_ok=True)
        args.failure_report.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["failed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
