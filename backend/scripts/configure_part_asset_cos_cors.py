from __future__ import annotations

import argparse
import json
from typing import Any

from app.core.config import get_settings
from app.services.cos_storage import COSStorageService


RULE_ID = "starrc-part-assets-web"
ALLOWED_METHODS = ["GET", "HEAD", "PUT"]
EXPOSE_HEADERS = ["ETag", "x-cos-request-id"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect or apply the browser CORS rule used by PartAssets.",
    )
    parser.add_argument(
        "--origin",
        action="append",
        dest="origins",
        help="Allowed browser origin. Repeat for each exact origin.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the desired rule. Without this flag the script is read-only.",
    )
    return parser.parse_args()


def normalized_rule(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(rule.get("ID") or ""),
        "origins": sorted(str(item) for item in rule.get("AllowedOrigin") or []),
        "methods": sorted(str(item) for item in rule.get("AllowedMethod") or []),
        "allowedHeaders": sorted(str(item) for item in rule.get("AllowedHeader") or []),
        "exposeHeaders": sorted(str(item) for item in rule.get("ExposeHeader") or []),
        "maxAgeSeconds": int(rule.get("MaxAgeSeconds") or 0),
    }


def get_current_rules(client: Any, bucket: str) -> list[dict[str, Any]]:
    try:
        response = client.get_bucket_cors(Bucket=bucket)
    except Exception as exc:
        error_code = getattr(exc, "get_error_code", lambda: "")()
        if error_code == "NoSuchCORSConfiguration":
            return []
        raise
    return response.get("CORSRule") or []


def main() -> None:
    args = parse_args()
    settings = get_settings()
    storage = COSStorageService(settings)
    client = storage._require_client()
    origins = sorted(
        {
            origin.strip().rstrip("/")
            for origin in (args.origins or settings.cors_origin_list)
            if origin.strip()
        }
    )
    if not origins:
        raise SystemExit("At least one exact --origin is required.")

    desired_sdk_rule = {
        "ID": RULE_ID,
        "AllowedOrigin": origins,
        "AllowedMethod": ALLOWED_METHODS,
        "AllowedHeader": ["*"],
        "ExposeHeader": EXPOSE_HEADERS,
        "MaxAgeSeconds": 600,
    }
    current_rules = get_current_rules(client, settings.cos_bucket)
    current = [normalized_rule(rule) for rule in current_rules]
    desired = normalized_rule(desired_sdk_rule)
    has_desired_rule = desired in current

    if args.apply and not has_desired_rule:
        preserved = [
            rule
            for rule in current_rules
            if str(rule.get("ID") or "") != RULE_ID
        ]
        client.put_bucket_cors(
            Bucket=settings.cos_bucket,
            CORSConfiguration={"CORSRule": [*preserved, desired_sdk_rule]},
        )
        current_response = get_current_rules(client, settings.cos_bucket)
        current = [
            normalized_rule(rule)
            for rule in current_response
        ]
        has_desired_rule = desired in current

    print(
        json.dumps(
            {
                "bucket": settings.cos_bucket,
                "mode": "apply" if args.apply else "check",
                "desired": desired,
                "current": current,
                "configured": has_desired_rule,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.apply and not has_desired_rule:
        raise SystemExit("COS CORS verification failed after apply.")


if __name__ == "__main__":
    main()
