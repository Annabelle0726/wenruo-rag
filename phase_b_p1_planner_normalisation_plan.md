# P1 — Planner Normalisation: Planning Document (planning only, no implementation authorised)

Phase B P0 is closed. This document scopes P1. **Nothing here is implemented, and no production mutation is
authorised by it.**

---

## 1. Problem statement

Retrieval **topology** — the set of routes the retrieval pipeline actually executes — is currently a
function of the LLM decomposition's *surface form*, and therefore of **cache state**. Under a cold cache the
same question has been measured to produce **different route sets on repeat**; under a warm cache the same
question is stable.

The consequence is precisely what the operator has identified: **a cache hit and a cache miss are not the
same retrieval**, so answer quality and citation pools can differ for identical input depending on an
invisible infrastructure condition (Redis cache occupancy).

## 2. Evidence base (measured, already on disk)

From the earlier decomposition cold-cache probe (`decomposition_cold_raw.txt`,
`failure_mode_characterization.md`), with the in-process LLM cache **bypassed** so that misses are real and
provable:

| observation | value |
| --- | --- |
| chat-model calls made under bypass (proves misses, not hits) | **60** |
| verdict | **`MATERIAL_DECOMPOSITION_VARIANCE_OBSERVED_AT_ROUTE_LEVEL_REPLAY_BLOCKED`** |
| measured per query | distinct decompositions, sub-query count per run, min pairwise sub-query Jaccard, min pairwise **route-set Jaccard**, max symmetric difference |
| decisive follow-up finding | **`REDIS_CACHE_IS_FACTUALLY_PERFORMING_REPRODUCIBILITY_STABILISATION`** — with the cache bypassed, repeats diverge at route level; warm-cache runs did not |
| complement | *"Under pinned inputs and configuration, deployed retrieval is reproducible. The remaining reproducibility and availability risks are upstream LLM decomposition on cache…"* |

So the retrieval layer itself is reproducible; the variance enters **upstream, at planning**, and the cache
is currently masking it rather than fixing it.

## 3. Goal and the invariant P1 must establish

> **Cache Hit/Miss must not change retrieval topology.**

Formally, for a fixed `(question, plan_version, retrieval config, kb scope)`, the executed route set must be
**identical** whether the planner result came from a warm cache, a cold cache, a retry, or a deterministic
fallback. Ideal target (to be narrowed in design):

```
routes = PlanNormalise(PlannerLLM(question))      # same for hit and miss
routes = FallbackPlan(question)  when the LLM result is unusable
```

with `routes` a **canonical, ordered, deduplicated, bounded** sequence whose identity is captured by a
`plan_hash`, so a topology change is detectable and reportable rather than silent.

## 4. Design directions to evaluate (not decisions yet)

| # | direction | note |
| --- | --- | --- |
| D1 | **Normalise instead of cache-trust.** Canonicalise the planner output (trim, case/diacritic folding, whitespace collapse, dedupe, stable sort, hard cap on route count) before it reaches the route loop. | Directly attacks "surface form decides topology" |
| D2 | **Cache the normalised plan, keyed on canonical input**, rather than raw LLM text. | Makes hit and miss converge by construction instead of by luck |
| D3 | **Deterministic plan fallback.** A rules-based plan (the existing deterministic routes — side routes, clause route) when the LLM output is missing/invalid/empty. | Removes "LLM failed ⇒ different topology"; also reuses logic already in the pipeline |
| D4 | **Plan identity as data.** Emit a `plan_version` + `plan_hash` (and, if authorised, expose it through the existing operator event) so the topology is observable. | Ties P1 back to P0-7's sink; **any new field is a contract change and needs its own authorisation** |
| D5 | **Stability-aware route selection.** Prefer routes that survive across N samples of the same question. | Higher cost (N planner calls); only worth it if D1–D3 are insufficient |

## 5. Scope boundaries (hard)

* **In scope:** the planner/decomposition normalisation boundary and the plan-to-routes mapping.
* **Out of scope, unchanged by P1:** retrieval parameters (`routes_top_k`, `final_top_n`, thresholds,
  weights), fusion/scoring, the embedding model, the index/mapping, prompts *except* where a planner prompt
  change is explicitly authorised as part of P1, the reranker, and **answer-policy enforcement** (stays
  DISABLED).
* **P0 invariants P1 must not break:** producer truth (no leg invented, no status synthesised), the honest
  health contract, and the P0-6 disclosure semantics (unified copy, one notice per retrieval, silent on
  `full`, no history re-notification).
* Any new reason code or DTO field is a **contract change** and needs explicit authorisation
  (e.g. B-2 in the closure record).

## 6. Acceptance gates P1 must satisfy (draft)

| gate | assertion |
| --- | --- |
| G1 **Topology invariance** | For N ≥ 10 repeats of each frozen query, cold-cache and warm-cache route sets are **identical** (`route-set Jaccard = 1.0`, symmetric difference `= 0`), `plan_hash` equal |
| G2 **Cache-state equivalence** | The same question answered with cache forced-miss and forced-hit yields the same route set and the same `plan_hash` |
| G3 **Fallback determinism** | With the planner deliberately failing (invalid JSON / empty plan / timeout), the fallback plan is deterministic and stable across repeats |
| G4 **No recall regression** | A frozen retrieval-quality baseline (the existing Phase A/E set) is not degraded beyond a pre-declared tolerance |
| G5 **P0 invariants intact** | P0-A/B/C gates still PASS; P0-6 C1–C6 still PASS; P0-7 still emits exactly one 9-field line per retrieval |
| G6 **Honesty preserved** | A normalised plan never inflates evidence coverage; `evidence_completeness` behaviour and `validate()` are unchanged |

## 7. Staged plan

| stage | work | exit condition |
| --- | --- | --- |
| **P1-0** | Evidence lock: re-run the cold/warm topology probe against the **current baseline `ea93cd3bb795`**, define "topology" precisely (route set vs ordered routes), freeze the query set and the divergence metrics | a reproducible, baselined divergence number |
| **P1-1** | Design: choose among D1–D5, specify the normalisation contract and the `plan_hash` definition, and state which P0-7 field (if any) is requested | design approved by the operator |
| **P1-2** | Implementation behind an explicit switch, with unit tests for the normaliser and the fallback | gates G1–G3 pass in isolation |
| **P1-3** | Acceptance: cold/warm matrix on the deployed candidate, plus G4–G6 | G1–G6 all PASS, or rollback |
| **P1-4** | Promotion through the established discipline (candidate tag → acceptance → `latest`), rollback anchor retained | baseline advanced |

## 8. Risks and open questions

1. **Over-collapse.** Aggressive normalisation could merge legitimately distinct route intents and lose
   recall — G4 exists for this, and the tolerance must be pre-declared *before* optimisation.
2. **Cache key design.** What belongs in the canonical key (question text normalisation, tenant, KB scope,
   `plan_version`, model id)? A too-narrow key reintroduces variance; a too-wide key serves stale plans
   across changed configuration.
3. **Prompt-level determinism.** Even with normalisation, an unstable planner may return *semantically*
   different plans; P1 must decide whether topology invariance is achieved at the normalisation boundary
   (D1–D3) or needs sampling consensus (D5).
4. **Interaction with the current provider outage.** The dense leg is down (`EMBEDDING_UNAVAILABLE`), which
   changes retrieval behaviour during P1-0 measurements. Baseline measurements must either be taken with
   that condition recorded, or wait until the provider condition clears — **otherwise G4's baseline is
   contaminated**. This is a sequencing question for the operator.
5. **Definition of "retrieval topology"** must be frozen early; if it is the ordered route list, invariance
   is strictly stronger than if it is the route set.

## 9. Explicitly not started

No P1 code, no planner change, no cache change, no prompt change, no retrieval-parameter change, and no new
contract field. **P1 is unlocked for planning only.**
