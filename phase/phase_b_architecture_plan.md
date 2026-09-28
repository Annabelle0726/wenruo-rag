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

---

# Revision 2 — approved decisions (binding, supersedes conflicting text above)

Revision 2 was approved by the project owner. Where earlier text disagrees with this section, **this section wins**.

## R2.1 D1 / D3 — answer policy graded by question risk

| Question class | Evidence state | Required behaviour |
| --- | --- | --- |
| Narrative / explanation | degraded | answer allowed, **disclosure mandatory** |
| Constraint-bearing / numeric / standard-compliance | a key evidence leg failed and completeness cannot be proven | **definitive conclusion forbidden**; must return evidence-incomplete / cannot-verify |
| any | failed | **refuse every factual answer** |

The decision criterion is **not** "did the dense leg fail" but "**is evidence completeness sufficient for this
question's claim type**". This is why the contract must expose the two layers of R2.5 separately: a degraded
execution layer can still carry fully sufficient evidence (for example a standard-identifier lookup whose evidence
came entirely from the lexical leg), and in that case a constraint question may be answered.

## R2.2 D2 — planner variance control contract

Adopt **sampling pinning (`temperature=0`, explicit `seed`) + canonical order + schema validation + deterministic
fallback** jointly.

Positioning is explicit: **pinning is a variance-reduction aid and must never be treated as a correctness guarantee.**
The system contract is carried by schema validation, canonical ordering, deduplication and the deterministic
pass-through fallback, all of which hold even when a provider ignores or lacks the seed parameter.

## R2.3 D4 — API exposure of retrieval health

`chunks`, `doc_aggs` and `total` stay byte-compatible. An **additive** `retrieval_health` field is introduced.

Internal Python callers receive a structured health object; the API layer stably exposes `overall`,
`evidence_completeness` and a publishable `degradation_reason`. **Burying the state in log traces only is
forbidden.**

## R2.4 D7 — quota circuit breaker and availability control

Implement the **circuit breaker and budget guard first**.

**A fallback embedding model must never be swapped in at query time to search an existing vector index** — that
introduces vector-space semantic mismatch and uncontrolled noise. No fallback model may be introduced until an
independent vector representation exists and vector compatibility has been verified.

## R2.5 Architecture distinction — Retrieval Health is NOT Evidence Sufficiency

```
RetrievalHealth
 ├─ execution_health (machine-determined)
 │    ├─ lexical / dense / decomposition / followup / rerank
 │    └─ status: success | degraded | failed
 └─ evidence_state (semantic sufficiency)
      ├─ completeness: full | partial | insufficient
      └─ support_level / authority
```

The first layer is machine-determined execution health; the second layer is the semantic judgement of whether the
evidence is sufficient to support an answer. They are reported separately and **both** feed the answer policy of
R2.1. Collapsing them into one field is prohibited, because it would make a mere leg failure indistinguishable from
genuine evidence insufficiency.

## R2.6 Gate G6 revision

**G6 — No Unjustified Cross-Family Contamination** (replaces the earlier absolute rule):

- **Single-target query:** contamination by an unrelated document family is strictly forbidden.
- **Comparison / cross-document query:** justified cross-family evidence retrieval is allowed **and required**.

## R2.7 P0 implementation plan — Retrieval Health Contract

**Deliverable 1: the contract module.** New dependency-free module `../rag/retrieval/health.py`:

- Enumerations: `LegStatus` (success / degraded / failed / skipped / not_triggered / unknown), `OverallStatus`
  (full / degraded / failed), `ReasonCode` (enumerated failure reasons), `Completeness`
  (full / partial / insufficient), `QuestionRisk` (narrative / constraint_bearing),
  `AnswerAction` (answer / answer_with_disclosure / refuse_insufficient / refuse_failed).
- Structures: `ExecutionHealth` (per-leg status, route counts attempted vs succeeded, reason),
  `EvidenceState` (completeness, support level, authority, families), `RetrievalHealth` (execution + evidence +
  alerts + versions).
- Aggregation: **monotonic worst-of**, where skipped and not-triggered legs are neutral (they neither grant nor deny
  `full`), any failed evidence leg caps the result below `full`, all evidence legs failed yields `failed`, and an
  unknown or missing leg status is never `full`.
- Invariants (violations are reportable, not silently tolerated): a non-`full` status must carry at least one reason
  code; `insufficient` evidence must never report `full` (this is gate G7 in code form); a failed leg must carry a
  reason.
- Policy: `decide_answer_action(health, risk)` implementing R2.1 exactly, plus a generic disclosure notice with no
  domain vocabulary.
- Interop: `api_view()` exposing precisely `overall`, `evidence_completeness`, `degradation_reason`;
  `attach_health(result, health)` adding the field while preserving every existing key; JSON round-trip.

**Deliverable 2: producer wiring (deployment-gated).** Per-route outcome captured where routes are isolated and at
the recall-floor rescue; aggregation in the retrieval entry point beside the existing keys; selection and follow-up
legs reported; the decomposition leg fed by the plan validation outcome (P1).

**Deliverable 3: propagation.** One structured event per retrieval, counters per leg and reason, trace attributes,
and the health object passed to synthesis as an input constraint.

**Deliverable 4: the P0 gate — fault injection with zero external quota.** Inject dense 429, planner validation
failure, empty plan and lexical failure through test doubles; assert for each: correct status and reason code,
monotonic `overall`, correct evidence state, and the policy action required by R2.1; assert that **no injected
failure produces a silent degradation** (every non-`full` health carries at least one reason and never yields an
unrestricted answer).

**Deployment note.** The running container executes its own revision and shares no bind mount with this tree, so this
code lands in the repository and its unit and fault-injection gates run on the host. Deploying it into the running
container requires a rebuild and is a separate authorization; no container file is patched in place, and Phase A
artifacts stay frozen.

**Stage order (single-threaded, as instructed).** P0 contract → P0 fault-injection gate → P1 planner normalisation
and schema contract → P1 gate precision with a corpus-independent synthetic suite → P2 deterministic tie-breaker →
holdout final acceptance. No parallel workstreams, and tie-breaker work does not start early.

---

# Revision 3 — P0 Target Behaviour and FROZEN Acceptance Contract

Revision 3 incorporates the historical forensic audit (commit `69f16b336`) into the P0 design. It is binding and
freezes the P0 acceptance boundary. Documentation only: **no front-end code is written in this revision, no key
probe is run, and no production mutation is performed.**

## R3.1 The historical root cause that defines the target

| era | mechanism | user-perceived result |
| --- | --- | --- |
| old (pre-isolation) | embedding 429 → **hard failure** (`embedding_failure` raised) → request rejected → the Search page's **per-request** `.catch()` fires `message.error` once **per in-flight request** | toast storm: N concurrent requests → N toasts; later reworded by `a785e1842` into readable sentences |
| current | route boundary isolates the Dense exception, logs a warning, returns `RouteResult(failed=True)` → retrieval returns a normal success payload from the surviving routes → the global interceptor toasts only on 413/504, so the `.catch()` never runs | **complete silence** — `SILENT_RETRIEVAL_DEGRADATION` as seen by the front end |

Therefore: the old toast storm is **forbidden to restore**, and the current silence is **the defect to fix**. The
fix is a single, deliberate, retrieval-scoped notice — never a re-raised exception.

## R3.2 Target behaviour definition (binding)

1. **Keep route isolation.** A dead Dense leg must continue to let the Lexical leg return evidence. The pipeline
   must not re-raise the Dense exception, and no layer may convert a missing Dense leg into a request failure.
   > **Forbidden rollback:** re-throwing the Dense exception to make the UI show an error is prohibited, in every
   > form — no re-raise, no synthetic non-2xx, no error `code` for a partial retrieval.
2. **Pass `retrieval_health` through** unchanged: collected at the execution points, aggregated once, attached
   additively to the retrieval result, exposed on the DTO.
3. **Exactly ONE retrieval-level friendly notice.** Granularity is **one retrieval**, not one route and not one
   leg. If five routes fail on the same retrieval, the user sees **one** notice. The notice is a function of the
   attached health block, so it is naturally deduplicated: one health block per retrieval → at most one notice.
4. **Answer-policy enforcement stays `DISABLED`** (R2.1's refusal logic remains out of scope for P0). The notice
   informs; it does not refuse, and it does not alter the baseline answer flow.

## R3.3 FROZEN acceptance contract

| # | condition | required user-visible outcome |
| --- | --- | --- |
| C1 | `overall = full` | **no degradation notice at all** — not a toast, banner, inline note or badge |
| C2 | `overall = degraded` **and** `degradation_reason = EMBEDDING_QUOTA_EXHAUSTED` | **exactly one** friendly "semantic retrieval limited" notice for that retrieval |
| C3 | `overall = degraded` **and** `degradation_reason = EMBEDDING_UNAVAILABLE` | **exactly one** generic "retrieval degraded" notice for that retrieval |
| C4 | any other degraded/failed reason | **exactly one** generic retrieval-degraded notice; never a provider or infrastructure message |
| C5 | N routes or N legs failed on one retrieval | **still exactly one** notice (multiplicity is a hard failure, not a cosmetic issue) |
| C6 | safety red line | notice text must never contain an API key or key fragment, the provider's JSON error body, model/provider identifiers beyond what a user needs, endpoint/version strings, stack traces, or any infrastructure detail |
| C7 | decoupling | answer-policy enforcement remains `DISABLED`; `partial` evidence must not by itself produce a refusal in P0 |

**Separate acceptance tracks (must not be conflated).**

- **Operator observability** (machine-readable DTO + log line + metrics/trace) and **user disclosure** (the single
  notice) are accepted **independently**. Passing one never implies the other.
- Note the current honest gap: the candidate delivers the DTO only. The structured event it builds is appended
  in-process and is **not** written to logs or metrics, so operator observability is **not yet accepted**.

## R3.4 Evidence required to accept each rule (for the future gate)

| rule | evidence |
| --- | --- |
| C1 | healthy-path run: `overall = full`, notice count **0** |
| C2 / C3 | injected quota failure and injected unavailable failure: notice count **1**, and the text matches the required semantic class |
| C4 | injection with another reason: notice count **1**, generic text |
| C5 | injection failing **all** Dense routes at once: notice count **1** (the deduplication proof) |
| C6 | text assertion that the rendered notice contains no key material, no JSON body, no endpoint or stack text |
| C7 | assertion that a `partial` evidence state alone produces no refusal and no answer-flow change |
| isolation | assertion that no injection produces a non-2xx status, a non-zero `code`, or a re-raised exception |
| tracks | separate reports for operator observability and user disclosure, each with its own PASS/FAIL |

## R3.5 Scope and blockers recorded with this revision

- **Front-end implementation is deferred.** R3.3 is now a frozen contract; the UI work is a separate, later work
  order, and this revision writes no front-end code.
- **Gemini credential compatibility is an independent Blocker.** The `KEY_1` / `KEY_2` probe and the model-id
  question are **paused** (both returned HTTP 404 model-not-found; quota health undetermined) and are tracked
  separately from P0. They must be resolved before any live gate, and the fact that a 404 would block the
  healthy-path negative control is recorded, not worked around.
- **No production mutation, no DB change, no restart, no P1 entry** in this revision.
- The P0 acceptance boundary is now **frozen**: changes to C1–C7 require a new revision, not an in-flight edit.
