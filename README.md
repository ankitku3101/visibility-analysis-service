# Kasparro AI Visibility Analysis Service

A FastAPI + SQLite backend. It reads 150 saved AI answers, uses a local LLM to label how each one talks about
Kasparro (with exact quotes checked by code), scores the results with plain code, and only exports a report
after a reviewer approves it.

| | |
|---|---|
| **Result** | 150/150 answers analysed. Kasparro is named in **0/75** unbranded answers and 72/75 branded ones. |
| **Final report** | [out/analysis.json](out/analysis.json): approved; scores, 3 diagnostics, 3 remedies, active time |
| **Evaluation** | [eval/results/report.md](eval/results/report.md): LLM vs keyword baseline on hand labels |
| **Decisions** | [docs/DECISIONS.md](docs/DECISIONS.md): one page on choices, risks and AI use |
| **Time** | About 5 h active ([docs/TIME_LOG.md](docs/TIME_LOG.md)) |
| **Design docs** | [docs/SPEC.md](docs/SPEC.md) (what) and [docs/DESIGN.md](docs/DESIGN.md) (how) |

> **Why I used Python?** My strongest stack is TypeScript (Node, Next.js, React). I chose Python because the brief
> prefers it, the scope is small, and it was a good chance to learn by building. Pydantic felt like Zod, and
> FastAPI's `Depends` felt like middleware.

## Quick start (no model needed, about 2 minutes)

You need Python 3.10+ and the assignment pack. The pack is not in Git, so copy its `data/` folder into this
project folder, or set `PACK_DIR` in `.env` to the pack folder.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env
python -m app.db init
uvicorn app.main:app --port 8000
```

Open http://localhost:8000/docs (click **Authorize** and use a token from `.env`). This runs in `replay`
mode, which uses the saved outputs of the real model run, so it needs no model.

## Full flow (second terminal)

```bash
B=http://localhost:8000; J="Content-Type: application/json"
A="Authorization: Bearer change-me-analyst"; R="Authorization: Bearer change-me-reviewer"

curl -X POST $B/datasets -H "$A"                                  # 201 import (again → 200, no duplicates)
curl -X POST $B/analyses -H "$A" -H "$J" -d '{"dataset_id": 1}'   # 202 starts in the background
curl "$B/analyses/1?include_results=false" -H "$A"                # wait for "completed" (seconds)

curl -X POST $B/reports -H "$A" -H "$J" -d '{"analysis_id": 1}'   # 201 draft v1
curl -X PATCH $B/reports/1 -H "$A" -H "$J" -d @out/report_edits.json   # 200 add explanations + remedies
curl -X POST $B/reports/1/submit -H "$A"                          # 200 v1 frozen

curl -X POST $B/reports/1/decision -H "$A" -H "$J" -d '{"version":1,"decision":"approve","comment":"ok"}'   # 403 wrong role
curl -X POST $B/reports/1/decision -H "$R" -H "$J" -d '{"version":1,"decision":"reject","comment":"Add time"}'  # 200
curl $B/reports/1/export -H "$A"                                  # 409 rejected → no export

curl -X PATCH $B/reports/1 -H "$A" -H "$J" -d '{"notes":"Active time added."}'   # 200 new draft v2
curl -X POST $B/reports/1/submit -H "$A"                          # 200
curl -X POST $B/reports/1/decision -H "$R" -H "$J" -d '{"version":2,"decision":"approve","comment":"Checked"}'  # 200
curl $B/reports/1/export -H "$A"                                  # 200 exported

curl -X PATCH $B/reports/1 -H "$A" -H "$J" -d '{"notes":"late edit"}'   # 200 new draft v3
curl $B/reports/1/export -H "$A"                                  # 409 v3 needs a new review
curl "$B/reports/1/export?version=2" -H "$A"                      # 200 old approval, "is_latest": false
```

`out/report_edits.json` is the real analyst edit behind `out/analysis.json`. The server checks every quote in
it against the answer text; a made-up quote gets a 422.

<details><summary>Same flow in PowerShell</summary>

```powershell
$B = "http://localhost:8000"
$A = @{ Authorization = "Bearer change-me-analyst" }; $R = @{ Authorization = "Bearer change-me-reviewer" }
Invoke-RestMethod -Method Post "$B/datasets" -Headers $A | Format-List
Invoke-RestMethod -Method Post "$B/analyses" -Headers $A -ContentType "application/json" -Body '{"dataset_id": 1}'
(Invoke-RestMethod "$B/analyses/1?include_results=false" -Headers $A).status
Invoke-RestMethod -Method Post "$B/reports" -Headers $A -ContentType "application/json" -Body '{"analysis_id": 1}' | Out-Null
Invoke-RestMethod -Method Patch "$B/reports/1" -Headers $A -ContentType "application/json" `
  -Body ([IO.File]::ReadAllBytes("$PWD\out\report_edits.json")) | Out-Null    # bytes keep UTF-8 intact
Invoke-RestMethod -Method Post "$B/reports/1/submit" -Headers $A | Out-Null
Invoke-RestMethod -Method Post "$B/reports/1/decision" -Headers $R -ContentType "application/json" `
  -Body '{"version": 1, "decision": "approve", "comment": "Checked"}' | Out-Null
(Invoke-RestMethod "$B/reports/1/export" -Headers $A).content.remedies | Format-List id, title
```
Error answers (403/409) show as red text in PowerShell. That is expected.
</details>

## Tests and evaluation

```bash
pytest -q                          # 150 tests, no model needed (3 skip if data/ is missing)
python -m eval.run_eval            # writes eval/results/report.md (add --split tuning for the tuning cases)
py -3 tools/check_pack.py          # run in the pack folder: the input files are unchanged
```

In replay mode the eval report is marked **UNVERIFIED** (it proves the pipeline, not model quality). It
rewrites `eval/results/` with the same numbers; `git checkout eval/results` restores the original.

## Use the real model

```bash
ollama pull qwen2.5:7b                              # about 4.7 GB, once
LLM_MODE=local uvicorn app.main:app --port 8000     # PowerShell: $env:LLM_MODE="local"; uvicorn ...
LLM_MODE=local python -m eval.run_eval              # the eval on the real model (about 2 min)
```

- A full run of 150 answers takes about 23 minutes. Don't use `--reload` and don't edit code during a run.
- If Ollama is off, `POST /analyses` returns 503 at once.
- A local run overwrites `replay/`. Use `git checkout replay` to restore the committed recordings.

| `LLM_MODE` | What it does |
|---|---|
| `replay` (default) | Uses the saved outputs in `replay/`. Same results as the real run, no model needed. |
| `local` | Calls Ollama `qwen2.5:7b` (temperature 0, JSON output) and saves every output to `replay/`. |
| `stub` | Fake outputs for tests. |
| `live` | Not set up (no hosted API access); returns 400. |

## Good to know

- The role comes only from the bearer token. A role or actor name sent in the body is never used.
- Citations are counted but never opened, so all are marked `unverified`.
- After changing `app/schema.sql`, delete `app.db` and run `python -m app.db init` again.
- Known gap: replaying the eval's tuning split differs on one case (c02); see DECISIONS.md.
