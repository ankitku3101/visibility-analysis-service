# Phase 01 — Setup and storage

**Goal:** An empty app that starts, creates the database and answers `/health`. (SPEC T1)

**Build**
- venv, pinned `requirements.txt`, `.env.example`, `pytest.ini`
- config loader, SQLite schema + `python -m app.db init` (tables from DESIGN §4)
- JSON error format and bearer-token roles (DESIGN §5, §10)
- `GET /health`, test setup with a temp DB

**Done when**
- `python -m app.db init` creates the DB, `uvicorn app.main:app` serves `/health` and `/docs`
- `pytest -q` passes (health, error format, 401/403)

**Commit:** `feat: project setup, config, db schema, health and auth`
