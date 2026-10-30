# Phase 05 — Scoring

**Goal:** Turn results into `score-v1` scores with visible parts, counts and failure ranges. Code only. (SPEC T5, DESIGN §9)

**Build**
- per-response points, group stats (engine, category, branded/unbranded), per-prompt table
- competitor counts, citation stats with the dedup rule
- rates among mentioned answers too, so branded results are easy to read

**Done when**
- a hand-calculated example matches the code exactly
- `GET /analyses/{id}` shows `scores` after a run

**Commit:** `feat: deterministic scoring and aggregates`
