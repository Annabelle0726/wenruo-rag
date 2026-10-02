# Retrieval Improvement Phase 1 — deterministic supplemental routes

Controlled design + implementation. **Nothing was deployed, no image was built, and the running
deployment was not modified.**

Depends on Phase 0: `rag/res/synonym.json` (`设计使用寿命 → 设计使用年限`) stays in force and is not
changed here. `寿命 → 年限` is still absent.

---

## 1. Audit of the deployed route-planning path

The image runs the **pre-planner** pipeline: `rag/retrieval/pipeline.py` = git blob
`da38414bd59b`, and `rag/retrieval/planner.py` **does not exist in it**. `decomposition.py` and
`query_router.py` are byte-identical to HEAD. So `compile_retrieval_plan` is **not deployed** — it is
future work in the working tree. This matters: a designer who reads `planner.py` would conclude the
deterministic machinery already exists in production. It does not.

### 1.1 Deployed route assembly (`pipeline.py:277-300`)

```python
routes = [question]
sub_queries = []
if looks_composite(question):
    sub_queries = await decompose_question(chat_mdl, question, max_sub_queries)   # LLM
    routes.extend(sub_queries)
sides = comparison_sides(question)
side_routes = comparative_routes(question, sides) if is_comparative_question(question) else []
if side_routes: routes.extend(side_routes)
targeted = clause_route(question)
if targeted: routes.append(targeted)
```

| component | what it does | deterministic? | fires on QA-004? |
|---|---|---|---|
| `looks_composite` | gate for the LLM call: an enumerating conjunction, or ≥2 interrogatives | yes | yes (`与`) |
| `decompose_question` | asks the chat model for ≤ `MAX_SUB_QUERIES` (=4) sub-queries, parsed by `parse_sub_queries` | **no** | yes — **this is the unstable part** |
| `comparative_routes` | one route per **comparison side**, gate `is_comparative_question` (`对比\|比较\|区别\|不同\|差异`), members read by `comparison_sides`, side markers stripped from the shared subject | yes | **no** — QA-004 has no comparative verb |
| `clause_route` | one prose-tier route + `CLAUSE_ROUTE_ANCHOR`, gate `seeks_clause` | yes | no |
| `query_router.route_question` | classifies NUMERIC / REVISION / CONCEPTUAL and adjusts `vector_similarity_weight` + `routes_top_k` | yes | no (no rule matched) |
| entity / fact-type extraction | **none exists** | — | — |

`comparative_routes` is the reusable precedent: "one route per axis value, with the axis markers
removed from the shared subject". What did not exist is a reader for **two** axes, and a gate that
fires on an **enumerated object list** rather than a comparative verb.

### 1.2 The working-tree planner already does the single-axis version

`planner.dimension_heads` splits at the same enumerating conjunctions, takes the last segment's
predicate, and emits one dimension route per head; `compile_plan` orders base → dimensions → sides →
clause, dedups, and caps at `MAX_PLAN_ROUTES = 1 + 4 + 6 + 1 = 12`. It is **single-axis**: applied to
`标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求` its split yields the malformed heads
`标准对电缆附件（终端` / `接头）的设计使用寿命` — it cannot read a nested entity × fact-type
enumeration, and it is not deployed. Phase 1 therefore adds the two-axis reader rather than relying
on it.

### 1.3 Root cause, re-confirmed on this build

Pinning the LLM channel (a stub chat model returning a fixed decomposition payload) isolates the
route set as the only variable:

| mode | routes the pipeline used | design-life passages in the final window |
|---|---|---|
| `PRODUCTION_ASIS` (real model) | its own, 2 sub-queries this session | **0 / 0 / 0** |
| `CTRL_BEFORE` (frozen **2**-route LLM payload) | 2 | **0 / 0 / 0** |
| `CTRL_BEFORE_llm4` (frozen **4**-route LLM payload) | 4 | **3 / 3 / 3** |

Same question, same build, same index, same models — only the decomposed route set differs. That is
the root cause, measured rather than inferred.

---

## 2. Design

A question that enumerates an **entity axis** and a **fact-type axis** gets their bounded cross
product as **deterministic supplemental routes**, added after the LLM decomposition.

```
…（终端与接头）的设计使用寿命与结构有何要求
   └── entities: 终端, 接头      └── fact types: 设计使用寿命, 结构
        ↓ cross product
   终端 设计使用寿命 · 终端 结构 · 接头 设计使用寿命 · 接头 结构
```

Design rules, each with the reason it is there:

1. **Additive.** Nothing is removed, reordered or rewritten; the caller's routes are passed in and
   every emitted route is distinct from every existing one.
2. **No second LLM call.** The two axes are read structurally from the question's own words — the
   same way `dimension_heads` reads one axis — using the *same* `ENUMERATING_CONJUNCTION_RE` the
   deployed code already uses, so the readers cannot disagree about what an enumeration is.
3. **No domain vocabulary in the core.** There is no list of cable words in the new module. The only
   domain input is the **existing** profile table: expansion is offered only when the deployed
   `retrieval_projection.classify_category` recognises the question as belonging to a known domain
   (`power_cable` here). A new domain is a new entry in that table, not a new branch.
4. **Two axes required.** Fewer than two members on *either* axis emits nothing, so a
   single-information-need question is untouched.
5. **Bounded.** ≤ `MAX_AXIS_MEMBERS` (3) per axis, ≤ `MAX_SUPPLEMENTAL_ROUTES` (4) emitted, and the
   caller passes a `budget`; the pipeline computes `ROUTE_BUDGET(16) − len(routes)`. No Cartesian
   explosion: a 4×3 question is capped at 4 routes, not 12.
6. **Deduplicated.** Against existing routes and internally, in the question's own member order.
7. **Non-regressive by construction.** For a question the rule declines, the route list is
   byte-identical to today's, so retrieval cannot change.

Two deterministic cuts are needed because the fact axis sits mid-sentence rather than in
parentheses: the shared subject is dropped up to and including the first `的`
(`标准对电缆附件 的设计使用寿命` → `设计使用寿命`), and the question's predicate is dropped from
the first interrogative/requirement marker (`结构有何要求` → `结构`).

### 2.1 Integration point

`rag/retrieval/pipeline.py`, immediately after `routes = list(plan.texts)`:

* supplemental routes are appended to `routes` (so they are retrieved);
* they are also appended to `sub_queries` (so `core_document_followup` and `cross_part_fallback`
  prefer them, exactly as the `KIND_DIMENSION` routes are);
* the route-count log line now reports compiled + supplemental + the expansion reason.

Note the supplemental routes intentionally bypass `max_sub_queries`: in the deployed pipeline
`parse_sub_queries` truncates the model's list at 4, which is precisely the cap that would have eaten
the supplemental routes had they been injected through the LLM channel.

---

## 3. Rule behaviour (measured)

| question | entities | fact types | profile | reason | added |
|---|---|---|---|---|---|
| QA-004 exact | 终端, 接头 | 设计使用寿命, 结构 | power_cable | expanded | 4 |
| QA-004 narrow life | — | — | — | no_entity_enumeration | 0 |
| QA-001 | — | — | — | no_entity_enumeration | 0 |
| QA-002 | — | — | — | no_entity_enumeration | 0 |
| QA-003 | — | — | — | no_entity_enumeration | 0 |
| QA-005 | 出厂, 安装后 | — | — | no_fact_enumeration | 0 |

Budget and de-duplication verified directly: with one route pre-supplied and `budget=2` the rule
emits 2 and reports the dropped duplicate; with `budget=0` it emits nothing and reports
`no_route_budget`.

---

## 4. Validation

Because the image does not contain the rule, the deployed pipeline was driven through a **stub chat
model** whose decomposition answer is fixed, so before/after differ by exactly one thing — the
presence of the supplemental routes. All modes use the assistant's own parameters
(`similarity_threshold 0.55`, `vector_similarity_weight 0.5`, `final_top_n 12`, `knn_top_k 1024`,
`rerank_candidates_count 30`), the deployed reranker, the deployed index and the deployed embedding
model. `max_sub_queries` is raised to the route budget in every controlled mode so the sub-query cap
is never the variable; `PRODUCTION_ASIS` keeps the deployed default.

### 4.1 QA-004 exact composite — 3 runs per mode

| mode | routes used | design-life passages | structure passages | both halves | grounded answer |
|---|---|---|---|---|---|
| `PRODUCTION_ASIS` | as-is | **0 / 0 / 0** | 4 / 4 / 4 | 0/3 | "知识库中并没有直接给出…具体年限数字" (honest refusal) |
| `CTRL_BEFORE` (2 LLM) | 2 | **0 / 0 / 0** | 4 / 4 / 4 | 0/3 | refusal |
| **`CTRL_AFTER` (2 LLM + 4 det.)** | **6** | **3 / 3 / 3** ✅ | **3 / 3 / 3** ✅ | **3/3** | "终端和接头的设计使用年限均**不少于30年**" with `Q/GDW 73285.2-2026` citations ✅ |
| `CTRL_BEFORE_llm4` (4 LLM) | 4 | 3 / 3 / 3 | 3 / 3 / 3 | 3/3 | grounded, 4 structure topics |
| **`CTRL_AFTER_llm4` (4 LLM + 4 det.)** | **8** | **4 / 4 / 4** ✅ | **3 / 3 / 3** ✅ | **3/3** | grounded ✅ |
| `AFTER_NO_LLM` (0 LLM + 4 det.) | 4 | **5 / 5 / 5** ✅ | **3 / 3 / 3** ✅ | **3/3** | grounded ✅ |

Acceptance criteria:

* **3/3 design-life evidence** — met in every `AFTER` mode.
* **3/3 structure evidence retained** — met (3 structure passages in every `AFTER` run).
* **Independent of the 2-route vs 4-route granularity** — met. `CTRL_AFTER` (2-route base) and
  `CTRL_AFTER_llm4` (4-route base) both give 3/3, and `AFTER_NO_LLM` shows the rule **alone**
  suffices with the LLM channel entirely dead (5 design-life passages, the best of the set).
* **Other four frozen QAs unchanged** — §4.2.

Answer-fact probe caveat: the probe is a substring test, so a *negated* mention
("并没有直接给出…比如"30年"") scores as if the fact were asserted. `CTRL_BEFORE`'s
`design_life_years=True` in one batch is that false positive, confirmed by reading the answer text;
the window held 0 design-life passages, which is what decides the outcome.

### 4.2 Controls — 3 runs per mode

| question | routes before → after | design-life | structure | window routes | distinct docs |
|---|---|---|---|---|---|
| QA004_narrow_life | 2 → 2 | 1/1/1 → 1/1/1 | 4/4/4 → 4/4/4 | 3 → 3 | 6 → 6 |
| QA-001 | 4 → 4 | 0 → 0 | 0 → 0 | 8 → 8 | 4 → 4 |
| QA-002 | 2 → 2 | 1 → 1 | 0 → 0 | 3 → 3 | 3 → 3 |
| QA-003 | 1 → 1 | 0 → 0 | 0 → 0 | 2 → 2 | 6 → 6 |
| QA-005 | 3 → 3 | 0 → 0 | 0 → 0 | 5 → 5 | 1 → 1 |

Every control question has `added = 0`, so its route list is identical and its retrieval cannot
change; the measured windows confirm it.

---

## 5. Additional checks

**Route explosion — none.** The rule adds at most 4 routes; the largest merged set observed is 8
(4 LLM + 4 supplemental), well under `ROUTE_BUDGET = 16`. The 3-per-axis member cap means a question
naming four entities and three fact types yields 4 routes, not 12. Control questions add 0.

**Duplicate chunks — none.** `duplicate_chunks = 0` in all 90 runs. `merge_route_hits` de-duplicates
by `chunk_id`, so a passage found by several routes enters the window once; the supplemental routes
do add `route_hits`, not duplicates.

**Context diversity — not reduced.** Distinct documents in the window are unchanged for QA-004
(6 → 6) and for every control (2/3/4/6/1 → identical). The window is one passage shorter on the
structure side (4 → 3) because three design-life passages now occupy slots, which is the intended
re-allocation of a fixed 12-slot window, not a diversity loss.

**Latency.** Median of 3 runs, production entry, same parameters:

| question | before | after | delta |
|---|---|---|---|
| QA-004 exact (2 → 6 routes) | 2.52 s | 3.43 s | +0.91 s (+36 %) |
| QA-004 exact (4 → 8 routes) | 2.04 s | 3.49 s | +1.45 s (+71 %) |
| QA-004 exact (supplemental only, 4 routes) | — | 2.31 s | — |
| QA-004 narrow life | 1.49 s | 1.55 s | +0.06 s |
| QA-001 | 3.84 s | 3.79 s | −0.05 s |
| QA-002 | 1.37 s | 1.29 s | −0.08 s |
| QA-003 | 1.16 s | 1.28 s | +0.12 s |
| QA-005 | 3.90 s | 3.05 s | −0.85 s |

Cost tracks route count, as expected: routes are retrieved concurrently, so +4 routes costs roughly
one extra round-trip of the slowest route (rerank is over a larger merged pool). A single 19.1 s
first-run outlier appeared on a cold process and is excluded by using medians. Controls are flat
within measurement noise.

---

## 6. Regressions

**None observed.**

* No change to embedding, reranker, similarity threshold, vector weight, `final_top_n`,
  `knn_top_k`, chunking or any metadata schema — the diff touches route assembly only.
* No retrieval parameter is altered; the only parameter difference in the harness is
  `max_sub_queries`, applied identically to before and after so it is not a variable.
* The 4 other frozen benchmark questions and the narrow design-life question return identical
  route counts, identical life/structure counts, identical window-route counts and identical
  document diversity.
* Residual, already-characterised non-determinism: the reranker is not bit-deterministic
  (max |Δ| 0.0064 on identical input, from the QA-004 investigation), which shows up as a
  ±0–35 character context-length jitter on QA-001. It is not caused by this change and was
  present before it.
* Phase 0's synonym resource is untouched and still loaded; `寿命 → 年限` remains absent.

---

## 7. Files changed

| file | change |
|---|---|
| `rag/retrieval/route_expansion.py` | **new** — the deterministic two-axis rule |
| `rag/retrieval/pipeline.py` | modified — import, `ROUTE_BUDGET`, the expansion call after the plan, route-count logging |
| `tools/scripts/phase1_route_expansion_ab.py` | **new** — the controlled A/B harness |
| `docs/evaluation/rag_terminology_phase1.md` | **new** — this report |

Not modified: embedding code, `rag/retrieval/rerank.py`, `rag/retrieval/planner.py`,
`rag/retrieval/decomposition.py`, `rag/retrieval/multi_route.py`, `rag/retrieval/query_router.py`,
`rag/res/synonym.json`, any `api/` file, any frontend file, any Dockerfile.

---

## 8. Verdict

**Ready for a candidate build.** The rule is additive, bounded, vocabulary-free, declines cleanly on
five of six test questions, and turns a 0/3 design-life coverage into 3/3 with structure evidence
retained — including when the LLM decomposition channel is dead.

Carry-forward caveats for the candidate:

1. The change is verified on a **controlled path** (stub-pinned decomposition against the deployed
   stack). It has not been exercised end-to-end through the deployed entry point, because that
   requires an image containing the new module.
2. `AFTER_NO_LLM` is the strongest result and also the one to watch: it means the deterministic rule
   can carry the question alone. In production it will run *with* the LLM routes (2 or 4), i.e. the
   `CTRL_AFTER` and `CTRL_AFTER_llm4` rows — both 3/3.
3. The window now spends 3 of 12 slots on design-life passages that the structure half previously
   held. That is the intended trade and it did not reduce document diversity, but the structure half
   of the *answer* was thinner in one mode (`structure_drawings=False`), so a future phase may want
   to confirm the balance on the full benchmark rather than on this question alone.
