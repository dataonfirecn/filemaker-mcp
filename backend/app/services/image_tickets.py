"""Short-lived signed tickets for product thumbnail URLs.

A thumbnail is served to a plain ``<img>`` element, which cannot carry the
WebViewer bearer token. Instead the list endpoint mints a capability URL for
every row the caller was already allowed to see, and the thumbnail route
verifies that signature instead of a session.

The ticket is deliberately narrow: it names one record, one asset version and
the ``thumb`` size only, and it expires quickly, so a leaked URL cannot be
escalated into a full-resolution download or outlive the page that produced it.
"""

from __future__ import annotations

import hashlib
import hmac
import time

TICKET_TTL_SECONDS = 3600
# Expiries are quantised to this bucket so that repeated listings of the same
# product mint a byte-identical URL. A ticket minted per request would carry a
# fresh expiry every time, changing the URL and making the browser re-download
# every thumbnail on every page view -- exactly what the signature is meant to
# avoid. A ticket therefore lives between (TTL - bucket) and TTL seconds.
TICKET_BUCKET_SECONDS = 1800
_SIGNATURE_LENGTH = 32


def _digest(record_id: str, version: str, expires_at: int, secret: str) -> str:
    payload = f"{record_id}|thumb|{version}|{expires_at}".encode("utf-8")
    return hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()[:_SIGNATURE_LENGTH]


def sign_thumbnail_ticket(
    record_id: str,
    version: str,
    secret: str,
    *,
    ttl_seconds: int = TICKET_TTL_SECONDS,
    now: float | None = None,
) -> tuple[int, str]:
    """Return ``(expires_at, signature)`` for one product thumbnail."""
    current = now if now is not None else time.time()
    bucket = int(current // TICKET_BUCKET_SECONDS) * TICKET_BUCKET_SECONDS
    expires_at = bucket + ttl_seconds
    return expires_at, _digest(record_id, version, expires_at, secret)


def verify_thumbnail_ticket(
    record_id: str,
    version: str,
    expires_at: int,
    signature: str,
    secret: str,
    *,
    now: float | None = None,
) -> bool:
    if not secret or not signature:
        return False
    current = now if now is not None else time.time()
    if expires_at <= current:
        return False
    expected = _digest(record_id, version, expires_at, secret)
    return hmac.compare_digest(expected, signature)
