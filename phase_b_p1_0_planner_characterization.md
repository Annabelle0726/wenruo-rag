# P1-0 — Planner Characterization + Gate Construction (no planner implementation changed)

Status: **characterization only.** No planner, cache, prompt, retrieval-parameter or contract change was
made. Production untouched: no deploy, no retag (`latest` remains `ea93cd3bb795`).

---

## 1. Gate status board

| gate | status |
| --- | --- |
| **P1-0 planner characterization** | **READY** — completed and reproducing Phase A |
| **G1 topology invariance** | **READY** (harness constructed; currently *detects* variance, as expected before normalisation) |
| **G2 cache-state equivalence** | **READY** (same harness; cold series measured) |
| **G3 fallback determinism** | **READY** (fallback provenance captured per run) |
| **G4 recall neutrality** | **`BLOCKED_BY_EXTERNAL_PROVIDER_AVAILABILITY`** |
| **G5 P0 invariants** | **READY** (P0 gates unchanged and green) |
| **G6 health honesty** | **READY** (contract untouched; `validate()` semantics unmodified) |

**Rule now in force** (recorded verbatim):

> **Planner determinism acceptance may proceed while Dense is degraded; retrieval-quality/recall acceptance
> may not establish or compare a healthy baseline while a required retrieval leg is degraded.**

G4 being blocked does **not** mark P1 blocked: the planner line proceeds; the recall line waits.

## 2. What was measured, and how (isolation)

Re-ran the Phase A cold-cache probe against the **current baseline `ea93cd3bb795`**, then analysed its
capture with the new P1-0 characterizer (`deploy/p1_gates/p1_0_planner_characterization.py`).

* Isolation: `get_llm_cache` forced to **miss** and `set_llm_cache` a **no-op**, in this process only —
  production Redis was never read, written, deleted or flushed; no deployed file modified.
* Proof the cache was genuinely bypassed: **60 chat-model calls** executed, `decompose_question` fired **60**
  times (10 runs × 6 queries).
* Captured per run: sub-queries (ordering included), side routes, decomposition/follow-up call counts,
  fallback provenance (empty plan vs produced plan), and the response keys.

## 3. Results — Phase A verdict reproduced exactly

| query | kind | distinct raw hashes | distinct **canonical** hashes | route counts | min pairwise Jaccard | max symmetric diff |
| --- | --- | --- | --- | --- | --- | --- |
| `C_STD` | COMPOSITE | 3 | 2 | `[2]` | 0.3333 | 2 |
| `C_COMPARE` | COMPOSITE | 6 | 5 | **`[4, 5]`** | 0.2857 | 5 |
| `C_PARTS` | COMPOSITE | 4 | 2 | `[3]` | **0.0** | 6 |
| `C_MULTI` | COMPOSITE | 5 | 5 | `[6]` | 0.2 | 8 |
| `N_STD` | NON_COMPOSITE_CONTROL | 2 | 2 | **`[0, 1]`** | **0.0** | 1 |
| `N_ARMOUR` | NON_COMPOSITE_CONTROL | 3 | 3 | **`[0, 1]`** | **0.0** | 2 |

Aggregate: **6/6 queries show topology variance**; **3/6 show route-*count* variance**; worst-case min
pairwise Jaccard **0.0** (some run pairs are *disjoint*) and worst symmetric difference **8 routes**;
total distinct raw hashes **23** vs distinct canonical hashes **19**.

**Verdict: `MATERIAL_DECOMPOSITION_VARIANCE_OBSERVED_AT_ROUTE_LEVEL_REPLAY_BLOCKED`** — reproduced on the
current baseline. **G1/G2 therefore demonstrably detect the Phase A variance**, which is the precondition
the operator set before touching the normalisation implementation.

### 3.1 The most damning row

The two **non-composite control** queries — questions that should need no decomposition at all — vary
between **0 and 1 sub-queries**. The planner is not merely rephrasing; it intermittently *adds or omits a
route* on questions that carry no composite intent. Topology instability is therefore not confined to
complex questions.

## 4. `plan_hash` contract — specified, with measured justification

Agreed relation, now written down as the contract P1-1 must implement:

```
raw model output → validate → canonicalise → deterministic fallback if needed
                 → canonical RetrievalPlan → plan_hash → cache → execute
```

**`plan_hash` is computed over the canonical validated plan, never over the raw model response.**
Canonical plan = deduped, order-free (or explicitly ordered, see §5), normalised route set; the hash is taken
over the sorted canonical form so it is independent of the model's serialization order.

Measured justification for the operator's concern: across the same 6 queries, hashing the **raw** output
yields **23** distinct values while hashing the **canonical** plan yields **19**. Raw-output hashing
over-reports by ~21% — it would monitor serialization noise (trailing `？`, `"是多少"` vs `"是什么"`,
key order) as if it were topology change.

Consequently the Redis role changes as the operator described: instead of "freezing whichever random result
happened to arrive first", it caches **an already-deterministic planner artifact**. Cache hit/miss
correctness comes from validation + canonicalisation + fallback, not from Redis.

**Honest caveat discovered by the measurement — textual canonicalisation is not sufficient on its own.**
The reference canonicaliser (NFKC, whitespace collapse, trailing-punctuation strip, dedupe, sort) closes
23→19, but the residual still contains **disjoint** topologies (`min Jaccard = 0.0`), because paraphrase is
not punctuation: `导体有什么技术要求` and `导体的技术要求是什么` are different strings with the same intent.
So P1-1 must decide between:

* **(a) intent-level canonicalisation** — normalise paraphrase (template/keyword canonical forms), or
* **(b) canonicalise textually *and* pin the plan with a deterministic/validated fallback** so the executed
  topology does not depend on the LLM's phrasing at all, or
* **(c) sampling consensus (D5)** — accept planner variance but resolve it deterministically.

My recommendation: **(b)**, with (a) as a bounded refinement — it is the only option that makes G1/G2 true
by construction rather than by probability, and it keeps the contract change small.

## 5. Gate construction (built now, not yet expected to pass)

`deploy/p1_gates/p1_0_planner_characterization.py` is the P1-0 harness. It computes, per frozen query:
distinct raw vs canonical hashes, distinct route counts, min pairwise Jaccard, max symmetric difference,
cosmetic-only vs real variance, and fallback provenance — i.e. the exact inputs G1/G2/G3 need.

| gate | assertion once normalisation exists | construction status |
| --- | --- | --- |
| G1 | N ≥ 10 repeats ⇒ one canonical topology; `min Jaccard = 1.0`, symmetric diff `= 0` | **READY** (currently reports variance) |
| G2 | cache forced-miss vs forced-hit ⇒ identical route set **and** identical `plan_hash` | **READY** (cold leg measured; warm leg is the same harness with patching disabled) |
| G3 | planner fails (invalid JSON / empty / timeout) ⇒ deterministic stable fallback | **READY** (provenance captured; fallback determinism assertion to be added with the implementation) |
| G5 | P0-A/B/C, P0-6 C1–C6, P0-7 event shape all still PASS | **READY** — unchanged and green |
| G6 | `validate()` and evidence behaviour unchanged; nothing inflates coverage | **READY** — contract untouched |

**Open definitional decision for P1-1 (deliberately not decided here):** whether "retrieval topology" means
the **route set** or the **ordered route list**. The harness currently scores the set (order-free); if
ordered routes are chosen, G1 becomes strictly stronger and the `plan_hash` must include ordering.

## 6. Deliverables and next step

* New: `deploy/p1_gates/p1_0_planner_characterization.py` (characterization + gate construction), result
  artifact `p10_char_summary.json`.
* Reused unchanged: `tools/scripts/decomposition_cold_cache_probe.py` (the Phase A isolation method).
* **Not done, by instruction:** no planner normalisation implementation, no cache-key change, no prompt
  change, no retrieval-parameter change, no new contract field.

**Next step (needs your go-ahead): P1-1 design**, resolving §4's (a)/(b)/(c) choice and §5's topology
definition, and stating explicitly whether the operator event should carry `plan_hash` (a **contract
change**, so it needs its own authorisation — the same bar as B-2).

**G4 remains `BLOCKED_BY_EXTERNAL_PROVIDER_AVAILABILITY`** and must not be used to gate P1's planner line,
nor may a recall baseline be established or compared while the dense leg is degraded.
