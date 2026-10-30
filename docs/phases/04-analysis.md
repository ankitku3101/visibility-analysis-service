# Phase 04 — Run analysis

**Goal:** `POST /analyses` classifies every response in a background thread. Each one ends as succeeded, failed or skipped. (SPEC T4, DESIGN §7)

**Build**
- preprocessing (strip the `Citations:` URL list, mention check, quote check)
- per-response analysis, background runner, `GET /analyses/{id}` with progress and counts

**Done when**
- stub run on the real pack accounts for 150/150
- one broken response fails alone; a Kasparro URL in the list is not a mention
- local smoke run with `limit: 3` gives real quotes
- full 150 local run waits until Phase 08 (after prompt tuning)

**Commit:** `feat: background analysis run with evidence checks`
