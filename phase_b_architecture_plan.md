# Phase B — Architecture Hardening: Design Spec (first batch)

Status: **proposal for review. No code, no diffs, no parameter changes are included or proposed for immediate merge.**
Phase A (micro-diagnosis and tuning against the 73286 submarine-cable corpus) is **frozen**: its artifacts, the 155
canary chunks, the retrieval parameters, the embedding/reranker configuration and the KB index stay exactly as
they are.

## 0. Purpose and governing principles

Phase A used one corpus as an engineering hammer and exposed mechanisms that do not depend on its content. Phase B
converts those findings into architectural guarantees, judged on unseen document families.

Governing principles, in priority order:

1. **Determinism over score.** A predictable result is worth more than a higher benchmark number. Target: identical
   pinned inputs produce identical outputs, or the system declares why it cannot.
2. **Transparent degradation.** Graceful degradation is allowed; **silent** degradation is forbidden. A degraded
   result must be machine-readable and human-visible.
3. **Corpus independence.** No rule, gate or test may depend on domain vocabulary (no standard designations, no core
   counts, no document-part names). Everything ships with corpus-independent tests.
4. **Additive evolution.** New fields are additive and backward compatible; existing callers keep working.
5. **Observable by default.** Every new mechanism emits structured state, not just log prose.
6. **No Phase A regression.** Any change must be provably neutral on the frozen Phase A corpus except where it
   fixes a declared defect.

Non-goals for this batch: improving retrieval quality metrics, changing similarity thresholds or weights, changing
tokenization or headers/profiles, changing the embedding or reranker model, re-tuning routes, and adding domain
rules.

### Traceability — Phase A finding to Phase B work item

| Phase A finding | Class | Phase B item |
| --- | --- | --- |
| Embedding quota exhaustion (remote 429) drops a whole retrieval leg; warning-only; result object has no health field; classification `SILENT_RETRIEVAL_DEGRADATION` | P0 | P0-1, P0-2, P0-3, P0-4 |
| Cold-cache decomposition produces materially different route sets (Jaccard down to 0.143); sampling never pinned; a 24 h cache is the only stabiliser | P1 | P1-1, P1-2, P1-3 |
| Gate admits short single-fact questions and can emit **zero** sub-queries | P1 | P1-4, P1-5 |
| Three ordering sites have no secondary key; no failure observed in 240 pinned runs | P2 | P2-1, P2-2 |
| Pool-dependent branches (recall-floor rescue, core-document follow-up) amplify small upstream changes | P1 + P0 | P1-6, P0-2 |
| ANN nondeterminism not observed; hash ordering has no path to output | n/a | closed, keep regression coverage only |

---

## 1. P0 — Retrieval Health Contract and Observability

**Problem.** When the dense leg fails (remote embedding API returns 429 for the day), the failing route is isolated,
the failure is logged as a warning, the window is assembled from the surviving routes, and the caller receives an
ordinary result object exposing exactly `chunks`, `doc_aggs`, `total`. Nothing in that object says evidence is
incomplete, so the synthesis layer and the product surface cannot distinguish full hybrid evidence from a
lexical-only remnant.

**P0-1 — Define the health contract (schema, versioned, additive).**

Illustrative shape, to be finalised in review:

```json
{
  "retrieval_health": {
    "schema_version": "1.0",
    "overall": "full | degraded | failed",
    "legs": {
      "decomposition": { "status": "ok | skipped | failed", "plan_version": "1.0", "reason": null },
      "dense":   { "status": "ok | degraded | failed", "routes_attempted": 5, "routes_succeeded": 2, "reason": "EMBEDDING_QUOTA_EXHAUSTED" },
      "lexical": { "status": "ok | degraded | failed", "routes_attempted": 5, "routes_succeeded": 5, "reason": null },
      "rerank":  { "status": "not_configured | ok | failed", "reason": null },
      "followup":{ "status": "not_triggered | triggered | failed", "reason": null }
    },
    "evidence": { "completeness": "hybrid | lexical_only | partial", "chunk_count": 6, "families": ["..."] },
    "alerts": ["DENSE_LEG_UNAVAILABLE"]
  }
}
```

Rules that belong in the contract, not in a caller's judgement:

- **Monotonic aggregation.** `overall` is the worst of the legs: any `failed` leg makes `overall` at least
  `degraded`; all legs `ok` is required for `full`. Unknown or missing leg status counts as **not `full`**.
- **Reason codes are enumerated**, not free text (initial set: `EMBEDDING_QUOTA_EXHAUSTED`, `EMBEDDING_UNAVAILABLE`,
  `EMBEDDING_TIMEOUT`, `STORE_UNAVAILABLE`, `ROUTE_TIMEOUT`, `PLAN_VALIDATION_FAILED`, `PLAN_EMPTY`,
  `RERANK_UNAVAILABLE`, `THRESHOLD_EMPTY`, `FOLLOWUP_FAILED`, `INTERNAL_ERROR`).
- **Disclosure is mandatory**, serving is optional. The contract never permits a body with `overall != "full"` to be
  returned without its reason codes.
- **No new write path.** Health is computed from state the pipeline already has; it must not add queries, retries or
  index operations.

**P0-2 — Producer and aggregation points.**

- Per-route truth is produced where routes are isolated today (the route-level failure handling in the multi-route
  module) and where the rescue call at the recall floor happens: both must report their outcome upward rather than
  only logging.
- Aggregation happens in the retrieval entry point, which today returns only `chunks`, `doc_aggs`, `total`; the
  health block is added **beside** those keys so existing consumers are unaffected.
- Decomposition, selection and follow-up steps contribute their own leg status (this is why P0-2 depends on P1-1:
  the plan needs an identity and a validation outcome to report).

**P0-3 — Propagation to trace, metrics and synthesis.**

- **Event:** one structured event per retrieval, emitted once, containing question hash, plan version, leg statuses,
  evidence completeness, route counts and reason codes. Log prose stays for humans; this event is the machine record.
- **Metrics:** counters keyed by leg and reason (failures, degradations, rescue-triggered, follow-up-triggered),
  plus a completeness histogram. Alarm on any dense-leg failure rate above a threshold in a window, because a silent
  quota exhaustion must not wait for a customer to notice.
- **Trace:** leg statuses attached as trace attributes so a single request can be explained end to end.
- **Synthesis:** the answer layer receives the health block and must treat it as an input constraint, not decoration.

**P0-4 — Answer-layer policy (needs a product decision; see §4).**

Recommended two-tier policy:

| Evidence completeness | Question class | Required behaviour |
| --- | --- | --- |
| `hybrid` | any | answer normally |
| `lexical_only` / `partial` | narrative or definitional | answer **and** disclose that evidence came from a reduced retrieval path |
| `lexical_only` / `partial` | numeric-constraint or value-precision | refuse to state values, or state them as unverified, and disclose |
| `failed` / empty window with `overall != full` | any | no answer; explicit unavailability notice |

The invariant behind the table: **an answer may never assert hybrid-evidence confidence when a leg has failed.**

**P0-5 — Fault-injection test harness (design requirement).**

Verification must not depend on a real quota exhaustion. The harness injects failures through test doubles at the
embedding boundary: quota error, timeout, partial route failure, total failure. Assertions: status field is present
and correct, reason code is the expected enum member, `overall` is monotonic, the answer layer discloses, no answer
asserts hybrid evidence, and no injection consumes external quota.

---

## 2. P1 — Query Planner normalisation and gate precision

**Problem 1 (routing amplification).** Decomposition calls a model with no sampling constraints, so a cache miss can
return a different route set — measured route-set Jaccard as low as 0.143 on the same question — and pool-dependent
branches downstream amplify that into different windows. The 24 h cache is currently the only thing making the
system reproducible, which means reproducibility is an accident of cache lifetime, not a property of the system.

**Problem 2 (gate too wide).** The composite gate admitted every short single-fact question we offered it, and the
model sometimes returned **zero** sub-queries for a question the gate admitted. Model randomness therefore reaches
the whole retrieval entrance, including for questions that never needed rewriting.

**P1-1 — `RetrievalPlan` schema (explicit contract instead of prose rewriting).**

```json
{
  "plan_version": "1.0",
  "intent": "single_fact | comparison | multi_hop | ambiguous | numeric_constraint | procedural",
  "source": "deterministic | model | model_cached",
  "question_normalized": "...",
  "sub_queries": [ { "order": 1, "text": "...", "target": "value | definition | scope | relation" } ],
  "constraints": { "values": [], "units": [], "document_scope": null },
  "validation": { "schema": "pass", "sub_query_count": 2, "rejected": [] },
  "determinism": { "temperature": 0, "seed": 1234, "canonical_order": true }
}
```

- `plan_version` is the contract identity: health reporting, cache keys and regression tests all key off it.
- Validation is **fail-closed on structure**: a plan that does not satisfy the schema is rejected and replaced by the
  deterministic pass-through plan, and the rejection is reported as `PLAN_VALIDATION_FAILED` — never silently used.

**P1-2 — Determinism contract (preferred order of enforcement).**

1. Pin sampling: `temperature = 0` and an explicit `seed` where the provider supports it. Where the provider ignores
   or lacks the parameter, do not pretend: record that the plan came from a non-pinned source.
2. Canonicalise: deduplicate sub-queries on a normalised form, assign canonical order (first-mention order, stable),
   and cap the count. Two semantically equal model answers must produce identical route sets.
3. Validate: schema and cardinality checks with an explicit fallback (see P1-3).
4. Only then cache: the cache stores **validated plans**, keyed on `plan_version` + normalised question + model id.
   Its documented role becomes *performance*, and the tests must prove hit and miss are behaviourally identical
   (same plan, same routes, same window). This converts the current accidental stabiliser into an explicit one.

**P1-3 — Plan cardinality floor.**

An empty or rejected plan must degrade to the deterministic pass-through plan (the original question as the single
route). **Zero sub-queries must never be a terminal state**, because that is how a model failure currently becomes a
silently narrower retrieval. This is a contract requirement, not a heuristic.

**P1-4 — Two-stage gate with corpus-independent features.**

- **Stage 1 — deterministic structural check**, computed from question structure only: coordination conjunctions
  (language-level function words), count of distinct interrogative heads, comparison markers, enumeration, multiple
  distinct constrained values, clause count, and a length band. Output: `not_composite`, `composite`, or `uncertain`.
- **Stage 2 — optional model confirmation** only for `uncertain`, with a strict schema and the same determinism
  contract as P1-2.
- Explicitly forbidden in the gate: any domain vocabulary, any corpus-specific string, any document-part name. The
  gate must behave identically on a transformer datasheet and a software specification.

**P1-5 — Gate test suite (offline, corpus-independent, de-identified).**

Structure classes, with hand-written synthetic questions containing no domain terms: `single_fact`,
`numeric_constraint`, `comparison`, `multi_hop`, `ambiguous`, `procedural`. Each item carries an expected gate label.
Metrics and gates: false-positive rate on `single_fact` must be ~0 (a single-fact question must not trigger
rewriting); false-negative rate on `comparison` and `multi_hop` must stay low; the suite runs without any model or
embedding dependency so it can run in CI on every change. A second, model-enabled tier measures plan quality
(cardinality, validation pass rate) against the same items.

**P1-6 — Route-set stability reporting.**

Because the pool-dependent branches (rescue at the recall floor, core-document follow-up) amplify upstream change,
each retrieval should report which branches fired and what the route set was (part of the P0 health block). This
makes amplification visible instead of inferable.

---

## 3. P2 — Deterministic tie-breaking

**Problem.** Three ordering sites — the cross-route merge, the rank-adjusted selection sort, and the store-side sort —
order by score only. Ties fall through to insertion order, which is derived from route order and store order. No
tie-induced window change was observed in 240 pinned runs, so this is a **latent risk, not an observed failure**;
Phase B closes it because it costs almost nothing and removes an entire class of future ambiguity.

**P2-1 — Total order at every ordering site.**

- Add a fixed secondary key (stable document/chunk identifier, ascending) to all three sites so the order is total:
  equal scores can no longer inherit input order.
- The comparison must be exact: do **not** introduce fuzzy epsilon tie bands, which would trade one ambiguity for
  another. Any tolerance, if ever needed, must be a single documented constant applied identically everywhere.
- The store side must be addressed too: an approximate kNN clause has no tie-break parameter, so the deterministic
  order has to be imposed by the application after fusion, and the store request must not rely on shard merge order.

**P2-2 — Verification.**

- Fixture tests with deliberately equal scores across multiple documents and across shards; shuffled-input property
  tests asserting identical output for identical score multisets.
- A neutrality check on the frozen Phase A corpus with the pinned configuration: expected result is **no observable
  change** except where ties actually existed, and any change must be itemised with its cause.

---

## 4. Decisions requested before implementation

| # | Decision | Options | Recommendation |
| --- | --- | --- | --- |
| D1 | Behaviour of the answer layer under degraded evidence | qualify and disclose / refuse / two-tier | two-tier per §1 P0-4 |
| D2 | Determinism enforcement for the planner | pin sampling where supported / canonicalise+validate only / both | both, with provenance recorded |
| D3 | Degraded-serving posture when the dense leg is unavailable | serve with disclosure / refuse until quota returns | serve with disclosure for narrative, refuse values |
| D4 | API surface for health | additive response field / header only / trace only | additive field, plus trace |
| D5 | Holdout ingestion and corpus selection | OPGW-ADSS, transformer, software spec as named | approve all three, read-only, Phase A artifacts untouched |
| D6 | Fault-injection mechanism | test doubles at the embedding boundary / synthetic 429 | test doubles; never spend real quota on failure tests |
| D7 | Quota availability control | per-day budget guard and circuit breaker / local fallback model | guard and breaker first; a fallback model changes retrieval semantics and needs its own review |

---

## 5. Holdout acceptance criteria (Phase B exit)

**Setup.** A small holdout set spanning four families — the existing cable corpus plus OPGW/ADSS, transformer, and
software-specification documents — ingested with **no change to any rewriting rule or retrieval code**. Phase A
artifacts, the canary chunks and the pinned configuration remain untouched. Note that a fallback embedding model, if
ever approved (D7), must be evaluated as its own configuration rather than as part of this gate.

**Gates.**

| id | Gate | Threshold | Failure meaning |
| --- | --- | --- | --- |
| G1 | Determinism per family: repeated pinned runs per query produce identical windows | exact match, all runs, all queries | the system is not reproducible on unseen content |
| G2 | Health coverage: every retrieval with a failed leg carries correct reason codes and monotonic `overall` | 100% | silent degradation |
| G3 | Disclosure integrity: no answer asserts hybrid evidence when a leg failed; degraded answers disclose | 100% | product-level false confidence |
| G4 | Gate precision: single-fact questions never trigger model rewriting | false-positive rate ~0 | unnecessary model randomness at the entrance |
| G5 | Gate recall: comparison and multi-hop questions are still decomposed | false-negative rate low | lost recall on genuinely composite questions |
| G6 | Family isolation: windows for a question in family A contain no document from family B | 0 cross-family hits | cross-family contamination on unseen content |
| G7 | No silent emptiness: an empty or near-empty window never reports `full` | 100% | the exact Phase A failure, unfixed |
| G8 | Phase A neutrality: frozen corpus results unchanged except for declared, itemised causes | no unexplained diffs | hardening changed judged behaviour |

**Suite mechanics.** The Phase A probe pattern — pinned configuration, ten runs per query, per-stage capture, JSON
artifacts — becomes the reusable reliability regression suite. Determinism and gate suites run offline without
external calls; only holdout validation needs the live embedding path, and it runs inside a budget guard so a quota
exhaustion cannot masquerade as a product result. If quota is unavailable, the round reports `BLOCKED_BY_QUOTA`
rather than a degraded substitute — the same discipline this characterization round used.

---

## 6. Sequencing, dependencies and definition of done

| Order | Item | Depends on | Definition of done |
| --- | --- | --- | --- |
| 1 | P0-1 contract + P0-2 aggregation | — | schema reviewed; health present on every retrieval; existing consumers unaffected |
| 2 | P0-5 fault-injection harness | P0-1 | injected quota/timeout/partial failures produce correct codes; zero real quota consumed |
| 3 | P0-3 propagation, P0-4 answer policy | P0-1, D1, D3 | degraded retrieval is visible in trace, metrics and the answer; disclosure assertions pass |
| 4 | P1-1 plan schema + P1-2 determinism + P1-3 floor | P0-1 | hit and miss provably identical; rejected plans fall back and are reported; no empty plan |
| 5 | P1-4 gate + P1-5 suite | P1-1 | gate suite green offline; single-fact false positives ~0 |
| 6 | P1-6 stability reporting | P0-2 | fired branches and route sets visible per retrieval |
| 7 | P2-1 tie-breaker + P2-2 verification | — (independent) | total order proven; Phase A neutrality check itemised |
| 8 | Holdout validation | all of the above | gates G1-G8 pass or the round stops with a declared blocker |

**Standing constraints for every item:** no retrieval-parameter tuning, no prompt/reranker/embedding changes, no KB
index writes, no modification of the frozen Phase A artifacts, and no change that cannot be explained by a named
finding in the traceability matrix.
