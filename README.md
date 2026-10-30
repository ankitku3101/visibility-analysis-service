# Kasparro AI Visibility Analysis Service

A FastAPI + SQLite backend that imports 150 saved AI answers, classifies how each one treats Kasparro with a
local LLM (with exact-quote evidence checked by code), scores visibility with plain code, and runs a report
through analyst/reviewer review before export.

- What and why: [docs/SPEC.md](docs/SPEC.md). How: [docs/DESIGN.md](docs/DESIGN.md).
  Choices, risks and AI use: [docs/DECISIONS.md](docs/DECISIONS.md). Time spent: [docs/TIME_LOG.md](docs/TIME_LOG.md).
- Final output: [out/analysis.json](out/analysis.json) (approved report: scores, coverage, 3 diagnostics,
  3 remedies, active time). Evaluation: [eval/results/report.md](eval/results/report.md).

> **Why Python?** My strongest experience is in TypeScript (Node, Next.js, React), not Python. I still chose
> Python + FastAPI for this project. The brief prefers Python, the scope is small, and as an assignment it was
> a good chance to learn a new stack by building something real. FastAPI felt close to what I know: Pydantic
> models play the role of Zod schemas, and dependencies (`Depends`) work like middleware. Plain SQL with
> SQLite kept the data layer simple enough to understand fully. I'm happy to walk through any part of the code.

## 1. Prerequisites

- Python 3.10+ (built and tested on 3.12, Windows 11).
- The assignment pack. Its files are **not in Git** (hiring team's data). Either copy the pack's `data/`
  folder into this project folder, or set `PACK_DIR` in `.env` to the extracted pack folder.
- Ollama is **optional**. The default `replay` mode reuses the saved model outputs in `replay/`, so no model
  is needed to run everything below. See section 6 for the real model.

## 2. Setup (about 2 minutes)

```bash
git clone <repo-url> kasparro && cd kasparro
python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env               # Windows: copy .env.example .env   (then set PACK_DIR if needed)
python -m app.db init              # creates app.db
```

## 3. Start the server

```bash
uvicorn app.main:app --port 8000
```

- `GET http://localhost:8000/health` → `{"status":"ok","db":"ok","llm_mode":"replay"}`
- Swagger UI: http://localhost:8000/docs (use **Authorize** with a token from `.env`)

## 4. Full flow with curl

Run in a second terminal (bash, or Git Bash on Windows). Tokens are the defaults from `.env.example`.
Expected status is in each comment.

```bash
B=http://localhost:8000
A="Authorization: Bearer change-me-analyst"
R="Authorization: Bearer change-me-reviewer"
J="Content-Type: application/json"

curl -X POST $B/datasets -H "$A"                                   # 201: 50 prompts, 150 responses, 2439 citations
curl -X POST $B/datasets -H "$A"                                   # 200: same pack again, nothing new added
curl -X POST $B/analyses -H "$A" -H "$J" -d '{"dataset_id": 1}'    # 202: runs in the background
curl "$B/analyses/1?include_results=false" -H "$A"                 # repeat until "completed" (replay: seconds)
curl "$B/analyses/1" -H "$A"                                       # per-response results + scores

curl -X POST $B/reports -H "$A" -H "$J" -d '{"analysis_id": 1}'    # 201: draft v1 (scores + 3 diagnostic drafts)
curl -X PATCH $B/reports/1 -H "$A" -H "$J" -d @out/report_edits.json   # 200: explanations + 3 remedies
curl -X POST $B/reports/1/submit -H "$A"                           # 200: v1 frozen for review

curl -X POST $B/reports/1/decision -H "$A" -H "$J" \
  -d '{"version": 1, "decision": "approve", "comment": "ok"}'      # 403: analyst cannot approve
curl -X POST $B/reports/1/decision -H "$R" -H "$J" \
  -d '{"version": 1, "decision": "reject", "comment": "Add the active time to notes."}'   # 200
curl $B/reports/1/export -H "$A"                                   # 409: rejected, export blocked

curl -X PATCH $B/reports/1 -H "$A" -H "$J" -d '{"notes": "Active time: see TIME_LOG."}'  # 200: new draft v2
curl -X POST $B/reports/1/submit -H "$A"                           # 200
curl -X POST $B/reports/1/decision -H "$R" -H "$J" \
  -d '{"version": 2, "decision": "approve", "comment": "Evidence checked."}'              # 200
curl $B/reports/1/export -H "$A"                                   # 200: approved v2

curl -X PATCH $B/reports/1 -H "$A" -H "$J" -d '{"notes": "late edit"}'   # 200: new draft v3
curl $B/reports/1/export -H "$A"                                   # 409: v3 is a draft, needs a new review
curl "$B/reports/1/export?version=2" -H "$A"                       # 200: old approved v2, "is_latest": false
```

`out/report_edits.json` is the analyst's real PATCH body used for `out/analysis.json`. Every quote in it is
checked against the answer text by the server; a wrong quote gives 422 `invalid_report`.

**PowerShell** instead of curl (non-2xx answers show as red errors; that is expected for the 403/409 steps):

```powershell
$B = "http://localhost:8000"
$A = @{ Authorization = "Bearer change-me-analyst" }
$R = @{ Authorization = "Bearer change-me-reviewer" }
Invoke-RestMethod -Method Post "$B/datasets" -Headers $A | Format-List
Invoke-RestMethod -Method Post "$B/analyses" -Headers $A -ContentType "application/json" -Body '{"dataset_id": 1}'
(Invoke-RestMethod "$B/analyses/1?include_results=false" -Headers $A).status
Invoke-RestMethod -Method Post "$B/reports" -Headers $A -ContentType "application/json" -Body '{"analysis_id": 1}' | Out-Null
Invoke-RestMethod -Method Patch "$B/reports/1" -Headers $A -ContentType "application/json" `
  -Body ([IO.File]::ReadAllBytes("$PWD\out\report_edits.json")) | Out-Null    # bytes keep the UTF-8 quotes intact
Invoke-RestMethod -Method Post "$B/reports/1/submit" -Headers $A | Out-Null
Invoke-RestMethod -Method Post "$B/reports/1/decision" -Headers $R -ContentType "application/json" `
  -Body '{"version": 1, "decision": "approve", "comment": "Evidence checked."}' | Out-Null
(Invoke-RestMethod "$B/reports/1/export" -Headers $A).content.remedies | Format-List id, title
```

## 5. Tests, evaluation, pack check

```bash
pytest -q                      # 148 tests, no model needed; 3 that read the real pack skip if data/ is absent
python -m eval.run_eval        # LLM vs keyword baseline on the hand-labelled final split
python -m eval.run_eval --split tuning
py -3 tools/check_pack.py      # from the pack folder: inputs unchanged
```

In `replay` mode the eval reuses saved outputs and marks its report **UNVERIFIED** (it shows the pipeline,
not model quality). It rewrites `eval/results/report.md` with the same numbers; `git checkout eval/results`
restores the committed local-model report, or pass `--out some/folder`. Known gap: the final split replays
exactly; the tuning split differs on c02, because the final run re-ran c02 as a regression case and its newer
recording replaced the tuning one (the model gave a different answer, see known disagreements).

## 6. LLM modes

Set `LLM_MODE` in `.env` (or the environment) and restart the server.

| Mode | What it does |
|---|---|
| `replay` (default) | Reads saved outputs from `replay/classify-v3/`. No model, same results as the local run. A response with no recording fails with `replay_missing`. |
| `local` | Calls Ollama (`qwen2.5:7b`, temperature 0, JSON format, 8k context) and records every output to `replay/`. |
| `stub` | Fake outputs, used by the tests. |
| `live` | Not configured (no hosted API access); returns 400 `live_not_configured`. |

Real model run:

```bash
ollama pull qwen2.5:7b         # about 4.7 GB download, once
ollama serve                   # if it is not already running
LLM_MODE=local uvicorn app.main:app --port 8000      # PowerShell: $env:LLM_MODE="local"; uvicorn ...
```

Then the same `POST /datasets` and `POST /analyses` calls. A full 150-response run took 23 minutes on the dev
machine (about 9 s per answer). Do not use `--reload` and do not edit code during a run: a restart marks the
run `interrupted`. If Ollama is not running, `POST /analyses` returns 503 `provider_unavailable` at once.
A local run overwrites the recordings in `replay/classify-v3/`.

## 7. Notes

- Changing `app/schema.sql` needs a fresh database: delete `app.db` and run `python -m app.db init`.
- Roles come only from the bearer token. A role or actor sent in a body is rejected or ignored.
- Citations are all `unverified`: no cited page was opened.
