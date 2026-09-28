# Stage-two attribution: rule-level causes for `d1d75672f2dbc333`

**Read-only. Nothing under `rag/` is modified, no threshold, window, top-k, `max_table_share`,
`min_prose`, `top_n` or reranker parameter is touched, and production, the index, the planner and the
P0 contract are unchanged.** Every number comes from wrapping the existing boundaries, reading the
policy's own constants, and arithmetic over the recorded pool — no retrieval was re-run with
different settings to produce a result.

Queries traced: the Q/GDW composite question plus **four** single-route control questions whose answer
fact lives principally in a table chunk.

---

## 1. `apply_rank_adjustments` attribution

### The target's complete ranking inputs

| input | value |
| --- | --- |
| base score (`similarity`, no reranker configured) | **0.30324606239931556** |
| `is_table_chunk` | **True** |
| `is_hollow_table` | False |
| `is_core_document` | **True** (第3部分 is in `core_documents`) |
| `is_compared_document` | True |
| `paired_values(chunk, question_values)` | **empty set — pairs nothing** |
| `carries_value(chunk, question_values)` | **True** |
| `question_values` | `['2026', '73286.2', '73286.3']` |

### Which adjustments fired, and the delta

```
rank_score = base * penalty * boost

penalty = TABLE_PENALTY(0.85) * VALUE_LIST_PENALTY(0.80)   = 0.68
boost   = CORE_DOCUMENT_BOOST(1.15)                         = 1.15

rank_score = 0.30324606239931556 * 0.68 * 1.15 = 0.23713842079626477
```

* **`TABLE_PENALTY` 0.85** — it is a table (×0.85)
* **`VALUE_LIST_PENALTY` 0.80** — it is a table that *carries* a question value (`73286.3`, from the
  standard's own designation) and pairs none (×0.80)
* **`CORE_DOCUMENT_BOOST` 1.15** — it belongs to the standard the question is about (×1.15)
* `HOLLOW_TABLE_PENALTY` did **not** fire (the table is filled)
* `VALUE_PAIRING_BOOST` did **not** fire (it pairs nothing)

### The delta

| | |
| --- | --- |
| order | **rank 28 → rank 45 — 17 places down** |
| score | 0.30324606239931556 → 0.23713842079626477 — **×0.782, −21.8 %** |

### Candidates that overtook it *because of* the adjustment

**18 chunks moved from behind the target to ahead of it.** Six of them have a **lower** raw similarity
and overtook it purely through multiplier asymmetry:

| adjusted # | chunk | type | similarity | vs target | penalty | boost | raw inversion |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 15 | `66f462a9de91e03c` | prose | 0.228520 | **−0.074726** | 1.00 | **1.495** | +0.1045 |
| 18 | `bc2a6dfa54206eab` | prose | 0.221808 | **−0.081438** | 1.00 | **1.495** | +0.0945 |
| 20 | `0b4e3c1a73c1e334` | prose | 0.210616 | **−0.092630** | 1.00 | **1.495** | +0.0777 |
| 16 | `8065ad3f4096ca30` | prose | 0.297047 | −0.006199 | 1.00 | 1.150 | +0.1045 |
| 17 | `d79d92725b46b084` | prose | 0.295510 | −0.007737 | 1.00 | 1.150 | +0.1025 |
| 19 | `9fa9e164a3e3ca7a` | prose | 0.287356 | −0.015890 | 1.00 | 1.150 | +0.0933 |

The `1.495` boost is `CORE_DOCUMENT_BOOST × VALUE_PAIRING_BOOST` (1.15 × 1.3): prose that happens to
place the question's own designation/year (`2026`, `73286.2`) beside a number is treated as "pairing a
section with a result" and raised 30 %, while the table is lowered 32 % for carrying the same
designation without pairing it. **The widest inversion is 0.0926 of raw similarity** — a prose passage
scoring 23 % below the target ends up 33 % above it in ordering value.

Note `8065ad3f4096ca30`: it is **prose from the target's own document** (第3部分) at a *lower* score,
and it overtakes the target. The document is not under-represented; its prose is preferred over its
table.

---

## 2. Route-local evidence preservation attribution

### The merge rule, named

`multi_route._merge_degraded_routes` (the degraded path in force) uses:

* **`winner = max(rows, key=lexical_selection_score)`** — the merged record's `similarity` is the
  **maximum lexical score across the routes that admitted the chunk**;
* **route membership as metadata** — `retrieval_routes` is the union of route queries, `route_hits` the
  count;
* **a single global lexical scale** — the records are then sorted by that one score.

**It is a max-score rule. Route-local rank is not an input at all**, and no route-local normalisation
exists. Route *coverage* is preserved (which routes touched the chunk), but route *strength* is not.

### The strength that was lost, measured

| | |
| --- | --- |
| target's best ES rank | 13 (route `Q/GDW 73286.3-2026 标准表 1 三芯…`) |
| target's best **route-page rank** | **4 of 20** |
| merged rank | 28 of 58 |
| adjusted rank | 45 |
| final context | not chosen |

**30 chunks with a *worse* route-local rank than the target's rank 4 hold a better adjusted rank.**
Measured examples:

| adjusted # | chunk | its route-page rank | type | similarity |
| --- | --- | --- | --- | --- |
| 5 | `3fb0a03b92cc70d7` | **5** | prose | 0.382949 |
| 6 | `d5f07f5d24ec3cc7` | **11** | prose | 0.363957 |
| 12 | `646ab90775aa14a5` | **17** | prose | 0.337258 |
| **20** | `0b4e3c1a73c1e334` | **20** | prose | 0.210616 |
| **45** | `d1d75672f2dbc333` | **4** | TABLE | 0.303246 |

A passage ranked **20th** in its own route ends up 25 places ahead of one ranked **4th** in its route.
The scores are not comparable across routes, and the data proves it: the same chunk
`ea4a0fbc49651bc5` scores **0.328464** as the top of the 三芯 route and **0.327141** as the top of the
original question's route, and the target's own route tops out at 0.3285 while another route's page
reaches 0.404.

### The structural phenomenon

> **`strong evidence in a highly-specific route → weak global evidence after merge` — CONFIRMED.**

The route that ranked the target 4th is precisely the question's 三芯 half
(`Q/GDW 73286.3-2026 标准表 1 三芯…内衬层…覆盖范围是多少？`). Locally the target is the **second-best
table and fourth-best passage** of that route. Globally, after the max-score merge, it is background.

One further instance of the same rule: `select_context` **step 1 does reserve one slot per route**, but
it hands the slot to *the first passage in the global order* that carries that route — not to the
passage that ranks best *within* the route. So the 三芯 route's reserved seat went to a
higher-globally-scoring passage of the same route, and the target never became that route's
representative. Route-local rank is discarded twice.

---

## 3. Context table-policy attribution

### The chosen 12 (incident composite)

| cut order | chunk | type | similarity | rank_score | routes | document |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `8daa8e50dcd8e921` | prose | 0.404372 | 0.465028 | 4 | 第2部分 单芯专用 |
| 2 | `ea4a0fbc49651bc5` | prose | 0.401644 | 0.461890 | 8 | 第1部分 通用 |
| 3 | `bac8e77cef90c8cf` | prose | 0.400708 | 0.460815 | 5 | 第1部分 通用 |
| 4 | `d8277d37a03a2b0a` | prose | 0.391454 | 0.450172 | 1 | 第2部分 单芯专用 |
| 5 | `3fb0a03b92cc70d7` | prose | 0.382949 | 0.440391 | 4 | 第2部分 单芯专用 |
| 6 | `d5f07f5d24ec3cc7` | prose | 0.363957 | 0.418550 | 2 | 第2部分 单芯专用 |
| 7 | `f224470a51f32350` | prose | 0.363416 | 0.417928 | 1 | 第2部分 单芯专用 |
| 8 | `43e96b415797394b` | prose | 0.353294 | 0.406288 | 5 | 第2部分 单芯专用 |
| 10 | `f6bf347f95c33598` | prose | 0.344095 | 0.395709 | 3 | 第1部分 通用 |
| 11 | `af74d2eeaaf2c4a4` | prose | 0.341131 | 0.392301 | 7 | 第1部分 通用 |
| 13 | `c7347587e61a3532` | prose | 0.320457 | 0.368525 | 3 | 第3部分 三芯专用 |
| 14 | `663de80696a67296` | prose | 0.314986 | 0.362234 | 5 | 第1部分 通用 |

**12 of 12 are prose; 0 are tables.** Positions 9 and 12 were skipped — both 第2部分 prose blocked by
the compared-document quota (`every_document_cap = ceil(12 × 0.5) = 6`, already saturated) — and the
two freed slots went to **more prose**, because the table pass had not started.

### Tables that outscore the weakest chosen prose but were not chosen

**11 candidates**, all excluded:

| chunk | similarity | gap over weakest chosen prose (0.314986) |
| --- | --- | --- |
| `255c187f4e228542` | 0.398047 | **+0.08306** |
| `423069af31359e65` | 0.397656 | +0.082669 |
| `ab96130b7a5d5c8f` | 0.382408 | +0.067421 |
| `b5aaf72bcd33d44a` | 0.375481 | +0.060495 |
| `41f10551fa1033e5` | 0.366861 | +0.051874 |
| `4bf3ddbeb9a17ec0` | 0.366861 | +0.051874 |
| `a14eb97907268118` | 0.353294 | +0.038308 |
| `d243b62eda461615` | 0.350852 | +0.035865 |
| (+ 3 more, down to +0.02062) | | |

### Pure-score Top-12 — the operator's counterfactual, answered

Strictly by selection score with the type axis removed (`table_penalty = 1`, no prose-first walk), the
window would be **6 tables and 6 prose**:

```
#1  prose 0.404372   #2  prose 0.401644   #3  prose 0.400708
#4  TABLE 0.398047   #5  TABLE 0.397656   #6  prose 0.391454
#7  prose 0.382949   #8  TABLE 0.382408   #9  TABLE 0.375481
#10 TABLE 0.366861   #11 TABLE 0.366861   #12 prose 0.363957
```

* **Six tables would be seated** — including the control `b5aaf72bcd33d44a` at #9.
* **The target would NOT be seated**: it is 28th by raw similarity, 16 places below where any 12-slot
  window ends; its position under the pure-score ordering is 28 either way (`table_penalty` removed or
  not — it is one of the last tables, not the first).

So the table policy is **material to the loss of table evidence in general (six slots' worth) and not
material to this chunk**, which is consistent with stage one's counterfactual.

---

## 4. Generality check

The same chunk, and the same pipeline, across five questions:

| query | routes | pool tables | tables chosen | target similarity | target route-page rank | target adjusted rank | target chosen |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **INCIDENT_COMPOSITE** | 8 | 22 | **0** | 0.303246 | 4 | 45 | **no** |
| TABLE_SINGLE_PART2 | 1 | 10 | 5 | not in pool | — | — | — |
| TABLE_THREE_PART3 | 1 | 12 | **4** | **0.268895** | **2** | **6** | **YES** |
| TABLE_STRUCTURE | 1 | 11 | 5 | 0.221531 | 19 | 18 | no |
| TABLE_VALUE_LOOKUP | 1 | 20 | **12** | 0.226634 | 5 | 2 | **YES** |

**The decisive control:** on the single-route question that names its own part, the target is recalled
at route rank **2**, ordered to rank **6**, and **seated in the context** — at a similarity of
**0.268895**, *lower* than the 0.303246 it scored on the composite question where it was dropped.

**Table evidence is not systematically excluded.** Table-fact questions seat 4, 5, 5 and 12 tables of
their 12 slots. The policy that defers tables activates only on the composite question, because
`seeks_clause` matches the word **规定** in it and that branch sets `min_prose=4,
max_table_share=0.5, table_penalty=0.85`. Every single-route control keeps `max_table_share=1.0,
table_penalty=1.0, min_prose=0` and therefore takes a plain top-N.

**"High-score table crowded out by low-score prose" does occur elsewhere, but far more mildly:** 3
inversions on `TABLE_SINGLE_PART2`, 6 on `TABLE_THREE_PART3`, 0 on the other two, against **11** on the
composite question. Those smaller inversions come from the family-batch and document quotas, not from
the table deferral.

---

## Outputs

### `PRIMARY_DROP_MECHANISM`

**Multi-route evidence preservation (B), amplified by the ordering pass (C) and then filtered by the
context table policy (D) — i.e. E, with B as the root.** Not A: the chunk is not badly scored, as the
single-route control proves (0.2689 seated there, 0.3032 dropped here). The composite question merges
**8 routes onto one global lexical scale**, so a passage that is the *4th-best of the sub-question it
answers* becomes the *28th-best of the whole question*; the merge keeps only the maximum score and
discards route-local rank, and `select_context`'s per-route reservation then hands the route's seat to
a different passage of the same route.

### `APPLY_RANK_ADJUSTMENT_DELTA`

**−17 places (28 → 45).** Score 0.30324606239931556 → 0.23713842079626477 = **×0.782 (−21.8 %)**,
from `TABLE_PENALTY(0.85) × VALUE_LIST_PENALTY(0.80) × CORE_DOCUMENT_BOOST(1.15) = 0.782`. **18
candidates overtook it**, six of them with lower raw similarity, the widest inversion being **0.0926**
(`0b4e3c1a73c1e334`, 0.2106, ×1.495, ends at #20 against the target's #45). The asymmetry is
`0.68` for the table against `1.15`/`1.495` for prose.

### `ROUTE_LOCAL_STRENGTH_LOST`

**YES.** Route-page rank **4** (ES rank 13) in the route that names its own half of the question →
merged rank **28** → adjusted **45** → not chosen. The merge rule is **max score with route membership
as metadata**; route-local rank is used nowhere, and route-local normalisation does not exist.
**30 chunks with a worse route-local rank hold a better adjusted rank** — a passage ranked 20th in its
own route finishes 25 places ahead of one ranked 4th in its route.

### `TABLE_POLICY_MATERIAL_TO_DROP`

**Material for table evidence as a class; not material for this chunk.** The clause-intent branch
(`seeks_clause` matched 规定) sets `max_table_share=0.5` ⇒ `table_cap=6 < top_n=12`, so
`select_context` walks all non-table passages first and the 12 slots closed at walked position 14 —
before the table pass began. **0 tables were seated while 11 tables outscored the weakest admitted
prose** (up to +0.08306). The table cap of 6 was never binding.

### `PURE_SCORE_TOP12_COUNTERFACTUAL`

By selection score with the type axis removed: **6 tables / 6 prose**. Seated tables would be
`255c187f4e228542` (0.398047), `423069af31359e65` (0.397656), `ab96130b7a5d5c8f` (0.382408), the
control `b5aaf72bcd33d44a` (0.375481), `41f10551fa1033e5` and `4bf3ddbeb9a17ec0` (0.366861 each).
**The target is not among them** — 28th of 58 either way, 16 places below the cut.

### `GENERALITY_CHECK`

Five questions, the same pipeline and the same chunk. Table evidence is celebrated where the question
is a table lookup (4–12 tables seated) and absent only on the composite question (0 of 22).
`d1d75672f2dbc333` is **seated on 2 of 4 single-route controls**, including the one naming its own
part, where it is seated at a **lower** similarity than the composite run that dropped it. Score
inversions: 11 composite, 6, 3, 0, 0 elsewhere.

### `SYSTEMIC_OR_QUERY_SPECIFIC`

**SYSTEMIC, CONDITIONED ON QUESTION SHAPE.** Not "this chunk scores badly" (the control refutes A) and
not "tables are ignored" (the controls refute D alone). It is a property of the composite branch: the
question-shape classifier routes a composite question onto a policy set (`min_prose`, `max_table_share`,
`table_penalty`) that (i) merges 8 route-local score scales into one, (ii) penalises tables 0.68 while
boosting prose up to 1.495, and (iii) defers every table behind every prose passage — so any composite
question whose answer is table-borne loses its table evidence. It reproduced on the incident question
by construction, and the single-route controls show the branch is the difference.

### `RECOMMENDED_FIX_LAYER`

Attribution only — no fix is implemented, and the ordering below names the *layer* each candidate
belongs to. No fusion algorithm is proposed.

1. **Rule-input layer — narrowest and best-evidenced.** `policy.question_values` degenerates to the
   standard's own identity tokens (`['2026', '73286.2', '73286.3']`) for a question that names a
   standard. That single input both fires `VALUE_PAIRING_BOOST` (×1.3) on prose that merely places
   `2026` beside a number — producing 5 of the 6 lower-score overtakers — and `VALUE_LIST_PENALTY`
   (×0.8) on the target for carrying the same designation without pairing it. Fixing *what counts as a
   question figure* changes both multipliers without touching any frozen parameter.
2. **Selection-policy layer.** The `seeks_clause` branch's table deferral is what removes table
   evidence wholesale on composite questions. A table-evidence reservation (the shape `min_prose`
   already uses) or a rule that a table outscoring an admitted passage cannot be excluded, would seat
   the six tables the counterfactual names. This is a *policy* decision with a measured cost and needs
   its own authorisation and recall evidence.
3. **Merge layer — identified, not proposed.** The max-score-only merge and the global-order route
   reservation are where route-local strength dies. Any change here is a new fusion algorithm, which
   this window explicitly excludes.
4. **Recall layer — do this first.** The 0.30325 is a pure lexical score with **no dense component**.
   The whole certificate is a degraded-mode fact; the target's rank on the healthy path is unmeasured,
   and on the healthy path it would carry a vector similarity. Re-measure when G4 unblocks before
   designing anything.

---

## Artifacts

* probe (observation only): `deploy/repair_gates/attribution_matrix.py`
* recorded matrix: `deploy/repair_gates/attribution_matrix_result.json`
* `git diff -- rag/` is empty for this window; no parameter, index, planner or P0 artefact was touched.
