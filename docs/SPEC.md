# Kasparro AI Visibility Analysis Service

## Why

Kasparro sells AI visibility audits. We have 150 saved AI answers (captured 31 July 2026) and need to know
how Kasparro shows up in them, backed by evidence. A human must review the report before it can be exported.

## What

A Python backend (FastAPI + SQLite) that:

1. Imports the pack: 50 prompts, 150 responses, 2,439 citations. Importing twice does not create duplicates.
2. Analyses every response. Each one ends as `succeeded`, `failed` (with error code) or `skipped` (with reason).
   A successful result has:
   - labels: `absent`, `mentioned`, `recommended`, `negative` (the last three can appear together)
   - an exact quote from the answer for each true label
   - competitors named in the answer, Kasparro's list position (or `null`), and the answer's citations
3. Calculates a visibility score with code. Shows each part of the score and its count (e.g. `4/10`), split by
   engine, prompt category, and branded vs unbranded prompts. Compares the same prompt across the 3 engines.
4. Creates a draft report with scores, 3 diagnostics and 3 remedies.
   - Diagnostic = pattern seen, possible explanation, evidence that would test it, response IDs + quotes.
   - Remedy = problem, evidence, action or investigation, expected benefit, effort, uncertainty,
     how to measure if it worked. Each remedy links to a diagnostic.
5. Controls review: analyst edits and submits, reviewer approves or rejects. Only an approved version exports.
6. Has an evaluation script that compares the LLM against hand-made labels and a simple rule-based baseline.
7. Uses a real local model (Ollama, `qwen2.5:7b`) for analysis. Outputs from that run are saved, so the
   whole app can also run without Ollama in `replay` mode.

Done = every command in Validation passes on a fresh clone in under 10 minutes.

## Constraints

### Must

- Python 3.10+. Dependencies: `fastapi`, `uvicorn`, `pydantic` v2, `httpx`, `python-dotenv`, `pytest`,
  pinned in `requirements.txt`. Use built-in `sqlite3` with plain SQL, no ORM.
- Separate modules for: import, LLM calls, analysis, scoring, storage, review, API. Route handlers only
  call service functions.
- Pack location comes from the `PACK_DIR` env var (default: project root).
- Keep all original IDs as they are (`prompt_id`, `response_id`, `citation_id`, `run_id`).
- Missing values stay `null`. Never guess `model_version`, `publication_date` or `force_web_search`.
- `answer_text` and `answer_markdown` are the same response. Analyse `answer_text` only.
- Before classification, cut off the `Citations:` URL list at the end of `answer_text` (`[n] https://...`
  lines), so a `kasparro.com` link is not read as a mention. Quotes must still be exact substrings of
  `answer_text`.
- LLM is used only for classification (labels, quotes, competitors, position). Counting, scoring,
  categories, validation and permissions are plain code.
- Prompt categories come from a versioned mapping in code based on the question text. Every result records
  the category version, prompt template version and scoring version.
- `LLM_MODE` env var picks the mode: `local` (Ollama), `replay` (saved outputs from a `local` run),
  `stub` (fake outputs for tests), `live` (hosted API, only if the hiring team gives access).
  Default is `replay` so a reviewer can run the app without Ollama.
  Every result and export records which mode produced it.
- Ollama settings: model `qwen2.5:7b`, `temperature: 0`, `format: json`, `num_ctx: 8192`
  (the default context is too small for the longest answers and would cut them off).
- Check every LLM output against a Pydantic model. Limit timeout, retries (max 2), total calls and output
  size. Bad, empty or timed-out output is saved as a failure, never as a guessed result.
- Each analysis run records total LLM calls, total time and cost (`$0` for local).
- Answer text is untrusted. It cannot change roles, permissions or report status.
- User role comes only from the bearer token (`ANALYST_TOKEN`, `REVIEWER_TOKEN` in env). Any role sent in
  the request body is ignored. Permissions:
  - analyst: import, run analysis, create/edit/submit reports
  - reviewer: approve or reject a submitted version (comment required)
  - both: read reports and export approved versions
- Report versions: a submitted version is frozen. Editing a submitted or approved report creates a new
  draft version that needs a new review. Export works only for an approved version. An old approval
  exports only its own old version.
- Every review step is saved with actor, action, version, comment and time.
- Errors return JSON `{ "error": { "code", "message", "details" } }` with the right status:
  400/422 bad input, 401 no token, 403 wrong role, 404 not found, 409 duplicate or wrong state.
- Every number in the report shows its count and total, plus failed and skipped counts.
- Branded prompts (text contains "kasparro") and unbranded prompts are always reported separately.
- Secrets only in `.env`. Commit `.env.example`. The repo must be private. Git-ignore all supplied pack
  files (they are the hiring team's data), `.env` and `*.db`.
- Max 6 hours of work, tracked in `docs/TIME_LOG.md`. List anything left unfinished.

### Must Not

- Edit any supplied pack file (`data/`, `provenance/`, `reference/`, `schemas/`, `fixtures/`, `tools/`,
  `Assignment.*`, `START_HERE.txt`, `PACK_MANIFEST.json`).
- Use the `ai_shortlisting` part of the prompt ID as a category. Make categories from the question text.
- Count a failed or skipped response as `absent` or as a score of zero.
- Treat a mention as a recommendation, or a citation as proof.
- Make up facts about Kasparro or promise ranking gains in remedies.
- Pay for model access or query ChatGPT, Gemini or AI Mode again.
- Use an LLM to grade the LLM. The grader is code.
- Add dependencies not listed above without writing the reason in DESIGN.md.
- Change code outside the current phase.

### Out of Scope

- Frontend, Docker, deployment, crawling, vector search, multiple agents.
- Opening cited URLs. All citations are marked `unverified`.
- New live AI checks or website observations in the report.
- OAuth or user accounts. Two fixed tokens are enough.
- Job queues (Celery, Redis) and resuming a crashed run. One analysis runs at a time in a background thread.
- Review expiry and two reviewers acting at once (mentioned as future work only).

## Current State

New project. Only the supplied pack exists.

- Input data: `data/prompts.jsonl`, `data/responses.jsonl`, `data/citations.jsonl`, `data/run.json`
- Input schema: `schemas/input_contract.json`. Failure cases to test: `fixtures/failure_scenarios.json`
- Pack check: `py -3 tools/check_pack.py` (passes)
- Facts about the data:
  - Prompts 1–25 mention Kasparro by name. Prompts 26–50 do not.
  - `model_version` is null for all 50 AI Mode responses and 5 ChatGPT responses.
  - 149/150 `answer_text` values end with a numbered URL list that `answer_markdown` does not have.
  - Citations: 1,518 inline + 921 sources panel. 180 URLs contain "kasparro" but only 21 are on kasparro.com
    (14 responses); most others are job sites (bebee, getmereferred, iimjobs) and LinkedIn.
- Ollama is installed with `qwen2.5:7b` at `http://localhost:11434`. Measured on the dev machine:
  about 7–10 s per call once the model is loaded, plus about 10 s to load it. A full 150-response run
  takes about 20–25 min.
- In a first test call, the model marked "Kasparro is not a widely recognized... tool" as not negative.
  Use this as an evaluation case.
- Planned folders (DESIGN.md has the details): `app/`, `eval/`, `tests/`, `replay/`, `out/`, `docs/`

## Tasks

Each task has a short plan in `docs/phases/`. Technical decisions live in DESIGN.md.

### T1: Setup and storage

What: Project skeleton, `requirements.txt`, `.env.example`, config loader, SQLite schema, DB init command,
`GET /health`, JSON error handler.
Verify: `python -m app.db init` creates the DB. `GET /health` returns 200. `/docs` loads.

### T2: Import data

What: `POST /datasets` reads and validates the pack files and stores them. Bad rows are listed in the
response and skipped. Good rows are still saved. Missing or unreadable file → 422.
Same `response_id` with same content → reuse. Same ID with different content → 409.
Includes a small made-up test pack in `tests/fixtures/mini_pack/`.
Verify: counts are 50/150/2439. Second import adds nothing. Bad row is listed with the reason.

### T3: LLM client

What: One `LLMClient` interface with `ollama`, `replay` and `stub` versions. A `local` run saves each
output to `replay/` so `replay` mode can reuse it. Versioned prompt template.
Timeout, retry and call limits. Output checked against schema. Each call logged (mode, model, prompt
version, time taken, attempt, status).
Verify: timeout twice then success → succeeded. Always timeout → failed after max retries.
Bad JSON or empty → failed.

### T4: Run analysis

What: `POST /analyses` starts classification in a background thread and returns 202 with the analysis ID.
It accepts an optional `limit` for quick test runs. `GET /analyses/{id}` returns status
(`running/completed/failed/interrupted`), counts (total/succeeded/failed/skipped) and per-response results.
Code checks each quote exists in `answer_text`, links citations, and sets prompt category and branded flag.
Verify: stub run covers all 150 responses. One broken result fails on its own without affecting others.

### T5: Scoring

What: Score calculated by code. Document its scale, parts, weights and how failed responses are handled.
Breakdown by engine, category and branded/unbranded, plus a per-prompt table across the 3 engines.
Includes totals, failed counts and citation stats. Citation dedup rule is written down.
Verify: hand-calculated example matches the code output exactly.

### T6: Report and review

What: `POST /reports` builds a draft from a completed analysis (scores + 3 diagnostic drafts with evidence).
The analyst adds explanations and 3 remedies. Check every referenced response ID and quote exists. Endpoints: `GET /reports/{id}`,
`PATCH /reports/{id}`, `POST /reports/{id}/submit`, `POST /reports/{id}/decision`,
`GET /reports/{id}/export`.
Verify: analyst trying to approve → 403. Rejected → export 409. Edit after approval → new draft that
can't export. Old approved version still exports.

### T7: Evaluation

What: At least 8 hand-labelled responses (all 3 engines, mixed categories) plus 2 made-up edge cases,
clearly marked. Selection reason written down. Tuning cases kept apart from final test cases. Grader gives
precision/recall per label and checks score math separately. Compares LLM vs rule-based baseline.
Includes one wrong-evidence case and one failure → fix → regression case. Grader limits written down.
Verify: `python -m eval.run_eval` writes `eval/results/report.md`. Replay results marked `unverified`.

### T8: Final output and docs

What: Run the full flow. Write:
- `out/analysis.json`: scores, coverage, diagnostics, remedies, time spent
- `README.md`: setup, model download note (~4.7 GB), commands, curl examples, how to switch modes
- `docs/DECISIONS.md`: one page covering scoring, backend and review choices, alternatives, top remedy,
  failure/fix, biggest risk, omissions, questions before release and AI assistance

Verify: fresh clone → follow README → full flow works in replay mode in under 10 minutes.

## Validation

- `py -3 tools/check_pack.py` passes (inputs unchanged).
- `python -m app.db init`, then `uvicorn app.main:app` → `/health` is 200 and `/docs` loads.
- `pytest -q` passes, with tests for: bad input, duplicate import, model timeout, bad model output,
  wrong role, rejection blocks export, edit after approval needs new review.
- `python -m eval.run_eval` writes a report with precision/recall for LLM vs baseline and
  total/succeeded/failed/skipped counts.
- Manual curl run: import → analyse → edit → submit → reject → export blocked →
  edit → submit → approve → export OK → edit again → new draft export blocked.
- `out/analysis.json` covers all 150 responses. Every diagnostic and remedy points to real response IDs
  and exact quotes.
