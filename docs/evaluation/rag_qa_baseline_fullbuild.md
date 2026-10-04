# Baseline

Image: my-wenruorag:fullbuild-6892b3c33
Digest: sha256:18711d10f0353a9f37d25611bd81030bd6c6af0f00f764ddf0132b5ad3f7d123

- captured at: 2026-10-02T00:54:31Z (UTC), inside container `e114ffbdf14a`
- revision the image tag names: 6892b3c3370835286d6431d274d13cfb217f1b9d
- deployed source, verified against the repository's git blobs:
  - the image tag `fullbuild-6892b3c33` does NOT identify the code that ran: `rag/retrieval/pipeline.py` in the image is the PRE-PLANNER revision (git blob `da38414bd59b`, last present in commit `138a1a79a`, 2026-09-29) and it routes via `decompose_question()`
  - `rag/retrieval/planner.py` does not exist in the image; at revision `6892b3c33` and at HEAD it does, and `pipeline.py` there is the newer planner version (`compile_retrieval_plan`)
  - `rag/retrieval/__init__.py` also differs from HEAD (HEAD's re-exports the planner symbols)
  - byte-identical to HEAD: `rag/nlp/search.py`, `rag/retrieval/multi_route.py`, `rag/retrieval/rerank.py`, `rag/retrieval/query_router.py`, `rag/retrieval/health.py`, `rag/retrieval/health_bridge.py`, `rag/retrieval/health_producers.py`, `rag/retrieval/decomposition.py`, `rag/retrieval/chunk_profile.py`, `rag/nlp/query.py`, `rag/prompts/generator.py`, `rag/utils/es_conn.py`, `rag/app/tag.py`, `api/db/services/dialog_service.py`, `api/db/cable_defaults.py`, `api/db/db_models.py`
  - the per-file digests below identify the running code directly, so this capture stands on its own regardless of the tag
- deployed-code fingerprint (sha256, first 16): 1acd2aef1856d7ba
  - rag/retrieval/pipeline.py: c9174c52926de66b
  - rag/retrieval/multi_route.py: 9a08bf97d5ca2692
  - rag/retrieval/rerank.py: 4498c2ed2b2ce64d
  - rag/retrieval/planner.py: ABSENT
  - rag/retrieval/query_router.py: 51bf6a62d77f943f
  - rag/nlp/search.py: 2daccc2fe1df3d1c
  - rag/utils/es_conn.py: f12a7367f1a69015

Parameters:

- embedding model: f79e37e5ab7611f18ecb3887d563fb04 via resolve_model_config -> LLMBundle(LLMBundle)
- rerank: workspace default reranker (dialog.rerank_id is empty) -> LLMBundle
- top k (knn_top_k): 1024
- final_top_n (dialog.top_n): 12
- similarity_threshold: 0.55
- vector_similarity_weight: 0.5
- routes_top_k (per-route recall window): pipeline default 12, adapted in memory per question by rag/retrieval/query_router.route_question; not a dialog column (the log shows it raised to 20 for QA-001)
- rerank_candidates_count: 30
- scored window: `similarity` is the RERANKER score: rag/retrieval/rerank.py:759 overwrites the fused score and preserves it in `fused_similarity`. `term_similarity` / `vector_similarity` are the retrieval legs' scores from `score_provenance`
- similarity_threshold effect: 0.55 is above the whole candidate pool, so `_retrieve_route` retried at RECALL_FLOOR=0.2 (rag/retrieval/multi_route.py:303) for every route of every QA above; the window is carried by the rescue path, not by the configured threshold
- max_sub_queries: pipeline default 4
- allow_dense_fallback: pipeline default True
- metadata scope (doc_ids): None - the assistant's meta_data_filter is {} so no document scope is derived
- rank_feature: label_question() - None unless the knowledge base configures tag_kb_ids (recorded per QA)
- keyword augmentation: OFF (dialog.prompt_config['keyword'] = false)
- refine_multiturn: OFF (dialog.prompt_config['refine_multiturn'] = false)
- cross_languages: not configured
- knowledge base: 9463d93eb97511f1938f2592e9bc6fe4 (6 documents, 315 chunks)
- assistant (dialog): 5c8c249eb8e411f180e20bf412cbc55e - 'QA2'
- tenant: a9e28731ab7011f19b833887d563fb04
- answer model: deepseek-v4-flash

## Trace coverage on this build

| required signal | evidence class | note |
|---|---|---|
| effective query | PRODUCTION | retrieve_multi_route's `question` argument. The owning assistant has keyword/refine_multiturn/cross_languages all OFF, so it equals the user question; the raw preprocessor output is logged (dialog_service.py:940) but not returned. |
| keyword extraction (app level) | NOT_OBSERVABLE | rag.prompts.generator.keyword_extraction is an LLM call whose result is concatenated onto the question (dialog_service.py:874); nothing records it. OFF for this assistant, so it does not affect this baseline. hook: record the preprocessor output with the turn. |
| keyword extraction (retrieval level) | CONTROLLED_VARIANT | reproduced offline from the deployed tokenizer via `Dealer.qryr.question(effective_query)` -> (lexical query string, keyword list); no deployed call returns this value. |
| lexical candidates | CONTROLLED_VARIANT | the doc store fuses both legs server-side in ONE request (es_conn.search: weighted_sum of query_string + kNN), so the production call has no lexical-only candidate set. Observed by re-asking at vector_similarity_weight=0.0. hook: a per-leg candidate list returned by the doc store. |
| dense candidates | CONTROLLED_VARIANT | same fusion; observed by re-asking at vector_similarity_weight=1.0. hook: same as above. |
| hybrid ranking | PRODUCTION | per returned chunk: `similarity` (fused/reranked), `term_similarity` (lexical), `vector_similarity` (dense) and `score_provenance{score_kind, mode, selection_score, lexical_selection_score, dense_score, configured_threshold, effective_vector_weight}`. Only the returned window is exposed: the pre-cut ranked pool is not. |
| final top N | PRODUCTION | the returned `chunks` list (dialog.top_n=12) plus `total`/`doc_aggs`. The cut diagnostics (pool size, prose/table mix, quota shortfall) are logged by rag/retrieval/rerank.py `_select` but NOT returned as data. hook: return the cut diagnostics with the result. |
| document metadata | PRODUCTION | per chunk: `docnm_kwd`, `doc_id`, `kb_id`, `doc_type_kwd`, positions/page, the injected `[标准号: ... \| 文档: ... \| 章节: ...]` prefix and its `content_prefix_*` provenance fields. |
| chunk content | PRODUCTION | per chunk: `content_with_weight` (markup preserved) and `content_ltks` (the indexed token stream the lexical leg scores against). |
| route plan (effective sub-queries) | PRODUCTION | each returned chunk carries `retrieval_routes` / `route_hits`, so the routes that reached the window are recoverable from the result itself. In the deployed (pre-planner) revision the route list is produced by `decompose_question()` at rag/retrieval/pipeline.py:280 and is not returned as data; there is no compiled plan or plan_hash in this image. hook: return the route plan with the result. |
| leg health / degradation | PRODUCTION | `retrieval_health` (execution, evidence state, answer action) attached by attach_retrieval_health, plus `route_execution` when a route failed or ran LEXICAL_DEGRADED. |

`PRODUCTION` = recorded from the deployed entry point; `CONTROLLED_VARIANT` = a leg-isolated call this script made, labelled where it appears; `NOT_OBSERVABLE` = the deployed code emits nothing for it.

## QA-001

Question: 根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？

Evidence retrieved:

- benchmark expects: Q/GDW 73286.2-2026 表 1; Q/GDW 73286.3-2026 表 1
- category: table retrieval; exact numeric retrieval
- production returned 12 passage(s) (total reported: 54) from: Q/GDW 73285.3-2026, Q/GDW 73286.1, Q/GDW 73286.2, Q/GDW 73286.3
- compiled route(s) that reached the window (8): Q/GDW 73286.2-2026 标准中单芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围是多少; Q/GDW 73286.2-2026 标准中单芯交联聚乙烯绝缘电力电缆的规格数量是多少; Q/GDW 73286.3-2026 标准中三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围是多少; Q/GDW 73286.3-2026 标准中三芯交联聚乙烯绝缘电力电缆的规格数量是多少; 三芯 根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定， 与 交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多…; 单芯 根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定， 与 交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多…; 根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？; 根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少…
- expected evidence `Q/GDW 73286.2-2026 表 1`: RETRIEVED: designation:73286.2 -> rank 1 (Q/GDW 73286.2); table:1 -> rank 1 (Q/GDW 73286.2)
- expected evidence `Q/GDW 73286.3-2026 表 1`: RETRIEVED: designation:73286.3 -> rank 3 (Q/GDW 73286.3); table:1 -> rank 1 (Q/GDW 73286.2)
- CONTROLLED_VARIANT lexical_only (vector_similarity_weight=0.0): 12 passage(s), top ids ea4a0fbc4965 af74d2eeaaf2 255c187f4e22 c7347587e61a 8065ad3f4096
- CONTROLLED_VARIANT dense_only (vector_similarity_weight=1.0): 12 passage(s), top ids 225d50acc129 b7674387caaf 1b7bdd60ba63 cb91e68e90fd 423069af3135
- CONTROLLED_VARIANT configured_weight (vector_similarity_weight=0.5): 12 passage(s), top ids ea4a0fbc4965 255c187f4e22 af74d2eeaaf2 8065ad3f4096 ab96130b7a5d
- retrieval-level keyword extraction (`Dealer.qryr.question`): 33 term(s) ['根据', 'q', 'gdw', '73286', '2', '2026', '与', 'q', 'gdw', '73286', '3', '2026', '标准表', '1', '的', '规定', '单', '芯与', '三', '芯', '交联', '聚乙烯', '绝缘', '电力电缆', '的', '导体', '标称', '截面', '覆盖范围', '及', '规格', '数量', '各']

Top chunks:

| # | chunk id | designation | part | doc | section | rerank | fused | term | dense | kind | routes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `d5f07f5d24ec3cc7` | Q/GDW 73286.2 | Part 2 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电… | 3 与其他标准/文件的关系 | 0.8015 | - | 0.1851 | 0.9231 | hybrid | 1 |
| 2 | `255c187f4e228542` | Q/GDW 73286.2 | Part 2 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电… | 4 标准技术参数表 | 0.9430 | - | 0.4317 | 0.9495 | hybrid | 4 |
| 3 | `d4d2304290d345b0` | Q/GDW 73286.3 | Part 3 | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电… | 4 标准技术参数表 | 0.9207 | - | 0.3549 | 0.9258 | hybrid | 3 |
| 4 | `423069af31359e65` | Q/GDW 73286.2 | Part 2 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电… | 4 标准技术参数表 | 0.9090 | - | 0.4267 | 0.9468 | hybrid | 2 |
| 5 | `ea4a0fbc49651bc5` | Q/GDW 73286.1 | Part 1 | 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | - | 0.7701 | - | 0.4308 | 0.9386 | hybrid | 5 |
| 6 | `d1d75672f2dbc333` | Q/GDW 73286.3 | Part 3 | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电… | 4 标准技术参数表 | 0.8826 | - | 0.3323 | 0.9131 | hybrid | 1 |
| 7 | `af74d2eeaaf2c4a4` | Q/GDW 73286.1 | Part 1 | 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 5 技术要求 | 0.7328 | - | 0.3477 | 0.9354 | hybrid | 4 |
| 8 | `c7347587e61a3532` | Q/GDW 73286.3 | Part 3 | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电… | - | 0.7309 | - | 0.3552 | 0.9124 | hybrid | 3 |
| 9 | `b7674387caaf661e` | Q/GDW 73285.3-2026 | Part 3 | 110kV海底电力电缆系统采购标准+第3部分：110kV三芯海底电… | - | 0.9387 | - | 0.3122 | 0.9416 | hybrid | 2 |
| 10 | `ab96130b7a5d5c8f` | Q/GDW 73286.2 | Part 2 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电… | 4 标准技术参数表 | 0.7976 | - | 0.2924 | 0.9416 | hybrid | 4 |
| 11 | `0b4e3c1a73c1e334` | Q/GDW 73286.1 | Part 1 | 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 4.1.5 | 0.6677 | - | 0.1904 | 0.9217 | hybrid | 1 |
| 12 | `43e96b415797394b` | Q/GDW 73286.2 | Part 2 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电… | - | 0.6179 | - | 0.2845 | 0.9367 | hybrid | 4 |

`rerank` is the score that ordered this window (`chunk['similarity']` after `rerank_chunks`); `fused` is the retrieval-side hybrid score it replaced, kept in `fused_similarity`; `term` / `dense` are the two retrieval legs. `kind` is `score_provenance.score_kind`, which still says `hybrid` after the reranker has overwritten the score.

Final context:

- passages handed to the answer model: 12 of 12 retrieved; 12944 characters
- designations in the window: Q/GDW 73285.3-2026, Q/GDW 73286.1, Q/GDW 73286.2, Q/GDW 73286.3
- prompt template: `dialog.prompt_config['system']` with `{knowledge}` filled; answer budget 1000000 tokens

Answer:

```
根据 Q/GDW 73286.2—2026（单芯）和 Q/GDW 73286.3—2026（三芯）标准表1的规定，两者的导体标称截面覆盖情况如下：

**单芯电缆（Q/GDW 73286.2—2026）**

覆盖范围从 **400 mm² 到 2000 mm²**，共 **10 种规格**，具体为：400、500、630、800、1000、1200、1400、1600、1800、2000 mm²。

**三芯电缆（Q/GDW 73286.3—2026）**

覆盖范围从 **400 mm² 到 1600 mm²**，共 **8 种规格**，具体为：400、500、630、800、1000、1200、1400、1600 mm²。

简单对比一下：单芯比三芯多出了 **1800 mm² 和 2000 mm²** 两个大截面规格，毕竟单芯海缆在大截面传输上更有优势；而两者的起始截面都是 400 mm²，400 到 1600 mm² 这段区间是重合的。
```

Assessment:

- provenance: EXPLORATORY_JUDGMENT (deterministic evidence probe; NOT a Gold Set)
- expected facts supported by the final context: 5/6
  - YES 单芯 覆盖下界 1×400 mm²
  - YES 单芯 覆盖上界 1×2000 mm²
  - YES 单芯 规格数量 = 10（表中枚举计数，仅对上下文）: enumerated 10 distinct value(s), expected 10 [1000, 1200, 1400, 1600, 1800, 2000, 400, 500, 630, 800]
  - YES 三芯 覆盖下界 3×400 mm²
  - YES 三芯 覆盖上界 3×1600 mm²
  - NO  三芯 规格数量 = 8（表中枚举计数，仅对上下文）: enumerated 9 distinct value(s), expected 8 [1000, 1200, 1400, 1600, 240, 400, 500, 630, 800]
- expected facts stated in the answer: 4/4
- every expected fact that reached the context is stated, and no stated fact lacks a match in the context
- retrieval health: `{"overall": "full", "evidence_completeness": "partial", "degradation_reason": null}`
- rank_feature resolved to None (no tag_kb_ids on this knowledge base)
- production window overlap with the same-weight Dealer.retrieval leg: 7/12 (the two differ by route count and by the reranker)
- answer prompt: dialog.prompt_config['system']

## QA-002

Question: Q/GDW 73285-2026 标准体系由哪些部分构成？各自适用范围是什么？

Evidence retrieved:

- benchmark expects: Part 1 通用技术规范; Part 2 单芯专用技术规范; Part 3 三芯专用技术规范
- category: document hierarchy; cross-document reasoning
- production returned 12 passage(s) (total reported: 18) from: 110kV海底电力电缆系统采购标准+第3部分：110kV三芯海底电力电缆系统专用技术规范.pdf, GB/T 29782-2013, Q/GDW 73285.2-2026, Q/GDW 73285.3-2026
- compiled route(s) that reached the window (3): Q/GDW 73285-2026 各部分的适用范围是什么？; Q/GDW 73285-2026 标准体系由哪些部分构成？; Q/GDW 73285-2026 标准体系由哪些部分构成？各自适用范围是什么？
- expected evidence `Part 1 通用技术规范`: NOT_MATCHABLE (prose-only expected evidence, not a designation or a table marker) - the expected-facts probe below carries the assessment for this QA
- expected evidence `Part 2 单芯专用技术规范`: NOT_MATCHABLE (prose-only expected evidence, not a designation or a table marker) - the expected-facts probe below carries the assessment for this QA
- expected evidence `Part 3 三芯专用技术规范`: NOT_MATCHABLE (prose-only expected evidence, not a designation or a table marker) - the expected-facts probe below carries the assessment for this QA
- CONTROLLED_VARIANT lexical_only (vector_similarity_weight=0.0): 12 passage(s), top ids 72c55b80afb3 920870ddf411 2f92c57b707d 01341cbc098d ed742b19b80b
- CONTROLLED_VARIANT dense_only (vector_similarity_weight=1.0): 12 passage(s), top ids a4f40fa47f80 e171fd29ec04 47d10a245dfb 455737939ddb 86447dd7f1a3
- CONTROLLED_VARIANT configured_weight (vector_similarity_weight=0.5): 12 passage(s), top ids 72c55b80afb3 2f92c57b707d 920870ddf411 e171fd29ec04 47d10a245dfb
- retrieval-level keyword extraction (`Dealer.qryr.question`): 11 term(s) ['q', 'gdw', '73285', '2026', '标准', '体系', '由', '部分', '构成', '各自', '适用范围']

Top chunks:

| # | chunk id | designation | part | doc | section | rerank | fused | term | dense | kind | routes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `72c55b80afb3f211` | Q/GDW 73285.2-2026 | Part 2 | 110kV海底电力电缆系统采购标准+第2部分：110kV单芯海底电… | 5 组件材料配置表 | 0.9929 | - | 0.4917 | 0.9192 | hybrid | 2 |
| 2 | `2f92c57b707d78d8` | 110kV海底电力电缆系统采购标准+第3部分：110kV三… | Part 3 | 110kV海底电力电缆系统采购标准+第3部分：110kV三芯海底电… | - | 0.9800 | - | 0.4297 | 0.9208 | hybrid | 2 |
| 3 | `32ef913fd4027af4` | Q/GDW 73285.2-2026 | Part 2 | 110kV海底电力电缆系统采购标准+第2部分：110kV单芯海底电… | - | 0.9624 | - | 0.4114 | 0.9123 | hybrid | 1 |
| 4 | `3df858bab875a115` | Q/GDW 73285.3-2026 | Part 3 | 110kV海底电力电缆系统采购标准+第3部分：110kV三芯海底电… | - | 0.9599 | - | 0.4114 | 0.9112 | hybrid | 1 |
| 5 | `920870ddf411a6d9` | GB/T 29782-2013 | Part 1 | 110kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | - | 0.9414 | - | 0.4297 | 0.9076 | hybrid | 2 |
| 6 | `ed742b19b80b251d` | Q/GDW 73285.3-2026 | Part 3 | 110kV海底电力电缆系统采购标准+第3部分：110kV三芯海底电… | - | 0.9013 | - | 0.4114 | 0.9230 | hybrid | 3 |
| 7 | `ea885444469f76a5` | GB/T 29782-2013 | Part 1 | 110kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | - | 0.8514 | - | 0.4205 | 0.9063 | hybrid | 1 |
| 8 | `86447dd7f1a32c57` | Q/GDW 73285.3-2026 | Part 3 | 110kV海底电力电缆系统采购标准+第3部分：110kV三芯海底电… | - | 0.8144 | - | 0.4114 | 0.9355 | hybrid | 3 |
| 9 | `57fd5e8f5067285c` | Q/GDW 73285.2-2026 | Part 2 | 110kV海底电力电缆系统采购标准+第2部分：110kV单芯海底电… | - | 0.9306 | - | 0.4205 | 0.9124 | hybrid | 1 |
| 10 | `01341cbc098d1623` | Q/GDW 73285.2-2026 | Part 2 | 110kV海底电力电缆系统采购标准+第2部分：110kV单芯海底电… | - | 0.7858 | - | 0.4114 | 0.9232 | hybrid | 3 |
| 11 | `5979e5c9399e8a69` | Q/GDW 73285.3-2026 | Part 3 | 110kV海底电力电缆系统采购标准+第3部分：110kV三芯海底电… | - | 0.9165 | - | 0.4114 | 0.9165 | hybrid | 1 |
| 12 | `bd8c9f94bc0d2f17` | Q/GDW 73285.3-2026 | Part 3 | 110kV海底电力电缆系统采购标准+第3部分：110kV三芯海底电… | - | 0.8925 | - | 0.4114 | 0.9223 | hybrid | 3 |

`rerank` is the score that ordered this window (`chunk['similarity']` after `rerank_chunks`); `fused` is the retrieval-side hybrid score it replaced, kept in `fused_similarity`; `term` / `dense` are the two retrieval legs. `kind` is `score_provenance.score_kind`, which still says `hybrid` after the reranker has overwritten the score.

Final context:

- passages handed to the answer model: 12 of 12 retrieved; 9365 characters
- designations in the window: 110kV海底电力电缆系统采购标准+第3部分：110kV三芯海底电力电缆系统专用技术规范.pdf, GB/T 29782-2013, Q/GDW 73285.2-2026, Q/GDW 73285.3-2026
- prompt template: `dialog.prompt_config['system']` with `{knowledge}` filled; answer budget 1000000 tokens

Answer:

```
Q/GDW 73285-2026这个标准体系是由三个部分组成的，我给你捋一捋：

**第一部分：通用技术规范**
这部分管的是110kV海底电力电缆系统采购的**一般性技术条款**，说白了就是共性的、面上的要求，不管你是单芯还是三芯，都得满足这些基础条件。

**第二部分：110kV单芯海底电力电缆系统专用技术规范**
这部分是针对**单芯**这个具体形态的，规定了单芯海底电力电缆系统的主要技术参数和工程环境使用条件。也就是说，单芯电缆有自己的"个性要求"，都在这部分里。

**第三部分：110kV三芯海底电力电缆系统专用技术规范**
同理，这部分是针对**三芯**的，规定了三芯海底电力电缆系统的主要技术参数和工程环境使用条件。

---

打个通俗的比方：这就像一套"通用款+定制款"的组合拳。第一部分的通用规范提出的是对110kV海底电力电缆这一大类物资的**共性要求**；第二、第三部分则是针对单芯、三芯这两种具体采购对象的**个性化要求**。

需要特别提醒的是，在实际物资采购过程中，**通用技术规范和对应的某一个专用技术规范是要配套使用的**，两者合在一起才构成完整的招标采购规范技术文件，不能只拿一本就用。
```

Assessment:

- provenance: EXPLORATORY_JUDGMENT (deterministic evidence probe; NOT a Gold Set)
- expected facts supported by the final context: 3/3
  - YES Part 1 通用技术规范
  - YES Part 2 单芯专用技术规范
  - YES Part 3 三芯专用技术规范
- expected facts stated in the answer: 3/3
- every expected fact that reached the context is stated, and no stated fact lacks a match in the context
- retrieval health: `{"overall": "full", "evidence_completeness": "partial", "degradation_reason": null}`
- rank_feature resolved to None (no tag_kb_ids on this knowledge base)
- production window overlap with the same-weight Dealer.retrieval leg: 7/12 (the two differ by route count and by the reranker)
- answer prompt: dialog.prompt_config['system']

## QA-003

Question: 2026版标准相比2019旧版标准，主要进行了哪些重要修订？

Evidence retrieved:

- benchmark expects: 2026 版前言的修订说明; 2019 旧版对照
- category: version comparison; change detection
- production returned 12 passage(s) (total reported: 12) from: 110kV海底电力电缆系统采购标准+第3部分：110kV三芯海底电力电缆系统专用技术规范.pdf, GB/T 29782-2013, Q/GDW 73285.2-2026, Q/GDW 73285.3-2026, Q/GDW 73286.1, Q/GDW 73286.2, Q/GDW 73286.3
- compiled route(s) that reached the window (2): 2026版标准相比2019旧版标准主要进行了哪些重要修订？; 2026版标准相比2019旧版标准，主要进行了哪些重要修订？
- expected evidence `2026 版前言的修订说明`: NOT_MATCHABLE (prose-only expected evidence, not a designation or a table marker) - the expected-facts probe below carries the assessment for this QA
- expected evidence `2019 旧版对照`: NOT_MATCHABLE (prose-only expected evidence, not a designation or a table marker) - the expected-facts probe below carries the assessment for this QA
- CONTROLLED_VARIANT lexical_only (vector_similarity_weight=0.0): 12 passage(s), top ids b800988ce48b 41c89a4c918a b5c1c8847eb2 eb3a0ace463b ae6d0202c1c1
- CONTROLLED_VARIANT dense_only (vector_similarity_weight=1.0): 12 passage(s), top ids ecaeb84e531f 054ae41d1998 67805b5f7879 82de4ff203d9 7de0deabdfbd
- CONTROLLED_VARIANT configured_weight (vector_similarity_weight=0.5): 12 passage(s), top ids 41c89a4c918a b800988ce48b b5c1c8847eb2 6fb51da41261 eb3a0ace463b
- retrieval-level keyword extraction (`Dealer.qryr.question`): 13 term(s) ['2026版标准相比2019旧版标准', '2026', '2019', '旧版', '版', '标准', '标准', '相比', '主要进行了重要修订', '修订', '主要', '进行', '重要']

Top chunks:

| # | chunk id | designation | part | doc | section | rerank | fused | term | dense | kind | routes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `6fb51da412617d98` | Q/GDW 73285.2-2026 | Part 2 | 110kV海底电力电缆系统采购标准+第2部分：110kV单芯海底电… | 5 组件材料配置表 | 0.8466 | - | 0.2634 | 0.8954 | hybrid | 2 |
| 2 | `ae6d0202c1c14e2a` | Q/GDW 73285.2-2026 | Part 2 | 110kV海底电力电缆系统采购标准+第2部分：110kV单芯海底电… | - | 0.7559 | - | 0.2642 | 0.8943 | hybrid | 2 |
| 3 | `5d098aff9be1f511` | Q/GDW 73285.3-2026 | Part 3 | 110kV海底电力电缆系统采购标准+第3部分：110kV三芯海底电… | - | 0.7372 | - | 0.2642 | 0.8933 | hybrid | 2 |
| 4 | `eb3a0ace463b2659` | Q/GDW 73285.2-2026 | Part 2 | 110kV海底电力电缆系统采购标准+第2部分：110kV单芯海底电… | 5 组件材料配置表 | 0.7014 | - | 0.2642 | 0.8944 | hybrid | 2 |
| 5 | `41c89a4c918a6e00` | Q/GDW 73285.2-2026 | Part 2 | 110kV海底电力电缆系统采购标准+第2部分：110kV单芯海底电… | 5 组件材料配置表 | 0.6534 | - | 0.2844 | 0.8898 | hybrid | 2 |
| 6 | `b800988ce48b9a62` | Q/GDW 73285.2-2026 | Part 2 | 110kV海底电力电缆系统采购标准+第2部分：110kV单芯海底电… | 5 组件材料配置表 | 0.5926 | - | 0.3046 | 0.8704 | hybrid | 2 |
| 7 | `b5c1c8847eb28e3f` | GB/T 29782-2013 | Part 1 | 110kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | - | 0.5230 | - | 0.2642 | 0.8995 | hybrid | 2 |
| 8 | `ecaeb84e531f4871` | Q/GDW 73286.3 | Part 3 | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电… | 3 与其他标准/文件的关系 | 0.0751 | - | 0.2363 | 0.9028 | hybrid | 2 |
| 9 | `67805b5f7879d2b9` | Q/GDW 73286.1 | Part 1 | 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 3 与其他标准/文件的关系 | 0.0690 | - | 0.2363 | 0.9018 | hybrid | 2 |
| 10 | `4859566265b332b6` | Q/GDW 73286.1 | Part 1 | 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 8.2.13 | 0.0375 | - | 0.2566 | 0.8860 | hybrid | 2 |
| 11 | `d8277d37a03a2b0a` | Q/GDW 73286.2 | Part 2 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电… | 5 组件材料配置表 | 0.0372 | - | 0.2566 | 0.8824 | hybrid | 2 |
| 12 | `3a813ab441e31df3` | 110kV海底电力电缆系统采购标准+第3部分：110kV三… | Part 3 | 110kV海底电力电缆系统采购标准+第3部分：110kV三芯海底电… | - | 0.0230 | - | 0.2566 | 0.8832 | hybrid | 2 |

`rerank` is the score that ordered this window (`chunk['similarity']` after `rerank_chunks`); `fused` is the retrieval-side hybrid score it replaced, kept in `fused_similarity`; `term` / `dense` are the two retrieval legs. `kind` is `score_provenance.score_kind`, which still says `hybrid` after the reranker has overwritten the score.

Final context:

- passages handed to the answer model: 12 of 12 retrieved; 9761 characters
- designations in the window: 110kV海底电力电缆系统采购标准+第3部分：110kV三芯海底电力电缆系统专用技术规范.pdf, GB/T 29782-2013, Q/GDW 73285.2-2026, Q/GDW 73285.3-2026, Q/GDW 73286.1, Q/GDW 73286.2, Q/GDW 73286.3
- prompt template: `dialog.prompt_config['system']` with `{knowledge}` filled; answer budget 1000000 tokens

Answer:

```
根据知识库中的资料，2026版标准（Q/GDW 73285.2—2026 / Q/GDW 73285.3—2026）相比2019版，主要做了以下几方面的重要修订：

**一、技术参数层面的具体改动**

这次修订最直接的技术变化有两条：

1. **导体结构名称做了更改**——在标准技术参数表（表1）中，对导体结构的命名进行了调整。也就是说，导体的结构形式本身可能没有颠覆性变化，但名称表述更规范了。

2. **删除了绝缘平均厚度的要求**——这是一个比较值得关注的改动。2019版中对绝缘平均厚度是有明确规定的，2026版把这一条从表1里删掉了。这通常意味着对绝缘厚度的管控思路从“规定平均值”转向了其他方式（比如更关注最薄点或偏心度等指标），但知识库中没有进一步展开说明具体原因。

**二、整体修订方向**

从标准的修编说明来看，这次修订还涵盖了以下几个方面：

- **引用标准更新**：对110kV海底电力电缆所引用的标准体系进行了修订提升；
- **原材料和组部件质量要求提高**：明确提到“优质属性部分提高原材料和组部件要求”，目的是提升电缆系统的质量和稳定性；
- **吸收运维检修意见**：修编过程中广泛征求了运维检修人员的意见和建议，从运行角度做了优化。

**三、修编工作背景**

这次修订工作从2023年6月启动，经过修编工作会、差异表专家评审、公开征求意见、送审稿审查等多个环节，于2024年初形成送审文件，最终以2026版发布。参与单位包括国网上海市电力公司、国网物资有限公司、国网浙江省电力公司、中国电力科学研究院等。

---

简单总结就是：**名称改了、绝缘平均厚度要求删了、引用标准和原材料要求提了、运维意见纳入了**。如果您需要了解某一条具体修订的技术细节，我可以再帮您进一步分析。
```

Assessment:

- provenance: EXPLORATORY_JUDGMENT (deterministic evidence probe; NOT a Gold Set)
- expected facts supported by the final context: 2/2
  - YES 更改导体结构名称
  - YES 删除绝缘平均厚度要求
- expected facts stated in the answer: 2/2
- every expected fact that reached the context is stated, and no stated fact lacks a match in the context
- retrieval health: `{"overall": "full", "evidence_completeness": "partial", "degradation_reason": null}`
- rank_feature resolved to None (no tag_kb_ids on this knowledge base)
- production window overlap with the same-weight Dealer.retrieval leg: 12/12 (the two differ by route count and by the reranker)
- answer prompt: dialog.prompt_config['system']

## QA-004

Question: 标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求？

Evidence retrieved:

- benchmark expects: 终端设计使用年限参数; 附件结构资料要求
- category: mixed retrieval; missing evidence detection
- production returned 12 passage(s) (total reported: 18) from: 110kV海底电力电缆系统采购标准+第3部分：110kV三芯海底电力电缆系统专用技术规范.pdf, GB/T 21429-2008, Q/GDW 13285.1-2019, Q/GDW 73285.2-2026, Q/GDW 73285.3-2026, Q/GDW 73286.1, Q/GDW 73286.2, Q/GDW 73286.3
- compiled route(s) that reached the window (5): 标准对电缆附件接头的结构有何要求？; 标准对电缆附件接头的设计使用寿命有何要求？; 标准对电缆附件终端的结构有何要求？; 标准对电缆附件终端的设计使用寿命有何要求？; 标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求？
- expected evidence `终端设计使用年限参数`: NOT_MATCHABLE (prose-only expected evidence, not a designation or a table marker) - the expected-facts probe below carries the assessment for this QA
- expected evidence `附件结构资料要求`: NOT_MATCHABLE (prose-only expected evidence, not a designation or a table marker) - the expected-facts probe below carries the assessment for this QA
- CONTROLLED_VARIANT lexical_only (vector_similarity_weight=0.0): 12 passage(s), top ids 5f81fce4a462 0eb621e18881 5d52c3f6cbe9 ea4a0fbc4965 0cd7b74071f4
- CONTROLLED_VARIANT dense_only (vector_similarity_weight=1.0): 12 passage(s), top ids 824a5f1f11af 9ea7300f4f6f d66a18e51bec 0de976c2ccab 9016014d35f2
- CONTROLLED_VARIANT configured_weight (vector_similarity_weight=0.5): 9 passage(s), top ids 5f81fce4a462 0eb621e18881 5d52c3f6cbe9 0cd7b74071f4 c910968a4a1c
- retrieval-level keyword extraction (`Dealer.qryr.question`): 17 term(s) ['标准对电缆附件', '电缆附件', '电缆', '附件', '标准', '对', '终端与接头', '终端', '接头', '的设计使用寿命与结构有何要求', '使用寿命', '使用', '寿命', '设计', '结构', '要求', '何']

Top chunks:

| # | chunk id | designation | part | doc | section | rerank | fused | term | dense | kind | routes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `0eb621e18881e734` | Q/GDW 73286.2 | Part 2 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电… | 5 组件材料配置表 | 0.8246 | - | 0.3544 | 0.9136 | hybrid | 5 |
| 2 | `7a8dca9e22d2bce1` | Q/GDW 13285.1-2019 | Part 1 | 110kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 5.1.12 外被层 | 0.6929 | - | 0.4071 | 0.9077 | hybrid | 5 |
| 3 | `5f81fce4a4628ebf` | Q/GDW 73286.3 | Part 3 | 220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电… | 4 标准技术参数表 | 0.7782 | - | 0.3544 | 0.9145 | hybrid | 5 |
| 4 | `109c57a8471be6fa` | Q/GDW 73286.1 | Part 1 | 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 5.2.3 修理接头 | 0.6558 | - | 0.3563 | 0.9242 | hybrid | 5 |
| 5 | `c910968a4a1cbc53` | Q/GDW 73285.2-2026 | Part 2 | 110kV海底电力电缆系统采购标准+第2部分：110kV单芯海底电… | - | 0.6177 | - | 0.2730 | 0.9102 | hybrid | 4 |
| 6 | `2bd4a61a1cc33692` | GB/T 21429-2008 | Part 1 | 110kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 6.4 型式试验 | 0.5041 | - | 0.3075 | 0.9072 | hybrid | 4 |
| 7 | `79007bcdc5c36b48` | Q/GDW 73285.3-2026 | Part 3 | 110kV海底电力电缆系统采购标准+第3部分：110kV三芯海底电… | - | 0.4295 | - | 0.1810 | 0.9270 | hybrid | 1 |
| 8 | `d66a18e51bec0e16` | Q/GDW 73286.2 | Part 2 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电… | 4 标准技术参数表 | 0.4270 | - | 0.1709 | 0.9312 | hybrid | 1 |
| 9 | `6d9ec190a4f4179d` | Q/GDW 13285.1-2019 | Part 1 | 110kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | - | 0.3300 | - | 0.3589 | 0.9097 | hybrid | 5 |
| 10 | `efac1853d5f95561` | Q/GDW 73286.1 | Part 1 | 220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 6.6.12 局部放电试验 | 0.3098 | - | 0.3284 | 0.9156 | hybrid | 1 |
| 11 | `9b0947b801d49c2d` | Q/GDW 73286.2 | Part 2 | 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电… | 4 标准技术参数表 | 0.3439 | - | 0.1810 | 0.9279 | hybrid | 1 |
| 12 | `0cd7b74071f4c9b1` | 110kV海底电力电缆系统采购标准+第3部分：110kV三… | Part 3 | 110kV海底电力电缆系统采购标准+第3部分：110kV三芯海底电… | - | 0.2869 | - | 0.2730 | 0.9168 | hybrid | 5 |

`rerank` is the score that ordered this window (`chunk['similarity']` after `rerank_chunks`); `fused` is the retrieval-side hybrid score it replaced, kept in `fused_similarity`; `term` / `dense` are the two retrieval legs. `kind` is `score_provenance.score_kind`, which still says `hybrid` after the reranker has overwritten the score.

Final context:

- passages handed to the answer model: 12 of 12 retrieved; 9550 characters
- designations in the window: 110kV海底电力电缆系统采购标准+第3部分：110kV三芯海底电力电缆系统专用技术规范.pdf, GB/T 21429-2008, Q/GDW 13285.1-2019, Q/GDW 73285.2-2026, Q/GDW 73285.3-2026, Q/GDW 73286.1, Q/GDW 73286.2, Q/GDW 73286.3
- prompt template: `dialog.prompt_config['system']` with `{knowledge}` filled; answer budget 1000000 tokens

Answer:

```
根据知识库中的资料，海缆附件在**设计使用年限**和**结构要求**方面主要有以下规定：

**一、设计使用年限**

标准明确要求终端和接头的设计使用年限**不少于30年**。这个要求同时出现在220kV单芯海缆（终端和接头）以及110kV三芯海缆（终端）的技术规范中，说明30年是海缆附件的基本寿命门槛。

**二、结构要求**

标准对附件结构的要求主要体现在以下几个方面：

**1. 型式试验配套要求**

附件应采用与其电缆**型式试验时配套的附件**——也就是说，终端和接头不能随便单独选，必须和电缆本体是在同一套型式试验体系里验证过的组合。附件的电气和防水性能不得低于海缆本体。

**2. 投标阶段需提供的结构图纸**

标准要求在投标时提供以下附件的结构图纸：户外终端、GIS终端和油浸终端的结构图纸；组合预制直通接头和绝缘接头的结构图纸；整体预制直通接头和绝缘接头的结构图纸；接头铜壳的结构图纸；还有直接接地箱、带保护接地箱及接地电缆的结构图纸。

**3. 工厂接头的专项结构要求**

如果采用工厂接头，标准规定得比较细：接头用的绝缘材料和导体屏蔽材料必须与海缆本体一致；恢复的绝缘厚度不能超过本体绝缘厚度的10%；铅套外径也不能超过电缆铅套外径的10%；此外工厂接头外要有醒目的永久标志，长度不小于5米。

**4. 接头敷设与防水**

接头要满足在水深下长期运行的要求，敷设方式通常为浸水，防水性能也是关键指标。

**5. 终端接口兼容性**

GIS终端方面，标准注明了参照IEC 62271有两种尺寸，投标人应承诺按招标人要求提供与之配套的GIS终端，这一点在采购时需要特别注意对接尺寸。

总结一下，标准对海缆附件的核心逻辑就是：寿命不低于30年，结构必须与电缆本体匹配并在型式试验中整体验证，各项尺寸和材料不能随意偏离本体。
```

Assessment:

- provenance: EXPLORATORY_JUDGMENT (deterministic evidence probe; NOT a Gold Set)
- expected facts supported by the final context: 6/6
  - YES 终端设计使用年限不少于30年
  - YES 户外终端
  - YES GIS终端
  - YES 油浸终端
  - YES 预制直通接头
  - YES 绝缘接头
- expected facts stated in the answer: 6/6
- every expected fact that reached the context is stated, and no stated fact lacks a match in the context
- retrieval health: `{"overall": "full", "evidence_completeness": "partial", "degradation_reason": null}`
- rank_feature resolved to None (no tag_kb_ids on this knowledge base)
- production window overlap with the same-weight Dealer.retrieval leg: 7/12 (the two differ by route count and by the reranker)
- answer prompt: dialog.prompt_config['system']

## QA-005

Question: 110kV海缆系统的耐压试验标准（出厂与安装后）是如何规定的？

Evidence retrieved:

- benchmark expects: 110kV 出厂耐压试验; 110kV 安装后耐压试验
- category: parameter retrieval; engineering specification
- production returned 12 passage(s) (total reported: 49) from: GB/T 21429-2008, Q/GDW 13285.1-2019
- compiled route(s) that reached the window (5): 110kV海缆出厂耐压试验标准是如何规定的？; 110kV海缆安装后耐压试验标准是如何规定的？; 110kV海缆系统的耐压试验标准是如何规定的？; 110kV海缆系统的耐压试验标准（出厂与安装后）是如何规定的？; 110kV海缆系统的耐压试验标准（出厂与安装后）是如何规定的？ 通用技术规范 正文条款
- expected evidence `110kV 出厂耐压试验`: NOT_MATCHABLE (prose-only expected evidence, not a designation or a table marker) - the expected-facts probe below carries the assessment for this QA
- expected evidence `110kV 安装后耐压试验`: NOT_MATCHABLE (prose-only expected evidence, not a designation or a table marker) - the expected-facts probe below carries the assessment for this QA
- CONTROLLED_VARIANT lexical_only (vector_similarity_weight=0.0): 12 passage(s), top ids 5ee5b33ba848 10d03a3b5836 d01712ad6d49 585d1e704c6c 8275cbc9b371
- CONTROLLED_VARIANT dense_only (vector_similarity_weight=1.0): 12 passage(s), top ids 8275cbc9b371 585d1e704c6c e4842832349c 4fe61afb09b2 a017bab8df00
- CONTROLLED_VARIANT configured_weight (vector_similarity_weight=0.5): 12 passage(s), top ids 5ee5b33ba848 d01712ad6d49 8275cbc9b371 585d1e704c6c 10d03a3b5836
- retrieval-level keyword extraction (`Dealer.qryr.question`): 14 term(s) ['110kv', '110kv', '海缆系统的耐压试验标准', '海缆', '标准', '系统', '耐压', '试验', '出厂与安装后', '出厂', '安装', '后', '规定的', '规定']

Top chunks:

| # | chunk id | designation | part | doc | section | rerank | fused | term | dense | kind | routes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `2bd4a61a1cc33692` | GB/T 21429-2008 | Part 1 | 110kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 6.4 型式试验 | 0.9804 | - | 0.2392 | 0.9389 | hybrid | 2 |
| 2 | `a017bab8df00f4be` | GB/T 21429-2008 | Part 1 | 110kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | - | 0.9892 | - | 0.1956 | 0.9390 | hybrid | 1 |
| 3 | `5ee5b33ba848b5f9` | GB/T 21429-2008 | Part 1 | 110kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 6.4 型式试验 | 0.9857 | - | 0.2970 | 0.9349 | hybrid | 3 |
| 4 | `a122748a001c922f` | Q/GDW 13285.1-2019 | Part 1 | 110kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 5.5.1 | 0.9798 | - | 0.2583 | 0.9312 | hybrid | 2 |
| 5 | `febb2f68a7009c91` | GB/T 21429-2008 | Part 1 | 110kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 6.3.8 铠装金属丝测量 | 0.9739 | - | 0.3496 | 0.9191 | hybrid | 3 |
| 6 | `d01712ad6d499d24` | GB/T 21429-2008 | Part 1 | 110kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 6.4 型式试验 | 0.9489 | - | 0.2612 | 0.9321 | hybrid | 5 |
| 7 | `a07e59e3f2c9cd6a` | GB/T 21429-2008 | Part 1 | 110kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 7.2.4 | 0.9410 | - | 0.2152 | 0.9295 | hybrid | 1 |
| 8 | `10d03a3b5836220e` | GB/T 21429-2008 | Part 1 | 110kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 7.2.4 | 0.9385 | - | 0.2612 | 0.9243 | hybrid | 4 |
| 9 | `c01aa1952b570c23` | GB/T 21429-2008 | Part 1 | 110kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 6.4 型式试验 | 0.9358 | - | 0.2493 | 0.9301 | hybrid | 3 |
| 10 | `300b2ade817b6ec1` | GB/T 21429-2008 | Part 1 | 110kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 6.4 型式试验 | 0.9341 | - | 0.2189 | 0.9237 | hybrid | 2 |
| 11 | `e48c0cfa68bb189c` | Q/GDW 13285.1-2019 | Part 1 | 110kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 5.1.12 外被层 | 0.8683 | - | 0.2003 | 0.9177 | hybrid | 1 |
| 12 | `6d64d34d4da3a0e1` | GB/T 21429-2008 | Part 1 | 110kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf | 7.2.4 | 0.8477 | - | 0.2483 | 0.9209 | hybrid | 5 |

`rerank` is the score that ordered this window (`chunk['similarity']` after `rerank_chunks`); `fused` is the retrieval-side hybrid score it replaced, kept in `fused_similarity`; `term` / `dense` are the two retrieval legs. `kind` is `score_provenance.score_kind`, which still says `hybrid` after the reranker has overwritten the score.

Final context:

- passages handed to the answer model: 12 of 12 retrieved; 7845 characters
- designations in the window: GB/T 21429-2008, Q/GDW 13285.1-2019
- prompt template: `dialog.prompt_config['system']` with `{knowledge}` filled; answer budget 1000000 tokens

Answer:

```
110kV海缆系统的耐压试验，在出厂和安装后两个阶段的要求是不一样的，我给您分别捋一捋。

**先说出厂阶段（例行试验）：**

按照标准规定，每一制造长度都要做交流电压试验。具体怎么打呢？就是在导体和金属屏蔽、金属套之间施加 **2.5U₀** 的试验电压，持续 **30分钟**，这期间绝缘不能发生击穿。试验是在室温下进行的。

除了耐压，出厂例行试验还包括局部放电试验——电压先升到1.75U₀保持10秒，然后缓慢降到1.5U₀，在这个电压下试品不应有可检测出的放电，测试系统灵敏度要求10 pC或更优。

如果有工厂接头的话，接头例行试验可以在铠装后一起做。

**再说安装后的电气试验：**

安装完之后要做主绝缘交流电压试验，这个和出厂阶段有明显区别。标准要求对海缆导体和金属屏蔽之间施加 **2U₀** 的交流试验电压，频率范围20 Hz～300 Hz，时间是 **1小时**，电压波形要基本是正弦形。

另外，标准还给了一个替代方案：可以用 **64 kV、24小时** 作为最低试验要求。

安装后除了耐压，还要做时域反射计试验（TDR），用来获取电缆线路行波传输特性的特征标志。

**简单对比一下：**

| 阶段 | 试验电压 | 持续时间 |
|------|---------|---------|
| 出厂 | 2.5U₀ | 30 min |
| 安装后 | 2U₀ | 1 h |
| 安装后（替代） | 64 kV | 24 h |

可以看到，出厂试验电压倍数更高但时间短，安装后电压倍数低一些但持续时间长，这背后是考虑现场条件和电缆已经过运输敷设后的实际状态。

顺便提一句，试验的环境温度一般控制在（20±15）℃，除非特殊试验另有规定。如果您这边有具体的U₀值需要换算成具体电压数字，随时告诉我，我帮您算。
```

Assessment:

- provenance: EXPLORATORY_JUDGMENT (deterministic evidence probe; NOT a Gold Set)
- expected facts supported by the final context: 5/7
  - NO  [benchmark] 出厂 160kV（绝对电压）
  - YES [benchmark] 出厂 30min
  - NO  [benchmark] 安装后 128kV（绝对电压）
  - YES [benchmark] 安装后 60min
  - YES [corpus] 出厂以 U₀ 倍数表述：2.5U₀
  - YES [corpus] 安装后以 U₀ 倍数表述：2U₀
  - YES [corpus] 安装后替代方案：64kV
- expected facts stated in the answer: 5/7
- every expected fact that reached the context is stated, and no stated fact lacks a match in the context
- retrieval health: `{"overall": "full", "evidence_completeness": "partial", "degradation_reason": null}`
- rank_feature resolved to None (no tag_kb_ids on this knowledge base)
- production window overlap with the same-weight Dealer.retrieval leg: 8/12 (the two differ by route count and by the reranker)
- answer prompt: dialog.prompt_config['system']
