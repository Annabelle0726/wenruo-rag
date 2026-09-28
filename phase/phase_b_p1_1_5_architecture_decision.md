# P1-1.5 — Architecture Decision / Counterfactual Evaluation (evaluation only)

**No production or planner code was modified.** No cache, prompt, sampling, retrieval-parameter, DTO or
event change. Production remains `latest` = `ea93cd3bb795`. G4 stays
`BLOCKED_BY_EXTERNAL_PROVIDER_AVAILABILITY`; `retrieval_plan` (O4) stays gated and is not designed here.

---

## 1. The two determinism dimensions, defined strictly

| dimension | definition | observable through |
| --- | --- | --- |
| **Structural Determinism** | the *number*, *identity* and *order* of Slots is fixed by the input | slot skeleton, `topology_size`, slot order |
| **Semantic Executable Determinism** | the *Canonical Query text actually executed* in each slot is fixed | `plan_hash`, per-slot canonical route content |

These are **independent**. A plan can be structurally identical and semantically divergent — the same four
slots in the same order executing four different texts on four runs. **G1 is frozen on ordered executable
routes, i.e. on Semantic Executable Determinism**, so structural stability alone is *not* a pass condition
and must never be reported as one.

**Named anti-pattern (prohibited):** *structural-stability illusion* — reporting "the topology is stable"
while the executed text inside the slots drifts. Any drift in executed text is
**Executable-Plan Variance** and must be classified as such, never hidden behind slot stability.

---

## 2. The counterfactual question, answered

> **Can OPEN_DISCOVERY preserve useful model discovery while still guaranteeing byte-identical Canonical
> Executable Plans and `plan_hash` across Cold / Warm / Retry / Fallback?**

**Answer: No — not while the discovery has any retrieval effect.** Proof by exhaustion over the only four
ways a discovered dimension can reach execution:

| variant | how the discovery reaches retrieval | determinism | useful discovery? |
| --- | --- | --- | --- |
| **C-1** | executed text is the model's proposal, verbatim/canonicalised | **broken**: model text is the hash input, so two runs differ whenever wording differs | yes, but the plan is non-reproducible |
| **C-2** | model selects from a **closed vocabulary**, executed text = the selected member | **broken**: two runs can select different members, so executed text and hash differ | partly |
| **C-3** | executed text is a **fixed input-derived template**; the model's proposal is provenance only | **holds** | **no retrieval effect** — the discovery is telemetry, not discovery |
| **C-4** | discovery leaves the plan entirely and drives a non-topological **execution parameter** | plan hash holds | **yes — but the variance moves outside the gate**: results can still differ run-to-run, and G1/G2 do not cover it |

Two structural facts sharpen this:

1. **Cardinality is frozen** (C red line: *the model may not change the executable plan's cardinality*).
   Since the OPEN_DISCOVERY slot is at most **one** slot, C's discovery ceiling is **one extra dimension per
   retrieval** — it can never scale to a multi-dimension unknown intent.
2. `plan_hash` is defined over the **ordered executable plan** (§P1-1 §3.3). Therefore *anything that changes
   executed text changes the hash*. C-1 and C-2 are self-defeating; C-3 is B-plus-telemetry; C-4 is a
   different, un-gated variance channel.

**Conclusion:** there is no architecture in which runtime model discovery is both *executable* and
*deterministic*. The two properties are mutually exclusive at the executable boundary, and Route C is only
deterministic in the variant where discovery has no effect.

---

## 3. Route comparison

### 3.1 Red-line compliance of Route C

| red line | C-1 | C-2 | C-3 | C-4 |
| --- | --- | --- | --- | --- |
| model may not create/delete/reorder/rename Slots | ok | ok | ok | ok |
| existence, identity, order of OPEN_DISCOVERY derived from input alone | ok | ok | ok | ok |
| empty/invalid model output ⇒ deterministic fallback | ok | ok | ok | ok |
| model output may not change executable-plan cardinality | ok | ok | ok | ok |
| **G1 (ordered executable identity) by construction** | **FAIL** | **FAIL** | PASS | PASS for the plan, **ungated elsewhere** |
| functional discovery | yes | partial | **none** | yes |

C satisfies every structural red line the operator set, and **still fails G1** in both variants where the
discovery does anything. The red lines protect the slot skeleton; G1 constrains the *executed text*. That
gap is the whole finding.

### 3.2 Per-route evaluation

| criterion | **A — Model-authoritative (current baseline)** | **B — Deterministic fixed-slot (P1-1)** | **C — Profiler + OPEN_DISCOVERY** |
| --- | --- | --- | --- |
| **Determinism guarantee** | none (measured) | **by construction** | **none in the useful variants**; only when discovery is inert |
| **Discovery capability** | high, but only ~1 dimension per run, unsupervised | none at runtime; **build-time** via profiler vocabulary | ≤ 1 dimension (cardinality freeze), and non-deterministic |
| **Failure mode** | non-reproducible topology; control jitter; cache as crutch; monitoring noise | systematic omission of un-vocabularied dimensions — **stable but potentially blind** | either **inert discovery** (theatre) or **Executable-Plan Variance masked by structural stability** |
| **`plan_hash` impact** | varies constantly — P1-0: 23 raw / 19 canonical distinct over 6 queries | **stable** | unstable in C-1/C-2; stable only in C-3 (where it carries no discovery) |
| **Recall risk** | erratic: improved on some runs, degraded on others, unpredictable | bounded and *known*: skeleton + deterministic routes always execute; un-vocabularied dimensions are missed | unbounded and untestable: recall depends on which sampled discovery arrived |
| **G1/G2 by construction** | no | **yes** | no |

### 3.3 Evidence from P1-0 (measured, not hypothetical)

| query | measured behaviour under A | consequence |
| --- | --- | --- |
| `N_STD`, `N_ARMOUR` (controls) | `looks_composite: true` **and** route count `[0, 1]` | A lets the model govern topology on inputs that need no decomposition |
| `C_COMPARE` | counts `[4, 5]`; 6 raw / 5 canonical hashes | cardinality itself is unstable — the red line C tries to hold is already violated today |
| `C_MULTI` | min Jaccard 0.2, max symmetric difference 8 | topologies can differ by 8 routes between runs of the same question |
| `C_PARTS` | 4 raw / 2 canonical | paraphrase-only differences (no topology change) — the noise class that raw hashing would over-report |
| `C_STD` | 3 raw / 2 canonical, counts `[2]` | even a stable-cardinality case has unstable executed text |

**What this says about discovery value.** In the measured runs, the model's contributions were
overwhelmingly *paraphrases of attributes the question already names* (`导体` / `内衬层` / `铠装层` — all
present in the input), plus occasional spurious routes on control questions (e.g. re-proposing the question
itself). There is **no measured instance** of the model discovering a retrieval dimension absent from the
input. The deterministic machinery already carries the structural work: `clause_route` fired **60/60** and
`comparative_routes` **40** times.

So Route B's sacrificed capability is real but **currently largely theoretical**, whereas Route A's
non-determinism is **measured and continuous**.

### 3.4 Counterexample derivations

**X1 — composite question with one un-vocabularied dimension**
`"220kV 三芯海缆的铠装层要求和弯曲半径分别是多少？"` (profile knows 铠装层; 弯曲半径 outside vocabulary)

| route | behaviour |
| --- | --- |
| A | sometimes 2 routes, sometimes 3, sometimes reordered; may or may not cover 弯曲半径 — **unpredictable per run** |
| B | `[canonical(question), clause/side routes…, slot(铠装层)]` — always the same; **弯曲半径 must be found by the question route alone** → real, bounded recall risk |
| C | OPEN_DISCOVERY may carry 弯曲半径 **or not**, and its text may differ between runs → G1 fails; the "structure" looks stable while the executed text drifts — the prohibited illusion |

**X2 — non-composite control** `"Q/GDW 73286.2-2026 是什么标准？"`
A: `[0, 1]` route jitter (measured). B: exactly 1, always. C: 1 + possibly an inert discovery slot → no
benefit, one extra failure surface.

**X3 — same intent, different wording across runs** (`内衬层厚度是多少？` vs `内衬层厚度要求是多少`)
A: different executed text → different hash (measured). B: one canonical text. C: if OPEN_DISCOVERY executed
the drift, G1 fails; if it did not, nothing was discovered.

---

## 4. Decisions

| id | decision | resolution |
| --- | --- | --- |
| **O1 — model's discovery role** | **RESOLVED — recommend Route B.** Runtime model discovery is excluded from the executable plan. Discovery capability is **moved from runtime to build time**: the deterministic profiler's vocabulary is extended by engineering change under a bumped `plan_version`, so new dimensions are added *reviewably, testably and deterministically*. This is the only construction that preserves the ability to improve discovery without reintroducing variance. |
| **O2 — canonicalisation depth** | **RESOLVED — largely dissolves under B.** Paraphrase mapping was needed only because model text could reach execution. Under B the canonicaliser must handle the **input question** and **vocabulary members**, not model paraphrase. So no paraphrase lexicon is required for P1; P1-0's disjoint-topology result stops mattering for the executable plan because model text no longer enters it. |
| **O3 — retry / sampling budget** | **DEFERRED.** Under B a retry is topology-inert, so the budget is not needed for correctness. |
| **O4 — `retrieval_plan` event** | **REMAINS GATED.** Not designed or implemented here. If C-3 style provenance is ever wanted, it belongs to that event, and it must be labelled as telemetry, not discovery. |
| **G4** | **BLOCKED_BY_EXTERNAL_PROVIDER_AVAILABILITY** — unchanged, and still the gate that P1-2 acceptance depends on. |

---

## 5. Recommendation

> **Adopt Route B — Deterministic Fixed-Slot Architecture — for P1-2**, with the OPEN_DISCOVERY slot
> **rejected**, and with the profiler vocabulary designated as the single, versioned, build-time path by
> which new retrieval dimensions are introduced.

### 5.1 The product capability this deliberately sacrifices

**Informed trade-off, stated plainly:**

* **Sacrificed:** the ability of the LLM to add, at request time, a retrieval dimension that the
  deterministic profiler does not already enumerate. Concretely, on a question like X1 the extra dimension
  will **not** be independently routed; it is covered only to the extent the base question route retrieves
  it. Route B trades **adaptive recall on unseen intents** for **reproducibility**.
* **Bounded by evidence:** P1-0 found no measured instance of the model discovering an input-absent
  dimension, so the sacrificed capability is presently theoretical; the non-determinism it was bought with is
  measured and continuous (6/6 queries vary, 2 controls jitter 0/1, one query pair differs by 8 routes).
* **Compensated, without violating determinism:** new dimensions are added by extending the profiler's
  vocabulary under a bumped `plan_version`. Discovery becomes an **engineering, reviewable, testable** act
  rather than a per-request sample. This is slower than runtime discovery and is the real cost of the
  choice.
* **Explicitly not accepted:** keeping model text in the executable plan and calling the result stable
  because the *slots* are stable (the structural-stability illusion, §1), or moving the variance into an
  un-gated execution parameter (C-4), which would relocate the problem rather than solve it.

### 5.2 Consequence for sequencing (carried forward)

Route B **changes which routes execute** relative to today, so **P1-2 acceptance still depends on G4**,
which remains blocked by the provider outage. Recommendation stands: P1-2 implementation should not be
authorised, or if authorised, cannot be *accepted*, until the dense leg is healthy or O5 is ruled on.

### 5.3 What was NOT done

No planner/cache/prompt/sampling/retrieval-parameter/DTO/event change. No `retrieval_plan` event designed.
No deployment, no retag. **Evaluation only — stopping here.**
