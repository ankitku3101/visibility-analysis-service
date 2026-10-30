from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from app.analysis.runner import start_run
from app.analysis.service import create_run, get_run
from app.auth import current_actor, require_role
from app.config import get_settings
from app.db import connect

router = APIRouter(tags=["analyses"])


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: int = Field(ge=1)
    limit: int | None = Field(default=None, ge=1, description="Analyse only the first N responses (quick tests)")


@router.post("/analyses", status_code=202, summary="Start an analysis in the background")
def create_analysis(body: AnalysisRequest, request: Request, actor: str = Depends(require_role("analyst"))):
    settings = get_settings()
    client = request.app.state.client_factory(settings)  # 400 here if the mode cannot run
    conn = connect(settings.db_path)
    try:
        run_id = create_run(conn, body.dataset_id, body.limit, client)
    finally:
        conn.close()
    start_run(run_id, client, settings)
    return {"analysis_id": run_id, "status": "running", "llm_mode": client.mode}


@router.get("/analyses/{analysis_id}", summary="Status, counts and per-response results")
def read_analysis(analysis_id: int, include_results: bool = True, actor: str = Depends(current_actor)):
    conn = connect(get_settings().db_path)
    try:
        return get_run(conn, analysis_id, include_results)
    finally:
        conn.close()
