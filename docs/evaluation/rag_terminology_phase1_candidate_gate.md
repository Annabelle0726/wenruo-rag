# Retrieval Phase 1 — Candidate Gate

Gate outcome: **STOP on generalization. No candidate image built, nothing deployed.** The backport
*mechanics* verified clean; the *rule* did not pass the generalization gate, so it was not promoted.

Commits under gate: `86d59afac` (Phase 0 synonym resource), `79078728f` (Phase 1 supplemental
routes). No retrieval algorithm was changed in this round, and no rerank/embedding/threshold value
was touched.

---

## GENERALIZATION_RESULTS

Nine questions, end-to-end on the deployed stack (`P1_SET=variants`, 3 runs per mode, assistant's
own parameters, deployed reranker/index/embedding). `CTRL_BEFORE` = the question's own observed
decomposition; `CTRL_AFTER` = the same route set plus whatever the rule adds.

| variant | phrase it tests | trigger | supp. routes | design-life b→a | structure b→a | both (after) | win routes b→a |
|---|---|---|---|---|---|---|---|
| V1 | 标准对电缆附件**（终端与接头）**的设计使用寿命与结构有何要求？ | **YES** | 4 | 3,3,3 → **4,4,4** | 4,4,4 → 3,3,3 | **3/3** | 5 → 9 |
| V2 | 电缆终端和接头的**设计寿命、结构**分别有什么要求？ | no | 0 | 4,4,4 → 4,4,4 | 4,4,4 → 4,4,4 | 3/3 | 4 → 4 |
| V3 | 终端与接头能**使用多少年**？结构上有什么规定？ | no | 0 | 5,5,5 → 5,5,5 | 1,1,1 → 1,1,1 | 3/3 | 4 → 4 |
| V4 | 电缆附件中的终端、接头，其**使用年限**和结构要求是什么？ | no | 0 | 9,9,9 → 9,9,9 | 2,2,2 → 2,2,2 | 3/3 | 5 → 5 |
| V5 | 标准对终端和接头的**结构以及设计使用年限**是怎样规定的？ | no | 0 | 6,6,6 → 6,6,6 | **0,0,0 → 0,0,0** | **0/3** | 6 → 6 |
| V6 | 终端、接头在**寿命和结构**方面有哪些技术要求？ | no | 0 | 2,2,2 → 2,2,2 | 1,1,1 → 1,1,1 | 3/3 | 5 → 5 |
| N1 | 海缆的设计使用寿命是多少？（one entity） | no | 0 | 0 → 0 | 4 → 4 | 0/3 | 1 → 1 |
| N2 | 终端结构有什么要求？（one fact） | no | 0 | 0 → 0 | 0 → 0 | 0/3 | 1 → 1 |
| N3 | 终端和接头有哪些类型？（one axis） | no | 0 | 0 → 0 | 4 → 4 | 0/3 | 3 → 3 |

Plus the frozen benchmark on the same build: QA-001/002/003/005 all `added = 0`, windows identical.

**Trigger rate on paraphrases: 1 of 6 (17 %).** Answers to the specific checks requested:

* **Not dependent on the parenthesis form — FAILS.** The entity axis is read only from a
  parenthesised group (`_PAREN_RE`). V2–V6 have no parentheses, so all five decline with
  `no_entity_enumeration` before the fact axis is ever considered.
* **Not dependent on "有何要求" — PASSES.** The fact-axis predicate cut keys on
  `有何|有哪|是什|是怎|如何|怎样|怎么|多少|哪些|什么|要求|规定|标准|参数|数值`, so V2 (有什么要求),
  V3 (多少 / 什么规定), V4 (是什么), V5 (怎样规定), V6 (有哪些要求) would all be cut correctly.
  The dependency is on the *bracket*, not on the phrase.
* **寿命 / 设计寿命 / 使用年限 variants — partially unstable.** See OVERFIT_RISK; when forced into
  the parenthesised form the fact axis picks up **predicate residue** and produces routes carrying
  vocabulary nothing can match.
* **Single-entity / single-fact questions must not expand meaninglessly — PASSES.** N1, N2, N3 and
  QA-005 all decline with a recorded reason and add 0 routes; windows are byte-identical.
* **No route explosion — PASSES.** Maximum merged route set 9 (V1: 5 → 9), bounded by
  `ROUTE_BUDGET`. Zero duplicate chunks in every run of both query sets.

### The outcome gap is narrower than the trigger gap, but real

Four of the five non-triggering paraphrases (V2, V3, V4, V6) reach **both** halves anyway, because
the LLM decomposer handles those phrasings adequately on its own. So the rule's failure to trigger
did not cost retrieval on them.

**V5 is the exception and it is a genuine uncovered failure**: `标准对终端和接头的结构以及设计使用
年限是怎样规定的？` returns life 6 passages but **structure 0 passages, 0/3 runs** — the structure
half of the question is never retrieved, and the rule could not help because it declined. This is
the same class of defect Phase 1 exists to fix, in a phrasing Phase 1 does not recognise.

---

## OVERFIT_RISK

**High, and in two independent directions.** The rule was written against one sentence's surface
form, and the gate exposes both the form dependency and a second defect beneath it.

**Risk 1 — the reader is bracket-shaped.** `read_axes` finds the entity axis only inside `（…）`.
Every natural enumeration without brackets (`终端和接头`, `终端、接头`, `终端与接头`) is invisible.
The trigger rate above is the measurement of this.

**Risk 2 — the fact axis is not cleaned up, and emits unmatchable vocabulary.** Forcing the
paraphrase wordings into the parenthesised form shows what the rule would produce if the bracket
requirement were relaxed:

| input fact wording | fact members emitted | Phase 0 synonym lookup |
|---|---|---|
| 设计使用寿命与结构有何要求 | `设计使用寿命`, `结构` | `设计使用寿命 → 设计使用年限` ✅ |
| **设计寿命、结构分别有什么要求** | `设计寿命`, **`结构分别有`** | `lookup(设计寿命) = []` ❌ |
| **寿命和结构有什么要求** | `寿命`, **`结构有`** | `lookup(寿命) = []` ❌ |
| 使用年限和结构有什么要求 | `使用年限`, **`结构有`** | `使用年限` is the corpus term ✅ |

Two defects visible at once:

* **Predicate residue.** `结构分别有什么要求` cuts at `什么` and leaves `结构分别有`;
  `结构有什么要求` leaves `结构有`. The cut list does not cover bare `有` / `分别有`. These are not
  fact types; they are fragments, and they become route text.
* **The route inherits the user's vocabulary verbatim, and Phase 0 only bridges two spellings.**
  Phase 0 maps `设计使用寿命` and `使用寿命` to `使用年限`, and deliberately refuses
  `寿命 → 年限`. So a route `终端 设计寿命` or `终端 寿命` carries a term that occurs in **0** of the
  317 corpus chunks and is not synonym-expanded — it retrieves on the dense leg alone, which this
  corpus's flat 0.0145 cosine separation cannot be trusted to resolve.

So Phase 0 + Phase 1 together cover **the exact QA-004 vocabulary** and the already-correct corpus
term. They do not cover `设计寿命` or bare `寿命`. Closing that would mean either widening the
synonym table (which the earlier coverage investigation measured as a precision risk, since `寿命`
appears in 26 chunks including unrelated clauses) or making the rule emit the *corpus* term rather
than the user's — which is a design change, not a special case, and is out of scope here.

**Per the gate instruction, no special cases were added.** Widening `_PAREN_RE` to also accept
non-bracketed enumerations, and listing the fact-axis predicate residue, are exactly the
"堆特例" this gate forbids doing reactively; they are a redesign of the axis reader, and they should
be specified and measured on their own, not patched in to make this variant set pass.

---

## PRODUCTION_PIPELINE_DIFF

Three revisions of `rag/retrieval/pipeline.py`, by git blob:

| revision | blob | lines | note |
|---|---|---|---|
| **production image** `sha256:18711d10…` | `da38414bd59b` | 341 | pre-planner; **zero** references to `planner`, `compile_retrieval_plan` or `plan_hash` |
| `79078728f^` (= the gate's base revision, `7a63b6f57`) | `669a0879d6` | 507 | the P1-2 planner evolution |
| HEAD (`79078728f`) | `ca1565cefa` | 507 | the above + Phase 1's 3 hunks |

```
git diff --numstat da38414bd59b 669a0879d6   →   201 insertions(+), 35 deletions(-)
```

So **236 lines of route-planning evolution between the image and the parent commit are NOT
deployed**, and a full build from HEAD would ship them silently as part of a "Phase 1" validation —
which is exactly what the task forbade. What HEAD adds:

* `rag/retrieval/planner.py` — a whole module that does not exist in the image
  (`compile_retrieval_plan`, `plan_hash`, `PlanCache`, `QuestionProfile`, `dimension_heads`);
* `pipeline.py` route assembly rewritten around the compiled plan, with the base route, dimension,
  side and clause routes all sourced from `plan.texts`;
* `MAX_CORE_DOCUMENT_ROUTES`, follow-up and fallback passes reading `sub_queries`/`side_routes`
  back out of the plan.

Deployed route assembly, for reference (`pipeline.py:277-300`):

```python
routes = [question]
sub_queries = []
if looks_composite(question):
    sub_queries = await decompose_question(chat_mdl, question, max_sub_queries)
    routes.extend(sub_queries)
sides = comparison_sides(question)
side_routes = comparative_routes(question, sides) if is_comparative_question(question) else []
if side_routes:
    routes.extend(side_routes)
targeted = clause_route(question)
if targeted:
    routes.append(targeted)
```

---

## MINIMAL_BACKPORT

**Verdict: safely portable.** Exactly **3 hunks, +24 lines, 0 deletions** against the deployed
`pipeline.py`, with no planner symbol and no behavioural change to any existing route. Produced and
reviewed by `tools/scripts/phase1_build_backport.py`; the full diff is in §"MINIMAL_BACKPORT diff"
below.

Portability rests on three facts, each verified:

1. The deployed pipeline **already imports** `MAX_SUB_QUERIES` from `rag.retrieval.decomposition`
   (`pipeline.py:40`), so the budget constant needs no planner import:
   `ROUTE_BUDGET = MAX_SUB_QUERIES + MAX_SUPPLEMENTAL_ROUTES` (= 8).
2. `rag/retrieval/route_expansion.py` depends only on `rag.nlp.retrieval_projection` and
   `rag.retrieval.decomposition` — both **byte-identical to HEAD in the deployed image** — and was
   imported successfully against the deployed tree (`deps: ['rag.nlp.retrieval_projection',
   'rag.retrieval.decomposition']`).
3. The insertion point is the end of the deployed route assembly, not the plan hand-off, so no
   deployed line is rewritten.

### MINIMAL_BACKPORT diff (deployed → candidate)

```diff
--- deployed/pipeline.py
+++ candidate/pipeline.py
@@ -47,6 +47,7 @@
 from rag.retrieval.query_router import route_question
 from rag.retrieval.rerank import DEFAULT_FINAL_TOP_N, rerank_chunks, resolve_final_top_n
+from rag.retrieval.route_expansion import MAX_SUPPLEMENTAL_ROUTES, supplemental_routes

 _LOG = logging.getLogger(__name__)
@@ -54,6 +55,11 @@
 MAX_CORE_DOCUMENT_ROUTES = 3
+
+#: Total route allowance for one question on THIS pipeline: the decomposition cap plus room for the
+#: deterministic supplemental cross product. Derived from a constant the deployed module already
+#: imports, so the backport introduces no dependency on the planner.
+ROUTE_BUDGET = MAX_SUB_QUERIES + MAX_SUPPLEMENTAL_ROUTES

 #: How thin a standard's PROSE may be before a clause question triggers the
@@ -297,6 +303,24 @@
     targeted = clause_route(question)
     if targeted:
         routes.append(targeted)
+    # Deterministic supplemental routes: a question that enumerates both an entity axis and a
+    # fact-type axis gets their bounded cross product, so its per-fact-type coverage does not depend
+    # on how granular the decomposition model happened to be in this session. Additive: every route
+    # above is kept. See `rag.retrieval.route_expansion`.
+    supplemental, expansion = supplemental_routes(
+        question,
+        existing_routes=routes,
+        budget=max(0, ROUTE_BUDGET - len(routes)),
+    )
+    if supplemental:
+        routes.extend(supplemental)
+        sub_queries.extend(supplemental)
+        _LOG.info(
+            "[Multi-route] deterministic expansion=%s added %d route(s): %s",
+            expansion.get("reason"),
+            len(supplemental),
+            supplemental,
+        )
     _LOG.info("[Multi-route] question=%r -> %d route(s): %s", question[:80], len(routes), routes)

     async def _retrieve(queries, doc_scope):
```

Semantic equivalence with the committed Phase 1 hunk is exact: same import of the same two names,
same call with the same `existing_routes` / `budget` arguments, same append to `routes` and
`sub_queries`. The only difference is the budget's derivation (`+ MAX_SUB_QUERIES` instead of
`+ MAX_PLAN_ROUTES`) and the insertion point, both forced by the deployed revision's shape.

---

## CANDIDATE_IMAGE

**NOT BUILT — deliberately.**

The gate's own instruction is to stop and report when the variants largely fail to trigger. Five of
six paraphrases do not trigger, and the rule emits malformed fact members on paraphrase vocabulary.
Building an image would enshrine a rule that works for one sentence's surface form, and — because
`latest` must not be retagged and the artifact would exist — would create a plausible-looking
candidate that a later reader could mistake for an approved one.

What was done instead, which yields the same end-to-end evidence without the artifact: the deployed
`pipeline.py` was patched into a **standalone module** in `/tmp` (never the deployed tree), the
Phase-1 rule was injected under its real dotted name so the candidate's import line is the shipping
one, and the candidate's own `retrieve_multi_route` was driven end-to-end against the deployed
index, embedding model, reranker and assistant parameters. The module reported
`ROUTE_BUDGET=8` and `route_expansion is Phase-1 rule: True`, so **the production code path under
test genuinely went through `route_expansion`**.

---

## WHOLE_IMAGE_DIFF

No image exists, so there is no built-artifact diff. The prospective diff was instead established
from the production image itself:

| path | state in production image | candidate |
|---|---|---|
| `rag/res/synonym.json` | **absent** | added (Phase 0) |
| `rag/retrieval/route_expansion.py` | **absent** | added (Phase 1) |
| `rag/retrieval/pipeline.py` | present, sha256 `c9174c52…d…` | replaced by the +24/−0 backport above |
| every other `*.py` under `rag/`, `api/`, `common/` (485 files in total) | — | **unchanged** |

and by the dependency proof that the two added files are self-contained: their only imports resolve
against modules already present and byte-identical in the image. So a candidate built this way would
differ from the baseline in **exactly those three paths**, with no `planner.py`, no rerank change, no
metadata change, no frontend and no unrelated backend code. This is an argument, not a build
attestation — no artifact was produced to hash.

---

## END_TO_END_QA

Frozen 5-question benchmark plus the paraphrase set, through the isolated candidate's production
code path, 3 runs each, assistant's own parameters, deployed reranker/index/embedding.

| question | expansion | added | design-life | structure | both | median latency | win routes | dup |
|---|---|---|---|---|---|---|---|---|
| QA-004 exact | expanded | 4 | **3,3,3** | **3,3,3** | **3/3** | 1.92 s | 7 | 0 |
| QA-004 V2 | no_entity_enumeration | 0 | 3,3,3 | 4,4,4 | 3/3 | 1.05 s | 4 | 0 |
| QA-004 V3 | no_entity_enumeration | 0 | 5,5,5 | 1,1,1 | 3/3 | 1.12 s | 4 | 0 |
| QA-004 V4 | no_entity_enumeration | 0 | 9,9,9 | 2,2,2 | 3/3 | 1.26 s | 5 | 0 |
| QA-004 V5 | no_entity_enumeration | 0 | 6,6,6 | **0,0,0** | **0/3** | 1.58 s | 6 | 0 |
| QA-004 V6 | no_entity_enumeration | 0 | 1,1,1 | 1,1,1 | 3/3 | 1.25 s | 5 | 0 |
| QA-001 | no_entity_enumeration | 0 | 0,0,0 | 0,0,0 | 0/3 | 2.11 s | 8 | 0 |
| QA-002 | no_entity_enumeration | 0 | 1,1,1 | 0,0,0 | 0/3 | 0.91 s | 3 | 0 |
| QA-003 | no_entity_enumeration | 0 | 0,0,0 | 0,0,0 | 0/3 | 0.85 s | 2 | 0 |
| QA-005 | no_fact_enumeration | 0 | 0,0,0 | 0,0,0 | 0/3 | 1.55 s | 5 | 0 |
| N1 single entity | no_entity_enumeration | 0 | 0,0,0 | 4,4,4 | 0/3 | 0.67 s | 1 | 0 |
| N2 single fact | no_entity_enumeration | 0 | 0,0,0 | 0,0,0 | 0/3 | 0.65 s | 1 | 0 |
| N3 one axis | no_entity_enumeration | 0 | 0,0,0 | 4,4,4 | 0/3 | 1.07 s | 3 | 0 |

Against the stated acceptance criteria:

* **QA-004 exact: 3/3 life + structure — MET** (3 life, 3 structure, every run).
* **QA-004 paraphrases: "绝大多数应稳定覆盖相同事实" — NOT MET.** 4 of 6 cover both halves; V5 covers
  only the life half (structure 0/3) and the rule cannot reach it.
* **QA-001/002/003/005 no regression — MET.** Rule adds 0 routes; windows identical to the deployed
  behaviour measured in the Phase 1 round.
* **Production code path really goes through `route_expansion` — MET** (`route_expansion is
  Phase-1 rule: True`, and the V1 window route count rises 5 → 9 while every other question is
  bit-identical).
* **Latency acceptable — MET** (below).
* **No route explosion — MET** (max 9 merged routes; duplicates 0).

---

## PARAPHRASE_STABILITY

| variant | question | runs | design-life | structure | both | verdict |
|---|---|---|---|---|---|---|
| V1 | 标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求？ | 3 | 4/4/4 | 3/3/3 | 3/3 | stable ✅ |
| V2 | 电缆终端和接头的设计寿命、结构分别有什么要求？ | 3 | 4/4/4 | 4/4/4 | 3/3 | stable ✅ |
| V3 | 终端与接头能使用多少年？结构上有什么规定？ | 3 | 5/5/5 | 1/1/1 | 3/3 | stable ✅ |
| V4 | 电缆附件中的终端、接头，其使用年限和结构要求是什么？ | 3 | 9/9/9 | 2/2/2 | 3/3 | stable ✅ |
| V5 | 标准对终端和接头的结构以及设计使用年限是怎样规定的？ | 3 | 6/6/6 | **0/0/0** | **0/3** | **structure half never retrieved** ❌ |
| V6 | 终端、接头在寿命和结构方面有哪些技术要求？ | 3 | 1/1/1 | 1/1/1 | 3/3 | stable ✅ |

Run-to-run stability is good: every cell above is identical across its 3 runs, including the two
variants whose wording uses the corpus term (`使用年限` in V4/V5) and the two that use unmatchable
terms (`设计寿命` in V2, `寿命` in V6) — the dense leg carries those, which is why they work without
the rule. The single instability is V5's missing structure half, and it is a coverage gap rather
than jitter (0 in all three runs).

---

## LATENCY

Median of 3, isolated candidate, same parameters as the deployed assistant:

| question | routes added | median latency | vs deployed baseline |
|---|---|---|---|
| QA-004 exact | 4 | 1.92 s | Phase 1 measured +0.91 s at this route count |
| QA-004 V2–V6 | 0 | 1.05 / 1.12 / 1.26 / 1.58 / 1.25 s | unchanged (no routes added) |
| QA-001 / QA-002 / QA-003 / QA-005 | 0 | 2.11 / 0.91 / 0.85 / 1.55 s | unchanged |
| N1 / N2 / N3 | 0 | 0.67 / 0.65 / 1.07 s | unchanged |

The cost is confined to questions the rule expands, and it is one extra concurrent round trip at
2 routes → 6 and roughly two at 4 → 8 (measured in the Phase 1 round as +0.91 s and +1.45 s; the
absolute numbers above are lower because the candidate run had a warm process). Nothing on a
declining question costs anything, because the route list is unchanged.

---

## REGRESSIONS

**None attributable to this change.** QA-001/002/003/005 and the three negatives all get
`added = 0`, i.e. a byte-identical route list, so their retrieval cannot have changed; the measured
windows confirm it. Zero duplicate chunks across every run of this round. No metadata, rerank,
embedding, threshold, chunking or frontend file is involved.

Two pre-existing observations, neither caused by this change and both already characterised in the
QA-004 investigation:

* the reranker is not bit-deterministic (max |Δ| 0.0064 on identical input), visible as small
  context-length jitter on questions with many routes;
* the substring answer-fact probe scores a *negated* mention as if asserted — `N1` reports
  `design_life_years=True` on a run whose window contains 0 design-life passages, while the same
  context in the `CTRL_BEFORE` run reports `False`. Generation non-determinism plus a naive probe,
  not a retrieval change.

---

## READY_FOR_RETRIEVAL_DEPLOYMENT

**NO.**

The blocker is **generalization, not portability**. The backport is a clean 3-hunk, +24/−0 change
that runs on the deployed baseline and provably does not drag in the planner; the rule itself is
form-dependent (needs a parenthesised entity axis → 1/6 paraphrases trigger), leaves predicate
residue in the fact axis (`结构分别有`, `结构有`), and emits the user's vocabulary rather than the
corpus's, which Phase 0's synonym table only bridges for two of the observed spellings. One
paraphrase (V5) still misses the structure half entirely.

What would need to happen before this can be promoted, stated as scope rather than as a patch:

1. **Redesign the axis reader** to find an entity enumeration without requiring brackets — the
   existing `dimension_heads` split (which the working-tree planner already performs) is the
   starting point, and it must be specified and measured against this variant set rather than
   widened case by case.
2. **Clean the fact members** — extend the predicate cut to cover `有` / `分别有` and validate that
   every emitted member is a noun phrase, or drop members that are not.
3. **Decide the route vocabulary question**: emit the corpus's term (needs a mapping table wider
   than Phase 0's, which the terminology-coverage investigation measured as a precision risk for
   `寿命`) or keep the user's term and accept dense-only retrieval for it.
4. **Re-run this gate** — the variant set here is a good first acceptance suite and should be
   adopted as such.

Phase 1's *mechanism* is proven: a deterministic supplemental route set removes QA-004's dependence
on decomposition granularity (3/3 with the LLM channel dead, in the Phase 1 round). Phase 1's
*coverage rule* is not ready. `79078728f`'s rule should not ship as-is, and `86d59afac`'s synonym
resource is independent of this verdict — it was measured non-regressive on its own and can ship
separately.

---

## PRODUCTION_MUTATED

**NO.**

* image id unchanged: `sha256:18711d10f0353a9f37d25611bd81030bd6c6af0f00f764ddf0132b5ad3f7d123`,
  created 2026-09-30T11:22:06Z — **not rebuilt, `latest` not retagged**;
* container `wenruo-rag-cpu` still runs that same image id;
* `rag/retrieval/pipeline.py` in the container still hashes to `c9174c52…` (the deployed
  pre-planner revision) — the candidate lives only in `/tmp/p1cand/`;
* `rag/retrieval/route_expansion.py` and `rag/res/synonym.json` are still **absent** from the image;
* no index write, no MySQL write, no Redis key left behind, nothing deployed;
* at the end of the round the `/tmp` control-path artifacts were removed from the container.

**Nothing was committed in this round.** `79078728f` and `86d59afac` remain the only Phase 0/1
commits; this report and the three gate tools are left uncommitted, because the gate's conclusion is
that the rule should be revised before further attestation.
