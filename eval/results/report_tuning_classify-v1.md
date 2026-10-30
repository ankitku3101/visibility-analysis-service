# Evaluation report

- Run at: 2026-10-30T09:03:49+00:00 | split: **tuning** | cases: 4
- LLM mode: **local** | model: qwen2.5:7b | versions: prompt classify-v1, category cat-v1, scoring score-v1
- Labels: confirmed by developer on 2026-10-30 before tuning: the 4 'ambiguous' cases (c02, c06, c07, c10) were decided explicitly; the 8 clear cases were accepted as proposed by the AI assistant (labels_v1.json)
- LLM calls: 6 | time: 84.3 s | cost: $0 (local)

## Counts

| Path | eligible | succeeded | failed | skipped |
|---|---|---|---|---|
| llm | 4 | 3 | 1 | 0 |
| baseline | 4 | 4 | 0 | 0 |

## Labels: LLM vs rule-based baseline

| Label / path | TP | FP | FN | precision | recall |
|---|---|---|---|---|---|
| mentioned / llm | 1 | 0 | 1 | 1.0 | 0.5 |
| mentioned / baseline | 2 | 0 | 0 | 1.0 | 1.0 |
| recommended / llm | 0 | 0 | 0 | None | None |
| recommended / baseline | 0 | 1 | 0 | 0.0 | None |
| negative / llm | 1 | 0 | 0 | 1.0 | 1.0 |
| negative / baseline | 1 | 0 | 0 | 1.0 | 1.0 |
| absent / llm | 2 | 0 | 0 | 1.0 | 1.0 |
| absent / baseline | 2 | 0 | 0 | 1.0 | 1.0 |
| cited / llm | 0 | 0 | 0 | None | None |
| cited / baseline | 0 | 0 | 0 | None | None |

| Other | LLM | baseline |
|---|---|---|
| competitors precision | 0.727 | 0.818 |
| competitors recall | 0.889 | 1.0 |
| position exact | 3/4 | 4/4 |
| LLM quotes found in answer | 2/2 | n/a |

## Per case

| case | split | engine | expected | LLM | baseline | LLM ok | base ok |
|---|---|---|---|---|---|---|---|
| c01 | tuning | aimode | men+neg; pos=None; comp=0 | men+neg; pos=None; comp=2 | men+neg; pos=None; comp=0 | ✓ | ✓ |
| c02 | tuning | chatgpt | men; pos=None; comp=1 | failed: evidence_not_found | men+rec; pos=None; comp=2 | ✗ | ✗ |
| c03 | tuning | aimode | absent; pos=None; comp=8 | absent; pos=None; comp=8 | absent; pos=None; comp=9 | ✓ | ✓ |
| c04 | tuning | gemini | absent; pos=None; comp=0 | absent; pos=None; comp=1 | absent; pos=None; comp=0 | ✓ | ✓ |

## Score math (hand-computed points vs score-v1)

12/12 cases match.

## Evidence checks (real report validator on crafted claims)

| probe | expected | found | ok |
|---|---|---|---|
| supported claim | [] | [] | ✓ |
| unsupported claim (quote not in answer) | ['quote_not_found'] | ['quote_not_found'] | ✓ |
| incorrect evidence (right quote, wrong answer) | ['quote_not_found'] | ['quote_not_found'] | ✓ |
| evidence from an unknown response | ['unknown_response'] | ['unknown_response'] | ✓ |
| remedy that does not follow from any diagnostic | ['unknown_diagnostic'] | ['unknown_diagnostic'] | ✓ |

## Failure → fix → regression

**F1** — The first test call (an ad-hoc prompt, before classify-v1) marked c01 'Kasparro is not a widely recognized ... tool' as NOT negative.
- Diagnosis: The prompt asked for 'negative' without defining it. The 7B model read 'not widely recognized' as a neutral description, not as doubt about the brand.
- Change: classify-v1 defines negative explicitly: 'criticises Kasparro, doubts it, warns about it, or says it is unknown, not widely recognized or not established'.
- Regression cases: c01 ✓

## Limits of this evaluation

- Small sample: 10 real + 2 synthetic cases; one wrong label moves precision/recall a lot.
- One human labeller; ambiguous cases (tag 'ambiguous') could reasonably be labelled differently.
- One model run per case (temperature 0); no repeated-run variability study.
- Competitor names are matched loosely (lowercase alphanumeric containment), e.g. 'Semrush (AI Visibility Toolkit)' = 'Semrush'.
- The baseline's tool list was written after reading the data, which flatters the baseline on competitors.
- The grader checks labels and evidence references; it cannot judge whether the report's explanations are right.
