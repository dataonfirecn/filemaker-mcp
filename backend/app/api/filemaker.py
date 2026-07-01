from fastapi import APIRouter, Depends, HTTPException, status

from app.models.filemaker import (
    FindRecordsRequest,
    RecordWriteRequest,
    RunScriptRequest,
)
from app.services.dependencies import get_filemaker_client
from app.services.filemaker_client import FileMakerAPIError, FileMakerClient

router = APIRouter(prefix="/filemaker", tags=["filemaker"])


def filemaker_error_response(exc: FileMakerAPIError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code or status.HTTP_502_BAD_GATEWAY,
        detail={"message": str(exc), "payload": exc.payload},
    )


@router.get("/layouts")
async def list_layouts(
    client: FileMakerClient = Depends(get_filemaker_client),
) -> dict[str, list[str]]:
    try:
        return {"layouts": await client.list_layouts()}
    except FileMakerAPIError as exc:
        raise filemaker_error_response(exc) from exc


@router.get("/layouts/{layout}/fields")
async def get_layout_fields(
    layout: str,
    client: FileMakerClient = Depends(get_filemaker_client),
) -> dict[str, object]:
    try:
        return {"layout": layout, "fields": await client.get_layout_fields(layout)}
    except FileMakerAPIError as exc:
        raise filemaker_error_response(exc) from exc


@router.post("/{layout}/find")
async def find_records(
    layout: str,
    body: FindRecordsRequest,
    client: FileMakerClient = Depends(get_filemaker_client),
) -> dict[str, object]:
    try:
        sort = None
        if body.sort:
            sort = [
                item.model_dump(by_alias=True)
                for item in body.sort
            ]
        return await client.find_records(
            layout,
            query=body.query,
            limit=body.limit,
            offset=body.offset,
            sort=sort,
        )
    except FileMakerAPIError as exc:
        raise filemaker_error_response(exc) from exc


@router.get("/{layout}/records/{record_id}")
async def get_record(
    layout: str,
    record_id: str,
    client: FileMakerClient = Depends(get_filemaker_client),
) -> object:
    try:
        return await client.get_record(layout, record_id)
    except FileMakerAPIError as exc:
        raise filemaker_error_response(exc) from exc


@router.post("/{layout}/records", status_code=status.HTTP_201_CREATED)
async def create_record(
    layout: str,
    body: RecordWriteRequest,
    client: FileMakerClient = Depends(get_filemaker_client),
) -> dict[str, object]:
    try:
        return await client.create_record(layout, body.field_data)
    except FileMakerAPIError as exc:
        raise filemaker_error_response(exc) from exc


@router.patch("/{layout}/records/{record_id}")
async def update_record(
    layout: str,
    record_id: str,
    body: RecordWriteRequest,
    client: FileMakerClient = Depends(get_filemaker_client),
) -> dict[str, object]:
    try:
        return await client.update_record(layout, record_id, body.field_data)
    except FileMakerAPIError as exc:
        raise filemaker_error_response(exc) from exc


@router.delete("/{layout}/records/{record_id}")
async def delete_record(
    layout: str,
    record_id: str,
    client: FileMakerClient = Depends(get_filemaker_client),
) -> dict[str, object]:
    try:
        return await client.delete_record(layout, record_id)
    except FileMakerAPIError as exc:
        raise filemaker_error_response(exc) from exc


@router.post("/{layout}/scripts/{script_name}")
async def run_script(
    layout: str,
    script_name: str,
    body: RunScriptRequest,
    client: FileMakerClient = Depends(get_filemaker_client),
) -> dict[str, object]:
    try:
        return await client.run_script(layout, script_name, body.script_param)
    except FileMakerAPIError as exc:
        raise filemaker_error_response(exc) from exc
