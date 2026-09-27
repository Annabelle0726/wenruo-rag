# Retrieval Reproducibility — P0 FIRST_DIVERGENCE_STAGE

Read-only instrumentation. Answer Synthesis is paused: this round generates no answer at all.

- Runs per query per series: 10 (series A = chat model present, series B = chat_mdl=None)
- Frozen parameters: `{"similarity_threshold": 0.2, "vector_similarity_weight": 0.6, "routes_top_k": 12, "final_top_n": 8, "knn_top_k": 1024, "max_sub_queries": 4, "allow_dense_fallback": true}`
- Chat model path: `TENANT_CONFIGURED_CHAT_MODEL (get_tenant_default_model_by_type(tenant, LLMType.CHAT) -> LLMBundle)`
- Chat model calls during the whole round: 3 (all from the pipeline's own decomposition path)

## 1. Reproducibility Set

| id | class | origin | query |
| --- | --- | --- | --- |
| S_A1 | CANDIDATE_STABLE | previous turn 1 (Session A round 1) | Q/GDW 73286.2-2026 是什么标准？ |
| S_A3 | CANDIDATE_STABLE | previous turn 3 (Session A round 3) | 那 220kV 单芯海底电缆的主要结构有哪些？ |
| S_B1 | CANDIDATE_STABLE | previous turn 7 (Session B round 1) | 220kV 三芯海底电缆一般有哪些主要结构？ |
| S_C3 | CANDIDATE_STABLE | previous turn 15 (Session C round 3) | 哪些要求是它们共同的？ |
| U_A2 | CANDIDATE_UNSTABLE | previous turn index 2 (divergent) | 这个标准适用于什么类型的电缆？ |
| U_A4 | CANDIDATE_UNSTABLE | previous turn index 4 (divergent) | 导体、内衬层和铠装层分别有什么技术要求？ |
| U_A5 | CANDIDATE_UNSTABLE | previous turn index 5 (divergent) | 这些要求都是这个专用技术规范自己规定的吗？ |
| U_B6 | CANDIDATE_UNSTABLE | previous turn index 12 (divergent) | 那你把专用规范和通用规范的要求区分开告诉我。 |
| U_C1 | CANDIDATE_UNSTABLE | previous turn index 13 (divergent) | 220kV 单芯和三芯海底电缆的技术要求有什么区别？ |
| K_STD | CRITICAL_BUSINESS | new (standard number + numeric demand) | Q/GDW 73286.2-2026 中 220kV 单芯海底电缆内衬层厚度要求是多少？ |
| K_3CORE | CRITICAL_BUSINESS | new (natural-language three-core) | 请说明 220kV 三芯海底电缆的主要结构以及铠装层的一般要求。 |
| K_LAYER | CRITICAL_BUSINESS | new (内衬层/铠装层 requirement lookup) | 220kV 单芯海底电缆的内衬层和铠装层分别有什么技术要求？ |

## 2. Embedding determinism (10 encodes per query)

| query | dim | unique sha256 | bit-identical | pairwise cosine min | verdict |
| --- | --- | --- | --- | --- | --- |
| S_A1 | None | None/None | None | None | None |
| S_A3 | None | None/None | None | None | None |
| S_B1 | None | None/None | None | None | None |
| S_C3 | None | None/None | None | None | None |
| U_A2 | None | None/None | None | None | None |
| U_A4 | None | None/None | None | None | None |
| U_A5 | None | None/None | None | None | None |
| U_B6 | None | None/None | None | None | None |
| U_C1 | None | None/None | None | None | None |
| K_STD | None | None/None | None | None | None |
| K_3CORE | None | None/None | None | None | None |
| K_LAYER | None | None/None | None | None | None |

## 3. First divergence stage and window statistics

| query | series | first divergence stage | EMR vs run 1 | distinct windows | Jaccard@K mean | cutoff flag | classification |
| --- | --- | --- | --- | --- | --- | --- | --- |
| S_A1 | A | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |
| S_A1 | B | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |
| S_A3 | A | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |
| S_A3 | B | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |
| S_B1 | A | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |
| S_B1 | B | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |
| S_C3 | A | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |
| S_C3 | B | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |
| U_A2 | A | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |
| U_A2 | B | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |
| U_A4 | A | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |
| U_A4 | B | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |
| U_A5 | A | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |
| U_A5 | B | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |
| U_B6 | A | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |
| U_B6 | B | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |
| U_C1 | A | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |
| U_C1 | B | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |
| K_STD | A | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |
| K_STD | B | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |
| K_3CORE | A | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |
| K_3CORE | B | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |
| K_LAYER | A | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |
| K_LAYER | B | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1 | 1.0 | NOT_OBSERVABLE | STABLE |

## 4. Stage-by-stage verdict per query

### S_A1 — Q/GDW 73286.2-2026 是什么标准？

**A_chat_model_present**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

**B_chat_model_absent**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

### S_A3 — 那 220kV 单芯海底电缆的主要结构有哪些？

**A_chat_model_present**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

**B_chat_model_absent**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

### S_B1 — 220kV 三芯海底电缆一般有哪些主要结构？

**A_chat_model_present**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

**B_chat_model_absent**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

### S_C3 — 哪些要求是它们共同的？

**A_chat_model_present**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

**B_chat_model_absent**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

### U_A2 — 这个标准适用于什么类型的电缆？

**A_chat_model_present**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

**B_chat_model_absent**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

### U_A4 — 导体、内衬层和铠装层分别有什么技术要求？

**A_chat_model_present**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

**B_chat_model_absent**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

### U_A5 — 这些要求都是这个专用技术规范自己规定的吗？

**A_chat_model_present**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

**B_chat_model_absent**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

### U_B6 — 那你把专用规范和通用规范的要求区分开告诉我。

**A_chat_model_present**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

**B_chat_model_absent**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

### U_C1 — 220kV 单芯和三芯海底电缆的技术要求有什么区别？

**A_chat_model_present**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

**B_chat_model_absent**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

### K_STD — Q/GDW 73286.2-2026 中 220kV 单芯海底电缆内衬层厚度要求是多少？

**A_chat_model_present**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

**B_chat_model_absent**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

### K_3CORE — 请说明 220kV 三芯海底电缆的主要结构以及铠装层的一般要求。

**A_chat_model_present**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

**B_chat_model_absent**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

### K_LAYER — 220kV 单芯海底电缆的内衬层和铠装层分别有什么技术要求？

**A_chat_model_present**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

**B_chat_model_absent**

- first divergence: `NONE_UP_TO_FINAL_SELECTION`

  - query_decomposition: IDENTICAL
  - effective_retrieval_question: NOT_OBSERVABLE
  - per_route_candidates: NOT_OBSERVABLE
  - fused_pool_before_cut: IDENTICAL
  - final_selection: IDENTICAL
- effective retrieval questions per run: [[], []] (first two runs)
- route labels observed: []
- error(s): none

## 5. Window overlap detail

| query | series | always present | usually present | borderline | rare | most common window share |
| --- | --- | --- | --- | --- | --- | --- |
| S_A1 | A | 8 | 0 | 0 | 0 | 10/10 |
| S_A1 | B | 8 | 0 | 0 | 0 | 10/10 |
| S_A3 | A | 8 | 0 | 0 | 0 | 10/10 |
| S_A3 | B | 8 | 0 | 0 | 0 | 10/10 |
| S_B1 | A | 8 | 0 | 0 | 0 | 10/10 |
| S_B1 | B | 8 | 0 | 0 | 0 | 10/10 |
| S_C3 | A | 8 | 0 | 0 | 0 | 10/10 |
| S_C3 | B | 8 | 0 | 0 | 0 | 10/10 |
| U_A2 | A | 8 | 0 | 0 | 0 | 10/10 |
| U_A2 | B | 8 | 0 | 0 | 0 | 10/10 |
| U_A4 | A | 8 | 0 | 0 | 0 | 10/10 |
| U_A4 | B | 8 | 0 | 0 | 0 | 10/10 |
| U_A5 | A | 8 | 0 | 0 | 0 | 10/10 |
| U_A5 | B | 8 | 0 | 0 | 0 | 10/10 |
| U_B6 | A | 8 | 0 | 0 | 0 | 10/10 |
| U_B6 | B | 8 | 0 | 0 | 0 | 10/10 |
| U_C1 | A | 8 | 0 | 0 | 0 | 10/10 |
| U_C1 | B | 8 | 0 | 0 | 0 | 10/10 |
| K_STD | A | 8 | 0 | 0 | 0 | 10/10 |
| K_STD | B | 8 | 0 | 0 | 0 | 10/10 |
| K_3CORE | A | 8 | 0 | 0 | 0 | 10/10 |
| K_3CORE | B | 8 | 0 | 0 | 0 | 10/10 |
| K_LAYER | A | 8 | 0 | 0 | 0 | 10/10 |
| K_LAYER | B | 8 | 0 | 0 | 0 | 10/10 |

## 6. Cutoff near-ties (Top-8 cut)

| query | series | cutoff delta min | cutoff delta max | min adjacent delta in window | flag |
| --- | --- | --- | --- | --- | --- |
| S_A1 | A | None | None | 0.001824 | NOT_OBSERVABLE |
| S_A1 | B | None | None | 0.002144 | NOT_OBSERVABLE |
| S_A3 | A | None | None | 0.000166 | NOT_OBSERVABLE |
| S_A3 | B | None | None | 0.000166 | NOT_OBSERVABLE |
| S_B1 | A | None | None | 0.000639 | NOT_OBSERVABLE |
| S_B1 | B | None | None | 0.000639 | NOT_OBSERVABLE |
| S_C3 | A | None | None | 2.9e-05 | NOT_OBSERVABLE |
| S_C3 | B | None | None | 2.9e-05 | NOT_OBSERVABLE |
| U_A2 | A | None | None | 0.000172 | NOT_OBSERVABLE |
| U_A2 | B | None | None | 0.000482 | NOT_OBSERVABLE |
| U_A4 | A | None | None | 0.00187 | NOT_OBSERVABLE |
| U_A4 | B | None | None | 0.004389 | NOT_OBSERVABLE |
| U_A5 | A | None | None | 0.000111 | NOT_OBSERVABLE |
| U_A5 | B | None | None | 0.000127 | NOT_OBSERVABLE |
| U_B6 | A | None | None | 0.000244 | NOT_OBSERVABLE |
| U_B6 | B | None | None | 0.000325 | NOT_OBSERVABLE |
| U_C1 | A | None | None | 5.5e-05 | NOT_OBSERVABLE |
| U_C1 | B | None | None | 0.000336 | NOT_OBSERVABLE |
| K_STD | A | None | None | 0.000162 | NOT_OBSERVABLE |
| K_STD | B | None | None | 0.000162 | NOT_OBSERVABLE |
| K_3CORE | A | None | None | 0.00117 | NOT_OBSERVABLE |
| K_3CORE | B | None | None | 0.000753 | NOT_OBSERVABLE |
| K_LAYER | A | None | None | 0.000294 | NOT_OBSERVABLE |
| K_LAYER | B | None | None | 0.000142 | NOT_OBSERVABLE |

### Per-run cutoff detail (series A)

**S_A1**: run1: last=9ac2797e006f5b84@0.7984255800858888 first_out=8ebd878ace520649@None delta=None; run2: last=9ac2797e006f5b84@0.7984255800858888 first_out=8ebd878ace520649@None delta=None; run3: last=9ac2797e006f5b84@0.7984255800858888 first_out=8ebd878ace520649@None delta=None

**S_A3**: run1: last=e518c08d493651a2@0.44905392561257207 first_out=0eb621e18881e734@None delta=None; run2: last=e518c08d493651a2@0.44905392561257207 first_out=0eb621e18881e734@None delta=None; run3: last=e518c08d493651a2@0.44905392561257207 first_out=0eb621e18881e734@None delta=None

**S_B1**: run1: last=cc4443ca2f4783ac@0.44573693148243054 first_out=bc2a6dfa54206eab@None delta=None; run2: last=cc4443ca2f4783ac@0.44573693148243054 first_out=bc2a6dfa54206eab@None delta=None; run3: last=cc4443ca2f4783ac@0.44573693148243054 first_out=bc2a6dfa54206eab@None delta=None

**S_C3**: run1: last=f224470a51f32350@0.5992253122399923 first_out=db3b79c036360d3c@None delta=None; run2: last=f224470a51f32350@0.5992253122399923 first_out=db3b79c036360d3c@None delta=None; run3: last=f224470a51f32350@0.5992253122399923 first_out=db3b79c036360d3c@None delta=None

**U_A2**: run1: last=2491aa2ce5eacd8d@0.6252253164781943 first_out=d17f1d620732e24d@None delta=None; run2: last=2491aa2ce5eacd8d@0.6252253164781943 first_out=d17f1d620732e24d@None delta=None; run3: last=2491aa2ce5eacd8d@0.6252253164781943 first_out=d17f1d620732e24d@None delta=None

**U_A4**: run1: last=663de80696a67296@0.61435772190166 first_out=5ab5e9b5f2bf95e9@None delta=None; run2: last=663de80696a67296@0.61435772190166 first_out=5ab5e9b5f2bf95e9@None delta=None; run3: last=663de80696a67296@0.61435772190166 first_out=5ab5e9b5f2bf95e9@None delta=None

**U_A5**: run1: last=d5f07f5d24ec3cc7@0.6877997131446925 first_out=c3a92b28cfd524d3@None delta=None; run2: last=d5f07f5d24ec3cc7@0.6877997131446925 first_out=c3a92b28cfd524d3@None delta=None; run3: last=d5f07f5d24ec3cc7@0.6877997131446925 first_out=c3a92b28cfd524d3@None delta=None

**U_B6**: run1: last=ea4a0fbc49651bc5@0.6537667201365337 first_out=ea4a0fbc49651bc5@None delta=None; run2: last=ea4a0fbc49651bc5@0.6537667201365337 first_out=ea4a0fbc49651bc5@None delta=None; run3: last=ea4a0fbc49651bc5@0.6537667201365337 first_out=ea4a0fbc49651bc5@None delta=None

**U_C1**: run1: last=9b0947b801d49c2d@0.5004345808962289 first_out=69b5a1ff838d3cb0@None delta=None; run2: last=9b0947b801d49c2d@0.5004345808962289 first_out=69b5a1ff838d3cb0@None delta=None; run3: last=9b0947b801d49c2d@0.5004345808962289 first_out=69b5a1ff838d3cb0@None delta=None

**K_STD**: run1: last=69b5a1ff838d3cb0@0.5827456055607593 first_out=a3e9d12dd321aec1@None delta=None; run2: last=69b5a1ff838d3cb0@0.5827456055607593 first_out=a3e9d12dd321aec1@None delta=None; run3: last=69b5a1ff838d3cb0@0.5827456055607593 first_out=a3e9d12dd321aec1@None delta=None

**K_3CORE**: run1: last=4859566265b332b6@0.46433191091050363 first_out=bac8e77cef90c8cf@None delta=None; run2: last=4859566265b332b6@0.46433191091050363 first_out=bac8e77cef90c8cf@None delta=None; run3: last=4859566265b332b6@0.46433191091050363 first_out=bac8e77cef90c8cf@None delta=None

**K_LAYER**: run1: last=109c57a8471be6fa@0.4336869943686662 first_out=69b5a1ff838d3cb0@None delta=None; run2: last=109c57a8471be6fa@0.4336869943686662 first_out=69b5a1ff838d3cb0@None delta=None; run3: last=109c57a8471be6fa@0.4336869943686662 first_out=69b5a1ff838d3cb0@None delta=None

## 7. Failure classification

| query | series | primary | all applicable | target family | runs with family in window |
| --- | --- | --- | --- | --- | --- |
| S_A1 | A | STABLE | STABLE | 第2部分 | 10 |
| S_A1 | B | STABLE | STABLE | 第2部分 | 10 |
| S_A3 | A | STABLE | STABLE | 第2部分 | 10 |
| S_A3 | B | STABLE | STABLE | 第2部分 | 10 |
| S_B1 | A | STABLE | STABLE | 第3部分 | 10 |
| S_B1 | B | STABLE | STABLE | 第3部分 | 10 |
| S_C3 | A | STABLE | STABLE | None | None |
| S_C3 | B | STABLE | STABLE | None | None |
| U_A2 | A | STABLE | STABLE | 第2部分 | 10 |
| U_A2 | B | STABLE | STABLE | 第2部分 | 10 |
| U_A4 | A | STABLE | STABLE,NO_TARGET_FAMILY_EVIDENCE_IN_ANY_RUN | 第2部分 | 0 |
| U_A4 | B | STABLE | STABLE | 第2部分 | 10 |
| U_A5 | A | STABLE | STABLE | None | None |
| U_A5 | B | STABLE | STABLE | None | None |
| U_B6 | A | STABLE | STABLE | None | None |
| U_B6 | B | STABLE | STABLE | None | None |
| U_C1 | A | STABLE | STABLE | None | None |
| U_C1 | B | STABLE | STABLE | None | None |
| K_STD | A | STABLE | STABLE | 第2部分 | 10 |
| K_STD | B | STABLE | STABLE | 第2部分 | 10 |
| K_3CORE | A | STABLE | STABLE | 第3部分 | 10 |
| K_3CORE | B | STABLE | STABLE | 第3部分 | 10 |
| K_LAYER | A | STABLE | STABLE | 第2部分 | 10 |
| K_LAYER | B | STABLE | STABLE | 第2部分 | 10 |

## 8. Historical 10/21 divergence — harness configuration or randomness?

| query | previous turn index | series A runs matching the old window | series B runs matching the old window |
| --- | --- | --- | --- |
| S_A1 | 1 | 10/10 | 10/10 |
| S_A3 | 3 | 10/10 | 10/10 |
| S_B1 | 7 | 10/10 | 10/10 |
| S_C3 | 15 | 10/10 | 10/10 |
| U_A2 | 2 | 0/10 | 10/10 |
| U_A4 | 4 | 0/10 | 10/10 |
| U_A5 | 5 | 0/10 | 10/10 |
| U_B6 | 12 | 0/10 | 10/10 |
| U_C1 | 13 | 0/10 | 10/10 |

## 9. Static code findings (read-only, deployed revision)

These were obtained by reading the deployed files inside the running container. Nothing was modified,
copied over, patched, restarted, or reconfigured, and Elasticsearch was accessed with GET requests only.

### 9.1 Query decomposition does call an LLM, with sampling left at provider defaults

- `rag/retrieval/decomposition.py:390` — `result = await gen_json(rendered, "Output:\n", chat_mdl)`, which
  reaches `rag/llm/chat_model.py:1013` — `chat.completions.create(model=..., messages=history, **gen_conf, **kwargs)`
  with `gen_conf` left at its `{}` default.
- **No `temperature`, `top_p`, `seed`, `max_tokens`, or `stream` is set anywhere on that path**, so the
  provider's default sampling applies. This is the only genuine source of run-to-run variation found in
  the retrieval package.
- The call is gated by `looks_composite(question)` (`pipeline.py:268`) together with
  `chat_mdl is None or max_sub_queries <= 0` (`decomposition.py:386`). It is **not** gated by
  `max_sub_queries > 1`.
- `chat_mdl is None` returns `[]` — decomposition is simply skipped, with **no deterministic splitting
  fallback**. The pipeline's own comparative/clause routes are separate and are LLM-free.
- The result is **memoized in Redis for 24 h** (`generator.py:574/587`, `graphrag/utils.py:170-187`); no
  `lru_cache` exists. Observation from this round: 360 `decompose_question` calls produced only **3**
  actual chat-model calls, i.e. almost every decomposition in this round was served from the warm cache.
- Decomposition returns a plain `list[str]` (`decomposition.py:377`): route entries are strings with **no**
  per-route `top_k`.

### 9.2 `routes_top_k = 20` provenance — a hardcoded router constant, not a configuration leak

- `rag/retrieval/query_router.py:69` — `NUMERIC_TOP_K = 20`, returned at `query_router.py:167`, applied at
  `pipeline.py:242` — `routes_top_k = max(decision.routes_top_k, required)`, and warned about at
  `multi_route.py:105` (`routes_top_k=20 is outside the recommended 10-15 band`).
- Ruled out as sources: the `routes_top_k` parameter default (12), the decomposition output, and any config
  file or environment variable — `routes_top_k` does not appear anywhere under `/ragflow/conf`.
- **Provenance: `NUMERIC_TOP_K = 20` (numeric-query router constant) → `max()` at `pipeline.py:242` →
  effective value 20 for numeric-standard questions.** Per this round's instruction the value was left
  exactly as deployed and only recorded.

### 9.3 No deterministic tie-breaker exists on the ordering path

- `multi_route.py:195` and `rerank.py:321` sort by score only; `select_context` ends with
  `[chunk for chunk in ordered if chunk_key(chunk) in chosen_keys]` (`rerank.py:563`). Ties therefore
  resolve purely through Python's stable sort on **pool insertion order** — there is no secondary key such
  as `_id`, `chunk_id`, or `doc_id`.
- No `set` / `sorted(set(...))` / dict-iteration construct determines candidate order in the package.
- No `random`, `uuid`, `time`, or string `hash()` is used anywhere in `/ragflow/rag/retrieval/`; the only
  hashing is content-addressed `hashlib.sha1` (`chunk_profile.py:244`).

### 9.4 Dense retrieval is approximate kNN over two shards

- `rag/nlp/es_conn.py:263-270` builds `s.knn(field, k, num_candidates, query_vector=..., filter=bool_query.to_dict(), similarity=similarity)`.
  There is **no `script_score`** path (NOT FOUND).
- Defaults: `knn_top_k = 1024`, `knn_num_candidates = 2048` (`rag/nlp/search.py:255-256`).
- `tie_breaker`: **NOT FOUND**. `boost` appears only at `es_conn.py:250-251`, where it evaluates to
  `bool_query.boost = 0.0` because the ES fusion weights are hardcoded `"0.001,1"`.
- The kNN `filter` includes the lexical `query_string`; the helper intended to strip it
  (`es_conn.py:75-97`) is **dead code**.
- Live store: `conf/service_conf.yaml:37-40` → `http://es01:9200`, **Elasticsearch 8.11.3**. Index
  `ragflow_a9e28731ab7011f19b833887d563fb04`: `number_of_shards = 2`, `number_of_replicas = 0`,
  `refresh_interval = 1000ms` (`conf/mapping.json:4-6`). `q_3072_vec` = `dense_vector, dims 3072, index
  true, similarity cosine`, with **no `index_options`**, so Elasticsearch HNSW defaults apply
  (`m`/`ef_construction`/`ef_search` NOT FOUND). **Two shards means per-shard merge order is in play.**
- Not used: `dfs_query_then_fetch` (only a comment in `opensearch_conn.py:472`), `preference`, `scroll`,
  `terminate_after`. `search_after` is unreachable on the dense routes (`es_conn.py:303`). `size` differs
  per route/caller (route cut `routes_top_k`, ES fetch `rerank_candidates_count`, second KNN leg
  `len(sres.ids)`).

### 9.5 The final cut, and why ES itself is not the culprit

- Cut: `np.argsort(sim_np * -1, kind="stable")` → threshold filter → `valid_idx[begin:end]`
  (`rag/nlp/search.py:848-863`). The sort is stable but has **no explicit tie-breaker**.
- Fusion is computed Python-side (`search.py:626-628`) from the local `term_similarity` and the
  Elasticsearch-returned cosine; the final window is the retrieval module's `final_top_n`
  (`rerank.py:94` default 8; the live canary kept 12 candidates into the selection step).
- **Direct determinism check (subagent, read-only GET):** three identical kNN probes against the frozen
  index returned **bit-identical** results. Combined with 9.4 this says Elasticsearch is deterministic for
  a fixed input, so a changing window must come from a changed **input** — the query text/sub-queries, the
  query embedding, or mutable ranking state — not from Elasticsearch wandering on its own.
- **OBSERVED IN LOGS:** the same question with reportably identical routes produced pools of
  `25/25/27/27/27` drawn from 1-3 documents, with final cuts of `0 prose / 12 table` versus
  `11 prose / 1 table` — indicative of a pool-composition-sensitive adjustment (table/prose dominance)
  rather than of random ordering. Provenance: log reading, not a controlled experiment; it motivated the
  stage-capture probe in section 10.

### 9.6 What can and cannot differ between two identical calls

Can differ: sub-queries from the LLM decomposition path (provider-default sampling, currently masked by the
24 h Redis cache), the query embedding if the embedding service is not bit-reproducible, per-shard merge
order for the approximate kNN leg on a 2-shard index, and any tie resolved by pool insertion order.
Cannot differ from the code read: the fusion formula, the sort implementation, the threshold filter, and the
slice bounds — all are pure functions of their inputs.


## 10. Stage capture (instrumentation v2, series A)

Probe v1 recorded decomposition and final windows for both series but could not see the per-route
candidates or the pre-cut pool: the deployed pipeline does **not** route through `Dealer.retrieval`
(`dealer_has_retrieval = True`), and the pool is passed as an
**argument** to the selection step. Version 2 records arguments as well as return values, on the same
frozen configuration. Answer generation still happens nowhere in the probe.

### 10.1 Embedding-quota degradation inside this probe (read before the tables)

- Status: **QUOTA_EXHAUSTED_MID_RUN**
- Last clean progress line: `[stage] U_B6 run 6/10` (query U_B6, run 6)
- Quota error lines: 290, route-failure lines: 139
- Queries measured **before** the failure: S_A1, S_A3, S_B1, S_C3, U_A2, U_A4, U_A5, U_B6
- Queries measured **after** it (degraded: the dense route dropped out): U_C1, K_STD, K_3CORE, K_LAYER
- Provenance: OBSERVED (probe stderr: GeminiEmbed 429 RESOURCE_EXHAUSTED, free-tier limit 1000 embed requests/day)

Probe v1 (both series, all 12 queries, 240 runs) recorded **zero** quota failures, so the stability
result in sections 3-7 stands. Only the stage detail below is affected, and each row says so.

| query | pool sizes | distinct pools | distinct sub-query sets | distinct route sets | distinct windows | first divergence | cutoff flag | min cutoff delta | quota |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S_A1 | [12, 12, 12]... | 1 | 1 | 1 | 1 | NONE_UP_TO_FINAL_SELECTION | NOT_OBSERVABLE | None | clean |
| S_A3 | [20, 20, 20]... | 1 | 1 | 1 | 1 | NONE_UP_TO_FINAL_SELECTION | NOT_OBSERVABLE | None | clean |
| S_B1 | [20, 20, 20]... | 1 | 1 | 1 | 1 | NONE_UP_TO_FINAL_SELECTION | NOT_OBSERVABLE | None | clean |
| S_C3 | [12, 12, 12]... | 1 | 1 | 1 | 1 | NONE_UP_TO_FINAL_SELECTION | NOT_OBSERVABLE | None | clean |
| U_A2 | [13, 13, 13]... | 1 | 1 | 1 | 1 | NONE_UP_TO_FINAL_SELECTION | NOT_OBSERVABLE | None | clean |
| U_A4 | [31, 31, 31]... | 1 | 1 | 1 | 1 | NONE_UP_TO_FINAL_SELECTION | NOT_OBSERVABLE | None | clean |
| U_A5 | [15, 15, 15]... | 1 | 1 | 1 | 1 | NONE_UP_TO_FINAL_SELECTION | NOT_OBSERVABLE | None | clean |
| U_B6 | [19, 19, 19]... | 4 | 1 | 1 | 1 | pool_before_cut | NOT_OBSERVABLE | None | DEGRADED |
| U_C1 | [0, 0, 0]... | 1 | 1 | 1 | 1 | NONE_UP_TO_FINAL_SELECTION | NOT_OBSERVABLE | None | DEGRADED |
| K_STD | [0, 0, 0]... | 1 | 1 | 1 | 1 | NONE_UP_TO_FINAL_SELECTION | NOT_OBSERVABLE | None | DEGRADED |
| K_3CORE | [0, 0, 0]... | 1 | 1 | 1 | 1 | NONE_UP_TO_FINAL_SELECTION | NOT_OBSERVABLE | None | DEGRADED |
| K_LAYER | [0, 0, 0]... | 1 | 1 | 1 | 1 | NONE_UP_TO_FINAL_SELECTION | NOT_OBSERVABLE | None | DEGRADED |

### 10.2 Query embedding determinism (10 encodes per query)

| query | convention used | dim | unique sha256 | bit-identical | pairwise cosine min | verdict |
| --- | --- | --- | --- | --- | --- | --- |
| S_A1 | encode_queries:str | 3072 | 1/10 | True | 1.0 | QUERY_EMBEDDING_DETERMINISTIC |
| S_A3 | encode_queries:str | 3072 | 1/10 | True | 1.0 | QUERY_EMBEDDING_DETERMINISTIC |
| S_B1 | encode_queries:str | 3072 | 1/10 | True | 1.0000000000000002 | QUERY_EMBEDDING_DETERMINISTIC |
| S_C3 | encode_queries:str | 3072 | 1/10 | True | 1.0000000000000002 | QUERY_EMBEDDING_DETERMINISTIC |
| U_A2 | encode_queries:str | 3072 | 1/10 | True | 1.0 | QUERY_EMBEDDING_DETERMINISTIC |
| U_A4 | encode_queries:str | 3072 | 1/10 | True | 0.9999999999999998 | QUERY_EMBEDDING_DETERMINISTIC |
| U_A5 | encode_queries:str | 3072 | 1/10 | True | 0.9999999999999999 | QUERY_EMBEDDING_DETERMINISTIC |
| U_B6 | encode_queries:str | 3072 | 1/10 | True | 1.0 | QUERY_EMBEDDING_DETERMINISTIC |
| U_C1 | None | None | None/None | None | None | None |
| K_STD | None | None | None/None | None | None | None |
| K_3CORE | None | None | None/None | None | None | None |
| K_LAYER | None | None | None/None | None | None | None |

### 10.3 Sub-queries actually used (first run of each query)

- **S_A1**: Q/GDW 73286.2-2026 是什么标准
- **S_A3**: NONE
- **S_B1**: NONE
- **S_C3**: NONE
- **U_A2**: 这个标准适用于什么类型的电缆
- **U_A4**: 导体有什么技术要求？ | 内衬层有什么技术要求？ | 铠装层有什么技术要求？
- **U_A5**: 专用技术规范自己规定了哪些要求 | 这些要求都是这个专用技术规范自己规定的吗？ 通用技术规范 正文条款 | 这些要求都是这个专用技术规范自己规定的吗？ 通用技术规范 正文条款
- **U_B6** (degraded): 专用规范对电缆产品的技术要求是什么？ | 通用规范对电缆产品的技术要求是什么？
- **U_C1** (degraded): 220kV 单芯海底电缆的技术要求 | 220kV 三芯海底电缆的技术要求 | 220kV 单芯和三芯海底电缆的技术要求区别 | 单芯 220kV 和 海底电缆的技术要求有什么区别？ | 三芯 220kV 和 海底电缆的技术要求有什么区别？ | 单芯 220kV 和 海底电缆的技术要求有什么区别？ | 三芯 220kV 和 海底电缆的技术要求有什么区别？
- **K_STD** (degraded): NONE
- **K_3CORE** (degraded): 220kV 三芯海底电缆的主要结构是什么 | 220kV 三芯海底电缆铠装层的一般要求是什么
- **K_LAYER** (degraded): 220kV 单芯海底电缆的内衬层有什么技术要求？ | 220kV 单芯海底电缆的铠装层有什么技术要求？

### 10.4 Cutoff detail (first run of each query)

- **S_A1**: pool 12, last included None@None, first excluded 646ab90775aa14a5@0.8402066200644166, delta None, min in-window adjacent delta None, excluded ['646ab90775aa14a5', '255c187f4e228542', '43e96b415797394b', 'ab96130b7a5d5c8f', '3fb0a03b92cc70d7', 'a14eb97907268118', '0b4e3c1a73c1e334', '455737939ddb4a47', '8ebd878ace520649', 'af100b79a9e9734d', '7de0deabdfbdccdc', '9ac2797e006f5b84']
- **S_A3**: pool 20, last included None@None, first excluded b5aaf72bcd33d44a@0.5340928110985942, delta None, min in-window adjacent delta None, excluded ['b5aaf72bcd33d44a', '3fb0a03b92cc70d7', 'd1d75672f2dbc333', 'bac8e77cef90c8cf', '43e96b415797394b', '83d1e77c201be56a', 'ab96130b7a5d5c8f', 'e518c08d493651a2', '0eb621e18881e734', '48f12a5a8ce5eb6c', 'd8277d37a03a2b0a', '5f81fce4a4628ebf', 'cc4443ca2f4783ac', 'bc2a6dfa54206eab', 'c37c0820c0438c3e', 'f96c7773551514ae', 'd415a7ac2958f635', 'af100b79a9e9734d', '69b5a1ff838d3cb0', '53fadbd4012a310c']
- **S_B1**: pool 20, last included None@None, first excluded d1d75672f2dbc333@0.5342719637483971, delta None, min in-window adjacent delta None, excluded ['d1d75672f2dbc333', 'b5aaf72bcd33d44a', '3fb0a03b92cc70d7', '5f81fce4a4628ebf', 'f96c7773551514ae', 'bac8e77cef90c8cf', '43e96b415797394b', 'cc4443ca2f4783ac', 'bc2a6dfa54206eab', '4859566265b332b6', 'ff249ff52cf67152', '8065ad3f4096ca30', 'd79d92725b46b084', '83d1e77c201be56a', 'ab96130b7a5d5c8f', 'e518c08d493651a2', '0eb621e18881e734', 'a03230e9a7559b31', '4238f6f6e9af11af', '322b5cb7a3e64f7b']
- **S_C3**: pool 12, last included None@None, first excluded c3a92b28cfd524d3@0.6112297913067793, delta None, min in-window adjacent delta None, excluded ['c3a92b28cfd524d3', 'ff6344911eb4df75', 'd5f07f5d24ec3cc7', '63e02a0f356894e8', '090dfb645da31bf7', 'cc73de0f16418d16', '8b1911d054c3a036', 'f224470a51f32350', 'db3b79c036360d3c', 'a18b9160c4084d5f', 'd66a18e51bec0e16', '9ea7300f4f6f4219']
- **U_A2**: pool 13, last included None@None, first excluded af100b79a9e9734d@0.6595418391791346, delta None, min in-window adjacent delta None, excluded ['af100b79a9e9734d', 'a2aa88912e75ca47', 'f6bf347f95c33598', '7402cf6c99cbd67e', '6940892bba5934b6', '545e7b340cc0f7c2', '2491aa2ce5eacd8d', 'd1d75672f2dbc333', 'd17f1d620732e24d', 'ab4c98652643c955', '4fb20686f0d2e452', 'ea4a0fbc49651bc5', 'dab0815ca83d0f4b']
- **U_A4**: pool 31, last included None@None, first excluded bac8e77cef90c8cf@0.7479514559714708, delta None, min in-window adjacent delta None, excluded ['bac8e77cef90c8cf', 'af74d2eeaaf2c4a4', 'a0bd8a6bde77b17e', '844f7e6b59d9764e', 'a14eb97907268118', '2491aa2ce5eacd8d', 'fc1c81cbe8032710', 'd1d75672f2dbc333', '5ab5e9b5f2bf95e9', 'b878ee18e84b6356', '322b5cb7a3e64f7b', 'a03230e9a7559b31', '4f291a3c82619d20', 'ab4c98652643c955', 'bf550e46c94ec75b', '14b813dabd06d5fe', 'bc2a6dfa54206eab', 'e356b2ab7a081555', 'ff249ff52cf67152', 'cc4443ca2f4783ac', 'c7347587e61a3532', 'a6989cb86469df8a', '5f81fce4a4628ebf', '663de80696a67296', 'a2aa88912e75ca47', 'acc2f7b2530f0d90', 'f96c7773551514ae', '22ce10ed2fd538bf', '7291b6a1b712f692', '9fa9e164a3e3ca7a', 'd66a18e51bec0e16']
- **U_A5**: pool 15, last included None@None, first excluded f224470a51f32350@0.7190502006458741, delta None, min in-window adjacent delta None, excluded ['f224470a51f32350', 'a18b9160c4084d5f', '48f12a5a8ce5eb6c', '8b1911d054c3a036', 'cc73de0f16418d16', '090dfb645da31bf7', 'ff6344911eb4df75', 'd5f07f5d24ec3cc7', 'c3a92b28cfd524d3', 'd8277d37a03a2b0a', 'd79d92725b46b084', '7de0deabdfbdccdc', 'a0ad87807e53b172', '0b4e3c1a73c1e334', '4859566265b332b6']
- **U_B6**: pool 19, last included None@None, first excluded 48f12a5a8ce5eb6c@0.6926114859555407, delta None, min in-window adjacent delta None, excluded ['48f12a5a8ce5eb6c', 'bac8e77cef90c8cf', 'f224470a51f32350', '91b65c311693d243', '4859566265b332b6', '8b1911d054c3a036', 'a18b9160c4084d5f', 'a0ad87807e53b172', 'ea4a0fbc49651bc5', '2bd4637c7292862b', 'd5f07f5d24ec3cc7', 'ff6344911eb4df75', 'c3a92b28cfd524d3', 'a3e9d12dd321aec1', '127b63ce057208eb', 'd8277d37a03a2b0a', '97ac46b1d738ff00', 'd79d92725b46b084', 'cc73de0f16418d16']
- **U_C1**: pool 0, last included None@None, first excluded None@None, delta None, min in-window adjacent delta None, excluded []
- **K_STD**: pool 0, last included None@None, first excluded None@None, delta None, min in-window adjacent delta None, excluded []
- **K_3CORE**: pool 0, last included None@None, first excluded None@None, delta None, min in-window adjacent delta None, excluded []
- **K_LAYER**: pool 0, last included None@None, first excluded None@None, delta None, min in-window adjacent delta None, excluded []

### 10.5 Instrumented call names

`["RouteResult", "_normalized", "_retrieve_route", "_score", "_sub_query_text", "chunk_key", "clause_route", "comparative_routes", "comparison_sides", "core_document_followup", "decompose_question", "dedupe_chunks", "document_id", "document_key", "empty_kbinfos", "gen_json", "is_comparative_question", "is_prose_chunk", "looks_composite", "merge_route_hits", "multi_route_retrieve", "parse_sub_queries", "rerank_chunks", "resolve_core_documents", "resolve_final_top_n", "resolve_routes_top_k", "retrieve_multi_route", "route_question", "seeks_clause", "strip_section_references"]`

Note: `Dealer.retrieval` never appears in that list, which is why probe v1 produced no per-route data —
the deployed multi-route path reaches the store through its own route helpers.

## 11. Limitations

- Answer Synthesis is paused: this round never generates an answer, so no answer-level field exists here.
- Label 'authoritative evidence' is a definition (target standard family present in the Top-8), not human-reviewed gold evidence.
- Series A activates the deployed decomposition path (which may call the chat model); series B is the same pipeline with chat_mdl=None and exists only to separate a harness-configuration difference from real randomness.
- No retrieval parameter, prompt, reranker, embedding, or index entry was modified in this round.

No fix, no parameter change, and no index write was performed in this round.

## 12. Late-arriving forensics addendum (same round, read-only)

Additional facts from a second read-only forensic pass that landed after sections 1-11 were written. They
do not change the measurement, but they add mechanism and refine several details.

- **Live assistant configuration differs from the frozen harness configuration.** Canary logs show
  `routes_top_k=20, threshold=0.55, vector_weight=0.25, rerank_candidates=30`, and a query-router line
  reporting `vector_weight=0.25, routes_top_k=20 (configured 0.5 / 12)`. The frozen harness used
  `threshold=0.2` and `vector_weight=0.6`, so absolute pool sizes here are not directly comparable with
  live assistant traffic.
- **The live path keeps 12 passages, not 8.** `rerank.py DEFAULT_FINAL_TOP_N = 8` is overridden by the cable
  default `TOP_N = 12` (`api/db/cable_defaults.py:69`), matching the log line
  `26 candidate(s) -> 12 passage(s) kept`. The frozen harness used `final_top_n=8`.
- **ES candidate fetch size vs route cut.** The ES fetch is sized by `rerank_candidates_count`
  (`search.py` default 64, cable default 30) while the per-route page cut is `routes_top_k` (12 default,
  10 or 20 from the router) at `search.py:859-863`. The pool sizes recorded in section 10 (12 / 20 / 19 / 31)
  are consistent with `routes_top_k`-derived cuts.
- **Threshold-rescue branching is divergence-capable by construction.** The live log shows
  `retrying at the 0.20 recall floor` 67 times: the 0.55-gated pass returned nothing and a second ES call
  with `similarity=0.20` filled the route. That branch changes the ES similarity filter. It did not trigger
  under the frozen 0.2 threshold used in this round.
- **The lexical `query_string` is part of the kNN filter, not only a scoring clause.** The kNN `filter` is the
  whole bool-query snapshot, and the helper meant to strip it (`_build_knn_filter_query`, `es_conn.py:75-97`)
  is dead code whose call site is commented out (`es_conn.py:268`). Dense recall therefore depends on lexical
  matching through an approximate filtered HNSW traversal.
- **A second approximate kNN leg scores the candidates** (`_knn_scores`): `topn = len(sres.ids)` with no
  `num_candidates`, so `k = len(ids)` and `num_candidates = 2k`. Small `num_candidates` is a second
  approximation surface.
- **`bool_query.boost` evaluates to 0.0** because the fusion weights are hardcoded `0.001,1`
  (`search.py:331` -> `es_conn.py:236-244`), so the lexical clause inside the kNN request acts purely as a
  pre-filter rather than as a score contribution.
- **No pagerank or tag-feature writer exists in `rag/`, `api/`, or `common/`** (`adjust_chunk_pagerank_fea`
  has no caller). Those fields still feed the fused score with weight 10 (`search.py:519-531`), so any
  out-of-tree writer would be invisible to this review.
- **Deployment inconsistency:** `conf/mapping.json` defines dense-vector dynamic templates only for 512 / 768 /
  1024 / 1536 dimensions, yet the live field `q_3072_vec` exists with `dims: 3072`. The live mapping was
  therefore not produced by that file.
- **Embedding backend discrepancy:** the container environment advertises `TEI_MODEL=Qwen/Qwen3-Embedding-0.6B`,
  while this round observed the query-embedding path failing against `gemini-embedding-1.0` with a free-tier
  quota error. The observed failure is direct evidence; the environment variable describes a different service
  and should not be read as the query-embedding provider.

### Reconciliation with the measurement in sections 3-7

The second pass also found cross-turn divergence in **live assistant traffic**: the same question with the same
five routes produced merged pools of `26 / 25 / 25 / 27 / 27` passages drawn from 1-3 documents, and final
windows of differing composition (`0 prose / 12 table` versus `11 prose / 1 table`). That traffic runs the
0.55 threshold with threshold-rescue branching, the 12-passage cut, and whatever embedding-quota state applied
at the time, whereas this round measured a fixed configuration.

The two observations are consistent and together they localise the problem: **with the configuration pinned,
the pipeline reproduced exactly in 240 runs (10/10 identical windows, Jaccard@K 1.0, bit-identical query
embeddings).** The live divergence must therefore come from a changed *input* or *configuration* - the
threshold-rescue branch, a dense route dropped by embedding-quota exhaustion, a changed query vector, or index
segment state - and never from the scoring path itself, whose fusion arithmetic, stable sort and cut bounds are
pure functions of their inputs.

No fix, no parameter change, and no index write was made in this addendum either.

## 13. Second forensics addendum: decomposition, routing and the ordering chain in detail

Facts from the decomposition-path forensic pass (same round, read-only). One of them **refines the
interpretation** in section 8; the rest add mechanism. None of them changes the headline.

### 13.1 The LLM decomposition call, precisely

- The single LLM call is `gen_json(rendered, "Output:\n", chat_mdl)`, and `gen_conf` keeps its `{}` default,
  so the request body carries no `temperature`, `top_p`, `seed`, `max_tokens` or `stream` — provider defaults
  apply. `_clean_conf` only filters keys; `_apply_model_family_policies` only removes sampling keys for some
  families and never injects a temperature or seed.
- The cache key is `xxh64(llm_name + system_prompt + user_prompt + gen_conf)` with a **24 h** TTL, which is why
  the live log shows byte-identical sub-query lists 26 minutes apart. This is the only stabiliser.
- `parse_sub_queries` truncates to `max_sub_queries`, so two cache-miss answers can differ in **cardinality** as
  well as content. `max_sub_queries == 1` still calls the LLM; only `<= 0` disables it.

### 13.2 REFINEMENT: `chat_mdl = None` does not reduce the pipeline to a single route

Two **LLM-free** routes fire regardless of the chat model: the comparative side routes
(`comparative_routes`, documented "No LLM call") and the normative-prose clause route (`clause_route`). The
route list is `[question] + sub_queries + side_routes + [targeted]`.

So the series A versus series B difference in section 8 is attributable specifically to the
**LLM-generated sub-queries**, not to the entire route set. Series B still had side routes and still returned
12-20 candidate pools; it simply lacked the model-written sub-queries. This does not change the conclusion
(the divergence is a configuration difference, not randomness) but it makes the attribution precise, and it
means a cold-cache comparison is the only way to observe raw LLM sampling variation.

### 13.3 `routes_top_k` provenance, completed

- `NUMERIC_TOP_K = 20`, `REVISION_TOP_K = 12`, `CONCEPTUAL_TOP_K = 10` (`query_router.py:69-73`), matched in rule
  order numeric -> revision -> conceptual. The numeric rule fires on unit/number/model/table shapes such as
  `220 kV` or `800 mm2`, which is why the business-critical queries in this round ran at 20 and the others at 12.
- `dialog_service.py` does **not** pass `routes_top_k`, so the log reads `(configured 0.5 / 12)` — `0.5` is
  `dialog.vector_similarity_weight`, `12` is the signature default. The pipeline then applies
  `routes_top_k = max(decision.routes_top_k, resolve_final_top_n(final_top_n))` (`pipeline.py:236-242`).
- Ruled out with evidence: signature default, config file, environment variable, and decomposition (it has no
  such field). The warning fires whenever the routed value leaves the recommended `(10, 15)` band, so for a
  numeric-shaped question it fires on every single request — by design, not as a symptom.

### 13.4 Pool-dependent branching is the amplification mechanism

Two branches are decided by the pool rather than by the question, and both are deterministic in themselves:

1. Every route makes a first call at `similarity_threshold` and, if that returns nothing, a **second call at
   `RECALL_FLOOR = 0.2`** (`multi_route.py:247/256`), which changes the ES `similarity` filter.
2. `core_document_followup` triggers a **second whole retrieval pass over up to 3 extra routes** when the first
   pool lacks core prose (`MIN_CORE_PROSE_PASSAGES = 4`, `MAX_CORE_DOCUMENT_ROUTES = 3`,
   `pipeline.py:56/63/317-326`), then re-merges.

Because both are functions of the pool, a small upstream change can change the route set, which then changes
every downstream tie. This is the concrete route by which modest perturbations become whole-window
differences, and it is consistent with the live `0 prose / 12 table` versus `11 prose / 1 table` observation.

### 13.5 The ordering value is not the raw cosine

`rank_score = base * penalty * boost` (`rerank.py:310-321`), with `base = rerank_score or similarity`,
`HOLLOW_TABLE_PENALTY = 0.6`, `VALUE_LIST_PENALTY = 0.8`, `core_document_boost = 1.15`,
`VALUE_PAIRING_BOOST = 1.3`. Every factor is a constant and the product is deterministic **for a fixed pool** —
but each factor depends on pool composition (table versus prose mix, whether a table pairs the question
figures, which document is core). Pool-dependent, not random.

`select_context` never re-sorts: it returns `[chunk for chunk in ordered if chunk_key(chunk) in chosen_keys]`
(`rerank.py:563`) after claiming slots in a fixed priority order — one slot per route, one per compared
document, a prose floor, then score fill — with `math.ceil`-derived quotas. Deterministic given the pool, and
the output order is the pool order.

### 13.6 Sizing and the hard guard

`rerank_candidates_count = max(configured or 64, top_k)` (`multi_route.py:294-295`), so the ES candidate fetch
scales with the routed `top_k`; and `page * page_size > rerank_candidates_count` (`search.py:745`) turns a
mismatch into a **hard failure** rather than a degraded result — the failure mode observed earlier in this
workstream when the parameter was passed explicitly as `None`.

### 13.7 Hash-order risk closed

`PYTHONHASHSEED` is not pinned, but no hash-order-dependent construct reaches the candidate order: every `set`
use on this chain is membership-only or truthiness-only (`resolve_compared_documents` and
`resolve_core_documents` return sets, but consumers wrap them in `frozenset`, test membership, or iterate a
list built from the already-ordered pool); there is no `list(set(...))` or `sorted(set(...))` in the retrieval
package; dict iteration is insertion order derived from lists; the only hashing is a content-addressed
`hashlib.sha1` used for table-family keys.

### 13.8 Complete ordering inventory

The package has exactly three ordering sites on the candidate path — `multi_route.py:195` (cross-route merge),
`rerank.py:321` (`rank_score`) and `search.py:848` (stable `argsort` inside the store). Display-only sorts and
the `sorted(policy.question_values)` canonicalisation do not affect candidate order. **None of the three has a
tie-breaker**; ties fall through to insertion order, which decomposes into route order (preserved by
`asyncio.gather`) times per-route store order.

Effect on the conclusions: unchanged headline. A changed input can enter at the LLM sub-queries (on a cache
miss) and at two pool-dependent branches; once the inputs and the pool are fixed, every ordering step is a pure
function. No fix, no parameter change, no index write.
