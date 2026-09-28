# Failure-Mode Characterization

**Headline:** Under pinned inputs and configuration, deployed retrieval is reproducible. The remaining reproducibility and availability risks are upstream LLM decomposition on cache miss and runtime dense-route degradation.

No retrieval parameter, prompt, reranker, embedding model, index, Redis key, or deployed file was modified in this round.

> **Correction up front.** The instrumentation-v2 stage capture is retracted: every one of its 120 runs
> returned an empty window and 8-10 of 10 runs per query raised `TypeError: 'classmethod' object is not
> callable` from this round's own wrapper, absorbed by the pipeline route-failure isolation. Sections 10,
> 12 and 13 of `scripts/audit/retrieval_reproducibility.md` drew pool sizes, cutoff deltas and per-route identities from
> that run; those numbers are withdrawn. The stability result rests on probe v1 (240 runs, zero errors,
> zero quota failures) and is unaffected.

## Task A — Decomposition cold-cache sensitivity

- Isolation: in-process cache bypass (get_llm_cache forced to miss, set_llm_cache no-op); production Redis never read, written, deleted or flushed
- Cache functions before patching: `{"get_llm_cache": "function", "set_llm_cache": "function"}`
- Chat-model calls actually made (proves the cache was bypassed rather than hit): **60**
- Frozen parameters: `{"similarity_threshold": 0.2, "vector_similarity_weight": 0.6, "routes_top_k": 12, "final_top_n": 8, "knn_top_k": 1024, "max_sub_queries": 4, "allow_dense_fallback": true}`
- Probe stderr: {"quota_error_lines": 460, "route_failure_lines": 230, "type_error_lines": 0}

| query | kind | looks_composite | runs | distinct decompositions | sub-query count per run | min pairwise sub-query Jaccard | min pairwise route-set Jaccard | max symmetric difference | replay |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C_STD | COMPOSITE | True | 10 | 2 | [2, 2, 2, 2, 2, 2, 2, 2, 2, 2] | 0.3333 | 0.5 | 2 | BLOCKED_BY_EMBEDDING_QUOTA |
| C_COMPARE | COMPOSITE | True | 10 | 4 | [2, 3, 2, 2, 2, 2, 2, 2, 2, 3] | 0.0 | 0.375 | 5 | BLOCKED_BY_EMBEDDING_QUOTA |
| C_PARTS | COMPOSITE | True | 10 | 3 | [3, 3, 3, 3, 3, 3, 3, 3, 3, 3] | 0.0 | 0.1429 | 6 | BLOCKED_BY_EMBEDDING_QUOTA |
| C_MULTI | COMPOSITE | True | 10 | 3 | [4, 4, 4, 4, 4, 4, 4, 4, 4, 4] | 0.0 | 0.2727 | 8 | BLOCKED_BY_EMBEDDING_QUOTA |
| N_STD | NON_COMPOSITE_CONTROL | True | 10 | 3 | [1, 1, 1, 2, 1, 1, 1, 1, 1, 0] | 0.0 | 0.5 | 2 | BLOCKED_BY_EMBEDDING_QUOTA |
| N_ARMOUR | NON_COMPOSITE_CONTROL | True | 10 | 5 | [0, 1, 0, 1, 1, 2, 0, 2, 0, 1] | 0.0 | 0.2 | 4 | BLOCKED_BY_EMBEDDING_QUOTA |

### Distinct decompositions observed (per query, up to four)

- **C_STD** (Q/GDW 73286.2-2026 中 220kV 单芯海底电缆的内衬层厚度和铠装层要求分别是多少？)
  1. Q/GDW 73286.2-2026 中 220kV 单芯海底电缆的内衬层厚度要求是多少 | Q/GDW 73286.2-2026 中 220kV 单芯海底电缆的铠装层要求是什么
  2. Q/GDW 73286.2-2026 中 220kV 单芯海底电缆的内衬层厚度是多少 | Q/GDW 73286.2-2026 中 220kV 单芯海底电缆的铠装层要求是什么
- **C_COMPARE** (220kV 单芯和三芯海底电缆的内衬层要求有什么区别？)
  1. 220kV 单芯海底电缆的内衬层要求是什么 | 220kV 三芯海底电缆的内衬层要求是什么
  2. 220kV海底电缆单芯与三芯的内衬层要求有什么区别 | 220kV单芯海底电缆的内衬层要求是什么 | 220kV三芯海底电缆的内衬层要求是什么
  3. 220kV 单芯海底电缆的内衬层要求 | 220kV 三芯海底电缆的内衬层要求
  4. 220kV 单芯海底电缆的内衬层要求是什么 | 220kV 三芯海底电缆的内衬层要求是什么 | 220kV 海底电缆单芯和三芯内衬层要求有什么区别
- **C_PARTS** (导体、内衬层和铠装层分别有什么技术要求？)
  1. 导体有什么技术要求？ | 内衬层有什么技术要求？ | 铠装层有什么技术要求？
  2. 导体的技术要求是什么？ | 内衬层的技术要求是什么？ | 铠装层的技术要求是什么？
  3. 导体的技术要求 | 内衬层的技术要求 | 铠装层的技术要求
- **C_MULTI** (单芯电缆与三芯电缆在金属套厚度和铠装层结构上有什么不同，各自依据哪份规范？)
  1. 单芯电缆的金属套厚度要求是什么 | 三芯电缆的金属套厚度要求是什么 | 单芯电缆的铠装层结构要求是什么 | 三芯电缆的铠装层结构要求是什么
  2. 单芯电缆的金属套厚度依据哪份规范 | 三芯电缆的金属套厚度依据哪份规范 | 单芯电缆的铠装层结构依据哪份规范 | 三芯电缆的铠装层结构依据哪份规范
  3. 单芯电缆金属套厚度依据哪份规范 | 三芯电缆金属套厚度依据哪份规范 | 单芯电缆铠装层结构依据哪份规范 | 三芯电缆铠装层结构依据哪份规范
- **N_STD** (Q/GDW 73286.2-2026 是什么标准？)
  1. Q/GDW 73286.2-2026 是什么标准
  2. Q/GDW 73286.2-2026 是什么标准 | Q/GDW 73286.2-2026 标准的内容范围是什么
  3. NONE (no sub-queries)
- **N_ARMOUR** (220kV 三芯海底电缆的铠装层要求是什么？)
  1. NONE (no sub-queries)
  2. 220kV 三芯海底电缆的铠装层要求是什么
  3. 220kV 三芯海底电缆的铠装层材料要求是什么？ | 220kV 三芯海底电缆的铠装层结构要求是什么？
  4. 220kV 三芯海底电缆的铠装层材料要求 | 220kV 三芯海底电缆的铠装层结构要求

**Verdict:** `MATERIAL_DECOMPOSITION_VARIANCE_OBSERVED_AT_ROUTE_LEVEL_REPLAY_BLOCKED`

**Is the Redis cache a performance optimisation or a reproducibility stabiliser?**
REDIS_CACHE_IS_FACTUALLY_PERFORMING_REPRODUCIBILITY_STABILISATION: with the cache bypassed the same question yields different route sets on repeat, while the earlier warm-cache round produced byte-identical decompositions and 10/10 identical evidence windows over 240 runs.

### Retrieval replay

- Status: **BLOCKED_BY_EMBEDDING_QUOTA** for every query that showed variance.
- Cause: the remote embedding quota was already exhausted, so the dense leg failed on every replay run (see the 429 counts above) and every window came back empty.
- Consequence: whether two cold decompositions yield different Top-8 evidence windows is **not answerable today**. The route sets differ, and section 13.4 documents the pool-dependent branches that would amplify such a difference, but no window-level claim is made.

### Downstream amplification (status per mechanism)

| mechanism | status in this round |
| --- | --- |
| recall-floor rescue branch | INERT at the pinned threshold (the configured threshold equals the recall floor, so the second call is identical) |
| core-document follow-up branch | NOT OBSERVABLE (its wrapper could not be exercised without a populated pool) |
| document-family change | NOT OBSERVED (blocked with the replay) |
| key evidence chunk loss | NOT OBSERVED (blocked with the replay) |

## Task B — Dense-route degradation characterization

| link in the chain | finding |
| --- | --- |
| 1 | embedding request failure (429 RESOURCE_EXHAUSTED from the remote embedding API) |
| 2 | route-level exception handling: the failing route is isolated and logged as a warning, the remaining routes continue |
| 3 | warning/error: warning only, in the retrieval module logger |
| 4 | remaining candidate pool: the window is built from the routes that survived |
| 5 | synthesis caller: receives the normal result object |

- **Machine-readable degradation state:** NOT PRESENT — the retrieval result exposes exactly ['["chunks", "doc_aggs", "total"]'] and no degraded/health field; a 240-run probe in which nothing failed returned zero errors, and the quota-affected probes returned the same key set
- **Caller awareness:** NOT AWARE in the silent case; in the observed 429 trace the caller sometimes received a raised exception instead, so awareness is path-dependent rather than guaranteed
- **HTTP status claim:** NOT VERIFIED THIS ROUND (no API call was issued; doing so would consume embedding quota, which is forbidden by the round rules)
- **Trace evidence:** {"stage_probe_429_route_failures": 139, "stage_probe_429_quota_lines": 290, "cold_probe_429_route_failures": 230, "cold_probe_429_quota_lines": 460, "quota_cap_evidence": "free-tier limit 1000 embed requests/day for gemini-embedding-1.0 as reported by the API error body"}

**Classification: `SILENT_RETRIEVAL_DEGRADATION`** — supported for the retrieval layer (no degradation flag, warning-only logging, window built from surviving routes); the HTTP layer is NOT VERIFIED

## Task C — Evidence impact: document family versus authoritative evidence

- **Document-family availability:** stable within a pinned configuration (v1: target family present in the window in 10/10 runs for every query that has a defined target family)
- **Authoritative-evidence availability:** NOT REVIEWED (no human annotation exists; the earlier human evidence template is still all PENDING, so no authoritative-evidence claim is made)

| query | first divergence | EMR | Jaccard@K | classification | runs with target family in window |
| --- | --- | --- | --- | --- | --- |
| S_A1 | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1.0 | STABLE | 10 |
| S_A3 | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1.0 | STABLE | 10 |
| S_B1 | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1.0 | STABLE | 10 |
| S_C3 | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1.0 | STABLE | None |
| U_A2 | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1.0 | STABLE | 10 |
| U_A4 | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1.0 | STABLE | 0 |
| U_A5 | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1.0 | STABLE | None |
| U_B6 | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1.0 | STABLE | None |
| U_C1 | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1.0 | STABLE | None |
| K_STD | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1.0 | STABLE | 10 |
| K_3CORE | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1.0 | STABLE | 10 |
| K_LAYER | NONE_UP_TO_FINAL_SELECTION | 10/10 | 1.0 | STABLE | 10 |

No window-Jaccard-only claim is made here: family availability and authoritative-evidence availability are
reported separately, and the latter is **NOT REVIEWED**.

## Task D — Tie-breaker status correction

**LATENT TIE-BREAK RISK - NOT OBSERVED AS A FAILURE**

three candidate-ordering sites have no secondary sort key, but 240 pinned runs produced 10/10 identical windows and Jaccard@K 1.0, so no tie-induced window change was observed.

## Task E — Failure Mode Matrix

| failure mode | status | evidence | impact |
| --- | --- | --- | --- |
| LLM decomposition variance (cold cache) | **OBSERVED** | cold-cache probe: distinct route sets per query on repeat | route-set change; window impact BLOCKED_BY_EMBEDDING_QUOTA |
| Embedding quota exhaustion (remote API 429) | **OBSERVED** | 460 quota lines and 230 route-failure lines in the cold probe; 290/139 in the stage probe | dense route drops out, warning-only, no degradation flag |
| ANN nondeterminism (same vector, same query) | **NO / controlled replay / NOT OBSERVED** | 240 pinned runs with 10/10 identical windows; three identical GET kNN probes bit-identical | none observed |
| Score tie instability (equal or near-equal score) | **LATENT RISK** | no secondary sort key at any of the three ordering sites; no tie-induced change observed in 240 runs | none observed |
| Hash ordering (process hash seed) | **CLOSED / NO PATH** | no set-ordered or dict-ordered construct reaches candidate order; the only hashing is content-addressed | none |

## Task F — Generalization Risk Table (corpus-independent)

| mechanism risk | mechanism | corpus-independent | observed |
| --- | --- | --- | --- |
| external embedding dependency | query and document vectors come from a remote provider with a request quota; exhaustion removes an entire retrieval leg | True | YES |
| decomposition sampling | the decomposition model call sets no temperature, top_p or seed, so a cache miss can return a different route set | True | YES |
| cache-dependent reproducibility | reproducibility currently rests on a time-limited external cache rather than on deterministic generation | True | YES |
| silent route degradation | a failed leg is logged as a warning and the result object carries no health field | True | YES |
| score tie handling | ordering is score-only with no secondary key, so ties inherit insertion order | True | NO (latent) |
| pool-dependent fallback amplification | recall-floor and follow-up branches are decided by pool composition, so a small upstream change can change the route set and then every downstream tie | True | DERIVED |

Deliberately free of corpus-specific wording: no standard number, no core count, no document-part name.

## Limitations

- Task A materiality is answered at the route-set level only; the evidence-window half is BLOCKED_BY_EMBEDDING_QUOTA because the embedding quota is exhausted for the day.
- No API call was made, so HTTP-level behaviour of a degraded retrieval is NOT VERIFIED.
- Authoritative-evidence availability is NOT REVIEWED: no human annotation exists.
- The remote quota resets daily, so the blocked replay can be repeated without any parameter change once quota is available.

Characterization complete. No fix code, no parameter change, no index write, no Redis mutation.

### Control-gate note (added after generation)

The two intended NON_COMPOSITE controls were both classified composite=true by the deployed looks_composite gate, so this test set contains **no non-composite control**. The gate therefore admits short single-fact questions, meaning the LLM decomposition path applies far more broadly than the COMPOSITE label suggests.

A second observation from the same table: for the armour-layer control the decomposition returned **zero** sub-queries in several runs (sub-query counts 0/1/2 across the ten runs), i.e. a cache miss can also produce an empty decomposition for a question the gate admitted.

Consequences for the verdict: the variance measured here is variance of the real deployed gate plus the real deployed model on real question text, but the round did not obtain a control group, so DECOMPOSITION_VARIANCE_NON_MATERIAL cannot be excluded for questions the gate rejects (that class was not sampled).
