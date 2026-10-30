# Phase 07 — Evaluation

**Goal:** Measure the LLM against hand labels and a rule-based baseline. (SPEC T7, DESIGN §11)

**Build**
- 10 real cases labelled by the developer **before** tuning, plus 2 synthetic ones (prompt injection,
  Kasparro only in the URL list). Include the "not widely recognized" case and the Gemini refusal.
- baseline rules, grader, `python -m eval.run_eval` → `eval/results/report.md`
- tune the prompt on the tuning split only; log one failure → fix → regression case

**Done when**
- the report shows LLM vs baseline precision/recall, counts and the failure log
- the final split was run once in local mode after the prompt was frozen

**Commit:** `feat: evaluation cases, grader, baseline and report`
