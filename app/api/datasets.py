from typing import Any

from fastapi import APIRouter, Body, Depends, Response
from pydantic import BaseModel, ConfigDict

from app.auth import require_role
from app.config import get_settings
from app.db import connect
from app.ingest.loader import load_pack
from app.ingest.service import import_dataset

router = APIRouter(tags=["datasets"])


class DatasetUpload(BaseModel):
    """Rows are plain values here and are checked one by one in the service,
    so one bad row is listed and skipped instead of failing the whole request."""
    model_config = ConfigDict(extra="forbid")
    run: dict
    prompts: list[Any] = []
    responses: list[Any] = []
    citations: list[Any] = []


@router.post("/datasets", status_code=201, summary="Import and validate the pack (no body = read from PACK_DIR)")
def create_dataset(
    response: Response,
    body: DatasetUpload | None = Body(default=None),
    actor: str = Depends(require_role("analyst")),
):
    settings = get_settings()
    records = body.model_dump() if body is not None else load_pack(settings.pack_dir)
    conn = connect(settings.db_path)
    try:
        result = import_dataset(conn, records)
    finally:
        conn.close()
    response.status_code = 201 if result["created"] else 200
    return result
