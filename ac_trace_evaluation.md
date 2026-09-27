# A/C trace evaluation (provenance-tagged)

* source artifact: `ac_trace_raw.json` (immutable; produced by the deployed tracer)
* configuration: {"similarity_threshold": 0.2, "vector_similarity_weight": 0.6, "page": 1, "page_size": 50, "knn_top_k": 1024, "allow_dense_fallback": true, "final_top_n": 8, "keyword_augmentation": "OFF"}
* embedding model id (OBSERVED): `f79e37e5ab7611f18ecb3887d563fb04`
* deployed `Dealer.retrieval` parameters (OBSERVED): `['aggs', 'allow_dense_fallback', 'doc_ids', 'embd_mdl', 'highlight', 'kb_ids', 'knn_num_candidates', 'knn_top_k', 'must_not', 'page', 'page_size', 'question', 'rank_feature', 'rerank_candidates_count', 'rerank_mdl', 'similarity_threshold', 'tenant_ids', 'trace_id', 'vector_similarity_weight']`
* standard-number probe tokens (OBSERVED): `['q', 'gdw', '73286', '2', '2026']`

## Superseded / Invalidated Findings

The following conclusions were reached with a HOST-side benchmark and are hereby
**INVALIDATED** by the deployed trace. They were artifacts of how the host benchmark
constructed its call, not behaviour of the deployed engine:

* "Query A fails lexical recall" - INVALIDATED. Deployed: Part 2 holds 32 of the lexical top 50.
* "Part 2 is absent from the Top-10 / Top-50" - INVALIDATED. Deployed: Part 2 is present and dominant.
* "other-document parameter tables (`4 标准技术参数表`, `5 组件材料配置表`) own the candidate pool" -
  INVALIDATED for the deployed engine: other-document chunks are **0** of the top 50 for Query A.
* "wrong-document lexical collision" as an A/C root cause - INVALIDATED as a candidate-level claim.

Consequently no root-cause classification from that period may be carried forward, and the
Generalization Risk table stays empty until human relevance review exists.

## Benchmark Trust Boundary

| layer | what it may be used for | what it may NOT be used for |
|---|---|---|
| Synthetic / unit tests | mechanism correctness (parser, normalisation, projection, convergence) | stating anything about real retrieval behaviour |
| **Host benchmark** | **development-time auxiliary diagnosis only** | **any root-cause claim about production retrieval** |
| **Controlled deployed trace** | **the basis for statements about real retrieval behaviour** | semantic relevance (it holds no judgement) |
| Human-reviewed corpus | semantic relevance | generalisation |
| Holdout corpus | generalisation | mechanism proof |

## Query A: `根据 Q/GDW 73286.2-2026 查找单芯 220kV 海缆参数`

* query tokens (OBSERVED): `['根据', 'q', 'gdw', '73286', '2', '2026', '查找', '单', '芯', '220kv', '海缆', '参数']`

### Stage summary (all counts OBSERVED)

| stage | total | returned | 第1部分 | 第2部分 | 第3部分 | other-document |
|---|---|---|---|---|---|---|
| stage1_lexical_only | 64 | 50 | 13 | 32 | 5 | 0 |
| stage2_dense_only | 64 | 50 | 12 | 33 | 5 | 0 |
| stage3_hybrid | 64 | 50 | 12 | 33 | 5 | 0 |
| stage6_final_context | None | None | 5 | 3 | 0 | 0 |

* `stage4_reranker`: NOT ACTIVE - the deployed call passes rerank_mdl=None (its own default)
* `stage5_rank_adjustments`: OBSERVED 
* stage 5 rank moves (OBSERVED): [{'chunk_id': '66f462a9de91e03c', 'from': 11, 'to': 1}, {'chunk_id': '834c0774c8fad3e2', 'from': 13, 'to': 2}, {'chunk_id': 'bc2a6dfa54206eab', 'from': 46, 'to': 3}, {'chunk_id': '3fb0a03b92cc70d7', 'from': 1, 'to': 4}, {'chunk_id': '646ab90775aa14a5', 'from': 2, 'to': 5}, {'chunk_id': '43e96b415797394b', 'from': 3, 'to': 6}, {'chunk_id': '48f12a5a8ce5eb6c', 'from': 6, 'to': 7}, {'chunk_id': '455737939ddb4a47', 'from': 10, 'to': 9}]

### Stage transition, by family (counts OBSERVED, Part from the document name)

| family | lexical Top50 | dense Top50 | hybrid Top50 | final window |
|---|---|---|---|---|
| 第1部分 | 13 | 12 | 12 | 5 |
| 第2部分 | 32 | 33 | 33 | 3 |
| 第3部分 | 5 | 5 | 5 | 0 |
| other-document | 0 | 0 | 0 | 0 |

* target family `第2部分` rank per stage: lexical 1 -> dense 1 -> hybrid 1 -> final 4
* Document-family recall (the family appears at all) and Authoritative-evidence recall (the passage states the requirement) are DIFFERENT questions: this artifact answers only the first; the second needs the human review table below.

### Human review table (relevance and evidence type left PENDING_HUMAN_REVIEW)

| rank (OBSERVED) | chunk | document (OBSERVED) | Part (OBSERVED) | family role (DERIVED) | score (OBSERVED) | blank_template (DERIVED) | evidence_type (PENDING_HUMAN_REVIEW) | relevance (PENDING_HUMAN_REVIEW) | snippet (OBSERVED) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 3fb0a03b92cc70 | 220kV海底电力电缆系统采购标准+第2部分：2 | 第2部分 | specific_spec | 0.6583 | false | | | [标准号: Q/GDW 73286.2 | 文档: 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力 |
| 2 | 646ab90775aa14 | 220kV海底电力电缆系统采购标准+第2部分：2 | 第2部分 | specific_spec | 0.6484 | false | | | [标准号: Q/GDW 73286.2 | 文档: 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力 |
| 3 | 43e96b41579739 | 220kV海底电力电缆系统采购标准+第2部分：2 | 第2部分 | specific_spec | 0.6478 | false | | | [标准号: Q/GDW 73286.2 | 文档: 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力 |
| 4 | 255c187f4e2285 | 220kV海底电力电缆系统采购标准+第2部分：2 | 第2部分 | specific_spec | 0.6477 | true | | | [标准号: Q/GDW 73286.2 | 文档: 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力 |
| 5 | ab96130b7a5d5c | 220kV海底电力电缆系统采购标准+第2部分：2 | 第2部分 | specific_spec | 0.6456 | true | | | [标准号: Q/GDW 73286.2 | 文档: 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力 |
| 6 | 48f12a5a8ce5eb | 220kV海底电力电缆系统采购标准+第1部分：通 | 第1部分 | common_spec | 0.6448 | false | | | [标准号: Q/GDW 73286.1 | 文档: 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf  |
| 7 | 9fa9e164a3e3ca | 220kV海底电力电缆系统采购标准+第3部分：2 | 第3部分 | specific_spec | 0.6444 | false | | | [标准号: Q/GDW 73286.3 | 文档: 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力 |
| 8 | ea4a0fbc49651b | 220kV海底电力电缆系统采购标准+第1部分：通 | 第1部分 | common_spec | 0.6431 | false | | | [标准号: Q/GDW 73286.1 | 文档: 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf  |
| 9 | a14eb979072681 | 220kV海底电力电缆系统采购标准+第2部分：2 | 第2部分 | specific_spec | 0.6430 | true | | | [标准号: Q/GDW 73286.2 | 文档: 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力 |
| 10 | 455737939ddb4a | 220kV海底电力电缆系统采购标准+第2部分：2 | 第2部分 | specific_spec | 0.6403 | false | | | [标准号: Q/GDW 73286.2 | 文档: 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力 |
| 11 | 66f462a9de91e0 | 220kV海底电力电缆系统采购标准+第1部分：通 | 第1部分 | common_spec | 0.6396 | false | | | [标准号: Q/GDW 73286.1 | 文档: 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf  |
| 12 | 8065ad3f4096ca | 220kV海底电力电缆系统采购标准+第3部分：2 | 第3部分 | specific_spec | 0.6369 | false | | | [标准号: Q/GDW 73286.3 | 文档: 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力 |
| 13 | 834c0774c8fad3 | 220kV海底电力电缆系统采购标准+第1部分：通 | 第1部分 | common_spec | 0.6355 | UNKNOWN (beyond the text-capture limit) | | |  |
| 14 | 8ebd878ace5206 | 220kV海底电力电缆系统采购标准+第2部分：2 | 第2部分 | specific_spec | 0.6325 | UNKNOWN (beyond the text-capture limit) | | |  |
| 15 | f8ebc69e5af7d8 | 220kV海底电力电缆系统采购标准+第1部分：通 | 第1部分 | common_spec | 0.6322 | UNKNOWN (beyond the text-capture limit) | | |  |
| 16 | af100b79a9e973 | 220kV海底电力电缆系统采购标准+第2部分：2 | 第2部分 | specific_spec | 0.6308 | UNKNOWN (beyond the text-capture limit) | | |  |
| 17 | b5aaf72bcd33d4 | 220kV海底电力电缆系统采购标准+第2部分：2 | 第2部分 | specific_spec | 0.6290 | UNKNOWN (beyond the text-capture limit) | | |  |
| 18 | 161e452916ad5a | 220kV海底电力电缆系统采购标准+第2部分：2 | 第2部分 | specific_spec | 0.6289 | UNKNOWN (beyond the text-capture limit) | | |  |
| 19 | d49e20e1ba5337 | 220kV海底电力电缆系统采购标准+第3部分：2 | 第3部分 | specific_spec | 0.6287 | UNKNOWN (beyond the text-capture limit) | | |  |
| 20 | d415a7ac2958f6 | 220kV海底电力电缆系统采购标准+第2部分：2 | 第2部分 | specific_spec | 0.6284 | UNKNOWN (beyond the text-capture limit) | | |  |

* `blank_template` is DERIVED from the host canonical detector and is NOT a relevance verdict: `true` does not imply relevance 0, and `UNKNOWN` means the detector could not judge that chunk.
### Factual token overlap (OBSERVED tokenizer output)

* `220kV` -> tokens `['220kv']`
  - stage1_lexical_only rank 1 chunk 3fb0a03b92cc70: overlap `['220kv']` coverage 1.0
  - stage1_lexical_only rank 2 chunk 9fa9e164a3e3ca: overlap `['220kv']` coverage 1.0
  - stage1_lexical_only rank 3 chunk 66f462a9de91e0: overlap `['220kv']` coverage 1.0
* `三芯` -> tokens `['三', '芯']`
  - stage1_lexical_only rank 1 chunk 3fb0a03b92cc70: overlap `['芯']` coverage 0.5
  - stage1_lexical_only rank 2 chunk 9fa9e164a3e3ca: overlap `['三', '芯']` coverage 1.0
  - stage1_lexical_only rank 3 chunk 66f462a9de91e0: overlap `[]` coverage 0.0
* `海底电力电缆` -> tokens `['海底', '电力电缆']`
  - stage1_lexical_only rank 1 chunk 3fb0a03b92cc70: overlap `['海底', '电力电缆']` coverage 1.0
  - stage1_lexical_only rank 2 chunk 9fa9e164a3e3ca: overlap `['海底', '电力电缆']` coverage 1.0
  - stage1_lexical_only rank 3 chunk 66f462a9de91e0: overlap `['海底', '电力电缆']` coverage 1.0

### Root-cause evidence (from stage transitions only)

* 第2部分 in lexical Top 50 (OBSERVED): rank 1
* 第2部分 in hybrid Top 50 (OBSERVED): rank 1
* 第2部分 in stage 6 window (OBSERVED): rank 4
* classification: NOT DETERMINED by the observed transitions alone

## Query C: `220kV 三芯海底电缆结构参数`

* query tokens (OBSERVED): `['220kv', '三', '芯', '海底', '电缆', '结构', '参数']`

### Stage summary (all counts OBSERVED)

| stage | total | returned | 第1部分 | 第2部分 | 第3部分 | other-document |
|---|---|---|---|---|---|---|
| stage1_lexical_only | 64 | 50 | 4 | 24 | 22 | 0 |
| stage2_dense_only | 64 | 50 | 3 | 28 | 19 | 0 |
| stage3_hybrid | 64 | 50 | 4 | 24 | 22 | 0 |
| stage6_final_context | None | None | 3 | 3 | 2 | 0 |

* `stage4_reranker`: NOT ACTIVE - the deployed call passes rerank_mdl=None (its own default)
* `stage5_rank_adjustments`: OBSERVED 
* stage 5 rank moves (OBSERVED): [{'chunk_id': '3fb0a03b92cc70d7', 'from': 2, 'to': 1}, {'chunk_id': 'bac8e77cef90c8cf', 'from': 12, 'to': 2}, {'chunk_id': '43e96b415797394b', 'from': 13, 'to': 3}, {'chunk_id': '8065ad3f4096ca30', 'from': 18, 'to': 4}, {'chunk_id': 'ff249ff52cf67152', 'from': 25, 'to': 5}, {'chunk_id': 'd79d92725b46b084', 'from': 26, 'to': 6}, {'chunk_id': '48f12a5a8ce5eb6c', 'from': 40, 'to': 7}, {'chunk_id': 'd8277d37a03a2b0a', 'from': 43, 'to': 8}]

### Stage transition, by family (counts OBSERVED, Part from the document name)

| family | lexical Top50 | dense Top50 | hybrid Top50 | final window |
|---|---|---|---|---|
| 第1部分 | 4 | 3 | 4 | 3 |
| 第2部分 | 24 | 28 | 24 | 3 |
| 第3部分 | 22 | 19 | 22 | 2 |
| other-document | 0 | 0 | 0 | 0 |

* target family `第3部分` rank per stage: lexical 1 -> dense 2 -> hybrid 1 -> final 4
* Document-family recall (the family appears at all) and Authoritative-evidence recall (the passage states the requirement) are DIFFERENT questions: this artifact answers only the first; the second needs the human review table below.

### Human review table (relevance and evidence type left PENDING_HUMAN_REVIEW)

| rank (OBSERVED) | chunk | document (OBSERVED) | Part (OBSERVED) | family role (DERIVED) | score (OBSERVED) | blank_template (DERIVED) | evidence_type (PENDING_HUMAN_REVIEW) | relevance (PENDING_HUMAN_REVIEW) | snippet (OBSERVED) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 5f81fce4a4628e | 220kV海底电力电缆系统采购标准+第3部分：2 | 第3部分 | specific_spec | 0.7022 | true | | | [标准号: Q/GDW 73286.3 | 文档: 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力 |
| 2 | 3fb0a03b92cc70 | 220kV海底电力电缆系统采购标准+第2部分：2 | 第2部分 | specific_spec | 0.6867 | false | | | [标准号: Q/GDW 73286.2 | 文档: 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力 |
| 3 | 0eb621e18881e7 | 220kV海底电力电缆系统采购标准+第2部分：2 | 第2部分 | specific_spec | 0.6852 | true | | | [标准号: Q/GDW 73286.2 | 文档: 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力 |
| 4 | d1d75672f2dbc3 | 220kV海底电力电缆系统采购标准+第3部分：2 | 第3部分 | specific_spec | 0.6824 | true | | | [标准号: Q/GDW 73286.3 | 文档: 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力 |
| 5 | f96c7773551514 | 220kV海底电力电缆系统采购标准+第3部分：2 | 第3部分 | specific_spec | 0.6737 | true | | | [标准号: Q/GDW 73286.3 | 文档: 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力 |
| 6 | 6e6bb92c7dcdcb | 220kV海底电力电缆系统采购标准+第3部分：2 | 第3部分 | specific_spec | 0.6726 | true | | | [标准号: Q/GDW 73286.3 | 文档: 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力 |
| 7 | c37c0820c0438c | 220kV海底电力电缆系统采购标准+第3部分：2 | 第3部分 | specific_spec | 0.6724 | true | | | [标准号: Q/GDW 73286.3 | 文档: 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力 |
| 8 | 0c919dcd5dbfb7 | 220kV海底电力电缆系统采购标准+第3部分：2 | 第3部分 | specific_spec | 0.6716 | true | | | [标准号: Q/GDW 73286.3 | 文档: 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力 |
| 9 | b5aaf72bcd33d4 | 220kV海底电力电缆系统采购标准+第2部分：2 | 第2部分 | specific_spec | 0.6686 | true | | | [标准号: Q/GDW 73286.2 | 文档: 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力 |
| 10 | ab96130b7a5d5c | 220kV海底电力电缆系统采购标准+第2部分：2 | 第2部分 | specific_spec | 0.6611 | true | | | [标准号: Q/GDW 73286.2 | 文档: 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力 |
| 11 | 83d1e77c201be5 | 220kV海底电力电缆系统采购标准+第2部分：2 | 第2部分 | specific_spec | 0.6607 | true | | | [标准号: Q/GDW 73286.2 | 文档: 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力 |
| 12 | bac8e77cef90c8 | 220kV海底电力电缆系统采购标准+第1部分：通 | 第1部分 | common_spec | 0.6606 | false | | | [标准号: Q/GDW 73286.1 | 文档: 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf  |
| 13 | 43e96b41579739 | 220kV海底电力电缆系统采购标准+第2部分：2 | 第2部分 | specific_spec | 0.6599 | UNKNOWN (beyond the text-capture limit) | | |  |
| 14 | e518c08d493651 | 220kV海底电力电缆系统采购标准+第2部分：2 | 第2部分 | specific_spec | 0.6575 | UNKNOWN (beyond the text-capture limit) | | |  |
| 15 | 22ce10ed2fd538 | 220kV海底电力电缆系统采购标准+第2部分：2 | 第2部分 | specific_spec | 0.6566 | UNKNOWN (beyond the text-capture limit) | | |  |
| 16 | 41f10551fa1033 | 220kV海底电力电缆系统采购标准+第2部分：2 | 第2部分 | specific_spec | 0.6564 | UNKNOWN (beyond the text-capture limit) | | |  |
| 17 | a03230e9a7559b | 220kV海底电力电缆系统采购标准+第3部分：2 | 第3部分 | specific_spec | 0.6524 | UNKNOWN (beyond the text-capture limit) | | |  |
| 18 | 8065ad3f4096ca | 220kV海底电力电缆系统采购标准+第3部分：2 | 第3部分 | specific_spec | 0.6502 | UNKNOWN (beyond the text-capture limit) | | |  |
| 19 | 322b5cb7a3e64f | 220kV海底电力电缆系统采购标准+第3部分：2 | 第3部分 | specific_spec | 0.6483 | UNKNOWN (beyond the text-capture limit) | | |  |
| 20 | b878ee18e84b63 | 220kV海底电力电缆系统采购标准+第3部分：2 | 第3部分 | specific_spec | 0.6479 | UNKNOWN (beyond the text-capture limit) | | |  |

* `blank_template` is DERIVED from the host canonical detector and is NOT a relevance verdict: `true` does not imply relevance 0, and `UNKNOWN` means the detector could not judge that chunk.
### Factual token overlap (OBSERVED tokenizer output)

* `220kV` -> tokens `['220kv']`
  - stage1_lexical_only rank 1 chunk 5f81fce4a4628e: overlap `['220kv']` coverage 1.0
  - stage1_lexical_only rank 2 chunk 3fb0a03b92cc70: overlap `['220kv']` coverage 1.0
  - stage1_lexical_only rank 3 chunk 0eb621e18881e7: overlap `['220kv']` coverage 1.0
* `三芯` -> tokens `['三', '芯']`
  - stage1_lexical_only rank 1 chunk 5f81fce4a4628e: overlap `['三', '芯']` coverage 1.0
  - stage1_lexical_only rank 2 chunk 3fb0a03b92cc70: overlap `['芯']` coverage 0.5
  - stage1_lexical_only rank 3 chunk 0eb621e18881e7: overlap `['芯']` coverage 0.5
* `海底电力电缆` -> tokens `['海底', '电力电缆']`
  - stage1_lexical_only rank 1 chunk 5f81fce4a4628e: overlap `['海底', '电力电缆']` coverage 1.0
  - stage1_lexical_only rank 2 chunk 3fb0a03b92cc70: overlap `['海底', '电力电缆']` coverage 1.0
  - stage1_lexical_only rank 3 chunk 0eb621e18881e7: overlap `['海底', '电力电缆']` coverage 1.0

### Root-cause evidence (from stage transitions only)

* 第3部分 in lexical Top 50 (OBSERVED): rank 1
* 第3部分 in hybrid Top 50 (OBSERVED): rank 1
* 第3部分 in stage 6 window (OBSERVED): rank 4
* classification: NOT DETERMINED by the observed transitions alone

## Generalization risk (proposed mechanisms only - nothing implemented)

| Proposed mechanism | Failure it addresses | Generic? | Risk of 73286 overfit | Validation corpus needed |
|---|---|---|---|---|
| (none proposed) | no stage data has been turned into a mechanism yet; the evidence above is the input to that discussion | - | - | - |

Nothing was fixed, tuned or re-run in this round, and no relevance grade was invented: the
`relevance` and `evidence type` columns are marked PENDING because no human has made that call
yet, and this evaluator will not guess on their behalf.