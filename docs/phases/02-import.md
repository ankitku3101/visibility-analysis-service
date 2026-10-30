# Phase 02 — Import data

**Goal:** `POST /datasets` loads and validates the pack and stores it without duplicates. (SPEC T2, DESIGN §6)

**Build**
- input models matching `schemas/input_contract.json`, file loader, import service
- prompt categories (`cat-v1`) and branded flag (DESIGN §8)
- small made-up test pack in `tests/fixtures/mini_pack/data/`

**Done when**
- real pack imports as 50 / 150 / 2,439; importing again adds nothing
- bad row is listed and skipped, changed content with the same ID → 409, missing file → 422
- `pytest -q` passes

**Commit:** `feat: dataset import with validation and duplicate handling`
