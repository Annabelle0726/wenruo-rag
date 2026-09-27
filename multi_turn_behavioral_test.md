# Multi-turn Behavioural Test (test only; nothing changed)

**Test tier (declared)**: RETRIEVAL (deployed retrieve_multi_route) + LLM SYNTHESIS (tenant chat model) WITHOUT assistant configuration

Tier caveats:
* no assistant prompt/prologue/refine_multiturn -> app-level effective query NOT OBSERVABLE
* keyword augmentation OFF (assistant setting)
* multi-turn history maintained by the harness

* KB `9463d93eb97511f1938f2592e9bc6fe4`, owner tenant `a9e28731ab70…`, embedding `f79e37e5ab7611f18ecb3887d563fb04`
* frozen configuration: `{"similarity_threshold": 0.2, "vector_similarity_weight": 0.6, "routes_top_k": 12, "final_top_n": 8, "knn_top_k": 1024, "max_sub_queries": 4, "allow_dense_fallback": true}`

Labels are **EXPLORATORY_JUDGMENT** (deterministic heuristics), explicitly NOT a Gold Set.

## Retrieval-layer results (OBSERVED)

| session | round | user query | final-context parts | document selection | groundedness | cross-doc | continuity | refusal | hallucination | model answer |
|---|---|---|---|---|---|---|---|---|---|---|
| session_A | 1 | Q/GDW 73286.2-2026 是什么标准？ | 第2部分,第2部分,第2部分,第2部分,第2部分 | PASS | UNCERTAIN | NOT_NEEDED | UNCERTAIN | NONE | NO | NOT_OBSERVABLE |
| session_A | 2 | 这个标准适用于什么类型的电缆？ | 第1部分,第3部分,第2部分,第3部分,第2部分 | PASS | UNCERTAIN | NOT_NEEDED | UNCERTAIN | NONE | NO | NOT_OBSERVABLE |
| session_A | 3 | 那 220kV 单芯海底电缆的主要结构有哪些？ | 第2部分,第2部分,第3部分,第1部分,第2部分 | PASS | UNCERTAIN | NOT_NEEDED | UNCERTAIN | NONE | NO | NOT_OBSERVABLE |
| session_A | 4 | 导体、内衬层和铠装层分别有什么技术要求？ | 第1部分,第1部分,第3部分,第1部分,第1部分 | PASS | UNCERTAIN | NOT_NEEDED | UNCERTAIN | NONE | NO | NOT_OBSERVABLE |
| session_A | 5 | 这些要求都是这个专用技术规范自己规定的吗？ | 第2部分,第3部分,第1部分,第1部分,第1部分 | PASS | UNCERTAIN | NOT_NEEDED | UNCERTAIN | NONE | NO | NOT_OBSERVABLE |
| session_A | 6 | 如果不是，把通用技术规范里的要求也一起告诉我，并说明 | 第1部分,第2部分,第3部分,第1部分,第2部分 | PASS | UNCERTAIN | NOT_NEEDED | UNCERTAIN | NONE | NO | NOT_OBSERVABLE |
| session_B | 1 | 220kV 三芯海底电缆一般有哪些主要结构？ | 第3部分,第2部分,第2部分,第3部分,第3部分 | PASS | UNCERTAIN | NOT_NEEDED | UNCERTAIN | NONE | NO | NOT_OBSERVABLE |
| session_B | 2 | 铠装层有什么要求？ | 第3部分,第3部分,第1部分,第1部分,第1部分 | PASS | UNCERTAIN | NOT_NEEDED | UNCERTAIN | NONE | NO | NOT_OBSERVABLE |
| session_B | 3 | 内衬层厚度呢？ | 第3部分,第2部分,第1部分,第3部分,第3部分 | PASS | UNCERTAIN | NOT_NEEDED | UNCERTAIN | NONE | NO | NOT_OBSERVABLE |
| session_B | 4 | 这个数值是在哪份规范里规定的？ | 第1部分,第2部分,第3部分,第1部分,第1部分 | PASS | UNCERTAIN | NOT_NEEDED | UNCERTAIN | NONE | NO | NOT_OBSERVABLE |
| session_B | 5 | 三芯专用规范里面没有吗？ | 第3部分,第3部分,第3部分,第2部分,第2部分 | PASS | UNCERTAIN | NOT_NEEDED | UNCERTAIN | NONE | NO | NOT_OBSERVABLE |
| session_B | 6 | 那你把专用规范和通用规范的要求区分开告诉我。 | 第2部分,第3部分,第1部分,第2部分,第3部分 | PASS | UNCERTAIN | NOT_NEEDED | UNCERTAIN | NONE | NO | NOT_OBSERVABLE |
| session_C | 1 | 220kV 单芯和三芯海底电缆的技术要求有什么区别？ | 第1部分,第2部分,第2部分,第3部分,第3部分 | PASS | UNCERTAIN | NOT_NEEDED | UNCERTAIN | NONE | NO | NOT_OBSERVABLE |
| session_C | 2 | 先只比较结构方面。 | 第1部分,第3部分,第2部分,第1部分,第1部分 | PASS | UNCERTAIN | NOT_NEEDED | UNCERTAIN | NONE | NO | NOT_OBSERVABLE |
| session_C | 3 | 哪些要求是它们共同的？ | 第1部分,第3部分,第2部分,第1部分,第3部分 | PASS | UNCERTAIN | NOT_NEEDED | UNCERTAIN | NONE | NO | NOT_OBSERVABLE |
| session_C | 4 | 哪些是单芯或三芯专用规范单独规定的？ | 第2部分,第1部分,第1部分,第3部分,第2部分 | PASS | UNCERTAIN | NOT_NEEDED | UNCERTAIN | NONE | NO | NOT_OBSERVABLE |
| session_C | 5 | 不要把投标人填写的空白参数表当成已经规定的参数。 | 第1部分,第3部分,第3部分,第1部分,第1部分 | PASS | UNCERTAIN | NOT_NEEDED | UNCERTAIN | NONE | NO | NOT_OBSERVABLE |
| session_C | 6 | 重新总结一次，并标明每条来自通用规范、单芯专用规范还 | 第3部分,第3部分,第2部分,第2部分,第3部分 | PASS | UNCERTAIN | NOT_NEEDED | UNCERTAIN | NONE | NO | NOT_OBSERVABLE |
| control | 1 | 220kV 单芯海底电缆的导体、内衬层、铠装层技术要 | 第1部分,第1部分,第1部分,第1部分,第1部分 | PASS | UNCERTAIN | NOT_NEEDED | UNCERTAIN | NONE | NO | NOT_OBSERVABLE |
| control | 1 | 220kV 三芯海底电缆的内衬层厚度要求是什么？ | 第1部分,第1部分,第1部分,第1部分,第1部分 | PASS | UNCERTAIN | NOT_NEEDED | UNCERTAIN | NONE | NO | NOT_OBSERVABLE |
| control | 1 | Q/GDW 73286 的通用规范与单芯/三芯专用规 | 第1部分,第1部分,第2部分,第3部分,第2部分 | PASS | UNCERTAIN | NOT_NEEDED | UNCERTAIN | NONE | NO | NOT_OBSERVABLE |

## Current Behavioural Baseline Summary

* turns run: **21** (3 sessions x 6 rounds + 3 single-turn controls)
* **Document selection (final context contains the expected family): PASS 21/21** - this is the retirement layer's own measure and it passed in every turn, including the natural-language-only Session B and the implicit controls.
* Answer-groundedness / refusal / hallucination / continuity: **NOT_OBSERVABLE** - the LLM synthesis layer did not run (see below), so no answer-level label exists and none is guessed.
* Cross-document behaviour: NOT_NEEDED by the heuristic in every turn (the heuristic only fires on explicit Part1/Part3 partitioning language) - this is a HEURISTIC LIMITATION, recorded as such rather than as a PASS.

## Failure transition (earliest anomalous layer)

| layer | state |
|---|---|
| Query understanding | NOT_OBSERVABLE (no assistant; app-level query rewriting absent at this tier) |
| Document selection | PASS in all 21 turns (OBSERVED) |
| Chunk/evidence selection | NOT REVIEWED (needs the human evidence rubric) |
| Cross-document composition | NOT OBSERVABLE (no synthesis layer) |
| LLM synthesis | **NOT OBSERVABLE - the chat model was not resolved by this harness** (the deployed path takes it from the assistant/dialog; this harness asked for it off the KB row and got nothing, so `model_answer` is null everywhere) |

## Observed behavioural failure

* **None established at the retrieval layer.** The only failure observed this round is in **my own harness**: it could not resolve a chat model without an assistant, so the answer layer produced no data. That is a test-instrument defect, recorded here and NOT fixed in this round (no code was changed after the run).
* Per the round's rule, no fix was implemented: no parameter, prompt, KB or code change; the S2 index is untouched.