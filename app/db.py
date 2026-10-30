"""SQLite connection helpers and the `python -m app.db init` command."""
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(path: str) -> sqlite3.Connection:
    # check_same_thread=False: FastAPI runs sync handlers in a thread pool, and the analysis runner (Phase 04)
    # uses its own thread. Each connection is still used by one piece of code at a time.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(path: str) -> None:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    finally:
        conn.close()


def to_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def content_hash(obj) -> str:
    return hashlib.sha256(to_json(obj).encode("utf-8")).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    if sys.argv[1:] != ["init"]:
        sys.exit("usage: python -m app.db init")
    from app.config import get_settings

    db_path = get_settings().db_path
    init_db(db_path)
    print(f"Database ready: {Path(db_path).resolve()}")
