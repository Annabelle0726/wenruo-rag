# P1-1 — Planner Normalisation: Design (DESIGN ONLY — no implementation authorised)

Red lines honoured: **no change to planner implementation, cache, prompts, sampling parameters, retrieval
parameters, the P0 `retrieval_health` DTO, or the frozen P0-7 nine-field log event.** Nothing in this
document is implemented. Production remains `latest` = `ea93cd3bb795`.

Architecture adopted: **Textual Canonicalisation + Schema/Semantic Validation + Deterministic Fallback.**

---

## 1. Correctness architecture

### 1.1 The governing constraint, stated plainly

> **Schema-valid ≠ topology-determined.** A plan that parses and satisfies every structural rule can still
> differ from another valid plan in *how many* routes it contains, *which* routes they are, and *in what
> order* — and it is that triple, not the schema, that defines retrieval topology.

### 1.2 The theorem the design must satisfy

`G1` is frozen as **ordered identity** (§2). Therefore:

> **For the ordered executable topology to be identical across runs, the number, identity and order of
> executable routes must be a function of the INPUT alone.**
> Formally: `Topology = F(question, plan_version, config, kb_scope)`, with the model output permitted only to
> take values that `F` maps into the same result.

Any architecture in which the model is authoritative for *count*, *identity* **or** *order* cannot satisfy
G1 by construction. It can only satisfy it probabilistically — which is exactly the failure P1 exists to
remove. **This forces the model out of the authority position for topology.** That is the central design
consequence, and it is the answer to the operator's question in §1.5.

### 1.3 Slot authority model (who decides what)

The executable plan is expressed as an **ordered list of slots**, each slot being one executable route.
Authority is assigned per property, not per field:

| property of the executable plan | authority | rationale |
| --- | --- | --- |
| **slot count** | **input-derived profiler** | the model's 0/1 route jitter on non-composite controls (P1-0) is exactly this property |
| **slot identity** (canonical route template) | **input-derived** template instantiated from input facts | guarantees byte-stability |
| **slot order** | **input-derived** canonical order | ordered identity requires a fixed total order |
| slot admission eligibility (composite vs pass-through) | **input-derived** classifier | see the `looks_composite` evidence in §5 |
| model-derived attribute hints, keywords, raw proposal text | **none on topology** — metadata/provenance only | model insight is preserved without touching topology |
| route *execution* parameters (existing frozen retrieval parameters) | **unchanged in P1** | out of scope; explicitly red-lined |

**Which model-derived fields may affect the final executable topology: none.** Every model-derived field is
either (a) discarded for topology purposes and retained as provenance, or (b) required to canonicalise into a
value the input already determines. **Which fields become Metadata/Provenance:** the raw proposal text,
per-proposal acceptance/rejection reason, the model's attribute hints, and any confidence or rationale —
recorded (§6) but topology-inert.

### 1.4 When Deterministic Fallback triggers, and how it is built from input

Fallback is **per slot**, not all-or-nothing, so one bad proposal cannot sink a plan:

| trigger | condition |
| --- | --- |
| T1 transport/parse | model call failed, timed out, or returned non-JSON |
| T2 schema | payload fails the schema (missing keys, wrong types, over-length strings) |
| T3 closure | proposals reference attributes outside the closed vocabulary |
| T4 mismatch | proposal does not canonicalise into the slot's required canonical form |
| T5 emptiness | the plan is empty **where the input declared at least one slot** |
| T6 non-composite | the input classifier says no decomposition is required ⇒ **pass-through, zero model slots** (§5) |

Fallback content is constructed **only from input**, never from model text:
`FallbackRoute(slot) = Template(slot.attribute_key) ⊗ InputFacts(question)` — e.g. the slot's canonical
attribute template filled with the question's entity/standard tokens. Because `slot`, `Template` and
`InputFacts` are all input-derived, the fallback is deterministic and identical on every run.

### 1.5 How different legal model outputs converge to one executable topology

Proof sketch, by construction:

1. The profiler computes, from the input alone: the slot count `N`, each slot's canonical identity, and the
   canonical order `σ`. These do not read the model output at all.
2. For each slot `i ∈ 1..N`, the model's proposal is admitted **only** if it canonicalises to
   `CanonicalForm(slot_i)`. Otherwise that slot takes `FallbackRoute(slot_i)` (T4).
3. The executable topology is `[ route(slot_1), …, route(slot_N) ]` in order `σ`.

Therefore any two model outputs — different wording, different order, extra or missing proposals, or no
proposal at all — yield the **same** `N`, the same per-slot identities and the same order, because every
per-slot value is either the slot's own canonical form or its input-derived fallback. The model influences
*which slots are satisfied by a canonicalised proposal versus by fallback* (a provenance fact), never the
topology. ∎

**Honest limitation, stated rather than hidden:** under this architecture the model can no longer *add* a
route the profiler did not declare. Its semantic contribution is therefore reduced to satisfying declared
slots and to provenance. Recovering the model's ability to *discover* attributes is an explicit open
decision (§8, O1) — and if it is granted, it must be granted as **slot declaration derived from input**
(e.g. an input-declared open slot whose identity is still a canonical template), never as free-text
topology.

---

## 2. Topology definition — FROZEN

```
retrieval_topology ≔ the ORDERED list of Executable Routes
                     after Validation / Canonicalisation / Fallback,
                     immediately BEFORE retrieval execution
```

| rule | statement |
| --- | --- |
| T-a | **G1 PASS requires ordered identity** — element-wise equal, same length, same sequence. |
| T-b | Unordered Jaccard and symmetric difference are **diagnostic metrics only**; they may never be used to declare G1 PASS. |
| T-c | The topology is compared on canonical route identity (§3.2), not on raw model text. |

**Consequence of T-a, accepted deliberately:** P1-0's `C_PARTS` and `C_MULTI` rows, which looked
"set-similar" by Jaccard, are **not** near-passes — under ordered identity they are outright failures. The
gate is stricter from P1-1 onward, by the operator's decision.

---

## 3. Plan identity and pipeline

### 3.1 The single processing chain (frozen)

```
Raw Output → Validate → Canonicalise → Deterministic Fallback
           → Canonical RetrievalPlan → plan_hash → Cache / Execute
```

`plan_hash` is computed over the **Canonical Ordered Executable Plan**. Hashing the raw model output is
prohibited: P1-0 measured that raw hashing reports **23** distinct values where canonical hashing reports
**19** on the same six queries — it would monitor serialization noise as if it were topology change.

### 3.2 Canonicalisation rules (textual layer)

| step | rule |
| --- | --- |
| C1 | Unicode **NFKC** normalisation |
| C2 | collapse all whitespace runs to a single space; trim ends |
| C3 | strip leading/trailing sentence punctuation (`？?。.！!，,、;；:：` and full-width equivalents) |
| C4 | case-fold (affects Latin only) |
| C5 | drop empty and duplicate routes |
| C6 | map to the slot's canonical template form (§1.4 T4) |
| C7 | order by the input-derived canonical order `σ` |

### 3.3 `plan_hash` serialization and versioning (byte-level determinism)

Hash input — no ambiguity, no optional whitespace:

```
digest = SHA-256( "P1PLAN" ‖ 0x1F ‖ plan_hash_version ‖ 0x1F ‖ plan_version ‖ 0x1F ‖ canonical_json )
plan_hash = first 16 hex chars of digest
```

where `canonical_json` is produced under these rules:

| rule | statement |
| --- | --- |
| S1 | JSON with **keys sorted** (code-point order), separators exactly `,` and `:`, no insignificant whitespace |
| S2 | strings NFC-normalised and JSON-escaped minimally; **no** locale-dependent formatting |
| S3 | integers only — no floats, no `NaN`, no `-0`; absent ≠ null (both are explicit and distinct) |
| S4 | the ordered route list is serialized as a JSON array, so **order is inside the hash** |
| S5 | the input includes `plan_hash_version` and `plan_version`, so a hash never silently means two things |
| S6 | **any** change to canonicalisation, slot semantics or serialization **bumps `plan_hash_version`**; hashes from different versions are non-comparable by construction |

Consequence: whitespace or JSON-key-order differences in the model response cannot change `plan_hash`
(regression case R5, §7). A changed route *order* **does** change it (by S4), which is what makes G1's
ordered requirement enforceable through the hash.

---

## 4. Cache invariant

```
Cold Miss ≡ Warm Hit ≡ Retry ≡ Deterministic Fallback
```

| aspect | rule |
| --- | --- |
| equality domain | **ordered executable topology AND `plan_hash`** — identical in all four states |
| cache key | `(plan_hash_version, plan_version, tenant/workspace scope, kb scope, canonical question digest, frozen config digest)` |
| what Redis stores | **only an already-determined canonical plan** — never a raw model response |
| read path | a stored plan is **re-canonicalised and re-validated on read**; a value that fails validation is treated as a **miss** and falls back deterministically (defence in depth against stale/poisoned entries) |
| failure of Redis | degrades to a cold miss, which by §1.5 yields the same topology — availability changes, correctness does not |
| role change | Redis stops being a reproducibility crutch ("freezing whichever random result arrived first") and becomes a cache **of a deterministic artifact**. Correctness now comes from validation + canonicalisation + fallback. |

**Retry** is modelled as a cold miss with the same key, so it inherits the same guarantee. **Bounded
retry** (at most one planner retry) may be specified in P1-2; a retry must not be able to alter topology
because every slot is already input-deterministic.

---

## 5. Controls — deterministic pass-through

**P1-0 evidence that motivates this section:** both control queries were labelled
`NON_COMPOSITE_CONTROL` yet the deployed gate recorded **`looks_composite: true`** for them, and their
executable route count oscillated between **0 and 1**. So the permissive classifier let the model become
topology-authoritative on questions that never needed decomposition, and the model then intermittently
invented or omitted a route.

Design:

| rule | statement |
| --- | --- |
| P-a | For an input classified non-composite, the model is **not consulted for topology** (zero model slots), and the input classifier is **authoritative**. |
| P-b | Topology = `[canonical(question)]` plus the input-derived deterministic routes (comparative side routes / clause route) in canonical order. |
| P-c | The classifier's decision must itself be a deterministic function of the input (no sampling, no model call). Tightening the existing permissive `looks_composite` is part of P1-2 — **as a classifier rule, not as a prompt change**. |
| P-d | Consequently the P1-0 `[0, 1]` route-count jitter on `N_STD` / `N_ARMOUR` becomes structurally impossible: count is 1 deterministic route, always. |

---

## 6. Observability boundary — a separate `retrieval_plan` event (design only)

**The frozen P0-7 nine-field `retrieval_health` event is not touched.** No `plan_hash`, no planner field may
be added to it. Planner provenance is designed as its own event.

Proposed event — name `retrieval_plan`, emitted independently of `retrieval_health`:

| field | type | notes |
| --- | --- | --- |
| `event` | const `"retrieval_plan"` | discriminator |
| `schema_version` | string | contract version for this event |
| `plan_hash_version` | string | which canonicalisation/serialization produced the hash |
| `plan_version` | string | planner semantics version |
| `plan_hash` | 16-hex string | **over the canonical ordered executable plan**, never raw output |
| `topology_size` | int | number of executable routes |
| `slot_sources` | array of enums | one per slot, in order: `model_canonicalised` \| `deterministic_fallback` |
| `fallback_reasons` | array of enums (bounded) | `T1..T6`, deduped, sorted |
| `cache_state` | enum | `cold_miss` \| `warm_hit` \| `retry` \| `fallback` |
| `contract_valid` | bool | plan-level schema/semantic validation result |

| property | design decision |
| --- | --- |
| **cardinality** | bounded: `topology_size` ≤ declared max; `slot_sources` length = `topology_size`; `fallback_reasons` restricted to the closed `T1..T6` set. No tenant, kb, question or route text — those would be unbounded labels |
| **privacy** | **no question text, no route text, no chunk content, no key, endpoint, provider body or stack trace.** Only enums, counts and a hash. Same whitelist-by-construction discipline as the P0-7 emitter (explicit literal, never a spread) |
| **exactly-once** | one `retrieval_plan` per retrieval, emitted at the same guarded anchor as the health event (first emission wins; later aggregation on the same session is a sink no-op). Verified by the repeat-count method already used for P0-7 (1/2/3 retrievals → 1/2/3 lines) |
| **plan_hash expression** | the 16-hex digest from §3.3, emitted as a plain string. It is topology-identifying but **not** reversible to route text, so it is safe in an operator sink |
| **relationship to P0-7** | independent sink, independent schema, independent acceptance gate. Adding this event is a **contract change requiring its own authorisation** (same bar as backlog item B-2) |

---

## 7. Gate specifications (updated)

### G1 — Topology invariance (**ordered**)

* N ≥ 10 repeats per frozen query, cold cache.
* **PASS ⟺ element-wise equality of the ordered route list** across all runs (same length, same sequence),
  and `plan_hash` identical.
* Unordered Jaccard / symmetric difference: **diagnostic only**, never a PASS criterion (T-b).
* Explicit **FAIL** trigger: any two runs whose ordered lists differ at any index — including a pure
  reordering with an identical set.

### G2 — Cache-state equivalence

* PASS ⟺ `topology(cold_miss) ≡ topology(warm_hit) ≡ topology(retry) ≡ topology(deterministic_fallback)`
  with identical **ordered** topology **and** identical `plan_hash`.
* Also asserts: a stored value failing re-validation on read is treated as a miss (no topology change).

### G3 — Fallback determinism

* PASS ⟺ for each trigger `T1..T6`, the produced topology is deterministic across N ≥ 10 repeats and equals
  the topology produced with an *absent* model output; `slot_sources` shows `deterministic_fallback` for the
  affected slots only.

### Regression cases mandated by the operator

| id | case | required outcome |
| --- | --- | --- |
| **R1** | several **distinct legal** model outputs (different wording, order, extra/missing proposals) | converge to **identical ordered executable topology** (and identical `plan_hash`) |
| **R2** | cold miss / warm hit / retry | **identical `plan_hash`** (and identical ordered topology) |
| **R3** | empty model plan; non-composite control group (`N_STD`, `N_ARMOUR`) | **deterministic pass-through / fallback**; route count fixed, no `[0,1]` jitter |
| **R4** | route **order** changed | **G1 must FAIL** (ordered identity; the set may still be equal) |
| **R5** | serialization-only differences (whitespace, JSON key order) | **identical hash** (S1–S3) |

### G4 — recall neutrality

**`BLOCKED_BY_EXTERNAL_PROVIDER_AVAILABILITY`** — unchanged. Rule in force: planner determinism acceptance
may proceed while Dense is degraded; retrieval-quality/recall acceptance may not establish or compare a
healthy baseline while a required retrieval leg is degraded.

**Important consequence to surface now:** §1.5 deliberately removes the model's authority over topology, so
P1-2 **will** change which routes execute relative to today. Therefore **P1-2 acceptance necessarily depends
on G4**, and G4 is blocked until the dense leg recovers (or until a healthy baseline is otherwise
established). P1-0/P1-1 are unaffected; **P1-2 is gated on provider recovery.**

### G5 / G6 — unchanged

G5: P0-A/B/C, P0-6 C1–C6 and the P0-7 nine-field event all still PASS. G6: `validate()` semantics and
evidence behaviour unchanged; nothing inflates coverage; **the nine-field event is not modified**.

---

## 8. Decision table

| # | decision | options | recommendation | status |
| --- | --- | --- | --- | --- |
| D1 | authority for slot count/identity/order | model-authoritative · input-authoritative · hybrid | **input-authoritative** — the only option that satisfies ordered G1 by construction | **decided by design** |
| D2 | fate of model-derived fields | topology-affecting · metadata/provenance only | **metadata/provenance only** | **decided by design** |
| D3 | textual canonicaliser scope | punctuation/whitespace only · + lexicon/paraphrase mapping | start narrow (C1–C7); paraphrase mapping is a bounded follow-up | open (O2) |
| D4 | topology comparison basis | route set · **ordered route list** | **ordered** (operator-frozen) | **frozen** |
| D5 | cache value | raw model output · **canonical plan** | **canonical plan**, re-validated on read | **decided by design** |
| D6 | cache key composition | question only · + scope/config/versions | **full composition** (§4) | **decided by design** |
| D7 | fallback granularity | whole-plan · **per slot** | **per slot** | **decided by design** |
| D8 | retry policy | none · bounded single retry | single bounded retry, topology-inert | open (O3) |
| D9 | planner event | extend `retrieval_health` · **separate `retrieval_plan`** | **separate event**, own authorisation | **decided by design** |
| D10 | non-composite handling | keep permissive classifier · **authoritative input classifier + pass-through** | **authoritative**, tightened deterministically | **decided by design** |

## 9. Open decisions (need the operator)

| id | question | why it matters |
| --- | --- | --- |
| **O1** | Under input-authoritative slots, the model can no longer *discover* attributes the profiler misses. Accept the reduced role, or authorise an **input-declared open slot** whose identity is still a canonical template? | This is the product-value trade-off of the whole architecture |
| **O2** | How far must the canonicaliser go beyond punctuation/whitespace? P1-0 showed textual canonicalisation alone leaves **disjoint** topologies (min Jaccard 0.0) because paraphrase ≠ punctuation | Determines whether G1 needs paraphrase mapping or only the slot mechanism |
| **O3** | Apply the planner **retry/bounded sampling** budget? | Sampling consensus would re-introduce model authority; currently it is not needed |
| **O4** | Authorise the `retrieval_plan` event (D9), and in which phase? | A contract change; the nine-field `retrieval_health` event stays frozen either way |
| **O5** | When is G4 unblocked — provider recovery, or an explicitly-recorded degraded baseline? | P1-2 acceptance cannot complete without it |

## 10. Explicitly not done

No planner normalisation code, no cache change, no prompt change, no sampling change, no retrieval-parameter
change, no change to the `retrieval_health` DTO, no change to the frozen P0-7 nine-field event, no
deployment, no retag. **P1-1 is design only; implementation requires a new authorisation.**
