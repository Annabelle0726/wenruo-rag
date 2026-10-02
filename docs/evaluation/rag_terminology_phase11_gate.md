# Retrieval Phase 1.1 — Generalized Axis Reader — Gate

**Gate outcome: PARTIAL PASS (7 of 9 criteria). STOP on promotion — no candidate image built, nothing
deployed.** The axis reader was fixed (trigger coverage 1/6 → 6/6, zero malformed routes); the one
remaining failure is V5's structure clause, and the diagnosis shows it is a **context-cut** outcome
that this Phase's constraints forbid touching. Per the instruction not to pile on special cases, the
work stops here and reports.

No retrieval score parameter, rerank model/threshold, embedding, chunking or metadata schema was
changed.

---

## AXIS_READER_DESIGN

Two axes, read from the sentence's structure, with **no complete question wording matched anywhere**
and **no domain vocabulary in the generic reader**.

### Entity axis (`_bracketed_entities` → `_conjunction_entities`)

Two readers, tried in order:

1. **Bracketed** — a parenthesised group split at the enumerating conjunctions. Preferred when
   present, and it is also what distinguishes a scope noun from the enumeration: in
   `电缆附件（终端与接头）` the bracket carries the enumeration and `电缆附件` is the scope, so the
   scope never becomes a member.
2. **Conjunctions** — brackets **not** required. The question is split at the same
   `ENUMERATING_CONJUNCTION_RE` the deployed dimension reader uses, extended with `/` and `／`, plus
   the structural boundaries that separate an enumeration from the phrase it sits in
   (`的 其 在 方面` and punctuation). Every fragment is then cleaned by
   `_trim_member`:

   * the question's own predicate is cut at its first marker
     (`有 是 多少 什么 怎样 怎么 如何 哪些 分别 以及 能 可以 要求 规定 构成 类型 各`) — this is what
     removes the residue that broke Phase 1 (`结构分别有什么要求` → `结构`);
   * leading framing is cut at its last marker (`标准对终端` → `终端`);
   * a **locative** fragment is dropped, not stripped (`电缆附件中` is where the question looks, not
     an object it asks about — stripping it created a phantom entity that displaced a real one from
     the bounded cross product);
   * what remains must be a 2–8 character ideographic noun phrase that is **not** a fact type and not
     generic scaffolding (`技术 要求 规定 方面 内容 …`).

   Supports all requested forms: `终端与接头`, `终端和接头`, `终端、接头`, `终端/接头`, `（终端与接头）`.

### Fact axis (`rag.retrieval.domain_facts`, the domain layer)

The reader holds **no vocabulary**. It asks the domain layer which declared fact types the question
names. The domain layer is `domain_facts.FACT_TYPES`, keyed by the same category string the deployed
`retrieval_projection.classify_category` returns:

| domain | fact type | surface cues | route term |
|---|---|---|---|
| `power_cable` | `design_life` | 设计使用寿命 · 设计使用年限 · 设计寿命 · 使用寿命 · 使用年限 · 使用年数 · 使用多少年 · 能用多少年 · 多少年 · 寿命年限 · 寿命 · 年限 | **设计使用年限** |
| `power_cable` | `structure` | 结构图纸 · 结构要求 · 结构尺寸 · 结构 | **结构** |

Two design decisions worth naming:

* **Routes carry the CORPUS's term, not the user's.** `route_term` is what a route is built from. A
  route spelled with the user's wording (`终端 设计寿命`) matches nothing lexically in this corpus,
  which is why Phase 1's routes were only usable through the Phase 0 synonym table. Building the
  route from `设计使用年限` / `结构` makes it match directly.
* **The domain is resolved from the fact vocabulary, not from a domain cue word.** Requiring a cue
  was measured to reject legitimate questions: `终端与接头能使用多少年？结构上有什么规定？` names two
  fact types of the cable profile and no cable word at all (rejected V3, V5, V6 with
  `unknown_domain`). `resolve_domain` treats a question naming **two or more** fact types of one
  domain as asking in that domain, and prefers the deployed classifier's answer when it agrees.

### Gate and bounds

Expansion requires **both** axes: ≥2 entities **and** ≥2 fact types, plus a resolved domain. Caps:
`MAX_AXIS_MEMBERS = 3`, `MAX_ENTITY_CHARS = 8`, `MAX_SUPPLEMENTAL_ROUTES = 4`, caller `budget`.
Additive, de-duplicated, order preserving. A declined question gets a byte-identical route set.

---

## FILES_CHANGED

| file | change |
|---|---|
| `rag/retrieval/domain_facts.py` | **new** — the power_cable fact vocabulary (domain layer) |
| `rag/retrieval/route_expansion.py` | **rewritten** — generalized two-axis reader replacing the bracket-dependent one |
| `rag/res/synonym.json` | one entry added: `设计寿命 → 设计使用年限` |
| `tools/scripts/phase11_acceptance.py` | **new** — acceptance harness (BEFORE deployed / AFTER candidate) |
| `tools/scripts/phase11_v5_diagnosis.py` | **new** — the V5 diagnosis probe |
| `docs/evaluation/rag_terminology_phase11_gate.md` | **new** — this report |

Not modified: embedding, `rerank.py`, `planner.py`, `decomposition.py`, `multi_route.py`,
`query_router.py`, `retrieval_projection.py`, any `api/` file, any frontend, any Dockerfile.
**Not committed** — see READY_FOR_CANDIDATE.

---

## ENTITY_AXIS_RESULTS

| question | source | entities read | route text |
|---|---|---|---|
| V1 | bracketed | 终端 · 接头 | 终端 设计使用年限 · 终端 结构 · 接头 设计使用年限 · 接头 结构 |
| V2 | conjunctions | 电缆终端 · 接头 | 电缆终端 设计使用年限 · 电缆终端 结构 · 接头 设计使用年限 · 接头 结构 |
| V3 | conjunctions | 终端 · 接头 | terminal pair, 4 routes |
| V4 | conjunctions | 终端 · 接头 | `电缆附件中` was **dropped** as a locative; the phantom entity is gone |
| V5 | conjunctions | 终端 · 接头 | `标准对终端` → `终端` via the framing cut |
| V6 | conjunctions | 终端 · 接头 | 4 routes |
| N1 | conjunctions | *(1)* `海缆` | 0 routes — `single_entity` |
| N2 | conjunctions | *(0)* `终端结构` read as a fact type | 0 routes — `no_fact_enumeration` |
| N3 | conjunctions | 终端 · 接头 | 0 routes — **two entities, zero fact types** |
| QA-001 | conjunctions | *(1)* `单芯` | 0 routes |
| QA-002 / QA-003 | — | none | 0 routes |
| QA-005 | bracketed | 出厂 · 安装后 | 0 routes — **two entities, zero fact types** |

Brackets are used when present but are **not required**: 5 of the 6 paraphrases go through the
conjunction reader. All entity members are clean 2–4 character noun phrases (`终端`, `接头`,
`电缆终端`); no member exceeded the length cap and none was a fragment.

---

## FACT_AXIS_RESULTS

The five requested natural expressions, and what the reader now yields:

| input wording | fact members emitted | residue? |
|---|---|---|
| 设计使用寿命与结构有何要求 | `设计使用年限`, `结构` | none |
| 设计寿命、结构分别有什么要求 | `设计使用年限`, `结构` | none — `结构分别有` is gone |
| 寿命和结构有什么规定 | `设计使用年限`, `结构` | none — `结构有` is gone |
| 结构以及设计使用年限是怎样规定的 | `结构`, `设计使用年限` | none — question order preserved |
| 寿命和结构方面有哪些技术要求 | `设计使用年限`, `结构` | none — `寿命方面有` / `技术` are gone |

Every previously forbidden output is absent: `结构有`, `结构分别有`, `结构有什么`, `寿命方面有`.
Fact members are **canonical route terms**, not verbatim fragments, so a member is clean by
construction: the only thing the fragmenter decides is *which* fact type was named, and the domain
layer decides what to call it.

---

## VOCABULARY_POLICY

**Added: `设计寿命 → 设计使用年限`. Evidence supports it.**

| term | corpus chunks (of 317) |
|---|---|
| `设计使用寿命` | **0** |
| `设计寿命` | **0** |
| `使用寿命` | **0** |
| `设计使用年限` | 20 |
| `使用年限` | 20 |
| `寿命` | 26 — **mixed contexts**, including clauses unrelated to attachment life |
| `结构` | 116 |
| `结构图纸` | 4 |

* The user phrase has **zero** corpus coverage, exactly like `设计使用寿命` which is already keyed;
  the target has 20. Same class of gap, same remedy.
* **False-recall risk is minimal** because `设计寿命` is a TIGHT PHRASE: it can only fire on a query
  token that is literally about design life. This is the structural difference from bare `寿命`.
* **Bare `寿命` is NOT added to the synonym dictionary**, and was verified still unmapped:
  `lookup(寿命) → []`, `lookup(年限) → []`. A question that says `寿命` is handled by the domain
  layer's fact canonicalisation instead (`寿命` is a `design_life` cue → the route carries
  `设计使用年限`), which is scoped to route construction and cannot touch another question's tokens.
* Phase 0 semantics are preserved: `设计使用寿命 → 设计使用年限` unchanged; no `寿命 → 年限`.

The resource remains pure ASCII (`\uXXXX`) and still loads through the real `Dealer` (7 entries).

---

## PARAPHRASE_RESULTS

Acceptance set, 3 runs per side. BEFORE = the deployed entry point as production runs it today.
AFTER = the deployed `pipeline.py` + the 3 Phase-1 hunks, loaded as a standalone module, with the
1.1 reader injected — so both sides execute the real production route assembly.

| question | trigger | supp. | design-life b→a | structure b→a | both (3 runs) |
|---|---|---|---|---|---|
| V1 | ✅ | 4 | 2,3,3 → **3,3,3** | 3,3,3 → 3,3,3 | **3/3** |
| V2 | ✅ | 4 | 3,3,3 → 3,3,4 | 4,4,4 → 4,4,4 | **3/3** |
| V3 | ✅ | 4 | 5,5,5 → 4,4,4 | 1,1,1 → 2,2,2 | **3/3** |
| V4 | ✅ | 4 | 9,9,9 → 7,7,7 | 2,2,2 → 2,2,2 | **3/3** |
| **V5** | ✅ | 4 | 6,6,6 → 6,6,6 | **0,0,0 → 0,0,0** | **0/3** |
| V6 | ✅ | 4 | 1,1,1 → **4,4,4** | 1,1,1 → **2,2,2** | **3/3** |

**Trigger coverage: 6/6** (was 1/6). Four paraphrases improve materially (V6's design-life passages
1 → 4, V1's stabilise from 2,3,3 to 3,3,3), and both halves are retained everywhere except V5.

### V5 — diagnosed, not fixed

V5 is **not** a route-coverage failure, and route expansion cannot fix it. Measured:

| route (window 12) | chunks returned | containing 结构 (any) | containing 结构图纸 (the clause) |
|---|---|---|---|
| the V5 question itself | 12 | 7 | **4** |
| `终端 结构` | 12 | 12 | 2 |
| `接头 结构` | 12 | 12 | **4** |
| `终端 设计使用年限` | 12 | 4 | 1 |
| `接头 设计使用年限` | 12 | 0 | **0** |

The clause **is** retrieved, by the question's own route and by both structure routes. The final
window, however:

| | n | 结构 (any) | 结构图纸 (clause) | design-life |
|---|---|---|---|---|
| BEFORE | 12 | 6 | **0** | 6 |
| AFTER | 12 | 6 | **0** | 6 |

So V5 already carries both halves in the broad sense — **6 structure passages and 6 design-life
passages before and after** — and the expansion changed only route *provenance* (routes per chunk
1–3 → 1–4), not the passage set. What is missing is the specific 结构图纸 clause, which is in the
merged pool (the structure routes returned 4 of them) and **loses the 12-slot cut** to the design-life
candidates that the two life routes flood the pool with.

That is a **context-cut / ranking** outcome. Reaching 3/3 would require changing the cut, the rerank
influence, or the window budget — every one of which this Phase forbids. The instruction is explicit
that a failing criterion means stop rather than add special cases, so the reader was not tuned to
make V5 pass.

---

## CONTROL_RESULTS

| question | role | supp. routes | design-life b→a | structure b→a | window routes b→a |
|---|---|---|---|---|---|
| N1 `海缆的设计使用寿命是多少？` | negative | 0 | 0 → 0 | 4 → 4 | 1 → 1 |
| N2 `终端结构有什么要求？` | negative | 0 | 0 → 0 | 0 → 0 | 1 → 1 |
| N3 `终端和接头有哪些类型？` | negative | 0 | 0 → 0 | 4 → 4 | 3 → 3 |
| QA-001 | frozen | 0 | 0 → 0 | 0 → 0 | 8 → 8 |
| QA-002 | frozen | 0 | 1 → 1 | 0 → 0 | 3 → 3 |
| QA-003 | frozen | 0 | 0 → 0 | 0 → 0 | 2 → 2 |
| QA-005 | frozen | 0 | 0 → 0 | 0 → 0 | 5 → 5 |

All seven add **0** routes, so their route lists are byte-identical and their retrieval cannot
change; the measured windows confirm it. N1 and N2 decline on `single_entity`-style gates, **N3 and
QA-005 decline because they carry two entities but zero declared fact types** — which is the
fact-axis gate doing exactly its job. The four frozen benchmark questions are unchanged.

---

## MALFORMED_ROUTE_CHECK

Checked on every emitted route, every question, every run:
`_RESIDUE_RE = 有|是|什么|怎样|怎么|如何|哪些|多少|分别|以及|能|可以|要求|规定|方面$|技术`.

**Malformed routes: 0.** Every route is `<entity> <canonical fact term>`, e.g.
`终端 设计使用年限`, `电缆终端 结构`. The Phase 1 residues `结构分别有` and `结构有` are gone, and the
previously observed failure mode of a phrase fragment becoming a route cannot recur, because route
text is composed from a cleaned entity and a term chosen by the domain layer rather than from a raw
fragment.

---

## ROUTE_COUNT_IMPACT

* **Supplemental routes per triggering question: exactly 4** (cap is 4; a 3×2 axis combination is
  capped, not expanded).
* **Merged route set: up to 8** = 4 LLM routes + 4 supplemental (bound `ROUTE_BUDGET = 8`).
* **Route count in the final window: 5/4/4/5/6/5 → 8** for V1–V6; unchanged for every control.
* **No route explosion.** The window count is pinned at 8 for every paraphrase because four
  supplemental routes each reserve a slot; it cannot exceed `ROUTE_BUDGET`.
* **Duplicate chunks: 0** in all 78 runs.

---

## LATENCY

Median of 3, same parameters both sides.

| question | before | after | delta |
|---|---|---|---|
| V1 | 1.20 s | 1.62 s | +0.42 s |
| V2 | 1.02 s | 1.71 s | +0.69 s |
| V3 | 1.14 s | 1.75 s | +0.61 s |
| V4 | 1.22 s | 2.64 s | +1.42 s |
| V5 | 1.47 s | 2.31 s | +0.84 s |
| V6 | 1.44 s | 1.79 s | +0.35 s |
| N1 / N2 / N3 | 0.71 / 0.68 / 1.12 s | 0.72 / 0.70 / 1.05 s | ≈ 0 |
| QA-001 / 002 / 003 / 005 | 2.04 / 0.84 / 0.79 / 1.44 s | 2.24 / 0.82 / 0.82 / 1.41 s | ≈ 0 |

Mean paraphrase delta **+0.72 s**, worst +1.42 s. Cost is confined to questions the rule expands and
scales with route count (routes are retrieved concurrently; rerank then runs over a larger merged
pool). Every declining question is flat. Acceptable for an answer-quality gain, though V4's +1.42 s
is the number to watch in a latency budget.

---

## OVERFIT_RISK

**Materially reduced, and now measurable in the right terms.**

Phase 1's risk was that the reader matched one sentence's surface form: it required a bracketed
entity enumeration and fired on 1 of 6 paraphrases. Phase 1.1 fires on 6 of 6 with no question
wording matched anywhere, and produces clean canonical routes on all of them.

Residual risks, stated plainly:

1. **The entity cleaner is still heuristic.** It relies on a predicate-marker list, a framing cut, a
   locative rule and a length window. Those are structural, not sentence-specific, and they were
   validated on 13 questions — but a question with an unusual boundary (`终端（含接头）的设计…`, or a
   long compound entity name) could still be mis-split. The three negatives declining for the right
   reasons is the main evidence that the heuristics are not merely permissive.
2. **The domain fact table is now the gate**, which is the intended design (vocabulary lives in the
   domain layer) but moves the precision question there: a question naming two `power_cable` fact
   types in another industry's context would be routed with cable terms. In this corpus, which holds
   only cable documents, that is harmless.
3. **V5 shows the reader's success does not guarantee the answer.** Route coverage and context
   composition are different layers; a reader can be correct and the window still not carry the
   clause. That is the honest limit of what this Phase can deliver.
4. **`结构` is broad (116 chunks) where the clause is narrow (4).** The route term is the corpus's
   general word rather than the clause's specific one (`结构图纸`). Widening this was considered and
   **deliberately not done**: it would be tuning the vocabulary to make one criterion pass, which is
   the special-casing the instruction forbids.

---

## READY_FOR_CANDIDATE

**NO.**

Criteria as stated:

| # | criterion | result |
|---|---|---|
| 1 | V1–V6 trigger coverage ≥ 5/6 | **PASS — 6/6** |
| 2 | V1–V6 3/3 both life + structure evidence | **PARTIAL — 5/6; V5 fails** |
| 3 | V5 structure 0/3 → 3/3 | **FAIL — 0/3, root cause is the context cut** |
| 4 | negatives must not expand meaninglessly | **PASS** — 0 routes, windows identical |
| 5 | QA-001/002/003/005 no regression | **PASS** — windows identical |
| 6 | no malformed routes | **PASS** — 0 |
| 7 | max supplemental routes ≤ 4 | **PASS** — exactly 4 |
| 8 | no route explosion | **PASS** — window routes ≤ 8 = budget |
| 9 | latency increment acceptable | **PASS** — mean +0.72 s, worst +1.42 s |

Criterion 3 is **not achievable within this Phase's constraints**, and criterion 2 fails only through
it. The axis reader was therefore not tuned further. What a future phase would need, stated as scope
rather than as a patch:

* **the context cut** — the window is spent on whichever half the reranker scores higher, and a
  route reservation does not guarantee the *specific* clause a route was aimed at. Two levers exist
  and both are out of scope here: give a clause-bearing route a reservation on its best
  clause-carrying passage rather than its best passage, or raise the window for a two-axis question.
* **the route term for `structure`** — `结构` is the corpus's general word; the clause the benchmark
  expects is `结构图纸`. Promoting the clause's own term is a domain-vocabulary decision with the same
  justification as `设计使用年限`, but doing it now would be tuning to one failing test.

Against that, Phase 1.1 does deliver the thing Phase 1 was chartered for and Phase 1's gate rejected:
the trigger no longer depends on the sentence's surface form (1/6 → 6/6), the fact reader no longer
emits residue (0 malformed), routes carry the corpus's vocabulary instead of the user's, and no
control question moves. That is a genuine improvement in the axis reader — demonstrated, but not
sufficient for promotion on its own.

---

## PRODUCTION_MUTATED

**NO.**

* image id unchanged: `sha256:18711d10f0353a9f37d25611bd81030bd6c6af0f00f764ddf0132b5ad3f7d123` —
  **not rebuilt, `latest` not retagged, no candidate image built**;
* container `wenruo-rag-cpu` still runs that image id;
* container `rag/retrieval/pipeline.py` still hashes to `c9174c52…` (the deployed pre-planner
  revision); the candidate pipeline exists only as `/tmp/p1cand/pipeline.py`;
* `rag/retrieval/route_expansion.py`, `rag/retrieval/domain_facts.py` and `rag/res/synonym.json` are
  still **absent** from the image;
* no index write, no MySQL write, no Redis key written;
* the `/tmp` control-path artifacts were removed from the container at the end of the round;
* **nothing was committed.** `rag/retrieval/route_expansion.py` and `rag/res/synonym.json` were
  modified in the working tree (they are committed files from Phase 0/1) and are left uncommitted,
  because the gate did not pass and a revision should not be attested as a candidate.
