import pytest

from app.services.product_photo_upload_store import (
    ProductPhotoSessionConflict,
    ProductPhotoSessionFull,
    ProductPhotoUploadStore,
)


async def _claim(
    store: ProductPhotoUploadStore,
    *,
    index: int,
    session_id: str = "session-a",
    operator_account: str = "pda",
):
    return await store.claim_slot(
        upload_id=f"upload-{index}",
        session_id=session_id,
        product_sku="PI0019694",
        product_record_id="100",
        source_mod_id="1",
        object_key=f"products/upload-{index}.jpg",
        original_filename=f"photo-{index}.jpg",
        mime_type="image/jpeg",
        file_size=100 + index,
        sha256=f"sha-{index}",
        source="camera",
        operator_account=operator_account,
    )


@pytest.mark.asyncio
async def test_capture_session_claims_six_slots_and_rejects_seventh(tmp_path):
    store = ProductPhotoUploadStore(str(tmp_path / "uploads.sqlite3"))
    await store.init()

    records = [await _claim(store, index=index) for index in range(1, 7)]

    assert [record.slot for record in records] == [1, 2, 3, 4, 5, 6]
    with pytest.raises(ProductPhotoSessionFull):
        await _claim(store, index=7)


@pytest.mark.asyncio
async def test_store_binds_filemaker_asset_to_canonical_cos_key(tmp_path):
    store = ProductPhotoUploadStore(str(tmp_path / "uploads.sqlite3"))
    await store.init()
    record = await _claim(store, index=1)

    bound = await store.bind_asset(
        record.upload_id,
        object_key="starrc/products/original/migration/100/ASSET-UUID.jpg",
        asset_record_id="asset-200",
    )

    assert bound is not None
    assert bound.object_key.endswith("/ASSET-UUID.jpg")
    assert bound.asset_record_id == "asset-200"


@pytest.mark.asyncio
async def test_active_capture_session_blocks_other_session_and_operator(tmp_path):
    store = ProductPhotoUploadStore(str(tmp_path / "uploads.sqlite3"))
    await store.init()
    await _claim(store, index=1)

    with pytest.raises(ProductPhotoSessionConflict):
        await _claim(store, index=2, session_id="session-b")

    with pytest.raises(ProductPhotoSessionConflict):
        await _claim(
            store,
            index=3,
            session_id="session-a",
            operator_account="another-pda",
        )


@pytest.mark.asyncio
async def test_sync_claim_is_atomic_and_recovers_after_process_restart(tmp_path):
    database_path = str(tmp_path / "uploads.sqlite3")
    store = ProductPhotoUploadStore(database_path)
    await store.init()
    record = await _claim(store, index=1)
    await store.mark_uploaded(record.upload_id, etag="etag")

    claimed = await store.claim_syncing(record.upload_id)
    duplicate = await store.claim_syncing(record.upload_id)

    assert claimed is not None
    assert claimed.status == "SYNCING"
    assert duplicate is None

    restarted_store = ProductPhotoUploadStore(database_path)
    await restarted_store.init()
    recovered = await restarted_store.get(record.upload_id)

    assert recovered is not None
    assert recovered.status == "UPLOADED"
    assert await restarted_store.claim_syncing(record.upload_id) is not None
