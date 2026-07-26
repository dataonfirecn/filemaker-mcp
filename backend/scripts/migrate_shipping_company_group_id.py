"""Back up and populate the canonical shipping-company group ID.

The script is read-only unless ``--commit`` is provided. In every mode it
captures the source company UUID stored through ``出貨單_客戶`` so the migration
can be audited or rolled back without depending on the new field.

Examples:

    python backend/scripts/migrate_shipping_company_group_id.py --backup-only
    python backend/scripts/migrate_shipping_company_group_id.py
    python backend/scripts/migrate_shipping_company_group_id.py --commit
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.services.filemaker_client import FileMakerClient  # noqa: E402


COMPANY_LAYOUT = "@公司資訊"
ORDER_LAYOUT = "@出貨單"
DETAIL_LAYOUT = "@mayako"
COMPANY_GROUP_FIELD = "出貨公司群組ID"
ORDER_GROUP_FIELD = "出貨公司群組ID"
SOURCE_COMPANY_FIELD = "出貨單_客戶::ID_出貨公司"
MAYAKO_COMPANY_ID = "0E254109-8698-4F5D-BE70-ABFD2B929CE9"
WT_GLOBAL_COMPANY_ID = "AF86AC3E-1CB1-450D-B410-DF7FC66CC086"
MERGED_COMPANY_IDS = frozenset({MAYAKO_COMPANY_ID, WT_GLOBAL_COMPANY_ID})
DEFAULT_BATCH_SIZE = 500


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backup-only",
        action="store_true",
        help="Export the pre-migration snapshot without requiring the new fields.",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Populate company and order group IDs. Without this flag writes are disabled.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Data API page size (default: {DEFAULT_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Maximum concurrent Data API updates in commit mode (default: 4).",
    )
    args = parser.parse_args()
    if args.backup_only and args.commit:
        parser.error("--backup-only and --commit cannot be used together")
    if not 1 <= args.batch_size <= 500:
        parser.error("--batch-size must be between 1 and 500")
    if not 1 <= args.concurrency <= 8:
        parser.error("--concurrency must be between 1 and 8")
    return args


def _text(value: Any) -> str:
    return str(value or "").strip()


def canonical_group_id(
    source_company_id: str,
    company_group_ids: dict[str, str],
) -> str:
    """Return the configured canonical group ID with a safe legacy fallback."""
    source_company_id = _text(source_company_id)
    if not source_company_id:
        return ""
    if source_company_id in MERGED_COMPANY_IDS:
        return MAYAKO_COMPANY_ID
    return _text(company_group_ids.get(source_company_id)) or source_company_id


async def _all_records(
    client: FileMakerClient,
    layout: str,
    *,
    batch_size: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    offset = 1
    while True:
        result = await client.find_records(layout, limit=batch_size, offset=offset)
        rows = result.get("data") or []
        if not rows:
            break
        records.extend(row for row in rows if isinstance(row, dict))
        returned = len(rows)
        offset += returned
        if returned < batch_size:
            break
    return records


async def _field_names(client: FileMakerClient, layout: str) -> set[str]:
    return {
        _text(item.get("name"))
        for item in await client.get_layout_fields(layout)
        if _text(item.get("name"))
    }


def _company_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    fields = record.get("fieldData") or {}
    return {
        "recordId": _text(record.get("recordId")),
        "modId": _text(record.get("modId")),
        "ID": _text(fields.get("ID")),
        "公司ID": _text(fields.get("公司ID")),
        "公司名稱": _text(fields.get("公司名稱")),
        COMPANY_GROUP_FIELD: _text(fields.get(COMPANY_GROUP_FIELD)),
    }


def _order_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    fields = record.get("fieldData") or {}
    return {
        "recordId": _text(record.get("recordId")),
        "modId": _text(record.get("modId")),
        "id": _text(fields.get("id")),
        "訂單 PO": _text(fields.get("訂單 PO")),
        SOURCE_COMPANY_FIELD: _text(fields.get(SOURCE_COMPANY_FIELD)),
        ORDER_GROUP_FIELD: _text(fields.get(ORDER_GROUP_FIELD)),
    }


def _counts(orders: list[dict[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(_text(order.get(field)) for order in orders).items()))


def _po_counts(orders: list[dict[str, Any]], field: str) -> dict[str, int]:
    return dict(
        sorted(
            Counter(
                _text(order.get(field))
                for order in orders
                if _text(order.get("訂單 PO"))
            ).items()
        )
    )


def _timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


async def _update_records(
    client: FileMakerClient,
    layout: str,
    updates: list[tuple[str, str]],
    *,
    concurrency: int,
) -> list[dict[str, str]]:
    semaphore = asyncio.Semaphore(concurrency)
    failures: list[dict[str, str]] = []

    async def update(record_id: str, value: str) -> None:
        async with semaphore:
            try:
                await client.update_record(
                    layout,
                    record_id,
                    {ORDER_GROUP_FIELD: value},
                    entry_mode="script",
                )
            except Exception as exc:  # noqa: BLE001 - every failed record is audited
                failures.append(
                    {
                        "recordId": record_id,
                        "value": value,
                        "error": str(exc),
                    }
                )

    await asyncio.gather(*(update(record_id, value) for record_id, value in updates))
    return failures


async def main() -> None:
    args = parse_args()
    client = FileMakerClient(get_settings())
    stamp = _timestamp()
    backup_path = Path(
        f"backups/filemaker/shipping-company-group-before-migration-{stamp}.json"
    )
    report_path = Path(
        f"outputs/shipping-company-group-migration-{stamp}.json"
    )

    try:
        company_fields = await _field_names(client, COMPANY_LAYOUT)
        order_fields = await _field_names(client, ORDER_LAYOUT)
        companies_raw, orders_raw = await asyncio.gather(
            _all_records(client, COMPANY_LAYOUT, batch_size=args.batch_size),
            _all_records(client, ORDER_LAYOUT, batch_size=args.batch_size),
        )
        companies = [_company_snapshot(record) for record in companies_raw]
        orders = [_order_snapshot(record) for record in orders_raw]
        before = {
            "companyCount": len(companies),
            "orderCount": len(orders),
            "sourceCompanyCounts": _counts(orders, SOURCE_COMPANY_FIELD),
            "sourceCompanyPoCounts": _po_counts(orders, SOURCE_COMPANY_FIELD),
            "mergedSourceCount": sum(
                1
                for order in orders
                if order[SOURCE_COMPANY_FIELD] in MERGED_COMPANY_IDS
            ),
            "mergedSourcePoCount": sum(
                1
                for order in orders
                if order[SOURCE_COMPANY_FIELD] in MERGED_COMPANY_IDS
                and order["訂單 PO"]
            ),
        }
        _write_json(
            backup_path,
            {
                "createdAt": datetime.now().astimezone().isoformat(),
                "database": client.settings.filemaker_database,
                "companyLayout": COMPANY_LAYOUT,
                "orderLayout": ORDER_LAYOUT,
                "sourceCompanyField": SOURCE_COMPANY_FIELD,
                "groupField": ORDER_GROUP_FIELD,
                "mayakoCompanyId": MAYAKO_COMPANY_ID,
                "wtGlobalCompanyId": WT_GLOBAL_COMPANY_ID,
                "before": before,
                "companies": companies,
                "orders": orders,
            },
        )

        if args.backup_only:
            print(
                json.dumps(
                    {
                        "mode": "backup-only",
                        "backup": str(backup_path),
                        "before": before,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return

        required_layout_fields = {
            COMPANY_LAYOUT: COMPANY_GROUP_FIELD in company_fields,
            ORDER_LAYOUT: ORDER_GROUP_FIELD in order_fields,
            DETAIL_LAYOUT: ORDER_GROUP_FIELD
            in await _field_names(client, DETAIL_LAYOUT),
        }
        missing = [
            layout for layout, present in required_layout_fields.items() if not present
        ]
        if missing:
            raise RuntimeError(
                "Add 出貨公司群組ID to these FileMaker layouts before migration: "
                + ", ".join(missing)
            )

        company_group_ids = {
            company["ID"]: (
                MAYAKO_COMPANY_ID
                if company["ID"] in MERGED_COMPANY_IDS
                else company["ID"]
            )
            for company in companies
            if company["ID"]
        }
        company_updates = [
            (company["recordId"], company_group_ids[company["ID"]])
            for company in companies
            if company["ID"]
            and company[COMPANY_GROUP_FIELD] != company_group_ids[company["ID"]]
        ]
        order_updates = [
            (
                order["recordId"],
                canonical_group_id(order[SOURCE_COMPANY_FIELD], company_group_ids),
            )
            for order in orders
            if order["recordId"]
            and canonical_group_id(order[SOURCE_COMPANY_FIELD], company_group_ids)
            and order[ORDER_GROUP_FIELD]
            != canonical_group_id(order[SOURCE_COMPANY_FIELD], company_group_ids)
        ]
        unresolved = [
            {
                "recordId": order["recordId"],
                "id": order["id"],
            }
            for order in orders
            if not order[SOURCE_COMPANY_FIELD]
        ]
        report: dict[str, Any] = {
            "createdAt": datetime.now().astimezone().isoformat(),
            "mode": "commit" if args.commit else "dry-run",
            "backup": str(backup_path),
            "before": before,
            "planned": {
                "companyUpdates": len(company_updates),
                "orderUpdates": len(order_updates),
                "unresolvedOrders": len(unresolved),
            },
            "unresolved": unresolved,
        }

        if args.commit:
            company_failures = await _update_records(
                client,
                COMPANY_LAYOUT,
                company_updates,
                concurrency=args.concurrency,
            )
            order_failures = await _update_records(
                client,
                ORDER_LAYOUT,
                order_updates,
                concurrency=args.concurrency,
            )
            report["commit"] = {
                "companyFailures": company_failures,
                "orderFailures": order_failures,
            }
            if company_failures or order_failures:
                _write_json(report_path, report)
                raise RuntimeError(
                    "Migration completed with failed records; inspect "
                    f"{report_path}"
                )

            after_orders_raw = await _all_records(
                client,
                ORDER_LAYOUT,
                batch_size=args.batch_size,
            )
            after_orders = [_order_snapshot(record) for record in after_orders_raw]
            report["after"] = {
                "groupCounts": _counts(after_orders, ORDER_GROUP_FIELD),
                "groupPoCounts": _po_counts(after_orders, ORDER_GROUP_FIELD),
                "mayakoGroupCount": sum(
                    1
                    for order in after_orders
                    if order[ORDER_GROUP_FIELD] == MAYAKO_COMPANY_ID
                ),
                "mayakoGroupPoCount": sum(
                    1
                    for order in after_orders
                    if order[ORDER_GROUP_FIELD] == MAYAKO_COMPANY_ID
                    and order["訂單 PO"]
                ),
            }
            if report["after"]["mayakoGroupCount"] != before["mergedSourceCount"]:
                raise RuntimeError(
                    "Mayako group count does not match the pre-migration union"
                )
            if (
                report["after"]["mayakoGroupPoCount"]
                != before["mergedSourcePoCount"]
            ):
                raise RuntimeError(
                    "Mayako PO group count does not match the pre-migration union"
                )

        _write_json(report_path, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
