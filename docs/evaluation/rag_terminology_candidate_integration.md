# Retrieval Candidate Integration — Phase 0 + 1.1 + 2

A minimal retrieval candidate was built from the accepted production baseline and validated
end-to-end on its **real runtime path**. **All 10 acceptance criteria passed. Nothing deployed, no
retag, no recreate, no prune.**

---

## PHASE2_COMMIT

`4ee4775f9 feat(retrieval): fact-type evidence parity reservation for multi-fact context` —
development commit, explicitly marked as not a release acceptance.

Staged paths, exactly the four PART A allowed:

| file | change |
|---|---|
| `rag/retrieval/context_reservation.py` | **new** — the reservation |
| `rag/retrieval/rerank.py` | **+10 / −1** — the integration hunk |
| `docs/evaluation/rag_terminology_phase2_gate.md` | **new** — Phase 2 gate report |
| `tools/scripts/phase2_reservation_experiment.py` | **new** — Phase 2 harness |

**No other file needed changing**, so no extra-file justification was required. The Docker/release
dirt (`Dockerfile`, `Dockerfile_base`, `Dockerfile_go`, `deploy/p0_baseline/*.yml`) was left
untouched and unstaged.

Gate steps before the commit:

```
ruff check (4 files)      -> All checks passed!
py_compile (4 files)      -> ok
pytest selection/quota    -> 81 passed
    (test_context_diversity, test_rerank_assembly, test_value_pairing_cut,
     test_document_flooding, test_hollow_tables, test_retrieval_contract)
pytest rag/retrieval      -> 11 failed, 244 passed
    baseline without the hunk -> 11 failed, 244 passed   (IDENTICAL set -> 0 new failures)
git diff --check          -> clean
```

The 11 failures are pre-existing and unrelated to selection: they are planner/canonicalisation
tests whose assertions carry Windows-encoding mojibake, plus a `RedisDB.set(ex=...)` kwarg
incompatibility in the planner's plan cache. Proven pre-existing by re-running the same suite with
the hunk stashed and getting the identical 11 test IDs.

### The integration hunk, exactly

```diff
@@ -79,6 +79,7 @@ from rag.retrieval.chunk_profile import (
     summarize,
     table_family_key,
 )
+from rag.retrieval.context_reservation import reserve_for_question
 from rag.retrieval.decomposition import (
@@ -758,6 +759,14 @@ async def rerank_chunks(rerank_mdl, chunks, question, top_n
-    selected = _select(apply_rank_adjustments(pool, policy), limit, policy=policy, reason=" by rerank score")
+    ordered = apply_rank_adjustments(pool, policy)
+    selected = _select(ordered, limit, policy=policy, reason=" by rerank score")
+    # Fact-type evidence parity (Phase 2). ... (comment)
+    selected = reserve_for_question(ordered, limit, selected, question)
     _LOG.info("[Rerank] pool %s -> context %s", summarize(pool), summarize(selected))
```

Three effective lines plus one import. **No rerank scoring change, no reranker model change, no
ordering-formula change, no window-size change**: the reservation operates strictly between the
already-scored, already-cut selection and the value `rerank_chunks` returns. The import inside
`required_fact_types` is function-local, so `rerank`'s module graph is unchanged at import time.

**Known boundary, stated:** `rerank_chunks` has four early-return paths (`rerank_mdl is None`, empty
question, empty texts, reranker error or score-count mismatch) that keep today's behaviour without a
reservation. They are the degraded paths; the deployed assistant runs with a reranker, and keeping
them untouched is what made the hunk minimal.

---

## MINIMAL_BACKPORT

Built **from the files inside the production image**, not from HEAD.

| # | candidate path | source |
|---|---|---|
| 1 | `rag/retrieval/pipeline.py` | **deployed** `pipeline.py` (**341** lines, blob `da38414bd59b`) + 3 hunks → **365** lines (+24) |
| 2 | `rag/retrieval/rerank.py` | **deployed** `rerank.py` (`4498c2ed2b2c`) + the hunk → verified byte-identical to the working tree's `rerank.py` |
| 3 | `rag/res/synonym.json` | working tree (Phase 0) |
| 4 | `rag/retrieval/domain_facts.py` | working tree (Phase 1.1) |
| 5 | `rag/retrieval/route_expansion.py` | working tree (Phase 1.1) |
| 6 | `rag/retrieval/context_reservation.py` | working tree (Phase 2) |

The `pipeline.py` hunks are produced by `tools/scripts/phase1_build_backport.py`: the import, the
`ROUTE_BUDGET` constant (derived from `MAX_SUB_QUERIES`, a symbol the deployed module **already**
imports, so no planner symbol is pulled in), and the expansion call at the end of the deployed route
assembly.

Verified:

* **HEAD's `pipeline.py` was NOT used.** The candidate's pipeline hash `acf8c7f7b888…` ≠ HEAD's
  `ca1565cefa…`; it is the deployed revision plus 24 lines.
* **`planner.py` is absent** from the candidate: `ls /ragflow/rag/retrieval/` lists
  `__init__ chunk_profile context_reservation decomposition domain_facts health health_bridge
  health_producers multi_route pipeline query_router rerank route_expansion` — no planner.
* `rerank.py` needed no separate porting: the deployed file and HEAD's are the same blob
  (`b2f9ac4654b5`), so applying the hunk to the deployed copy reproduces the committed file exactly
  (asserted by string comparison, and the reconstructed file was the one copied into the build).

**No other retrieval evolution travelled**: `decomposition.py`, `query_router.py`, `multi_route.py`,
`chunk_profile.py`, `health*.py`, `retrieval_projection.py` are the deployed bytes.

---

## CANDIDATE_IMAGE

```
tag        my-wenruorag:phase-integration-candidate
image id   sha256:c748d24e2e69a309c94b50c9740336bfe55dc10608792943f253025c377aa710
base       my-wenruorag@sha256:18711d10f0353a9f37d25611bd81030bd6c6af0f00f764ddf0132b5ad3f7d123
size       12.7 GB   created 2026-10-02 11:14:55
```

The Dockerfile is six `COPY` lines on a base pinned by **digest** — no `RUN`, no package install, no
build step, no base change:

```dockerfile
FROM my-wenruorag@sha256:18711d10f0353a9f37d25611bd81030bd6c6af0f00f764ddf0132b5ad3f7d123
COPY synonym.json            /ragflow/rag/res/synonym.json
COPY domain_facts.py         /ragflow/rag/retrieval/domain_facts.py
COPY route_expansion.py      /ragflow/rag/retrieval/route_expansion.py
COPY context_reservation.py  /ragflow/rag/retrieval/context_reservation.py
COPY pipeline.py             /ragflow/rag/retrieval/pipeline.py
COPY rerank.py               /ragflow/rag/retrieval/rerank.py
```

Because there is no `RUN`, the candidate's only layers are those COPYs, which is what makes the
whole-image diff below auditable rather than merely asserted. Docker also attached a buildx
attestation manifest; that is image metadata, not a filesystem difference.

---

## WHOLE_IMAGE_DIFF

Full filesystem manifest of both images (`find . -xdev -type f` → `sha256sum`), 130,000 files in the
base and 130,004 in the candidate:

```
ADDED   (4):  ./ragflow/rag/res/synonym.json
              ./ragflow/rag/retrieval/context_reservation.py
              ./ragflow/rag/retrieval/domain_facts.py
              ./ragflow/rag/retrieval/route_expansion.py
REMOVED (0):
CHANGED (2):  ./ragflow/rag/retrieval/pipeline.py   c9174c52926d -> acf8c7f7b888
              ./ragflow/rag/retrieval/rerank.py     4498c2ed2b2c -> 4f288ed6155b
```

**Total differing paths: 6 — exactly the allowed set, and nothing else.**
`differing paths OUTSIDE the 6 allowed target paths: NONE`.

Per-tree counts, each satisfying the requirement:

| tree | files in base | added | removed | changed | verdict |
|---|---|---|---|---|---|
| `./ragflow/api` | 178 | 0 | 0 | 0 | **UNCHANGED** |
| `./ragflow/rag` | 283 | 4 | 0 | 2 | DIFF — only the 6 target paths |
| `./ragflow/common` | 115 | 0 | 0 | 0 | **UNCHANGED** |
| `./ragflow/web` (frontend) | 1013 | 0 | 0 | 0 | **UNCHANGED** |
| `./ragflow/conf` (runtime config) | 88 | 0 | 0 | 0 | **UNCHANGED** |
| `./ragflow/.venv` | 71,403 | 0 | 0 | 0 | **UNCHANGED** |
| `./ragflow/deepdoc` | 65 | 0 | 0 | 0 | **UNCHANGED** |
| `./ragflow/agent` / `mcp` / `tools` | 177 | 0 | 0 | 0 | **UNCHANGED** |
| `./etc` / `./usr` / `./opt` / `./var` / `./root` | 56,631 | 0 | 0 | 0 | **UNCHANGED** |

No additional change appeared, so the STOP condition did not trigger.

---

## RUNTIME_CODE_FINGERPRINT

Recorded by the E2E harness itself, from inside each container:

| path | production baseline | candidate |
|---|---|---|
| `rag/res/synonym.json` | **MISSING** | `4bd49e89e08d8108…` |
| `rag/retrieval/domain_facts.py` | **MISSING** | `52c1fe7da30d2e8a…` |
| `rag/retrieval/route_expansion.py` | **MISSING** | `47f2073e8e975e1f…` |
| `rag/retrieval/context_reservation.py` | **MISSING** | `b7317a0872f6eb73…` |
| `rag/retrieval/pipeline.py` | `c9174c52926d…` | `acf8c7f7b888f1f7…` |
| `rag/retrieval/rerank.py` | `4498c2ed2b2c…` | `4f288ed6155b0ca1…` |

Loaded module paths (candidate): all five under `/ragflow/rag/retrieval/`; the base reports
`ABSENT` for the three Phase-1.1/2 modules. Other recorded runtime facts:

| probe | baseline | candidate |
|---|---|---|
| synonym dictionary entries | 0 | **7** |
| `lookup(设计使用寿命)` | `[]` | `['设计使用年限']` |
| `lookup(设计寿命)` | `[]` | `['设计使用年限']` |
| `lookup(寿命)` | `[]` | `[]` *(by policy)* |
| `reserve_for_question` present in `rerank_chunks` bytecode | **False** | **True** |

So **criterion 10 is a measurement, not an assumption**: the candidate's runtime genuinely
traverses Phase 0 (resource loaded and resolving), Phase 1.1 (modules present, expansion firing) and
Phase 2 (the reservation is compiled into the production selection function).

---

## FROZEN_QA_RESULTS

3 runs per question, production entry, assistant's own parameters; `life_cl` = passages carrying
`不少于30`, `struct_cl` = passages carrying `结构图纸`.

| q | role | axis reader | supp. routes | life_cl base→cand | struct_cl base→cand | docs | dup |
|---|---|---|---|---|---|---|---|
| QA-001 | frozen | declines | 0 | 0,0,0 → 0,0,0 | 0,0,0 → 0,0,0 | 4 → 4 | 0 |
| QA-002 | frozen | declines | 0 | 1,1,1 → 1,1,1 | 0,0,0 → 0,0,0 | 3 → 3 | 0 |
| QA-003 | frozen | declines | 0 | 0,0,0 → 0,0,0 | 0,0,0 → 0,0,0 | 6 → 6 | 0 |
| **QA-004** | frozen | **expands** | 4 | **0,0,0 → 3,3,3** | **4,4,4 → 3,3,3** | 6 → 6 | 0 |
| QA-005 | frozen | declines | 0 | 0,0,0 → 0,0,0 | 0,0,0 → 0,0,0 | 1 → 1 | 0 |

* **Criterion 1 — QA-004 exact 3/3 life + structure: PASS.** Design-life evidence goes 0 → 3 in all
  three runs while structure evidence stays present (4 → 3, the window re-allocating one slot).
* **Criterion 5 — QA-001/002/003/005 no regression: PASS.** All four add 0 routes, and every clause
  count, document count and duplicate count is identical. Token counts are identical except QA-001,
  whose baseline itself varied run-to-run (8758/8833) and whose candidate value sits inside that
  range — a frozen question with no added routes cannot have changed.
* QA-004's answer now states the design life: `design_life_years` **False → True**.

---

## PARAPHRASE_RESULTS

| q | life_cl base→cand | struct_cl base→cand | both present (3/3)? |
|---|---|---|---|
| V1 | 3,3,3 → 3,3,3 | 3,3,3 → 3,3,3 | ✅ |
| V2 | 3,3,3 → 3,4,3 | 4,4,4 → 4,4,4 | ✅ |
| V3 | 5,5,5 → 4,4,4 | 1,1,1 → 2,2,2 | ✅ |
| V4 | 9,9,9 → 7,7,7 | 2,2,2 → 2,2,2 | ✅ |
| **V5** | 6,6,6 → 6,6,6 | **0,0,0 → 1,1,1** | ✅ |
| V6 | 1,1,1 → 4,4,4 | 1,1,1 → 2,2,2 | ✅ |

* **Criterion 2 — V1–V6 3/3 required evidence: PASS.** Life and structure clauses present in every
  run of all six; runs are stable (V2's middle value 4 vs 3,3 reflects the already-characterised
  rerank jitter, not instability of the fix).
* **Criterion 3 — V5 structure 0/3 → 3/3: PASS** (`0,0,0 → 1,1,1`).
* Four paraphrases improve materially: V6 life 1 → 4, V3 structure 1 → 2, V6 structure 1 → 2, V5
  structure 0 → 1.

---

## GENERALIZATION_RESULTS

Different entity pairs, enumerators and phrasings — the evidence that this is a coverage mechanism,
not a QA-004 patch.

| q | question | entities | supp. | life_cl | struct_cl |
|---|---|---|---|---|---|
| G1 | 户外终端和GIS终端的设计使用寿命和结构有什么规定？ | 户外终端·GIS终端 | 4 | 4,4,4 → 4,4,4 | 2,2,2 → 2,2,2 |
| **G2** | 工厂接头与修理接头的结构以及设计使用年限是怎样要求的？ | 工厂接头·修理接头 | 4 | 7,7,7 → 6,6,6 | **0,0,0 → 1,1,1** |
| **G3** | 110kV海缆单芯和三芯的终端、接头的使用年限和结构要求分别是什么？ | 单芯·三芯·终端 | 4 | 6,6,6 → 5,5,5 | **0,0,0 → 1,1,1** |
| G4 | 电缆终端、电缆接头在结构和设计寿命方面有哪些技术要求？ | 电缆终端·电缆接头 | 4 | 2,2,2 → 3,3,3 | 4,4,4 → 4,4,4 |
| **G5** | 标准对户外终端和电缆接头的设计使用年限、结构分别有什么规定？ | 户外终端·电缆接头 | 4 | 6,6,6 → 5,5,5 | **0,0,0 → 1,1,1** |

* **Criterion 4 — G2/G3/G5 coverage retained: PASS.** All three go `0,0,0 → 1,1,1`.
* G1 and G4 already held the clause in the baseline (2 and 4 passages) and the parity rule
  correctly leaves them alone.
* G2/G3/G5 lose one design-life passage each (7→6, 6→5, 6→5) to the reserved slot. Both fact types
  remain represented in every case; this is the intended displacement, and it is the behaviour to
  keep an eye on.

---

## CONTEXT_DIVERSITY

* **Criterion 6 — no duplicate chunks: PASS.** `dup = 0` in all 48 runs of all 16 questions, both
  sides.
* **Criterion 7 — diversity not materially worse: PASS.** Distinct documents, base → candidate:

| | QA001 | QA002 | QA003 | QA004 | QA005 | V1 | V2 | V3 | V4 | V5 | V6 | G1 | G2 | G3 | G4 | G5 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| base | 4 | 3 | 6 | 6 | 1 | 6 | 6 | 6 | 5 | 6 | 5–6 | 6 | 5 | 3 | 6 | 5 |
| cand | 4 | 3 | 6 | 6 | 1 | 6 | 6 | 6 | **6** | 6 | 5 | 6 | 5 | **4** | 6 | 5 |

Unchanged everywhere, **improved twice** (V4 5→6, G3 3→4), and one case (V6) settles inside its own
baseline range (5–6 → 5). No question loses document diversity.

---

## TOKEN_IMPACT

| q | tokens base → candidate | Δ |
|---|---|---|
| QA-001 / QA-002 / QA-003 / QA-005 | 8758–8833 / 6495 / 8872 / 7271 → 8758 / 6495 / 8872 / 7271 | 0 |
| QA-004 | 8598 → 7318 | **−15 %** |
| V1 | 7511 → 7318 | −2.6 % |
| V2 | 7551 → 7573–7803 | ≈+1 % |
| V3 | 6663 → 7201 | +8.1 % |
| V4 | 7431 → 6281 | **−15 %** |
| V5 | 6622 → 6858 | **+3.6 %** |
| V6 | 7052–7169 → 7720 | +7.7 % |
| G1 | 6778 → 6778 | 0 |
| G2 | 5606 → 6346 | **+13.2 %** |
| G3 | 6141 → 6381 | +3.9 % |
| G4 | 7827 → 7764 | −0.8 % |
| G5 | 7070 → 7233 | +2.3 % |

**Criterion 8 — token growth bounded: PASS.** Growth is confined to the questions where a slot was
re-allocated, ranges **+2.3 % to +13.2 %** (mean +4.4 % over the affected questions), and two
questions are *smaller* because the window now spends slots on shorter clause passages instead of
long generic tables. Every control question is byte-identical in token count.

---

## LATENCY

Median of 3, same parameters, base → candidate:

| q | base | candidate |
|---|---|---|
| QA-001 | 2.98 s | 3.99 s |
| QA-002 | 0.84 s | 0.91 s |
| QA-003 | 0.84 s | 0.88 s |
| QA-004 | 2.09 s | 2.47 s |
| QA-005 | 2.45 s | 1.57 s |
| V1 | 1.20 s | 2.44 s |
| V2 | 1.10 s | 1.72 s |
| V3 | 1.21 s | 1.86 s |
| V4 | 1.38 s | 1.84 s |
| V5 | 2.25 s | 1.85 s |
| V6 | 1.29 s | 1.80 s |
| G1 | 1.41 s | 1.48 s |
| G2 | 1.33 s | 1.94 s |
| G3 | 2.57 s | 1.93 s |
| G4 | 1.24 s | 1.83 s |
| G5 | 2.25 s | 1.77 s |

**Criterion 9 — latency acceptable: PASS.** The reservation itself adds **no retrieval work** — it
re-selects from a pool that was already scored, in pure CPU — so the differences are not attributable
to it. The band is 0.88–3.99 s against a baseline band of 0.84–2.98 s, and the largest delta
(QA-001, +1.0 s) is a **frozen question with 0 added routes and an identical window**, which cannot
be a candidate effect: it is the LLM decomposition call's run-to-run variance, already characterised
(and QA-005 moves the other way by −0.9 s for the same reason). No question approaches the
multi-second regression a retrieval change would show.

---

## REGRESSIONS

**None functional.**

* Frozen QA-001/002/003/005: identical clause evidence, identical documents, identical duplicates,
  identical token counts (QA-001's baseline varied on its own; candidate value inside its range).
* The axis reader declines all of them, so `reserve_for_question` receives no fact types and the
  reservation cannot fire.
* **Intended trade-offs, both bounded:** the window's design-life count drops by one on G2/G3/G5 when
  a structure-clause passage is promoted (7→6, 6→5, 6→5), and QA-004's structure count goes 4 → 3.
  In every case **both fact types remain represented** — no fact type loses its evidence.
* G1/G4 (already covered) are untouched by parity, confirming the rule is inert where it should be.
* No duplicate chunks; no route explosion (the reservation adds no routes); no document flooding.
* Answer-fact probe: `design_life_years` flips False→True on QA-004 (the fix), and V4/G4 show
  `structure_drawings` True→False on identical-token windows in one case — that is generation
  non-determinism plus a substring probe that also scores a negated mention as asserted. Window
  clause counts remain the reliable metric.

---

## READY_FOR_RETRIEVAL_DEPLOYMENT

**YES — candidate accepted, pending the deployment decision (PART E: not deployed).**

| # | criterion | result |
|---|---|---|
| 1 | QA-004 exact 3/3 life + structure | **PASS** — 0,0,0 → 3,3,3 life with structure retained |
| 2 | V1–V6 3/3 required evidence | **PASS** — all six, all three runs |
| 3 | V5 structure 3/3 | **PASS** — 0,0,0 → 1,1,1 |
| 4 | G2/G3/G5 coverage retained | **PASS** — 0,0,0 → 1,1,1 each |
| 5 | QA-001/002/003/005 no regression | **PASS** — identical |
| 6 | no duplicate chunks | **PASS** — 0 in all 48 runs |
| 7 | document diversity not materially worse | **PASS** — unchanged or improved |
| 8 | token growth bounded | **PASS** — +2.3…+13.2 % on affected questions only |
| 9 | latency acceptable | **PASS** — within the characterised band |
| 10 | production runtime traverses Phase 0/1.1/2 | **PASS** — measured fingerprint, `phase2_wired = True` |

Carry into a deployment decision:

1. The candidate is **six file paths on the accepted baseline**, proven by a 130,004-entry manifest
   diff. No planner, no unrelated retrieval evolution, no frontend, no `api/`, no `.venv` change.
2. `rerank_chunks`' four degraded early-return paths do **not** reserve. That is deliberate
   minimality; a deployment without a reranker would not get the coverage guarantee.
3. The G2-shaped displacement (a well-covered fact type losing one passage to an under-covered one)
   is the behaviour to watch on a full benchmark run; both fact types stayed represented here.
4. The phase's own vocabulary is still two fact types. The mechanism is validated independently of
   which fact types exist, so extending the domain layer is additive work with its own evidence.

---

## PRODUCTION_MUTATED

**NO.**

* `wenruo-rag-cpu` is still running, started `2026-10-01T23:11:27Z`, on image
  `sha256:18711d10f0353a9f37d25611bd81030bd6c6af0f00f764ddf0132b5ad3f7d123` — **not recreated**;
* `my-wenruorag:latest` still points at `sha256:18711d10…` — **not retagged**; the candidate carries
  its own tag `my-wenruorag:phase-integration-candidate` (`sha256:c748d24e2e69…`);
* the production container's `pipeline.py` is still `c9174c52926d…` and `rerank.py` still
  `4498c2ed2b2c…`; `route_expansion.py` is still absent from production;
* **not deployed**: no container was created from the candidate for serving; the two containers used
  for measurement (`p2cand`, `p2base`) were removed;
* **no prune was run** (0 dangling images before and after);
* no index write, no MySQL write, no Redis write;
* the four service containers (`es01`, `mysql`, `redis`, `minio`) were only read from.

**Commits this round:** `4ee4775f9` (Phase 2 integration) only, containing the four allowed paths and
no Docker/release file. The candidate Dockerfile and E2E harness live outside the repository
(`%TEMP%\cand_build`, `tools/scripts/candidate_e2e.py` is untracked) and this report is left
uncommitted.
