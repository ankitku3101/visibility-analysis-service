# Phase 06 — Report and review

**Goal:** Draft report from an analysis, analyst edits and submits, reviewer decides, only approved versions export. (SPEC T6, DESIGN §10)

**Build**
- report content model, draft builder (scores + 3 diagnostic drafts), evidence validator
- version state machine, review events, report endpoints

**Done when** tests show:
- wrong role → 403, no token → 401
- rejected → export blocked
- edit after approval → new draft, old approved version still exports
- decision on an old version → 409, bad quote → 422

**Commit:** `feat: report versions, review workflow and export control`
