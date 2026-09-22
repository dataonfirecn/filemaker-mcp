"""Signed thumbnail tickets for the product catalog grid.

The grid renders thumbnails through plain <img> elements, which cannot send the
WebViewer bearer token, so the list response mints a capability URL per row.
These tests pin the properties that make that safe: the ticket is bound to one
record, one asset version and one expiry, and it is never minted for a caller
whose deployment has no signing secret.
"""

from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from app.services.image_tickets import (
    sign_thumbnail_ticket,
    verify_thumbnail_ticket,
)


def test_ticket_is_bound_to_record_version_and_expiry():
    expires_at, signature = sign_thumbnail_ticket("rec-1", "7", "secret")

    assert verify_thumbnail_ticket("rec-1", "7", expires_at, signature, "secret")
    # A ticket for one product must not open another, nor an older/newer image.
    assert not verify_thumbnail_ticket("rec-2", "7", expires_at, signature, "secret")
    assert not verify_thumbnail_ticket("rec-1", "8", expires_at, signature, "secret")
    # Pushing the expiry out must invalidate rather than extend the ticket.
    assert not verify_thumbnail_ticket(
        "rec-1", "7", expires_at + 3600, signature, "secret"
    )
    assert not verify_thumbnail_ticket(
        "rec-1", "7", expires_at, signature, "secret", now=expires_at + 1
    )


@pytest.mark.parametrize(
    ("signature", "secret"),
    [("", "secret"), ("deadbeef", "secret"), ("anything", "")],
)
def test_missing_or_forged_credentials_are_refused(signature, secret):
    expires_at, _ = sign_thumbnail_ticket("rec-1", "7", "secret")
    assert not verify_thumbnail_ticket("rec-1", "7", expires_at, signature, secret)


def test_repeated_signing_is_stable_so_browsers_can_cache_thumbnails():
    from app.services.image_tickets import TICKET_BUCKET_SECONDS

    base = 1_800_000_000.0
    first = sign_thumbnail_ticket("rec-1", "7", "secret", now=base)
    later = sign_thumbnail_ticket("rec-1", "7", "secret", now=base + 60)
    # Same URL within the bucket: the browser cache survives a page refresh.
    assert first == later

    next_bucket = sign_thumbnail_ticket(
        "rec-1", "7", "secret", now=base + TICKET_BUCKET_SECONDS
    )
    assert next_bucket != first
    # Even the shortest-lived ticket outlives the bucket that minted it.
    assert first[0] > base + TICKET_BUCKET_SECONDS


def test_row_omits_thumbnail_without_image_or_signing_secret():
    from app.api.business_products import _thumbnail_url

    assert _thumbnail_url("rec-1", "7", has_image=False, secret="secret") == ""
    assert _thumbnail_url("rec-1", "7", has_image=True, secret="") == ""
    assert _thumbnail_url("", "7", has_image=True, secret="secret") == ""

    url = _thumbnail_url("rec-1", "7", has_image=True, secret="secret")
    assert url.startswith("/api/business-products/rec-1/thumbnail?")
    assert "sig=" in url and "exp=" in url and "v=7" in url


def test_product_row_signs_thumbnail_for_records_with_an_image():
    from app.api.business_products import _product_row

    record = {
        "recordId": "rec-1",
        "modId": "7",
        "fieldData": {"product_sku": "SKU-1", "image_main": "/api/assets/1"},
    }
    row = _product_row(record, thumb_secret="secret")
    assert row.thumbnail_url.startswith("/api/business-products/rec-1/thumbnail?")

    blank = _product_row({**record, "fieldData": {"product_sku": "SKU-1"}}, thumb_secret="secret")
    assert blank.thumbnail_url == ""
    # A deployment without a secret degrades to no thumbnails, never to unsigned ones.
    assert _product_row(record).thumbnail_url == ""


@pytest.mark.asyncio
async def test_thumbnail_route_refuses_an_invalid_ticket():
    from fastapi import HTTPException
    from app.api.business_products import get_business_product_thumbnail

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(settings=SimpleNamespace(webviewer_context_secret="secret"))
        )
    )

    class NoFileMaker:
        def __getattr__(self, name):
            raise AssertionError("An unverified ticket must not reach FileMaker")

    expires_at, signature = sign_thumbnail_ticket("rec-1", "7", "secret")
    with pytest.raises(HTTPException) as error:
        await get_business_product_thumbnail(
            "rec-2", v="7", exp=expires_at, sig=signature,
            filemaker=NoFileMaker(), request=request,
        )
    assert error.value.status_code == 403


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "P", "L"])
def test_downscale_bounds_every_colour_mode_to_the_thumbnail_box(mode):
    from app.api.business_products import THUMBNAIL_MAX_EDGE, _downscale_image

    source = Image.new(mode, (1800, 1200))
    buffer = BytesIO()
    source.save(buffer, format="PNG")

    thumbnail = Image.open(BytesIO(_downscale_image(buffer.getvalue())))
    assert thumbnail.format == "WEBP"
    assert max(thumbnail.size) <= THUMBNAIL_MAX_EDGE
    # Aspect ratio survives the downscale (1800x1200 -> 160x107, not 160x160).
    assert thumbnail.size[0] > thumbnail.size[1]
