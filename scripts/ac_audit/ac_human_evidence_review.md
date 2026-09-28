# A/C human evidence review

* source: `ac_trace_raw.json` (immutable, OBSERVED) + `ac_evidence_judgment.json` (semantic fields)
* every `relevance` / `evidence_type` / `answerability` / `authority_scope` / `cross_document_needed` cell is a HUMAN call; rows still `PENDING` are reported as NOT REVIEWED, never as irrelevant
* the blank-template signal below is DERIVED from the host canonical detector and is NOT a relevance verdict

## Query A: `根据 Q/GDW 73286.2-2026 查找单芯 220kV 海缆参数`

* query tokens (OBSERVED): `['根据', 'q', 'gdw', '73286', '2', '2026', '查找', '单', '芯', '220kv', '海缆', '参数']`

| rank | stage | chunk | document | Part | score | blank_template (DERIVED) | relevance | evidence_type | answerability | authority_scope | cross_document_needed |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | final | 66f462a9de91e0 | 220kV海底电力电缆系统采购标准+第1部分 | 第1部分 | 0.6396 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 2 | final | 834c0774c8fad3 | 220kV海底电力电缆系统采购标准+第1部分 | 第1部分 | 0.6355 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 3 | final | bc2a6dfa54206e | 220kV海底电力电缆系统采购标准+第1部分 | 第1部分 | 0.6227 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 4 | final | 3fb0a03b92cc70 | 220kV海底电力电缆系统采购标准+第2部分 | 第2部分 | 0.6583 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 5 | final | 646ab90775aa14 | 220kV海底电力电缆系统采购标准+第2部分 | 第2部分 | 0.6484 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 6 | final | 43e96b41579739 | 220kV海底电力电缆系统采购标准+第2部分 | 第2部分 | 0.6478 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 7 | final | 48f12a5a8ce5eb | 220kV海底电力电缆系统采购标准+第1部分 | 第1部分 | 0.6448 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 8 | final | ea4a0fbc49651b | 220kV海底电力电缆系统采购标准+第1部分 | 第1部分 | 0.6431 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 4 | hybrid_pool | 255c187f4e2285 | 220kV海底电力电缆系统采购标准+第2部分 | 第2部分 | 0.6477 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 5 | hybrid_pool | ab96130b7a5d5c | 220kV海底电力电缆系统采购标准+第2部分 | 第2部分 | 0.6456 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 7 | hybrid_pool | 9fa9e164a3e3ca | 220kV海底电力电缆系统采购标准+第3部分 | 第3部分 | 0.6444 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 9 | hybrid_pool | a14eb979072681 | 220kV海底电力电缆系统采购标准+第2部分 | 第2部分 | 0.6430 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 10 | hybrid_pool | 455737939ddb4a | 220kV海底电力电缆系统采购标准+第2部分 | 第2部分 | 0.6403 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 12 | hybrid_pool | 8065ad3f4096ca | 220kV海底电力电缆系统采购标准+第3部分 | 第3部分 | 0.6369 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 14 | hybrid_pool | 8ebd878ace5206 | 220kV海底电力电缆系统采购标准+第2部分 | 第2部分 | 0.6325 | UNKNOWN | PENDING | PENDING | PENDING | PENDING | PENDING |
| 15 | hybrid_pool | f8ebc69e5af7d8 | 220kV海底电力电缆系统采购标准+第1部分 | 第1部分 | 0.6322 | UNKNOWN | PENDING | PENDING | PENDING | PENDING | PENDING |
| 16 | hybrid_pool | af100b79a9e973 | 220kV海底电力电缆系统采购标准+第2部分 | 第2部分 | 0.6308 | UNKNOWN | PENDING | PENDING | PENDING | PENDING | PENDING |
| 17 | hybrid_pool | b5aaf72bcd33d4 | 220kV海底电力电缆系统采购标准+第2部分 | 第2部分 | 0.6290 | UNKNOWN | PENDING | PENDING | PENDING | PENDING | PENDING |
| 18 | hybrid_pool | 161e452916ad5a | 220kV海底电力电缆系统采购标准+第2部分 | 第2部分 | 0.6289 | UNKNOWN | PENDING | PENDING | PENDING | PENDING | PENDING |
| 19 | hybrid_pool | d49e20e1ba5337 | 220kV海底电力电缆系统采购标准+第3部分 | 第3部分 | 0.6287 | UNKNOWN | PENDING | PENDING | PENDING | PENDING | PENDING |

### Evidence recall (REVIEWED rows only; unreviewed rows are excluded, not counted as failures)

* Document-family Recall@8 (`第2部分` present in the final window): NOT REVIEWED
* Authoritative Evidence Recall@8 / @20: FAIL / FAIL  (reviewed 0 of 8, 0 of 20)
* Answerable Evidence Recall@8 / @20: FAIL / FAIL
* best authoritative rank: NONE; best FULL-answerability rank: NONE
* better evidence already retrieved but BEYOND the cut (hybrid ranks 9-20): none reviewed as such

```text
Query A
document_family_recall: NOT REVIEWED
authoritative_recall_at_8: NOT REVIEWED
authoritative_recall_at_20: NOT REVIEWED
answerable_recall_at_8: NOT REVIEWED
answerable_recall_at_20: NOT REVIEWED
best_authoritative_rank: NONE
best_full_rank: NONE
better_evidence_beyond_cutoff: []
cross_document_needed: ['NOT REVIEWED']
```
* root cause: **NOT DETERMINED** until the semantic rows above are filled (a structural classification only becomes defensible with judged evidence)

## Query C: `220kV 三芯海底电缆结构参数`

* query tokens (OBSERVED): `['220kv', '三', '芯', '海底', '电缆', '结构', '参数']`

| rank | stage | chunk | document | Part | score | blank_template (DERIVED) | relevance | evidence_type | answerability | authority_scope | cross_document_needed |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | final | 3fb0a03b92cc70 | 220kV海底电力电缆系统采购标准+第2部分 | 第2部分 | 0.6867 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 2 | final | bac8e77cef90c8 | 220kV海底电力电缆系统采购标准+第1部分 | 第1部分 | 0.6606 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 3 | final | 43e96b41579739 | 220kV海底电力电缆系统采购标准+第2部分 | 第2部分 | 0.6599 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 4 | final | 8065ad3f4096ca | 220kV海底电力电缆系统采购标准+第3部分 | 第3部分 | 0.6502 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 5 | final | ff249ff52cf671 | 220kV海底电力电缆系统采购标准+第1部分 | 第1部分 | 0.6459 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 6 | final | d79d92725b46b0 | 220kV海底电力电缆系统采购标准+第3部分 | 第3部分 | 0.6450 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 7 | final | 48f12a5a8ce5eb | 220kV海底电力电缆系统采购标准+第1部分 | 第1部分 | 0.6294 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 8 | final | d8277d37a03a2b | 220kV海底电力电缆系统采购标准+第2部分 | 第2部分 | 0.6272 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 1 | hybrid_pool | 5f81fce4a4628e | 220kV海底电力电缆系统采购标准+第3部分 | 第3部分 | 0.7022 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 3 | hybrid_pool | 0eb621e18881e7 | 220kV海底电力电缆系统采购标准+第2部分 | 第2部分 | 0.6852 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 4 | hybrid_pool | d1d75672f2dbc3 | 220kV海底电力电缆系统采购标准+第3部分 | 第3部分 | 0.6824 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 5 | hybrid_pool | f96c7773551514 | 220kV海底电力电缆系统采购标准+第3部分 | 第3部分 | 0.6737 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 6 | hybrid_pool | 6e6bb92c7dcdcb | 220kV海底电力电缆系统采购标准+第3部分 | 第3部分 | 0.6726 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 7 | hybrid_pool | c37c0820c0438c | 220kV海底电力电缆系统采购标准+第3部分 | 第3部分 | 0.6724 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 8 | hybrid_pool | 0c919dcd5dbfb7 | 220kV海底电力电缆系统采购标准+第3部分 | 第3部分 | 0.6716 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 9 | hybrid_pool | b5aaf72bcd33d4 | 220kV海底电力电缆系统采购标准+第2部分 | 第2部分 | 0.6686 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 10 | hybrid_pool | ab96130b7a5d5c | 220kV海底电力电缆系统采购标准+第2部分 | 第2部分 | 0.6611 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 11 | hybrid_pool | 83d1e77c201be5 | 220kV海底电力电缆系统采购标准+第2部分 | 第2部分 | 0.6607 | false | PENDING | PENDING | PENDING | PENDING | PENDING |
| 14 | hybrid_pool | e518c08d493651 | 220kV海底电力电缆系统采购标准+第2部分 | 第2部分 | 0.6575 | UNKNOWN | PENDING | PENDING | PENDING | PENDING | PENDING |
| 15 | hybrid_pool | 22ce10ed2fd538 | 220kV海底电力电缆系统采购标准+第2部分 | 第2部分 | 0.6566 | UNKNOWN | PENDING | PENDING | PENDING | PENDING | PENDING |

### Evidence recall (REVIEWED rows only; unreviewed rows are excluded, not counted as failures)

* Document-family Recall@8 (`第3部分` present in the final window): NOT REVIEWED
* Authoritative Evidence Recall@8 / @20: FAIL / FAIL  (reviewed 0 of 8, 0 of 20)
* Answerable Evidence Recall@8 / @20: FAIL / FAIL
* best authoritative rank: NONE; best FULL-answerability rank: NONE
* better evidence already retrieved but BEYOND the cut (hybrid ranks 9-20): none reviewed as such

```text
Query C
document_family_recall: NOT REVIEWED
authoritative_recall_at_8: NOT REVIEWED
authoritative_recall_at_20: NOT REVIEWED
answerable_recall_at_8: NOT REVIEWED
answerable_recall_at_20: NOT REVIEWED
best_authoritative_rank: NONE
best_full_rank: NONE
better_evidence_beyond_cutoff: []
cross_document_needed: ['NOT REVIEWED']
```
* root cause: **NOT DETERMINED** until the semantic rows above are filled (a structural classification only becomes defensible with judged evidence)

## Root-cause classification (only from judged evidence)

**NOT DETERMINED** for both queries: no semantic row has been filled yet, so no
classification of the form candidate-generation / evidence-ranking / cutoff /
cross-document / source-document-insufficiency / blank-template-dominance is supportable.

## Observed failure mechanism (no implementation proposed)

* nothing is asserted yet; the standing rules forbid proposing a fix this round.