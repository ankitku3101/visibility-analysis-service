-- All tables. JSON columns are TEXT. Timestamps are ISO-8601 UTC text.

CREATE TABLE IF NOT EXISTS datasets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        TEXT NOT NULL UNIQUE,
    imported_at   TEXT NOT NULL,
    counts        TEXT NOT NULL DEFAULT '{}',
    rejected_rows TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS prompts (
    prompt_id    TEXT PRIMARY KEY,
    dataset_id   INTEGER NOT NULL REFERENCES datasets(id),
    text         TEXT NOT NULL,
    is_branded   INTEGER NOT NULL CHECK (is_branded IN (0, 1)),
    category     TEXT,
    content_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS responses (
    response_id     TEXT PRIMARY KEY,
    dataset_id      INTEGER NOT NULL REFERENCES datasets(id),
    prompt_id       TEXT NOT NULL REFERENCES prompts(prompt_id),
    engine          TEXT NOT NULL CHECK (engine IN ('aimode', 'chatgpt', 'gemini')),
    model_version   TEXT,
    answer_text     TEXT NOT NULL,
    answer_markdown TEXT,
    raw_json        TEXT NOT NULL,
    content_hash    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS citations (
    citation_id   TEXT PRIMARY KEY,
    response_id   TEXT NOT NULL REFERENCES responses(response_id),
    engine        TEXT NOT NULL CHECK (engine IN ('aimode', 'chatgpt', 'gemini')),
    "order"       INTEGER NOT NULL CHECK ("order" >= 1),
    citation_type TEXT NOT NULL CHECK (citation_type IN ('inline_hyperlink', 'sources_panel')),
    url           TEXT NOT NULL,
    domain        TEXT,
    title         TEXT,
    raw_json      TEXT NOT NULL,
    content_hash  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    dataset_id       INTEGER NOT NULL REFERENCES datasets(id),
    status           TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'interrupted')),
    llm_mode         TEXT NOT NULL,
    model            TEXT,
    prompt_version   TEXT NOT NULL,
    category_version TEXT NOT NULL,
    scoring_version  TEXT NOT NULL,
    "limit"          INTEGER,
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    counts           TEXT NOT NULL DEFAULT '{}',
    llm_calls        INTEGER NOT NULL DEFAULT 0,
    llm_seconds      REAL NOT NULL DEFAULT 0,
    cost_usd         REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS response_results (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id    INTEGER NOT NULL REFERENCES analysis_runs(id),
    response_id    TEXT NOT NULL REFERENCES responses(response_id),
    status         TEXT NOT NULL CHECK (status IN ('succeeded', 'failed', 'skipped')),
    error_code     TEXT,
    skip_reason    TEXT,
    mentioned      INTEGER CHECK (mentioned IN (0, 1)),
    recommended    INTEGER CHECK (recommended IN (0, 1)),
    negative       INTEGER CHECK (negative IN (0, 1)),
    evidence       TEXT NOT NULL DEFAULT '{}',
    competitors    TEXT NOT NULL DEFAULT '[]',
    ranked_list    TEXT,
    position       INTEGER,
    kasparro_cited INTEGER CHECK (kasparro_cited IN (0, 1)),
    UNIQUE (analysis_id, response_id)
);

CREATE TABLE IF NOT EXISTS llm_calls (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id    INTEGER REFERENCES analysis_runs(id),
    response_id    TEXT NOT NULL,
    attempt        INTEGER NOT NULL,
    mode           TEXT NOT NULL,
    model          TEXT,
    prompt_version TEXT NOT NULL,
    status         TEXT NOT NULL,
    latency_ms     INTEGER,
    error          TEXT
);

CREATE TABLE IF NOT EXISTS reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    analysis_id INTEGER NOT NULL REFERENCES analysis_runs(id),
    created_by  TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS report_versions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id    INTEGER NOT NULL REFERENCES reports(id),
    version_no   INTEGER NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('draft', 'submitted', 'approved', 'rejected')),
    content      TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_by   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    UNIQUE (report_id, version_no)
);

CREATE TABLE IF NOT EXISTS review_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id  INTEGER NOT NULL REFERENCES reports(id),
    version_no INTEGER NOT NULL,
    actor      TEXT NOT NULL,
    action     TEXT NOT NULL CHECK (action IN ('create', 'edit', 'submit', 'approve', 'reject', 'export')),
    comment    TEXT,
    at         TEXT NOT NULL
);
