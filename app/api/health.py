from fastapi import APIRouter

from app.config import get_settings
from app.db import connect

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    settings = get_settings()
    conn = connect(settings.db_path)
    try:
        conn.execute("SELECT 1")
    finally:
        conn.close()
    return {"status": "ok", "db": "ok", "llm_mode": settings.llm_mode}
