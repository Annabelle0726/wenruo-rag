# Round result: corrective-migration readiness READY; retrieval trace NOT VALIDATED

Read-only round: nothing was written to ES, MySQL or MinIO, no retrieval parameter changed, no
corrective write, no embedding, no re-parse, no mapping change.

## 1. Corrective Migration: **READY**

Produced by `tools/scripts/phase_a_readiness_check.py`, which calls the SAME projection as the
migration (`retrieval_projection.project_chunk` + `token_fields`; the canary now delegates to
them too, so there is one algorithm and no second opinion to disagree with).

| requirement | evidence |
|---|---|
| production dry run = 60 changed / 95 unchanged | **60 / 95** (matches the canary's own dry run exactly) |
| no false change | the `old X -> same X` bucket is **EMPTY** (`same_section: 0`) |
| raw-body hash before/after | present on **155/155** rows; both sides projected from the same body |
| no body mutation | every projected `retrieval_text` differs from the stored value only in its header; the raw part is byte-identical (asserted per row by the checker and by test) |
| `section_removed` explained | **0 removals** |
| `section_changed` spot-checked | **0 changes** — the census is `null_to_non_null: 60`, i.e. every one of the 60 is a section that was EMPTY and is now filled |
| S1 == S2 == S3 | **true for all 3 documents × 3 initial states** (legacy+raw / raw / current+raw), over the whole document sequence, comparing `content_with_weight` + `content_ltks` + `content_sm_ltks` |
| family outside = 0 | 326 outside chunks; the migration's whitelist is applied before any candidate exists |

The qualitative judgement the approval asked for: **all 60 are additions of a real heading to a
passage that had none**, none replace an existing value, and none come from a previous clause —
so the corrected state is strictly closer to the document's own structure than what the canary
wrote.

On the statefulness that the earlier failure hid: the section comes from `document_sections`,
which carries the "heading in force" forward **in chunk order**, and the order is the migration's
own document ordering (`page_num_int`, then `_id`). That is why the walk must run per DOCUMENT and
not per passage, why a re-run from the stored state is deterministic (the walk always starts from
the first chunk of the document), and why the first canary run — which walked the *projected*
bodies of 58 legacy-prefixed chunks — produced sections from the wrong text.

Tests: `test/unit_test/rag/nlp/test_phase_a_migration.py` (6 cases: three rounds are a no-op after
the first, for each of the three initial states; all three states converge to the same stored
representation; a passage's section comes from its own heading, not the previous chunk; the raw
body is never touched). `test/unit_test/rag/nlp` = **175 passed**.

## 2. Retrieval Trace: **TRACE NOT VALIDATED**

The production smoke test was NOT run, so per the round's own rule no root-cause classification is
given for A/C.

Why it was not run: the diagnostic must call the DEPLOYED implementation, and the deployed
revision's model-resolution API differs from this working tree's
(`get_tenant_default_model_by_type` returns a string there while `LLMBundle` expects a dict). The
adaptation has to be derived from the deployed code's own construction path
(`dialog_service` -> retrieval -> `Dealer.retrieval`), which is exactly what
`tools/scripts/retrieval_trace.py` was written to reuse via `Dealer.retrieval` — but the bundle
construction in it is still this tree's shape, so it cannot run yet. It pipes in over stdin
(`docker exec -i ... python -`), so nothing was written into the container, and the container's
code was not patched or replaced.

What remains unmeasured, explicitly: dense-only ranking, production hybrid ranking, reranker
delta, `apply_rank_adjustments`/`select_context` elimination point, and the standard-number probe.
No conclusion about A/C beyond the lexical leg is drawn.

## 3. Next round, in order

1. Read the deployed construction path for the embedding bundle and adapt
   `retrieval_trace.py` to it, then run the **E smoke test**; only if it agrees with the
   production path do the A/C stages.
2. Then the six-stage trace with the relevance labelling (3/2/1/0) over the hybrid top-10.
3. The 60-chunk corrective write becomes available now (READY), but still needs your explicit
   approval.
