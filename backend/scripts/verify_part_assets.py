"""Verify migrated PartAssets records against private COS objects.

The verifier checks the FileMaker record count, then samples records evenly
across the layout. Every sampled object is checked with COS HEAD and downloaded
through a short-lived signed URL so its size and SHA-256 can be compared with
the PartAssets metadata.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import httpx


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.services.cos_storage import COSStorageService  # noqa: E402
from app.services.filemaker_client import FileMakerClient  # noqa: E402


TARGET_LAYOUT = "PartAssets"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=12)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")
    return args


def _text(value: Any) -> str:
    return str(value or "").strip()


def _sample_offsets(found_count: int, sample_count: int) -> list[int]:
    count = min(found_count, sample_count)
    if count < 1:
        return []
    if count == 1:
        return [1]
    return sorted(
        {
            1 + round(index * (found_count - 1) / (count - 1))
            for index in range(count)
        }
    )


async def run(sample_count: int) -> dict[str, Any]:
    settings = get_settings()
    filemaker = FileMakerClient(settings)
    storage = COSStorageService(settings)
    if not storage.configured:
        raise RuntimeError("COS storage is not configured")

    summary: dict[str, Any] = {
        "layout": TARGET_LAYOUT,
        "foundCount": 0,
        "sampled": 0,
        "verified": 0,
        "samples": [],
    }
    try:
        first_page = await filemaker.find_records(TARGET_LAYOUT, limit=1)
        found_count = int(first_page.get("foundCount") or 0)
        summary["foundCount"] = found_count
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(180.0, connect=30.0),
            follow_redirects=True,
        ) as transfer:
            for offset in _sample_offsets(found_count, sample_count):
                result = await filemaker.find_records(
                    TARGET_LAYOUT,
                    limit=1,
                    offset=offset,
                )
                rows = result.get("data") or []
                if not rows:
                    raise RuntimeError(
                        f"PartAssets record missing at offset {offset}"
                    )
                row = rows[0]
                fields = row.get("fieldData") or {}
                object_key = _text(fields.get("object_key"))
                expected_size = int(float(fields.get("file_size") or 0))
                expected_sha256 = _text(fields.get("sha256")).lower()
                if not object_key or len(expected_sha256) != 64:
                    raise RuntimeError(
                        f"Incomplete PartAssets metadata at offset {offset}"
                    )

                metadata = await asyncio.to_thread(
                    storage.head_object,
                    object_key,
                )
                if metadata.content_length != expected_size:
                    raise RuntimeError(
                        f"COS HEAD size mismatch at offset {offset}"
                    )
                signed_url, _expires_at = await asyncio.to_thread(
                    storage.create_presigned_download,
                    object_key,
                )
                digest = hashlib.sha256()
                downloaded_size = 0
                async with transfer.stream("GET", signed_url) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        downloaded_size += len(chunk)
                        digest.update(chunk)
                if downloaded_size != expected_size:
                    raise RuntimeError(
                        f"Signed GET size mismatch at offset {offset}"
                    )
                if digest.hexdigest() != expected_sha256:
                    raise RuntimeError(
                        f"Signed GET SHA-256 mismatch at offset {offset}"
                    )

                summary["sampled"] += 1
                summary["verified"] += 1
                summary["samples"].append(
                    {
                        "offset": offset,
                        "recordId": _text(row.get("recordId")),
                        "partId": _text(fields.get("part_id_fk")),
                        "field": _text(fields.get("legacy_source_field")),
                        "fileSize": expected_size,
                        "mimeType": _text(fields.get("mime_type")),
                    }
                )
        return summary
    finally:
        await filemaker.close()


def main() -> None:
    args = parse_args()
    print(json.dumps(asyncio.run(run(args.samples)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
