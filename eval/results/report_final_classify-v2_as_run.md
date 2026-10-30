# Evaluation report

- Run at: 2026-10-30T09:10:53+00:00 | split: **final** | cases: 8
- LLM mode: **local** | model: qwen2.5:7b | versions: prompt classify-v2, category cat-v1, scoring score-v1
- Labels: confirmed by developer on 2026-10-30 before tuning: the 4 'ambiguous' cases (c02, c06, c07, c10) were decided explicitly; the 8 clear cases were accepted as proposed by the AI assistant (labels_v1.json)
- LLM calls: 11 | time: 91.9 s | cost: $0 (local)

## Counts

| Path | eligible | succeeded | failed | skipped |
|---|---|---|---|---|
| llm | 8 | 8 | 0 | 0 |
| baseline | 8 | 8 | 0 | 0 |

## Labels: LLM vs rule-based baseline

| Label / path | TP | FP | FN | precision | recall |
|---|---|---|---|---|---|
| mentioned / llm | 6 | 0 | 0 | 1.0 | 1.0 |
| mentioned / baseline | 6 | 0 | 0 | 1.0 | 1.0 |
| recommended / llm | 1 | 2 | 0 | 0.333 | 1.0 |
| recommended / baseline | 1 | 2 | 0 | 0.333 | 1.0 |
| negative / llm | 1 | 1 | 0 | 0.5 | 1.0 |
| negative / baseline | 1 | 1 | 0 | 0.5 | 1.0 |
| absent / llm | 2 | 0 | 0 | 1.0 | 1.0 |
| absent / baseline | 2 | 0 | 0 | 1.0 | 1.0 |
| cited / llm | 3 | 0 | 0 | 1.0 | 1.0 |
| cited / baseline | 3 | 0 | 0 | 1.0 | 1.0 |

| Other | LLM | baseline |
|---|---|---|
| competitors precision | 0.688 | 0.917 |
| competitors recall | 1.0 | 1.0 |
| position exact | 8/8 | 7/8 |
| LLM quotes found in answer | 11/11 | n/a |

## Per case

| case | split | engine | expected | LLM | baseline | LLM ok | base ok |
|---|---|---|---|---|---|---|---|
| c05 | final | gemini | men+rec; pos=None; comp=0 | men+rec; pos=None; comp=0 | men+rec; pos=None; comp=0 | ✓ | ✓ |
| c06 | final | chatgpt | men; pos=3; comp=2 | men+neg; pos=3; comp=4 | men+rec+neg; pos=None; comp=2 | ✗ | ✗ |
| c07 | final | gemini | men; pos=None; comp=0 | men; pos=None; comp=1 | men; pos=None; comp=1 | ✓ | ✓ |
| c08 | final | aimode | men; pos=None; comp=0 | men+rec; pos=None; comp=1 | men; pos=None; comp=0 | ✗ | ✓ |
| c09 | final | chatgpt | absent; pos=None; comp=6 | absent; pos=None; comp=6 | absent; pos=None; comp=6 | ✓ | ✓ |
| c10 | final | aimode | men+neg; pos=None; comp=0 | men+neg; pos=None; comp=1 | men+neg; pos=None; comp=0 | ✓ | ✓ |
| s01 (synthetic) | final | - | men; pos=None; comp=1 | men+rec; pos=None; comp=1 | men+rec; pos=None; comp=1 | ✗ | ✗ |
| s02 (synthetic) | final | - | absent; pos=None; comp=2 | absent; pos=None; comp=2 | absent; pos=None; comp=2 | ✓ | ✓ |

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

**F2** — Tuning run with classify-v1: c02 failed with evidence_not_found after 3 attempts. The model's quote was correct but used 'single' quotes where the answer has "double" quotes, and all 3 attempts returned exactly the same output.
- Diagnosis: Two problems. (1) Inside its JSON output the model swaps double quotes for single ones, and the quote check treated them as different characters. (2) At temperature 0 a plain retry repeats the same reply, so retrying a content error only wasted calls. Saved in eval/results/report_tuning_classify-v1.md.
- Change: Quote matching now treats all quote marks as one character. Content errors (bad JSON, missing quote) are retried with the previous reply and a short correction; timeouts still retry the same request. Prompt bumped to classify-v2.
- Regression cases: c02 ✗

**F3** — Tuning runs listed non-competitors: 'Third-Party Validation' and 'GEO' (headings) on c01, 'fundraiseinsider.com' on c04 and 'Genezio' on c02 (both only cited as sources).
- Diagnosis: The 7B model copies headings and cited sites into the competitor list. A clearer prompt (classify-v2) removed the headings but not the cited sites.
- Change: Code now keeps a competitor only if its name appears in the answer prose, ignoring URLs and link labels that are just domains (aliases such as 'Otterly.AI' are applied first). Tuning competitor precision went from 0.727 (v1) to 1.0.
- Regression cases: c01 ✓, c04 ✓

## Known disagreements (not tuned away)

- c02: the model keeps calling 'aimed much more at retail and CPG brands' negative; the developer labelled it not negative (an ambiguous case). Not tuned further, to avoid fitting the prompt to one label.

## Limits of this evaluation

- Small sample: 10 real + 2 synthetic cases; one wrong label moves precision/recall a lot.
- One human labeller; ambiguous cases (tag 'ambiguous') could reasonably be labelled differently.
- One model run per case (temperature 0); no repeated-run variability study.
- Competitor names are matched loosely (lowercase alphanumeric containment), e.g. 'Semrush (AI Visibility Toolkit)' = 'Semrush'.
- The baseline's tool list was written after reading the data, which flatters the baseline on competitors.
- The grader checks labels and evidence references; it cannot judge whether the report's explanations are right.
