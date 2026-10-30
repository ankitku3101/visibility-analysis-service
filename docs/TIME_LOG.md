# Time Log

Started: 30 Oct 2026, 12:00 PM.

| Date | Time | Entry |
|---|---|---|
| 30 Oct | 12:00 | Project started. Read pack and brief, wrote and reviewed `docs/SPEC.md`, added `.gitignore`. |
| 30 Oct | 12:24 | Wrote `docs/DESIGN.md` (layout, tables, API, analysis, scoring, review, eval). |
| 30 Oct | 12:41 | Wrote 8 phase plans in `docs/phases/`, synced 2 small details into DESIGN.md. |
| 30 Oct | 12:52 | Cut phase plans down to short 15-line plans; details go in code. |
| 30 Oct | 12:53 | Final docs review: fixed `.gitignore` hiding `tests/fixtures/`, synced SPEC wording with DESIGN. |
| 30 Oct | 12:57 | Phase 01 done: setup, config, DB schema, errors, auth, `/health`. 9 tests pass. |
| 30 Oct | 13:03 | Phase 01 review: fixed non-ASCII token 500, plain-text 500s, equal tokens; Swagger auth. 12 tests pass. |
| 30 Oct | 13:12 | Phase 02 done: import with row checks and duplicate handling; self-review fixed 3 bugs. 44 tests pass. |
| 30 Oct | 13:20 | Phase 03 done: LLM client (ollama/replay/stub), retries, limits; real call OK. Self-review fixed 2 issues. 67 tests pass. |
| 30 Oct | 13:28 | Phase 04 done: background analysis with evidence checks; local smoke 3/3 OK. Fixed regex hang + quote matching. 94 tests pass. |
| 30 Oct | 13:38 | Phase 05 done: score-v1, groups split branded/unbranded, citation stats. Fixed SPEC citation fact. 106 tests pass. |
| 30 Oct | 13:49 | Phase 06 done: report versions, review rules, export control; full curl flow on real pack OK. 126 tests pass. |
| 30 Oct | 13:56 | Phase 07 part 1: eval harness (baseline, grader, runner, probes), 12 proposed cases. 131 tests pass. Waiting on human labels. |
| 30 Oct | 14:50 | Phase 07 done: labels confirmed, tuned v1→v3 on tuning split (F2, F3), held-out run found injection (F4, fixed). 136 tests pass. |
| 30 Oct | 14:55 | Pre-run review: separate eval replay folder, Ollama preflight (503), context-size check. 140 tests pass. |
| 30 Oct | 15:47 | Full local run 1: 147/150 in 24 min. Diagnosed 3 failures → fixes F5 (quote punctuation) and F6 (retry loop, error text). 145 tests pass. |
| 30 Oct | 17:40 | Full local run 2 (final code): 150/150 in 23 min, F6 retry recovered 2 answers. Replay reproduces it exactly. Eval re-run locally. |
| 30 Oct | 18:00 | Phase 08 done: report from evidence, reject → edit → approve → export demo, `out/analysis.json`, README, DECISIONS. Fresh clone + README in replay: setup to export in under 2 min. |

| 30 Oct | 18:10 | Break excluded from the time count. `out/analysis.json` re-exported as v3: same content, notes corrected to the real active time, re-approved. |

**Break:** 15:48–17:08 (about 1 h 20 min, no work). This is the longest gap between commits (15:48 → 17:48). Run 2's
import started at 17:08:58, which marks the end of the break.

**Total active time: about 4 h 50 min.** That is the wall clock from 12:00 to 18:10 (6 h 10 min) minus the
1 h 20 min break. It includes about 50 min of waiting on the two full local model runs and the local eval runs.

**Unfinished / known gaps**
- Eval replay: the tuning split differs on c02, because recordings are shared between splits. The final split replays exactly.
- Review expiry is described in DECISIONS.md only. Parallel decisions are handled and tested. Parallel analyst edits and multi-process servers are not handled.
- Cited pages were never opened (all citations unverified). There is no resume after a crashed run.
