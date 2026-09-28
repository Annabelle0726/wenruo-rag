# Dense-failure short circuit: repair, takeover audit and gate results

**Incident class:** `FALSE_EMPTY_BY_DENSE_EXCEPTION_SHORT_CIRCUIT` — a dense (embedding) exception
raised before lexical ES execution, so the whole route returned false-empty instead of degrading.

**Window:** takeover of an interrupted repair. Repository implementation and offline gates only.
**No production build, no deploy, no retag** (`latest` is still `ea93cd3bb795`), **no mutation of
production ES, MySQL, Redis or configuration.** All production access was read-only.

---

## 1. `TAKEOVER_BASELINE_PROVENANCE`

Four trees were compared before a line was written. Every hash below is measured, not recalled.

| file | Git HEAD (`44bfb1037`) | deployed image `ea93cd3bb795` | worktree at takeover | authoritative copy |
| --- | --- | --- | --- | --- |
| `rag/nlp/search.py` | md5 `a59cb724f` — **pre-P0**, no bridge at all | md5 `54802` bytes, has the P0-B producer bridge | repaired | `deploy/p0_build/search.py` |
| `rag/retrieval/multi_route.py` | deployed P0-C bytes (from commit `f674828e1`) | md5 `dceab7d2` | + mixed-degrade merge | `deploy/p0_build/multi_route.py` |
| `rag/retrieval/health_bridge.py` | md5 `73a37fc9` (P0-C leg attribution) | md5 `73a37fc9` | unchanged | same |
| `rag/retrieval/health_producers.py` | md5 `d1649297` (P0-7 nine-field event) | md5 `d1649297` | unchanged | same |
| `rag/retrieval/pipeline.py` | repository tree (has `cross_part_fallback`) | md5 `1014a3e9` (does **not**) | unchanged | **differs — see below** |

**What the interrupted work had already changed, split by kind:**

* **Already-present repository state, NOT this round** — commit `f674828e1` ("P1-2 step 0") brought the
  deployed P0-B/C/7 producer wiring back into the repository tree: the pre-P0-C `health_bridge.py`
  (whose `_bump` popped both evidence legs and re-declared one `success` — the `SILENT_DEGRADATION`
  defect) was replaced by the approved one, and the P0-7 nine-field event, the route-level leg
  reporting in `multi_route.py` and the pipeline's health wiring were restored. **This is the
  reconciliation the operator asked to have identified, and it is not part of the incident repair.**
* **Already-present repository state, NOT this round** — commits `babab0047` and `44bfb1037`: the
  suspended P1-2 planner implementation and the operator's housekeeping commit.
* **The incident repair itself** — `rag/nlp/search.py`: the health-bridge reconciliation for that
  file (same class as `f674828e1`), plus the new embedding execution mechanism and the
  `LEXICAL_DEGRADED` execution state; `rag/retrieval/multi_route.py`: the mixed-state merge.
* **P1-2 / planner / cache changes in this round: none.** The repair touches two files and adds gates.

**One genuine, pre-existing divergence that the repair does not resolve:** the repository's
`pipeline.py` carries `cross_part_fallback` while the deployed one does not, because the P0 build
snapshots were taken before commit `98ffddcd5`. The gate container is therefore run as *deployed P0
`pipeline.py` + repaired `search.py` and `multi_route.py`* — the combination the deployed image would
have after this repair — and not as the repository's P1-2 pipeline.

---

## 2. `CODEX_DELTA_ACCEPTED / REVISED`

### Accepted as-is

* `SearchResult.retrieval_mode` with `HYBRID` / `LEXICAL_DEGRADED` / `LEXICAL_ONLY`.
* `Dealer.search`: dense failure is isolated at the `get_vector` boundary; a recoverable failure sets
  `LEXICAL_DEGRADED` and the lexical `MatchTextExpr` pass runs for real; a non-recoverable one is
  re-raised unchanged. Non-composite/generate-free questions keep `LEXICAL_ONLY`.
* Missing dense stays **absent**: `vector_similarity: None`, `vector: None`,
  `score_provenance.dense_score: None`, `dim = len(query_vector or [])` — no zero vector, no `D=0`.
* No hybrid weighting in degraded mode: `valid_idx` is not filtered by the hybrid-calibrated `.55`
  threshold, `rerank_with_knn` is not called, so no `_knn_scores` are spliced in. `.55` itself and
  every healthy-path use are untouched.
* The dedicated `ThreadPoolExecutor(max_workers=16)` + `BoundedSemaphore(32)` + 60 s
  `asyncio.wait_for` boundary, with `contextvars.copy_context().run` preserving the shared helper's
  contextvar behaviour.
* `_lexical_scores` / `_model_scores` extraction: pure refactor, healthy path byte-identical.
* `multi_route._merge_degraded_routes`: one lexical scale for a mixed pool, winner chosen by
  `lexical_selection_score` (never hybrid against lexical), stable ties, atomic winner, full
  `selection_sources`, `ValueError` instead of a fabricated score when provenance is missing.
* `_retrieve_route` no longer retries at the recall floor when the route is degraded — there is no
  threshold to relax, and one lexical pass is measured (`limit=30`, `MatchTextExpr` only).

### Revised — two corrections, each with its reason

1. **Credential and permission failures were being converted into a silent degradation.**
   `_recoverable_embedding_failure` accepted any `EmbeddingError`, and in this tree that class wraps
   every non-`ModelException` SDK failure as well as 408/429, with no status check anywhere. A revoked
   API key or a `403 PERMISSION_DENIED` would therefore have produced "semantic search is temporarily
   degraded" indefinitely instead of surfacing a lost capability. Credential/permission markers are
   now non-recoverable, `CancelledError`/`KeyboardInterrupt`/`SystemExit` are named explicitly, and
   everything unrecognised is fail-closed — while the incident's own
   `400 FAILED_PRECONDITION ... location is not supported` stays recoverable, which is asserted.
   Local pool saturation now raises a distinct `EmbeddingCapacityError` (`TimeoutError` subclass) so
   back-pressure is distinguishable from a provider timeout **without adding a reason code or touching
   any frozen enum**.
2. **The degraded `vector: None` crashed the citation path.** `insert_citations` computed
   `len(chunk_v[i])` on it, which raises as soon as the embedding provider recovers between retrieval
   and citation attribution — turning a degraded-but-answerable turn into a 500. An absent chunk
   vector is now handled exactly like the dimension mismatch the same loop already handles. No zero
   vector is introduced on the retrieval side; this is the citation-attribution input only.

### Revised — the gates had never run

Codex's last suite result was **`14 errors, 0 failures`**: every case failed during **fixture setup**,
so the repair was entirely unverified. Two environment defects (`scripted_sim` missing from the
recreated index; the image's local-dev `service_conf.yaml` pointing Redis at `localhost`) and one gate
defect (`_doc_exists_cache` seeded only for live documents, making `_prune_deleted_chunks` fail-open)
are fixed and documented in `deploy/repair_gates/README.md`.

### Revised — three assertions that were not supportable

* `test_healthy_semantic_differential[.25]` compared **two empty result sets**. At that weight the
  fused admission score stays under `.55` and both sides return zero chunks, so "the healthy path is
  unchanged" was being asserted about nothing. A non-vacuity case now runs the weight that admits
  candidates and requires 20 chunks.
* `test_mixed_route_selection_gate` built its "healthy" side at the default `.25` weight, so that side
  was empty and the mixed pool contained degraded rows only — the assertion could never hold. The side
  is now built at `.5` where it admits, and both sides are asserted non-empty.
* `assert rank == 38` and `(STRUCTURE, THREE)` demanded numbers a re-indexed copy cannot reproduce
  (section 5). They are replaced by membership assertions plus recorded ranks.

---

## 3. Verdict blocks

| verdict | result |
| --- | --- |
| `TAKEOVER_BASELINE_PROVENANCE` | **RESOLVED** — four trees compared by hash; P1-2/cache/planner changes identified and excluded from this round; the repository/deployment `pipeline.py` divergence named (section 1) |
| `CODEX_DELTA_ACCEPTED / REVISED` | **REVISED** — mechanism accepted in full; two correctness corrections, two harness repairs, three unsupportable assertions replaced (section 2) |
| `DEGRADED_CONTROL_FLOW_VERDICT` | **PASS** — a recoverable dense failure produces a real lexical pass and a served result; `overall=degraded`, `reason=EMBEDDING_UNAVAILABLE`, `dense=failed`, `lexical=success`, zero contract violations |
| `RETRIEVAL_QUALITY_VERDICT` | **NOT ESTABLISHED** — control flow is proven; recall is not, and G4 forbids comparing against a healthy baseline while a required leg is degraded. Partial evidence is never reported as a complete answer |
| `DENSE_FAILURE_LEXICAL_EXECUTED` | **PASS** — exactly one ES pass, `expressions == ["MatchTextExpr"]`, `limit == 30` |
| `TIMEOUT_LEXICAL_EXECUTED_BEFORE_WORKER_RELEASE` | **PASS** — the real 60 s deadline ran (`elapsed_seconds = 60.218`); the store search executed while the worker was still blocked and unreleased |
| `LATE_DENSE_RESULT_IGNORED` | **PASS** — the returned result and the session's `_leg_facts` are byte-identical before and after the late worker settles |
| `RESOURCE_LEAK_GATE` | **PASS** — 12 timeout cycles: budget returns to 32/32 and worker threads stay within the 16-worker ceiling |
| `CONTROL_SIGNAL_PRESERVATION` | **PASS** — `CancelledError`, `KeyboardInterrupt`, `SystemExit`, `PermissionError`, `401 UNAUTHENTICATED`, `403 PERMISSION_DENIED`, invalid-API-key are all **non**-recoverable; cancellation propagates out of the embedding await |
| `MISSING_DENSE_REPRESENTED_AS_ZERO` | **PASS (not represented as zero)** — `vector_similarity`, `vector` and `score_provenance.dense_score` are `None`; no `_knn_scores`, no hybrid weighted score, and the zero-vector fallback is never consulted in degraded mode (`vector_column` is computed but the field lookup is bypassed) |
| `HEALTHY_PATH_SEMANTIC_DELTA` | **PASS — none.** Against the frozen production `search.py` at weights `.5` and `.25`: identical result dicts after removing the one additive `score_provenance` field, byte-identical ES call trace, one provider call each, identical health DTO. Non-vacuity asserted (20 chunks at `.5`) |
| `MIXED_ROUTE_SCORE_PROVENANCE_PRESERVED` | **PASS** — every chunk keeps its winning row's full provenance; `selection_sources` retains all rows; a hybrid score is never compared with a lexical one; no composite score; the merge is a pure function of its inputs (re-verified with the store patched to explode); a provenance-less row raises instead of being scored; reranker called once over the whole merged pool with unchanged model and position |
| `QGDW_THREE_CORE_SURVIVED` | **PASS** — `d1d75672f2dbc333` at rank **28 of 30 in production**, rank **30 of 30 in the replay**: inside the original window in both, and selected through the degraded path |
| `QGDW_SINGLE_CORE_MAIN_QUERY_WINDOW_STATUS` | **OUTSIDE — frozen fact intact.** Production rank **38**, replay rank **39**; both outside the 30-candidate window. The window was **not** widened |
| `QGDW_CONTROL_QUERY_SURVIVED` | **PASS** — the same chunk `b5aaf72bcd33d44a` is at rank **28** in production and **26** in the replay on the control question that names it: inside a legal window in both |
| `P0_REGRESSION_STATUS` | **PASS** — with the repair in place: runtime symbol binding gate PASS; healthy-path contract gate PASS *including* its negative regression that must fail and flags `SILENT_DEGRADATION`; P0-7 nine-field operator event PASS (exactly one event, exact field set, no leak markers); P0-C frozen injections 5/5 + negative control + boundary leg attribution PASS. The two host-side P0-B build-provenance gates are **NOT_APPLICABLE_TREE_ADVANCED** (both already failed at HEAD, section 4) |
| `G4_STATUS` | **BLOCKED_BY_EXTERNAL_PROVIDER_AVAILABILITY** — unchanged. The A control-flow PASS is explicitly **not** used as retrieval-quality acceptance |
| `P1_2_STATUS` | **PAUSED** — no planner, cache or `plan_hash` change in this round. Two consequences of the suspension are recorded and deliberately **not** fixed here (section 6) |
| `PRODUCTION_MUTATED` | **NO** — no build, no deploy, no retag; `latest` is still `ea93cd3bb795`; production ES/MySQL/Redis/config untouched; every production access was a read (`_search`, `_count`, `_stats`, `get_mapping`, `get_settings`, `SELECT id, name, kb_id`, `GET`) |

**Gate totals: 44/44 PASS** (`test_degradation.py` 16, `test_embedding_execution.py` 28).

---

## 4. The two host-side "P0 regression" gates

`generator_anchor_gate.py` and `semantic_diff_suite.py` are **window provenance artifacts**, not
standing regression gates, and both were already failing before this repair. Measured in a detached
worktree at HEAD:

* `generator_anchor_gate.py` → `ANCHOR FAILURE [multi_route guard success binding]: expected exactly 1
  match(es), found 0` — identical at HEAD and in the worktree.
* `semantic_diff_suite.py` → at HEAD `pipeline.py` PASS, `multi_route.py` PASS, `search.py` PASS,
  `health_bridge.py` **FAIL** (`producer_api_unchanged_this_round` pins `health_producers.py` to a
  hash that predates P0-7) ⇒ `VERDICT: FAIL` before this repair touched anything.

With the repair, the `search.py` and `multi_route.py` scopes also fail — correctly, because a repair
that rewrites `get_vector` and the degraded selection cannot satisfy a gate that pins those files to
"reporter calls only". Classification: `NOT_APPLICABLE_TREE_ADVANCED`. The committed
`deploy/p0_gates/semantic_diff_suite_result.json` was **restored** after the run so the P0-B record is
not overwritten by a run of a gate that no longer applies.

---

## 5. The frozen Q/GDW facts and the fidelity limit

Measured read-only on production (`production_frozen_facts.py`) and in the replay
(`lexical_window_probe.py`):

| fact | production | replay | frozen property | reproduced |
| --- | --- | --- | --- | --- |
| INCIDENT → `d1d75672f2dbc333` (三芯) | rank 28 | rank 30 | inside the original 30 | **yes** |
| INCIDENT → `b5aaf72bcd33d44a` (单芯) | rank 38 | rank 39 | **outside** the 30 | **yes** |
| CONTROL → `b5aaf72bcd33d44a` | rank 28 | rank 26 | inside a legal window | **yes** |
| STRUCTURE → `d1d75672f2dbc333` | rank 27 | > 30 (rank 33 over two pages) | *not a frozen fact* | no — measured only |

**Root cause of the residual, proven rather than assumed.** The replay reproduces the live document
set (486), the shard distribution (251/235), the stored lexical field lengths and the term doc
frequencies **exactly**; the app-side query DSL is byte-identical. Production nevertheless reports
`docs_deleted: 42` against 486 live chunks while the clean copy reports `0`, and Lucene's collection
statistics still count deleted documents. A plain single-term `match` — no application code involved —
returns BM25 `3.455974` in production and `3.376191` in the copy for the same document with identical
`freq` and `docFreq`. The residual is therefore **index history**, which re-indexing cannot reproduce.

Two consequences were accepted rather than worked around:

* Codex's exact-rank assertions are replaced by membership assertions with both ranks recorded;
* the `STRUCTURE` case is a **measurement**, because it is not one of the operator's frozen facts and
  its membership flips at the window edge.

**A new finding, pre-existing and independent of the repair:** the deployed lexical ranking is a
function of index *history*, not only of the query and the live corpus. This directly supports the
standing G4 rule and is recorded for the operator.

---

## 6. Recorded, deliberately not fixed in this window

* **The suspended P1-2 planner leaves 11 of 228 repository retrieval unit tests failing**
  (`test_retrieval_pipeline.py`, `test_composite_question_coverage.py`,
  `test_core_document_route.py`), and its `PlanCache.store` calls `RedisDB.set(..., ex=...)` where this
  tree's wrapper takes `exp` — a live defect in suspended code.
  **Attribution measured, not guessed:** on the repaired tree the repository's own
  `test_multi_route_retrieval.py` **11/11** and `test_core_document_route.py` **13/13** PASS, so the
  failures belong to P1-2, not to this repair.
* **`_retrieve_route`'s recall-floor rescue is skipped for degraded routes** (correct: there is no
  threshold to relax). Note it therefore no longer tries a second pass on a genuine lexical zero-hit;
  that is asserted as `provider_calls == 1`.
* **Pool saturation is classified recoverable** (`EmbeddingCapacityError` → degrade). That is the right
  behaviour for a request, but it means 32 simultaneously hung provider calls degrade every subsequent
  turn immediately instead of failing loudly. Back-pressure is bounded and deliberate; the class is
  distinct so an operator can tell it apart, but the *reason code* reported remains
  `EMBEDDING_TIMEOUT`/`EMBEDDING_UNAVAILABLE` because reason codes are frozen.
* **A hung provider call still blocks interpreter exit**, because a `ThreadPoolExecutor`'s threads are
  joined at exit. This is **unchanged** from the shared helper it replaces (a per-call executor with
  `shutdown(wait=True)`), so the repair neither introduces nor removes it; the gate asserts the
  property explicitly instead of implying it was fixed.

---

## 7. Files

**Changed:** `rag/nlp/search.py` (repair + this round's two corrections),
`rag/retrieval/multi_route.py` (mixed-state merge), `.gitignore` (audit-artifact patterns),
`AGENTS.md` (milestone).

**Added:** `deploy/repair_gates/test_degradation.py`, `test_embedding_execution.py`,
`export_fixture.py`, `export_documents.py`, `lexical_window_probe.py`,
`production_frozen_facts.py`, `diagnose_failures.py`, `repair_gate_report.json`, `README.md`.

**Housekeeping:** the four stray root artifacts were cleared — the PowerShell parse artifact
`).Trim().Substring(7` deleted; `mt_raw.out`, `synthesis_eval_summary.txt` and `trace_out.md` moved to
`scripts/audit/`; `.gitignore` extended with `scripts/audit/*.out`, `scripts/audit/*.md`,
`scripts/ac_audit/*.md`, `scripts/ac_audit/*.txt` so the operator's designated artifact directories stay
local. Previously tracked audit files remain tracked. Three `phase/` leftovers
(`phase_a_readiness.md`, two `phase_a_*_snapshot_*.json`) are committed into `phase/` beside the rest.

**Not deployed.** Stopping here, waiting for the next deployment authorisation.
