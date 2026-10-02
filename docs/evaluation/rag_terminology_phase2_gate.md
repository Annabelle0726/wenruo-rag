# Retrieval Phase 2 — Multi-fact Context Coverage

Controlled design + experiment. **Nothing deployed, no candidate image built, production code
untouched.** The reservation was implemented as a new module and applied by swapping the cut in
process, so the whole production call path (index, embedding, reranker, route assembly, health) is
the deployed one.

Phase 1.1 was preserved first, as instructed, in commit `4e092c3a1` (development commit; not a
release acceptance).

**All 8 acceptance criteria are met.** One earlier diagnosis is corrected in §1.

---

## 1. STAGE_LOCALISATION (PART A)

Per question, from the deployed cut: the pool the cut sees, the window it produces, and — for the
strongest passage carrying each required clause — where it is lost.

| question | pool | window | design-life clause (rank, score) | structure clause (rank, score) |
|---|---|---|---|---|
| V1 | 20 | 12 | CONTEXT_CUT_DROP r=7 0.641 | CONTEXT_CUT_DROP r=2 0.824 |
| V2 | 21 | 12 | CONTEXT_CUT_DROP r=7 0.334 | CONTEXT_CUT_DROP r=5 0.374 |
| V3 | 29 | 12 | CONTEXT_CUT_DROP r=1 0.620 | CONTEXT_CUT_DROP r=10 0.052 |
| V4 | 32 | 12 | CONTEXT_CUT_DROP r=1 0.869 | CONTEXT_CUT_DROP r=6 0.643 |
| **V5** | 44 | 12 | CONTEXT_CUT_DROP r=1 0.861 | **RERANK_DROP r=19 0.258** |
| V6 | 31 | 12 | CONTEXT_CUT_DROP r=7 0.090 | CONTEXT_CUT_DROP r=4 0.166 |
| **G2** | 37 | 12 | CONTEXT_CUT_DROP r=4 0.772 | **RERANK_DROP r=17 0.035** |
| **G3** | 48 | 12 | CONTEXT_CUT_DROP r=3 0.987 | **RERANK_DROP r=13 0.871** |
| **G5** | 45 | 12 | CONTEXT_CUT_DROP r=3 0.830 | **RERANK_DROP r=16 0.471** |
| QA-001 | 63 | 12 | RERANK_DROP r=41 | RECALL_MISS |
| QA-002 | 17 | 12 | CONTEXT_CUT_DROP r=10 | RECALL_MISS |
| QA-003 | 12 | 12 | RECALL_MISS | RECALL_MISS |
| QA-005 | 50 | 12 | RERANK_DROP r=22 | RERANK_DROP r=28 |
| N1 / N2 / N3 | 12 / 12 / 32 | 12 | RECALL_MISS | CONTEXT_CUT_DROP r=1 / RECALL_MISS / CONTEXT_CUT_DROP r=5 |
| G1 | 32 | 12 | CONTEXT_CUT_DROP r=4 | CONTEXT_CUT_DROP r=10 |
| G4 | 29 | 12 | CONTEXT_CUT_DROP r=9 | CONTEXT_CUT_DROP r=5 |

**The classification, read correctly, corrects the Phase 1.1 conclusion.** The verdicts above are
about the *single strongest* clause-bearing passage; a `CONTEXT_CUT_DROP` on a question whose window
already holds several clause passages (V1, V2, V4, V6, G1, G4) is not a failure — a different,
lower-ranked clause passage took the slot.

The four questions whose window holds **zero** structure-clause passages are **V5, G2, G3 and G5**,
and all four are **RERANK_DROP**, not `CONTEXT_CUT_DROP`:

* V5's clause is at **rank 19** of the reranked pool, score 0.258 — below a 12-slot *and* below a
  16-slot boundary. G2 r=17, G5 r=16, G3 r=13.
* The Phase 1.1 report said the clause "loses the 12-slot cut". That was wrong: it is not a
  cut-boundary problem at all, it is that the **reranker ranks the clause passage below the window
  boundary**. This is confirmed independently by the `topn16` control, which enlarges the window by
  33 % and still returns **0** structure-clause passages for V5, G2 and G5.

Per-fact evidence shows the pool is never short — the deficit is entirely in the window:

| question | design_life pool → window | structure pool → window |
|---|---|---|
| V5 | 23 → 6 | 24 → 6 |
| G2 | 17 → 7 | 25 → 5 |
| G3 | 11 → 6 | 31 → 3 |
| G5 | 20 → 6 | 27 → 4 |

So: **RECALL_MISS never occurs for the failing questions** (the pool always holds the clause), and
**CONTEXT_CUT_DROP is not the mechanism** (the clause is ranked out before the cut sees it). A
reservation that merely re-allocated slots by score could not have fixed this, which is why the
design in §2 overrides score for a fact type that is under-covered.

---

## 2. RESERVATION_DESIGN (PART B)

`rag/retrieval/context_reservation.py` (new, controlled path).

**Rule — evidence parity.** For each fact type the question's axis reader names:

1. compute the strongest evidence the *pool* offers for that fact type, and the strongest the
   *window* already holds;
2. if the window's strongest is already as strong as the pool's, do nothing;
3. otherwise reserve the highest-evidence passage from the pool (ties broken by rerank score) —
   **regardless of its rerank rank**;
4. the reserved passage displaces the **weakest** member of the deployed selection, so the window
   size is unchanged, already-present evidence is not evicted, and the deployed cut's document and
   quota rules still hold for the passages that remain;
5. the result is read back out of the score-ordered pool, so prompt/citation order is preserved;
6. `chunk_id` de-duplication is by construction (the reserved key is added only if absent).

Evidence strength comes from the fact type's **own declared cues**, weighted by cue length:
`结构图纸` scores 6 against a bare `结构`'s 2; `设计使用年限` scores 12 against a bare `寿命`'s 2.
The vocabulary is read from the domain layer that already exists for route construction; no new
terms and no question-specific rules were added.

### The first design failed, and why it matters

The initial rule asked only whether the window carried **any** passage mentioning the fact type. It
changed nothing at all (V5: 6 design-life + 0 structure before and after). The reason is exactly the
V5 shape: the window holds six passages containing `结构`, so structure read as "covered" and the
reservation never fired, while the passage that actually states the requirement — the `结构图纸`
list, evidence 6 against their 2 — stayed outside.

**"The window mentions the topic" is not "the window answers the question".** Replacing presence with
**parity against the best evidence the pool offers** is what makes the rule act, and it also makes it
inert on questions that are already well covered (V1, V2, V4, V6, G1, G4 are untouched).

### Integration point (not applied)

Shipping this needs one production hunk in `rag/retrieval/rerank.py`: `rerank_chunks` already
computes the ordered pool and calls `_select(..., policy)`; the reservation is applied to that
selection before it is returned. The fact types are available from the existing axis reader at the
same point in `pipeline.retrieve_multi_route`. No score, threshold, weight, model or chunking change
is involved.

---

## 3. V1_V6_RESULTS (PART C, strategies A/B/C/D)

3 runs each, same questions, same parameters; only the cut differs.

| q | fact types | strategy | life clause | structure clause | docs | dup | mean score | tokens | latency |
|---|---|---|---|---|---|---|---|---|---|
| V1 | 2 | **A current** | 3,3,3 | 3,3,3 | 6 | 0 | 0.616 | 7511 | 2.22 s |
| V1 | 2 | **B fact-1** | 3,3,3 | 3,3,3 | 6 | 0 | 0.616 | 7511 | 1.14 s |
| V1 | 2 | C route-1 | 3,3,3 | 3,3,3 | 6 | 0 | 0.616 | 7511 | 1.15 s |
| V1 | 2 | D topn16 | 3,3,3 | 4,4,4 | 6 | 0 | 0.528 | 10427 | 1.15 s |
| V2 | 2 | A | 3,3,3 | 4,4,4 | 6 | 0 | 0.395 | 7551 | 1.06 s |
| V2 | 2 | **B** | 3,3,3 | 4,4,4 | 6 | 0 | 0.395 | 7551 | 1.08 s |
| V3 | 2 | A | 5,5,5 | 1,1,1 | 6 | 0 | 0.207 | 6663 | 1.16 s |
| V3 | 2 | **B** | 5,5,5 | 1,1,1 | 6 | 0 | 0.207 | 6663 | 1.17 s |
| V4 | 2 | A | 9,9,9 | 2,2,2 | 5 | 0 | 0.661 | 7293–7431 | 1.30 s |
| V4 | 2 | **B** | 9,9,9 | 2,2,2 | 5 | 0 | 0.664 | 7431 | 1.36 s |
| **V5** | 2 | **A** | 6,6,6 | **0,0,0** | 6 | 0 | 0.488 | 6622 | 2.37 s |
| **V5** | 2 | **B fact-1** | 6,6,6 | **1,1,1** ✅ | 6 | 0 | 0.508 | 6858 | 1.79 s |
| **V5** | 2 | **C route-1** | 6,6,6 | **0,0,0** | 6 | 0 | 0.488 | 6622 | 1.54 s |
| **V5** | 2 | **D topn16** | 8,8,8 | **0,0,0** | 6 | 0 | 0.457 | 8703 | 1.59 s |
| V6 | 2 | A | 1,1,1 | 1,1,1 | 5 | 0 | 0.154 | 7169 | 1.39 s |
| V6 | 2 | **B** | 1,1,1 | 1,1,1 | 5 | 0 | 0.154 | 7052–7169 | 1.33 s |

(Four-digit latency values are medians; V1's `current` median carries a cold-process outlier.)

**Strategy comparison on the failing question:**

| strategy | what it does | V5 structure clause | verdict |
|---|---|---|---|
| **A** current | the deployed cut (already reserves one slot per route) | 0,0,0 | fails |
| **B** fact-reserve-1 | evidence-parity reservation per fact type | **1,1,1** | **works** |
| **C** route-reserve-1 | one best passage per supplemental route | 0,0,0 | **no-op** |
| **D** topn16 | the deployed cut with a 16-slot window (control) | 0,0,0 | fails, and costs +31 % tokens |

**C is a no-op, and that is the informative result.** The deployed cut already reserves one slot per
route (`select_context` stage 1), and every supplemental route is represented in the window for V5 —
which is exactly why the failure survived route expansion. The reservation was at the wrong
granularity: **ROUTE**, when the requirement is per **FACT TYPE**. Reserving a route's best-scoring
passage does not reserve the passage that carries the clause.

**D is the control that proves the point.** A 33 % larger window does not recover the clause, because
the clause is ranked 19th and 16th is still not enough. The fix is not "more slots"; it is "rank must
not be the only criterion for a fact type the window cannot answer".

---

## 4. GENERALIZATION_RESULTS (PART E)

The mechanism was tested on questions with **different entity pairs, enumerators and phrasings**, not
only on V5:

| q | question | entities read | A: struct clause | **B: struct clause** |
|---|---|---|---|---|
| V5 | 标准对终端和接头的结构以及设计使用年限是怎样规定的？ | 终端·接头 | 0,0,0 | **1,1,1** ✅ |
| G2 | 工厂接头与修理接头的结构以及设计使用年限是怎样要求的？ | 工厂接头·修理接头 | 0,0,0 | **1,1,1** ✅ |
| G3 | 110kV海缆单芯和三芯的终端、接头的使用年限和结构要求分别是什么？ | 单芯·三芯·终端 | 0,0,0 | **1,1,1** ✅ |
| G5 | 标准对户外终端和电缆接头的设计使用年限、结构分别有什么规定？ | 户外终端·电缆接头 | 0,0,0 | **1,1,1** ✅ |
| G1 | 户外终端和GIS终端的设计使用寿命和结构有什么规定？ | 户外终端·GIS终端 | 2,2,2 | 2,2,2 (parity — correctly inert) |
| G4 | 电缆终端、电缆接头在结构和设计寿命方面有哪些技术要求？ | 电缆终端·电缆接头 | 4,4,4 | 4,4,4 (parity — correctly inert) |

**Four different questions, four different entity pairs, four different phrasings — all fixed by the
same rule, and the two already-covered questions are left untouched.** That is the evidence that this
is a composite-evidence-coverage mechanism rather than a QA-004 patch: the rule has no knowledge of
which question is asking, only of whether the window can answer each fact type the question named.

**Scope limitation, stated plainly.** PART E asked for four composite classes — 参数+结构, 试验+条件,
材料+性能, 寿命+防护. Only two fact types are declared in the domain layer
(`design_life`, `structure`), and this round froze the fact vocabulary, so only questions naming
those two could be exercised. The other classes are not a reservation problem: a question naming
`载流量` and `结构` never reaches the reservation at all, because the axis reader requires **two**
declared fact types and would find one. Exercising them needs the domain layer extended with those
fact types — a vocabulary increment, not a cut change — and that is the natural next step for this
mechanism, which is now validated independently of which fact types exist.

---

## 5. CONTROL_RESULTS (PART D)

| question | role | fact types | A: life / struct clause | **B: life / struct clause** | docs | dup |
|---|---|---|---|---|---|---|
| QA-001 | frozen | 0 | 0 / 0 | 0 / 0 | 4 | 0 |
| QA-002 | frozen | 0 | 1 / 0 | 1 / 0 | 3 | 0 |
| QA-003 | frozen | 0 | 0 / 0 | 0 / 0 | 6 | 0 |
| QA-005 | frozen | 0 | 0 / 0 | 0 / 0 | 1 | 0 |
| N1 single entity | negative | 0 | 0 / 4 | 0 / 4 | 6 | 0 |
| N2 single fact | negative | 0 | 0 / 0 | 0 / 0 | 6 | 0 |
| N3 one axis | negative | 0 | 0 / 4 | 0 / 4 | 6 | 0 |

Every control has **0 fact types** — the axis reader declines them, so `_representatives` receives an
empty fact list and returns no picks. Their windows are byte-identical between A and B (same token
counts, same clause counts, same document counts), and the four frozen benchmark questions are
unchanged. **Single-fact and single-axis behaviour does not change, existing correct evidence is not
lost, and nothing is flooded**: the reservation adds at most one passage per under-covered fact type
(two maximum), each displacing the weakest member of the window.

---

## 6. TOPN_CONTROL (criterion 7)

The reservation succeeds at `final_top_n = 12`, where the 16-slot control fails:

| | window | V5 structure clause | V5 tokens |
|---|---|---|---|
| A current | 12 | 0 | 6622 |
| B fact-reserve-1 | **12** | **1** | 6858 (+3.6 %) |
| D topn16 | 16 | **0** | 8703 (+31 %) |

The fix does not depend on a larger window, and it costs 3.6 % more context where the control costs
31 % and still does not work. Where `topn16` *does* add evidence (V1 struct 3→4, G1 struct 2→4,
G3 struct 0→2) it does so by spending 31 % more tokens to raise life counts as well (V5 life 6→8,
G5 life 6→8), and it fails on three of the four questions the reservation fixes. It is reported as a
control only and is **not** the proposal.

---

## 7. CONTEXT_DIVERSITY

| question | A docs | B docs | A dup | B dup |
|---|---|---|---|---|
| V1 / V2 / V3 / V5 | 6 | 6 | 0 | 0 |
| V4 | 5 | 5 | 0 | 0 |
| V6 | 5 | 5–6 | 0 | 0 |
| QA-001 / 002 / 003 / 005 | 4 / 3 / 6 / 1 | identical | 0 | 0 |
| N1 / N2 / N3 | 6 | 6 | 0 | 0 |
| G1 / G2 / G4 / G5 | 6 / 5 / 6 / 5 | identical | 0 | 0 |
| G3 | 3 | **4** (improved) | 0 | 0 |

Document diversity is unchanged everywhere and improved once (G3 3 → 4), because the reservation
displaces the weakest member of an already quota-satisfying selection and the reserved passage comes
from wherever the pool holds the best evidence. **Duplicate chunks: 0 in every run of every
strategy.**

---

## 8. TOKEN_LATENCY_IMPACT

| question | tokens A → B | Δ | latency median A → B | mean score A → B |
|---|---|---|---|---|
| V1 | 7511 → 7511 | 0 | 2.22 → 1.14 s | 0.616 → 0.616 |
| V2 | 7551 → 7551 | 0 | 1.06 → 1.08 s | 0.395 → 0.395 |
| V3 | 6663 → 6663 | 0 | 1.16 → 1.17 s | 0.207 → 0.207 |
| V4 | 7293–7431 → 7431 | ≈0 | 1.30 → 1.36 s | 0.661 → 0.664 |
| **V5** | 6622 → 6858 | **+3.6 %** | 2.37 → 1.79 s | 0.488 → 0.508 |
| V6 | 7169 → 7052–7169 | ≈0 | 1.39 → 1.33 s | 0.154 → 0.154 |
| **G2** | 5606 → 6346 | **+13.2 %** | 1.35 → 1.37 s | 0.487 → 0.474 |
| **G3** | 6141 → 6300 | **+2.6 %** | 2.49 → 1.75 s | 0.912 → 0.861 |
| **G5** | 7070 → 7416 | **+4.9 %** | 2.42 → 1.63 s | 0.602 → 0.624 |
| QAs + negatives | unchanged | 0 | unchanged | unchanged |

The reservation adds **no retrieval work** — it re-selects from a pool that was already scored, so
latency is flat or lower (the differences are reorderings, not savings; no configuration changed).
Token growth is confined to the questions that were under-covered: **+2.6 % to +13.2 %**, mean
+4.9 %, against +31 % for the `topn16` control. Mean rerank score of the window falls slightly
(0.487→0.474, 0.912→0.861) — the intended, bounded cost of spending a slot on the answer-bearing
passage instead of the best-scoring one.

---

## 9. REGRESSIONS

**No functional regression; one intended trade-off and one honest cost.**

* Frozen QA-001/002/003/005: identical windows, identical clauses, identical token counts,
  identical document counts. No change.
* Single-fact and single-axis negatives (N1/N2/N3): the reader declines them (0 fact types), so the
  reservation cannot fire; windows byte-identical.
* Well-covered composites (V1, V2, V4, V6, G1, G4): parity holds, reservation inert, windows
  essentially unchanged.
* **Intended trade-off:** G2's design-life clause count falls 7 → 6, because the reserved
  structure-clause passage displaced the weakest member of the window. Both fact types remain
  represented (6 life, 1 structure) — no fact type loses its evidence — but a case where the
  displaced passage was itself clause-bearing is worth watching in a candidate build.
* **Mean-score cost:** the window's mean rerank score drops on the three questions where a
  lower-ranked passage is promoted (G2 0.487→0.474, G3 0.912→0.861, V5 rose to 0.508). This is the
  designed behaviour, not an accident.
* No duplicate chunks, no route explosion (the reservation does not add routes), no document
  flooding, no change to any score, threshold, weight, model or chunk parameter.
* Answer-fact flips where A and B produce **identical** windows (V1, G1, G4 → `structure_drawings`
  True→False) are **generation non-determinism**, not a retrieval change — the token counts prove the
  context was identical. The answer-fact substring probe is noisy (it also scores a negated mention
  as asserted); window clause counts are the reliable metric here.

---

## 10. READY_FOR_CANDIDATE

**YES — the design is validated.**

| # | criterion | result |
|---|---|---|
| 1 | V1–V6 all 3/3 with required evidence present | **PASS** — life and structure clauses present in all 3 runs of all 6 |
| 2 | V5 from 0/3 to 3/3 | **PASS** — 0,0,0 → **1,1,1** |
| 3 | frozen QA no regression | **PASS** — identical windows |
| 4 | single-fact query unchanged | **PASS** — reader declines, reservation inert |
| 5 | no route/chunk flooding | **PASS** — ≤1 passage per under-covered fact type, 0 duplicates, no new routes |
| 6 | context diversity not significantly reduced | **PASS** — unchanged everywhere, improved once |
| 7 | does not depend on enlarging `final_top_n` | **PASS** — works at 12 where the 16-slot control fails |
| 8 | latency/token cost acceptable | **PASS** — latency flat/lower, tokens +2.6…+13.2 % (mean +4.9 %) vs +31 % for the control |

What is validated is the **design**, on a controlled path. Shipping it requires the integration hunk
in §2 applied to `rerank.py`, and — because the fact types come from the axis reader — the Phase 1.1
commit travelling with it. That pair is the candidate.

Recommended before promotion:

1. **Watch the G2-shaped case** (7 → 6 design-life passages) on the full benchmark, so the
   displacement rule can be confirmed not to erode a well-covered fact type over a larger question
   set.
2. **Extend the domain fact vocabulary** (`参数`, `试验`, `材料`, `性能`, `防护`) to make PART E's
   other composite classes testable; the mechanism is now validated independently of which fact
   types exist, so this is additive work with its own evidence to gather.
3. The reservation should stay **inert by default** — parity makes it so for six of the eleven
   composite questions measured — and its effect must remain limited to under-covered fact types.

---

## 11. PRODUCTION_MUTATED

**NO.**

* image id unchanged: `sha256:18711d10f0353a9f37d25611bd81030bd6c6af0f00f764ddf0132b5ad3f7d123` —
  **not rebuilt, `latest` not retagged, no candidate image built**;
* container `wenruo-rag-cpu` runs that same image id; container `rag/retrieval/pipeline.py` still
  hashes to `c9174c52…`;
* `route_expansion.py`, `domain_facts.py`, `context_reservation.py` and `rag/res/synonym.json` are
  still **absent** from the image; the Phase-2 module and the Phase-1.1 modules live only under
  `/tmp/p11`, and the cut was swapped **in process** (a Python attribute rebind), never on disk;
* no index write, no MySQL write, no Redis key written;
* `/tmp` control artifacts removed at the end of the round.

**Commits:** `4e092c3a1` (Phase 1.1, development commit) is the only commit made this round; it
contains the 7 Phase-1.1 paths and **no** Dockerfile or deploy file. The Phase-2 module,
harness and this report are **left uncommitted**, because the reservation is a validated design
awaiting its integration hunk rather than a promotion.
