"""Copy migrated ProductAssets images from FileMaker containers to Tencent COS.

The API never calls this script. It is an offline, idempotent migration tool:

* ProductAssets and @products remain read-only.
* Existing COS objects are skipped before FileMaker container data is requested.
* Dry-run is the default; writes require ``--commit``.

Examples:

    PYTHONPATH=backend .venv/bin/python \
      backend/scripts/migrate_product_assets_to_cos.py \
      --product-sku PTK-4528 --product-sku PTK-4562

    PYTHONPATH=backend .venv/bin/python \
      backend/scripts/migrate_product_assets_to_cos.py \
      --product-sku PTK-4528 --commit
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.services.cos_storage import COSStorageError, COSStorageService  # noqa: E402
from app.services.filemaker_client import FileMakerAPIError, FileMakerClient  # noqa: E402


PRODUCT_ASSET_LAYOUT = "ProductAssets"
DEFAULT_BATCH_SIZE = 100
DEFAULT_MAX_FILE_BYTES = 100 * 1024 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--product-sku",
        action="append",
        default=[],
        help="Migrate one product SKU; repeat for multiple products.",
    )
    parser.add_argument(
        "--primary-only",
        action="store_true",
        help="Only migrate each product's primary image.",
    )
    parser.add_argument("--offset", type=int, default=1)
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum matching assets; use 0 for all (default: 100).",
    )
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if args.offset < 1:
        parser.error("--offset must be at least 1")
    if args.limit < 0:
        parser.error("--limit cannot be negative")
    if args.batch_size < 1 or args.batch_size > 500:
        parser.error("--batch-size must be between 1 and 500")
    if args.concurrency < 1 or args.concurrency > 8:
        parser.error("--concurrency must be between 1 and 8")
    if args.max_file_bytes < 1:
        parser.error("--max-file-bytes must be positive")
    return args


def _text(value: Any) -> str:
    return str(value or "").strip()


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).casefold() in {"1", "true", "yes", "y", "是"}


def _container_url(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("url", "data", "value"):
            candidate = _text(value.get(key))
            if candidate:
                return candidate
    return ""


async def _asset_records(
    client: FileMakerClient,
    args: argparse.Namespace,
):
    product_skus = list(
        dict.fromkeys(_text(item) for item in args.product_sku if _text(item))
    )
    asset_types = (
        ("product_image",)
        if args.primary_only
        else ("product_image", "packaging_reference")
    )

    offset = args.offset
    returned_total = 0
    while args.limit == 0 or returned_total < args.limit:
        requested = (
            args.batch_size
            if args.limit == 0
            else min(args.batch_size, args.limit - returned_total)
        )
        query: list[dict[str, str]]
        if product_skus:
            query = [
                {
                    "asset_type": f"=={asset_type}",
                    "migration_status": "==copied",
                    **({"is_primary": "==1"} if args.primary_only else {}),
                    "product_sku_fk": f"=={sku}",
                }
                for sku in product_skus
                for asset_type in asset_types
            ]
        else:
            query = [
                {
                    "asset_type": f"=={asset_type}",
                    "migration_status": "==copied",
                    **({"is_primary": "==1"} if args.primary_only else {}),
                }
                for asset_type in asset_types
            ]
        result = await client.find_records(
            PRODUCT_ASSET_LAYOUT,
            query=query,
            limit=requested,
            offset=offset,
            sort=[
                {"fieldName": "product_sku_fk", "sortOrder": "ascend"},
                {"fieldName": "sort_order", "sortOrder": "ascend"},
            ],
        )
        rows = result.get("data") or []
        if not rows:
            break
        for record in rows:
            yield record
        returned_total += len(rows)
        offset += len(rows)
        if len(rows) < requested:
            break


async def _download_filemaker_container(
    client: FileMakerClient,
    transfer_client: httpx.AsyncClient,
    container_url: str,
    *,
    max_file_bytes: int,
) -> bytes:
    source_host = urlparse(client.settings.filemaker_host).hostname
    target = urlparse(container_url)
    if (
        not source_host
        or target.hostname != source_host
        or target.scheme not in {"http", "https"}
    ):
        raise RuntimeError("Container URL does not belong to the configured FileMaker host")
    token = await client.get_token()
    async with transfer_client.stream(
        "GET",
        container_url,
        headers={"Authorization": f"Bearer {token}"},
    ) as response:
        if not response.is_success:
            raise RuntimeError(
                f"FileMaker container download failed with HTTP {response.status_code}"
            )
        content_length = int(response.headers.get("content-length") or 0)
        if content_length > max_file_bytes:
            raise RuntimeError(
                f"Container is {content_length} bytes, over the safety limit"
            )
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > max_file_bytes:
                raise RuntimeError(
                    f"Container exceeded the {max_file_bytes}-byte safety limit"
                )
            chunks.append(chunk)
    return b"".join(chunks)


async def run(args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    storage = COSStorageService(settings)
    if not storage.configured:
        raise RuntimeError("Tencent COS is not configured")

    client = FileMakerClient(settings)
    summary = {
        "mode": "commit" if args.commit else "dry-run",
        "assetsScanned": 0,
        "candidates": 0,
        "copied": 0,
        "skippedExisting": 0,
        "failed": 0,
    }
    semaphore = asyncio.Semaphore(args.concurrency)
    pending: set[asyncio.Task[None]] = set()
    timeout = httpx.Timeout(
        max(60.0, settings.filemaker_timeout_seconds),
        connect=settings.filemaker_timeout_seconds,
    )

    async with httpx.AsyncClient(
        timeout=timeout,
        verify=settings.filemaker_ssl_verify,
        follow_redirects=True,
    ) as transfer_client:

        async def migrate(record: dict[str, Any]) -> None:
            fields = record.get("fieldData") or {}
            source_record_id = _text(fields.get("source_record_id"))
            asset_id = _text(fields.get("id_asset"))
            filename = _text(fields.get("original_filename"))
            mime_type = _text(fields.get("mime_type")) or "image/jpeg"
            container_url = _container_url(fields.get("asset_file"))
            object_key = storage.create_migrated_product_asset_object_key(
                source_record_id=source_record_id,
                asset_id=asset_id,
                mime_type=mime_type,
                original_filename=filename,
            )
            async with semaphore:
                try:
                    try:
                        await asyncio.to_thread(storage.head_object, object_key)
                    except COSStorageError:
                        pass
                    else:
                        summary["skippedExisting"] += 1
                        return

                    content = await _download_filemaker_container(
                        client,
                        transfer_client,
                        container_url,
                        max_file_bytes=args.max_file_bytes,
                    )
                    await asyncio.to_thread(
                        storage.put_object,
                        object_key=object_key,
                        content=content,
                        content_type=mime_type,
                    )
                    metadata = await asyncio.to_thread(storage.head_object, object_key)
                    if metadata.content_length != len(content):
                        raise RuntimeError("COS size verification failed")
                    summary["copied"] += 1
                    if args.verbose:
                        print(
                            f"copied sku={_text(fields.get('product_sku_fk'))} "
                            f"asset={asset_id} bytes={len(content)} key={object_key}",
                            flush=True,
                        )
                except (COSStorageError, FileMakerAPIError, httpx.HTTPError, RuntimeError) as exc:
                    summary["failed"] += 1
                    print(
                        f"ERROR sku={_text(fields.get('product_sku_fk'))} "
                        f"asset={asset_id}: {exc}",
                        file=sys.stderr,
                        flush=True,
                    )

        try:
            async for record in _asset_records(client, args):
                summary["assetsScanned"] += 1
                fields = record.get("fieldData") or {}
                if (
                    not _text(fields.get("source_record_id"))
                    or not _text(fields.get("id_asset"))
                    or not _container_url(fields.get("asset_file"))
                ):
                    continue
                if args.primary_only and not _truthy(fields.get("is_primary")):
                    continue
                summary["candidates"] += 1
                if args.commit:
                    pending.add(asyncio.create_task(migrate(record)))
                    if len(pending) >= args.concurrency * 2:
                        _, pending = await asyncio.wait(
                            pending,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                    if summary["assetsScanned"] % 250 == 0:
                        print(
                            "progress "
                            + json.dumps(
                                {
                                    "assets": summary["assetsScanned"],
                                    "candidates": summary["candidates"],
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
        finally:
            await client.close()
    return summary


def main() -> None:
    args = parse_args()
    summary = asyncio.run(run(args))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["failed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
