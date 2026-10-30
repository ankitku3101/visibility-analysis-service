# Design

How the service in `SPEC.md` is built. If code and this file disagree, fix one of them before moving on.

## 1. Flow

```
POST /datasets  → pack files validated and stored in SQLite
POST /analyses  → background thread, per response: preprocess → LLM → validate in code → save
POST /reports   → draft v1: computed scores + 3 diagnostic drafts with evidence
PATCH (analyst writes explanations + remedies) → submit → reviewer approve/reject → export if approved
```

## 2. Folder layout

```
app/
  main.py, config.py (env → Settings), db.py (`python -m app.db init`), schema.sql,
  errors.py (AppError + handlers), auth.py (bearer token → role dependency)
  ingest/          Pydantic input models, file loader, import service
  llm/             client interface, ollama.py, replay.py, stub.py, prompts.py (template + output model)
  analysis/        preprocess.py, categories.py, runner.py (thread), service.py
  scoring/         score.py, aggregate.py, citations.py
  reports/         models.py (report content), draft.py, validate.py, service.py (state machine)
  api/             health.py, datasets.py, analyses.py, reports.py (thin handlers)
eval/              cases/labels_v1.json, baseline.py, grader.py, run_eval.py, results/
tests/             conftest.py, fixtures/mini_pack/ (made-up data), test_*.py
replay/classify-v1/<response_id>.json   saved raw LLM outputs
out/analysis.json                       approved report export + active time (final output)
```

## 3. Config (env vars, all in `.env.example`)

`DB_PATH=app.db`, `PACK_DIR=.`, `LLM_MODE=replay`, `REPLAY_DIR=replay`, `ANALYST_TOKEN`, `REVIEWER_TOKEN`,
`OLLAMA_URL=http://localhost:11434`, `OLLAMA_MODEL=qwen2.5:7b`, `LLM_TIMEOUT_S=120`, `LLM_MAX_RETRIES=2`, `LLM_MAX_CALLS=450`.

## 4. Database tables

JSON columns are stored as TEXT. `content_hash` = sha256 of the JSON with sorted keys.

| Table | Key columns |
|---|---|
| `datasets` | id, run_id (unique), imported_at, counts (json), rejected_rows (json) |
| `prompts` | prompt_id (PK), dataset_id, text, is_branded, category, content_hash |
| `responses` | response_id (PK), dataset_id, prompt_id, engine, model_version, answer_text, answer_markdown, raw_json, content_hash |
| `citations` | citation_id (PK), response_id, engine, order, citation_type, url, domain, title, raw_json, content_hash |
| `analysis_runs` | id, dataset_id, status, llm_mode, model, prompt_version, category_version, scoring_version, limit, started_at, finished_at, counts (json), llm_calls, llm_seconds, cost_usd |
| `response_results` | id, analysis_id, response_id, status, error_code, skip_reason, mentioned, recommended, negative, evidence (json), competitors (json), ranked_list (json), position, kasparro_cited — unique(analysis_id, response_id) |
| `llm_calls` | id, analysis_id, response_id, attempt, mode, model, prompt_version, status, latency_ms, error |
| `reports` | id, analysis_id, created_by, created_at |
| `report_versions` | id, report_id, version_no, status, content (json), content_hash, created_by, created_at — unique(report_id, version_no) |
| `review_events` | id, report_id, version_no, actor, action, comment, at |

## 5. API

| Method + path | Role | Success | Main errors |
|---|---|---|---|
| `GET /health` | none | 200 | — |
| `POST /datasets` | analyst | 201 new / 200 reused | 409 same ID different content, 422 bad file |
| `POST /analyses` `{dataset_id, limit?}` | analyst | 202 | 404 dataset, 409 run already running |
| `GET /analyses/{id}` | any | 200 | 404 |
| `POST /reports` `{analysis_id}` | analyst | 201 | 409 analysis not completed |
| `GET /reports/{id}` `?version=` | any | 200 | 404 |
| `PATCH /reports/{id}` | analyst | 200 | 422 bad content or evidence |
| `POST /reports/{id}/submit` | analyst | 200 | 409 not a draft, 422 incomplete report |
| `POST /reports/{id}/decision` `{version, decision, comment}` | reviewer | 200 | 409 not latest or not submitted, 422 empty comment |
| `GET /reports/{id}/export` `?version=` | any | 200 | 409 not approved / hash mismatch |

401 = missing or unknown token. 403 = valid token, wrong role. Swagger at `/docs`.
Errors: services raise `AppError(status, code, message, details)`. One handler turns it into
`{"error": {...}}`. FastAPI validation errors and 404s use the same format.

## 6. Import (`POST /datasets`)

- No body → load the pack files from `PACK_DIR` (path is server config, never sent by the caller).
  Body `{prompts, responses, citations, run}` → use those records (used by tests).
- Each row is checked with a Pydantic model that mirrors `schemas/input_contract.json`. Bad rows go into
  `rejected_rows` with the reason. Good rows are saved. Missing file or broken JSON line → 422.
- Duplicates: compare `content_hash` per ID. Same hash → reuse (not counted as new). Different hash →
  whole import is rolled back with 409 and the conflicting IDs listed.

## 7. Analysis

**Preprocess (code):** cut the trailing `[n] https://...` URL list from `answer_text`. Empty text or
`capture_status != captured` → `skipped` with reason. Set `is_branded` and `category` from the prompt.

**Mention (code, not LLM):** `mentioned` = the word "kasparro" (case-insensitive) appears in the cleaned
text. Its quote is the sentence holding the first match. `absent = not mentioned`.

**LLM step** (one call per response, also for absent ones, to get competitors). Prompt `classify-v1`
sends the question and the cleaned answer inside `<answer>` tags and says the text is data, not
instructions. Output model:

```
recommended: bool, recommended_quote: str|null, negative: bool, negative_quote: str|null,
competitors: [str], ranked_list: [str]|null   (only if the answer has an explicit ranked/numbered list)
```

**Validation (code):** JSON must parse and match the model. Output over 8,000 chars → invalid.
Each `true` label needs a quote found in `answer_text` (exact match after collapsing whitespace in both).
If not mentioned, `recommended` and `negative` are forced false. Position = index of Kasparro in
`ranked_list`, else `null`. Competitor names are trimmed and matched against a small alias map.

**Retries:** timeout, connection error, bad JSON, schema error or quote not found → retry, up to
`LLM_MAX_RETRIES` (3 attempts total). Then `failed` with the last error code (`timeout`, `malformed_output`,
`empty_output`, `evidence_not_found`, `call_limit_reached`). One failed response never stops the run.

**Runner:** `threading.Thread`, own SQLite connection (WAL mode, `busy_timeout=5000`), one run at a time,
results saved one by one so `GET` shows progress. On startup, runs left `running` are marked `interrupted`.

**LLM clients:** `OllamaClient` (httpx POST `/api/chat`, settings from SPEC, `num_predict: 1024`). Every
local call's raw output or error is appended to `replay/classify-v1/<id>.json` (id = response_id or eval
case_id). `ReplayClient` plays them back in the same order, so failures replay too; no file → `replay_missing`.
`StubClient` follows a script per id (`ok`, `timeout`, `malformed`, `empty`). Every call goes to `llm_calls`.

## 8. Categories (`cat-v1`)

Keyword rules on the question text, checked in this order, first match wins:
`comparison` (names a rival or says better/vs/compare) → `pricing` (cost, price, worth, retainer, fees) →
`onboarding_access` (setup, onboarding, cancel, sign up, self serve) → `discovery` (what/best tools or
software, alternatives) → `trust_results` (legit, actually work, results, hype, skeptical, safe) →
`features_fit` (everything else). A test checks the per-category counts for all 50 prompts.

## 9. Scoring (`score-v1`)

Per successful response, points out of 100:

| Part | Points | Meaning |
|---|---|---|
| mentioned | 30 | Kasparro named in the answer text |
| recommended | 40 | presented as a suitable option |
| not negative (when mentioned) | 20 | mentioned without negative wording |
| kasparro cited | 10 | at least one citation domain ends with `kasparro.com` |

Group score = average over **succeeded** responses only. Each group also shows:
- the rate of each part as `x/n`, plus total, succeeded, failed and skipped counts
- a range: lowest (failed counted as 0) to highest (failed counted as 100), so failures stay visible
- `low_coverage: true` when succeeded/total < 80%

Groups: engine, category, branded vs unbranded (never merged into one headline number), plus a
per-prompt table showing all 3 engines side by side.

**Citations:** a raw count = every row. A unique count = per response, URL normalised (lowercase host,
no `#fragment`, no `utm_*` params, no trailing `/`). The report shows both, plus the top domains.
All citations are `unverified`.

## 10. Report content and review

Content (Pydantic, `extra=forbid`):
- `scores`: computed, read-only; a PATCH that touches it → 422
- `diagnostics[3]`: `id, title, pattern, explanation, test_evidence, evidence[{response_id, quote}]`
- `remedies[3]`: `id, priority (1-3), title, problem, diagnostic_ids, evidence (same shape), action,
  expected_benefit, effort (low|medium|high), uncertainty, validation_step`
- `notes`

**Draft (code):** fills `scores` and 3 diagnostics (`pattern` + `evidence`) from fixed rules:
(1) unbranded inclusion by engine (when absent, evidence quotes the sentences naming competitors instead),
(2) negative/recommended rate on branded prompts, (3) biggest engine gap on the same prompts.
`explanation`, `test_evidence` and remedies start empty for the analyst.

**Evidence check (`validate.py`)**, run on PATCH and submit: every `response_id` is in this analysis,
every quote is in that answer's text, every `diagnostic_ids` entry exists, and priorities are unique.
Submit also needs exactly 3 complete diagnostics and 3 complete remedies.

```
draft --submit--> submitted --approve--> approved
                            --reject---> rejected
PATCH on draft: edit in place.  PATCH on submitted/approved/rejected: copy → new draft (version + 1).
```

Decision: the body names the `version`. It must be the latest version and `submitted`, else 409.
Export: `?version=N` or the latest. Allowed only if that version is `approved` and its hash still matches.
Export JSON has version, approval event, hashes, llm_mode and version tags. All actions go to `review_events`.

**Auth:** `Authorization: Bearer <token>` compared with `hmac.compare_digest` to the two env tokens.
The actor name comes from the matched token, never from the body.

## 11. Evaluation

- `eval/cases/labels_v1.json`: 10 real responses (all 3 engines, at least 4 categories, mix of absent,
  mentioned, recommended, negative and cited) plus 2 synthetic edge cases marked `synthetic: true`
  (e.g. a prompt-injection text, Kasparro only in the URL list). Each case has `split: tuning|final`,
  expected labels, competitors, position, and why it was picked. Labels written before any tuning.
- `baseline.py`: rules only. Mention by regex. Recommended/negative by keyword lists in the Kasparro
  sentence. Competitors from a fixed name list.
- `grader.py`: per-label precision/recall for LLM vs baseline on the `final` split, competitor
  precision/recall, position exact match, and succeeded/failed/skipped counts. It checks score math
  against hand-computed numbers, and checks evidence with `validate.py`, including one unsupported-quote
  case and one wrong-response-ID case.
- `run_eval.py` writes `eval/results/report.md` + `results.json`, header shows the mode (replay → `unverified`).
- Failure → fix → regression: logged in the report. First candidate: "not widely recognized" missed as
  negative. The fixed case stays in the labels with tag `regression`.

## 12. Tests (pytest, `LLM_MODE=stub`, temp DB per test)

`test_ingest` (bad row, missing file, duplicate same/different content), `test_llm_harness` (timeout →
retry → success, permanent timeout, malformed, empty, call limit), `test_analysis` (one bad response doesn't
affect others, URL list stripped), `test_scoring`, `test_categories`, `test_review` (401, wrong role 403,
reject blocks export, edit after approval → new draft, old version exports, old-version decision 409, no comment 422).
