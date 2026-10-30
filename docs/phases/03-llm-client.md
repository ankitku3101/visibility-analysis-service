# Phase 03 — LLM client

**Goal:** One client for `local` (Ollama), `replay` and `stub`, with bounded retries and checked output. (SPEC T3, DESIGN §7)

**Build**
- `classify-v1` prompt and output model
- Ollama, replay and stub clients; local runs save outputs for replay
- retry loop with timeout, call limit, size limit and error codes

**Done when**
- tests pass for: timeout then success, permanent timeout, malformed, empty, call limit, replay
- one real Ollama call returns valid output

**Commit:** `feat: LLM client with ollama, replay and stub modes`
