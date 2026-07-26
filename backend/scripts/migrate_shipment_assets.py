"""Copy legacy shipment containers into the standalone ShipmentAssets table.

Safety boundary:

* ``@出貨單`` is a read-only source.
* Every create/update/container upload targets ``ShipmentAssets``.
* The default mode is a dry run. Writes require ``--commit``.

Examples:

    .venv/bin/python backend/scripts/migrate_shipment_assets.py --limit 100
    .venv/bin/python backend/scripts/migrate_shipment_assets.py --limit 0 --commit
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

import httpx


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.services.filemaker_client import (  # noqa: E402
    FileMakerAPIError,
    FileMakerClient,
)


SOURCE_LAYOUT = "@出貨單"
TARGET_LAYOUT = "ShipmentAssets"
TARGET_CONTAINER_FIELD = "asset_file"
MIGRATION_ACTOR = "codex_shipment_asset_migration"
DEFAULT_BATCH_SIZE = 500
DEFAULT_MAX_FILE_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True)
class AssetSpec:
    source_field: str
    sort_order: int
    is_primary: int
    asset_type: str = "shipment_attachment"
    visibility: str = "internal"


ASSET_SPECS = tuple(
    AssetSpec(
        source_field=f"相關文件{position}",
        sort_order=position,
        is_primary=1 if position == 1 else 0,
    )
    for position in range(1, 10)
)

REQUIRED_SOURCE_FIELDS = {
    "id",
    "內部訂單單據編號",
    "customer_id",
    *(spec.source_field for spec in ASSET_SPECS),
}

REQUIRED_TARGET_FIELDS = {
    "id_asset",
    "shipment_id_fk",
    "internal_order_no_snapshot",
    "customer_id_snapshot",
    "asset_type",
    "visibility",
    "legacy_source_field",
    "source_record_id",
    "source_mod_id",
    "original_filename",
    "mime_type",
    "migration_key",
    "migration_status",
    "created_by",
    "updated_by",
    "sort_order",
    "is_primary",
    "file_size",
    TARGET_CONTAINER_FIELD,
    "created_at",
    "updated_at",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offset",
        type=int,
        default=1,
        help="One-based source record offset (default: 1).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum source shipments to scan; use 0 for every shipment (default: 100).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Data API page size (default: {DEFAULT_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--max-file-bytes",
        type=int,
        default=DEFAULT_MAX_FILE_BYTES,
        help="Reject a single file larger than this many bytes.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="Maximum concurrent target copies in commit mode (default: 2).",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Write records and containers to ShipmentAssets. Without this flag the run is read-only.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print one line for every candidate asset.",
    )
    args = parser.parse_args()
    if args.offset < 1:
        parser.error("--offset must be at least 1")
    if args.limit < 0:
        parser.error("--limit cannot be negative")
    if args.batch_size < 1 or args.batch_size > 500:
        parser.error("--batch-size must be between 1 and 500")
    if args.max_file_bytes < 1:
        parser.error("--max-file-bytes must be positive")
    if args.concurrency < 1 or args.concurrency > 8:
        parser.error("--concurrency must be between 1 and 8")
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


def _filename_from_response(url: str, response: httpx.Response) -> str:
    disposition = response.headers.get("content-disposition", "")
    utf8_match = re.search(r"filename\*=UTF-8''([^;]+)", disposition, flags=re.IGNORECASE)
    if utf8_match:
        return Path(unquote(utf8_match.group(1))).name
    plain_match = re.search(r'filename="?([^";]+)', disposition, flags=re.IGNORECASE)
    if plain_match:
        return Path(plain_match.group(1).strip()).name
    filename = Path(unquote(urlparse(url).path)).name
    return filename or "shipment-attachment.bin"


def _validate_same_filemaker_host(filemaker_host: str, container_url: str) -> None:
    source = urlparse(filemaker_host)
    target = urlparse(container_url)
    if not source.hostname or target.hostname != source.hostname:
        raise RuntimeError("Container URL does not belong to the configured FileMaker host")
    if target.scheme not in {"http", "https"}:
        raise RuntimeError("Container URL must use HTTP or HTTPS")


def _data_api_base_url(settings: Any) -> str:
    host = settings.filemaker_host.rstrip("/")
    database = quote(settings.filemaker_database, safe="")
    return f"{host}/fmi/data/{settings.filemaker_api_version}/databases/{database}"


async def _validate_layouts(client: FileMakerClient) -> None:
    source_fields = {item.get("name") for item in await client.get_layout_fields(SOURCE_LAYOUT)}
    missing_source = sorted(REQUIRED_SOURCE_FIELDS - source_fields)
    if missing_source:
        raise RuntimeError(f"Source layout is missing required fields: {missing_source}")

    target_fields = {item.get("name") for item in await client.get_layout_fields(TARGET_LAYOUT)}
    missing_target = sorted(REQUIRED_TARGET_FIELDS - target_fields)
    if missing_target:
        raise RuntimeError(f"Target layout is missing required fields: {missing_target}")


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
        returned = len(rows)
        scanned += returned
        next_offset += returned
        if returned < requested:
            break


async def _target_record_index(client: FileMakerClient) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    offset = 1
    while True:
        try:
            result = await client.find_records(TARGET_LAYOUT, limit=500, offset=offset)
        except FileMakerAPIError as exc:
            payload = exc.payload if isinstance(exc.payload, dict) else {}
            messages = payload.get("messages") or []
            codes = {
                _text(message.get("code"))
                for message in messages
                if isinstance(message, dict)
            }
            if codes == {"101"}:
                break
            raise
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


async def _download_container(
    client: FileMakerClient,
    transfer_client: httpx.AsyncClient,
    url: str,
    *,
    max_file_bytes: int,
) -> tuple[bytes, str, str]:
    _validate_same_filemaker_host(client.settings.filemaker_host, url)
    token = await client.get_token()
    response = await transfer_client.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
    )
    if not response.is_success:
        raise RuntimeError(f"Container download failed with HTTP {response.status_code}")
    if len(response.content) > max_file_bytes:
        raise RuntimeError(
            f"Container is {len(response.content)} bytes, over the {max_file_bytes}-byte limit"
        )
    content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
    filename = _filename_from_response(url, response)
    return response.content, content_type, filename


async def _upload_target_container(
    client: FileMakerClient,
    transfer_client: httpx.AsyncClient,
    *,
    target_record_id: str,
    content: bytes,
    filename: str,
    content_type: str,
) -> None:
    if TARGET_LAYOUT.casefold() == SOURCE_LAYOUT.casefold():
        raise RuntimeError("Safety guard rejected a write to the source layout")
    token = await client.get_token()
    layout = quote(TARGET_LAYOUT, safe="")
    field = quote(TARGET_CONTAINER_FIELD, safe="")
    record_id = quote(target_record_id, safe="")
    url = (
        f"{_data_api_base_url(client.settings)}/layouts/{layout}/records/{record_id}"
        f"/containers/{field}/1"
    )
    response = await transfer_client.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        files={"upload": (filename, content, content_type)},
    )
    if not response.is_success:
        raise RuntimeError(f"Container upload failed with HTTP {response.status_code}")


async def _copy_asset(
    client: FileMakerClient,
    transfer_client: httpx.AsyncClient,
    *,
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
        and _container_url(existing_fields.get(TARGET_CONTAINER_FIELD))
    ):
        return "skipped_existing", existing

    content, content_type, filename = await _download_container(
        client,
        transfer_client,
        url,
        max_file_bytes=max_file_bytes,
    )
    target_data = {
        "shipment_id_fk": _text(source_fields.get("id")),
        "internal_order_no_snapshot": _text(source_fields.get("內部訂單單據編號")),
        "customer_id_snapshot": _text(source_fields.get("customer_id")),
        "asset_type": spec.asset_type,
        "visibility": spec.visibility,
        "legacy_source_field": spec.source_field,
        "source_record_id": source_record_id,
        "source_mod_id": source_mod_id,
        "original_filename": filename,
        "mime_type": content_type,
        "migration_key": migration_key,
        "migration_status": "uploading",
        "created_by": MIGRATION_ACTOR,
        "updated_by": MIGRATION_ACTOR,
        "sort_order": spec.sort_order,
        "is_primary": spec.is_primary,
        "file_size": len(content),
    }

    if existing:
        target_record_id = _text(existing.get("recordId"))
        await client.update_record(TARGET_LAYOUT, target_record_id, target_data)
    else:
        created = await client.create_record(TARGET_LAYOUT, target_data)
        target_record_id = _text(created.get("recordId"))
    if not target_record_id:
        raise RuntimeError("Target record creation did not return a recordId")

    try:
        await _upload_target_container(
            client,
            transfer_client,
            target_record_id=target_record_id,
            content=content,
            filename=filename,
            content_type=content_type,
        )
    except Exception:
        await client.update_record(
            TARGET_LAYOUT,
            target_record_id,
            {"migration_status": "upload_failed", "updated_by": MIGRATION_ACTOR},
        )
        raise
    await client.update_record(
        TARGET_LAYOUT,
        target_record_id,
        {"migration_status": "copied", "updated_by": MIGRATION_ACTOR},
    )
    return "copied", {
        "recordId": target_record_id,
        "fieldData": {
            **target_data,
            TARGET_CONTAINER_FIELD: "uploaded",
            "migration_status": "copied",
        },
    }


async def _verify_source_mod_ids(
    client: FileMakerClient,
    snapshots: dict[str, str],
) -> int:
    mismatches = 0
    for record_id, expected_mod_id in snapshots.items():
        rows = await client.get_record(SOURCE_LAYOUT, record_id)
        current = rows[0] if isinstance(rows, list) and rows else {}
        if _text(current.get("modId")) != expected_mod_id:
            mismatches += 1
    return mismatches


async def run(args: argparse.Namespace) -> dict[str, Any]:
    if TARGET_LAYOUT.casefold() == SOURCE_LAYOUT.casefold():
        raise RuntimeError("Source and target layouts must be different")

    client = FileMakerClient(get_settings())
    summary = {
        "mode": "commit" if args.commit else "dry-run",
        "sourceLayout": SOURCE_LAYOUT,
        "targetLayout": TARGET_LAYOUT,
        "sourceShipmentsScanned": 0,
        "candidateAssets": 0,
        "copied": 0,
        "skippedExisting": 0,
        "failed": 0,
        "sourceModIdMismatches": 0,
    }
    source_snapshots: dict[str, str] = {}
    try:
        await _validate_layouts(client)
        target_index = await _target_record_index(client) if args.commit else {}
        transfer_timeout = httpx.Timeout(
            max(60.0, client.settings.filemaker_timeout_seconds),
            connect=client.settings.filemaker_timeout_seconds,
        )
        async with httpx.AsyncClient(
            timeout=transfer_timeout,
            verify=client.settings.filemaker_ssl_verify,
            follow_redirects=True,
        ) as transfer_client:
            semaphore = asyncio.Semaphore(args.concurrency)
            pending: set[asyncio.Task[None]] = set()

            async def process_candidate(
                source_record: dict[str, Any],
                asset_spec: AssetSpec,
                container_url: str,
            ) -> None:
                migration_key = _migration_key(
                    _text(source_record.get("recordId")),
                    asset_spec.source_field,
                )
                async with semaphore:
                    try:
                        outcome, target_record = await _copy_asset(
                            client,
                            transfer_client,
                            source_record=source_record,
                            spec=asset_spec,
                            url=container_url,
                            existing=target_index.get(migration_key),
                            max_file_bytes=args.max_file_bytes,
                        )
                    except (FileMakerAPIError, httpx.HTTPError, RuntimeError) as exc:
                        summary["failed"] += 1
                        print(
                            f"ERROR recordId={_text(source_record.get('recordId'))} "
                            f"field={asset_spec.source_field}: {exc}",
                            file=sys.stderr,
                            flush=True,
                        )
                        return
                    if outcome == "copied":
                        summary["copied"] += 1
                        if target_record:
                            target_index[migration_key] = target_record
                    elif outcome == "skipped_existing":
                        summary["skippedExisting"] += 1

            async for record in _source_records(
                client,
                offset=args.offset,
                limit=args.limit,
                batch_size=args.batch_size,
            ):
                summary["sourceShipmentsScanned"] += 1
                fields = record.get("fieldData") or {}
                for spec in ASSET_SPECS:
                    url = _container_url(fields.get(spec.source_field))
                    if not url:
                        continue
                    source_record_id = _text(record.get("recordId"))
                    source_snapshots[source_record_id] = _text(record.get("modId"))
                    summary["candidateAssets"] += 1
                    if args.verbose:
                        print(
                            f"candidate recordId={source_record_id} "
                            f"field={spec.source_field} order={spec.sort_order}"
                        )
                    if not args.commit:
                        continue
                    pending.add(asyncio.create_task(process_candidate(record, spec, url)))
                    if len(pending) >= args.concurrency * 2:
                        _, pending = await asyncio.wait(
                            pending,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
            if pending:
                await asyncio.gather(*pending)
        if args.commit:
            summary["sourceModIdMismatches"] = await _verify_source_mod_ids(
                client,
                source_snapshots,
            )
        return summary
    finally:
        await client.close()


def main() -> None:
    args = parse_args()
    summary = asyncio.run(run(args))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["failed"] or summary["sourceModIdMismatches"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
