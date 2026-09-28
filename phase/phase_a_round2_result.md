# Round result: corrective-migration prep and the A/C trace (measurement round, no writes)

Nothing was written to ES, MySQL or MinIO this round. **Both deliverables are INCOMPLETE**,
and this file records exactly where each stopped, because the numbers a decision depends on
are not the ones I could produce.

## A. Corrective migration (the 60 chunks) — partially delivered

**Authoritative number: `changed = 60 / unchanged = 95`**, from the fixed canary dry run
(`../tools/scripts/phase_a_canary.py`, section walk over the RAW body). The other counts the
approval depends on hold: family 155, outside-family mutations 0.

**What is missing: the 60-row table** (id / Part / stored section / corrected section /
stored header / corrected header) and the classification the approval asks for
(`section → None`, `section → previous clause`). My ad-hoc script for it
(`tmp_corrective/readiness.py`) reported **155 changes with `'8.2.5' → '8.2.5'` counted as a
change**, which is impossible: it rebuilt the header by string surgery
(`stored_header[:-1] + " | 章节: X]"`) instead of re-running the projection, so a header that
legitimately has no 章节 gained one and every chunk looked changed. Its numbers are therefore
NOT evidence and its artifact was deleted rather than left in the tree.

What the buggy run does tell me, and why it is worth stating: the split it produced
(66 section added, 29 removed, 37 changed, 23 header-only) is an artifact of the same bug,
so it must not be quoted. The corrected script has to build the header through
`retrieval_projection` per chunk (identity + domain attributes + that chunk's section) and
compare only the `章节` value, and it needs one more iteration before it can support the
approval.

**Corrective write: not attempted** (correctly, since the readiness table does not exist yet).

## B. A/C end-to-end trace — NOT measured

`../tools/scripts/retrieval_trace.py` was written to separate the three legs without changing a
parameter (lexical-only = `vector_similarity_weight 0.0`, dense-only = `1.0`, hybrid = `0.3`),
because the dense and reranker stages only exist where the embedding model does - inside the
API container. It cannot run there yet:

* the container holds the DEPLOYED revision, not this working tree (no bind mount:
  `/ragflow/rag/nlp/retrieval_projection.py` does not exist in it), which is the right code to
  measure but a different API surface;
* `get_tenant_default_model_by_type(TENANT, LLMType.EMBEDDING)` returns a **string** in that
  revision while `LLMBundle` expects a **dict** (`tenant_llm_service.py:105`
  `model_config["llm_name"]` → `TypeError: string indices must be integers`), so the trace
  died before its first leg;
* the script was piped in over stdin (`docker exec -i ... python -`) so nothing was written
  into the container.

Stages 1, 3, 4, 5 and 6 are therefore **not measured**: no dense-only ranking, no hybrid
ranking, no reranker delta, no `apply_rank_adjustments` / `select_context` trace, and no
leg-by-leg attribution.

## What IS supported by evidence for A and C

From the after benchmark and the manual top-10 tables (lexical leg, production tokenizer):

* **A** (`根据 Q/GDW 73286.2-2026 查找单芯 220kV 海缆参数`) and **C**
  (`220kV 三芯海底电缆结构参数`) have **no target passage in the lexical top-10**, and their
  top-10 is dominated by other documents' parameter tables (`4 标准技术参数表`,
  `5 组件材料配置表` - the 抽水蓄能 and 10kV families).
* Classification, at the confidence the evidence allows: **lexical recall failure of the
  benchmark target, CONFIRMED for the lexical leg**. Dense mismatch, fusion suppression,
  reranker suppression, cutoff and benchmark-labelling issues are **NOT determined** - the
  stages that would decide between them did not run, and per the round's rules I am not
  substituting a guess.
* On "parameter tables own the top 10": the tables that own it are **mostly from OTHER
  standards**, not from Part 2/Part 3, so the candidate explanations remain open between
  (1) the benchmark target being narrow, (3) lexical density advantage, and (5) mislabelled
  relevance - all three need the stage trace plus a human read of each row.

## Next round, in order

1. Fix the readiness script the way A above describes, and produce the 60-row table with the
   `None` / previous-clause counts - that is the only thing standing between the canary and a
   corrective write.
2. Adapt `retrieval_trace.py` to the deployed revision's model-resolution API and run it
   inside the container, so stages 1 and 3-6 exist before any explanation of A/C is given.
3. No parameter changes, no corrective write, no embedding, until those two exist.
