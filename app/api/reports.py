from fastapi import APIRouter, Depends, Query

from app.auth import current_actor, require_role
from app.config import get_settings
from app.db import connect
from app.reports import service
from app.reports.models import CreateReport, DecisionBody, PatchBody

router = APIRouter(tags=["reports"])


def db():
    conn = connect(get_settings().db_path)
    try:
        yield conn
    finally:
        conn.close()


@router.post("/reports", status_code=201, summary="Create a draft report from a completed analysis")
def create(body: CreateReport, actor: str = Depends(require_role("analyst")), conn=Depends(db)):
    return service.get_report(conn, service.create_report(conn, body.analysis_id, actor))


@router.get("/reports/{report_id}", summary="Read a version (latest by default), its history and review events")
def read(report_id: int, version: int | None = Query(default=None, ge=1), actor: str = Depends(current_actor),
         conn=Depends(db)):
    return service.get_report(conn, report_id, version)


@router.patch("/reports/{report_id}", summary="Edit the draft (or start a new draft from a reviewed version)")
def edit(report_id: int, body: PatchBody, actor: str = Depends(require_role("analyst")), conn=Depends(db)):
    return service.get_report(conn, report_id, service.patch_report(conn, report_id, body, actor))


@router.post("/reports/{report_id}/submit", summary="Freeze the latest draft for review")
def submit(report_id: int, actor: str = Depends(require_role("analyst")), conn=Depends(db)):
    return service.get_report(conn, report_id, service.submit_report(conn, report_id, actor))


@router.post("/reports/{report_id}/decision", summary="Approve or reject the submitted version (reviewer only)")
def decision(report_id: int, body: DecisionBody, actor: str = Depends(require_role("reviewer")), conn=Depends(db)):
    service.decide(conn, report_id, body, actor)
    return service.get_report(conn, report_id, body.version)


@router.get("/reports/{report_id}/export", summary="Export an approved version (latest by default)")
def export(report_id: int, version: int | None = Query(default=None, ge=1), actor: str = Depends(current_actor),
           conn=Depends(db)):
    return service.export_report(conn, report_id, version, actor)
