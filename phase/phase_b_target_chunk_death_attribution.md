# Post-retrieval attribution: exact cause of death for the three-core target chunk

**Tracing only. No retrieval, reranking, threshold, window or reranker parameter was modified.** Every
fact below comes from wrapping an existing boundary and observing what it received and returned; the
run uses the production assistant's own configuration (`similarity_threshold=0.55`,
`vector_similarity_weight=0.5`, `final_top_n=12`, `knn_top_k=1024`, no reranker). The single-core
chunk stays exactly where it was — rank 38, outside the window — and was not moved.

---

## The trace, stage by stage

The pipeline was instrumented at seven boundaries in the order it runs them: `dataStore.search` (raw
ES window) → `Dealer.search` → `Dealer.retrieval` (the route's returned page) → `_retrieve_route` →
`merge_route_hits` → `apply_rank_adjustments` / `rerank_chunks` → `select_context`.

### 1. ES raw rank — confirmed

Eight routes, eight real ES requests, every one `MatchTextExpr` only (degraded lexical mode), each
with a 64-candidate window.

| route (as the router/decomposer built it) | target rank in the 64 window | control rank |
| --- | --- | --- |
| `Q/GDW 73286.3-2026 标准表 1 三芯…` | **13** | 21 |
| **the user's original question** | **28** | **38** |
| `Q/GDW 73286.2-2026 标准表 1 单芯…` | 57 | 11 |
| the other five routes | absent from the 64 window | 55, 56, absent… |

**`d1d75672f2dbc333` is at lexical rank 28 in the original question's window — confirmed** — and the
control `b5aaf72bcd33d44a` is at rank 38, also confirmed.

### 2. Route admission — which routes admitted it

Each route returns `page_size = 20` of its 64 candidates (the query router widens the window for a
numeric question: `NUMERIC_TOP_K = 20`, above the pipeline's 12 default).

* **Admitted by 2 of 8 routes:** the `Q/GDW 73286.3-2026 … 三芯` route at **page rank 4**, and the
  original question's route at **page rank 16**.
* Not admitted by the other six: five never had it in their ES window, and the `…单芯` route had it
  at ES rank 57, i.e. outside its 20-passage page.

### 3. Degraded lexical score, per route

| route | target score | kind | control score |
| --- | --- | --- | --- |
| `Q/GDW 73286.3-2026 … 三芯` | **0.30324606239931556** | `lexical` | 0.26294170293786534 |
| the original question | **0.26827248907889417** | `lexical` | 0.27035347737320764 |

Both are pure lexical scores (`score_kind = "lexical"`, mode `LEXICAL_DEGRADED`) — in degraded mode
there is no dense component to average in, so these are the whole score.

### 4. Per-route Top-K pruning — yes, in one route, but not the deciding one

It **is** pruned inside the `…单芯` route (ES rank 57 > the 20-passage page), and it never entered five
others at all. It is **not** pruned in the two routes that admitted it: page ranks 4 and 16 are both
inside 20. So per-route pruning cost it coverage, not its life.

### 5. Merge and de-duplication — it survived, at merged rank 28

Merged pool 58 passages; the target is present at **merged rank 28** carrying its best route score
(0.30324606239931556) with `selection_trace.policy = LEXICAL_COMMON_SCALE`. Nothing covered it,
nothing de-duplicated it away.

### 6. Reranker score and position — there is no reranker

`rerank_mdl` is `None` on this deployment (`dialog_row.rerank_id` is empty), so no reranker score and
no reranker ranking exist. The ordering actually used is `apply_rank_adjustments(pool, policy)`, and
that is where the target **loses 17 places**:

```
apply_rank_adjustments: in 58 -> out 58
   target  merged rank 28  ->  cut-order rank 45
   control merged rank  9  ->  cut-order rank 29
```

The demotion is the table penalty meeting the standards' core-document boost; it widens the target's
distance from any slot but, as the counterfactual below shows, it is not what decides the outcome.

### 7. Context selection — this is where it dies

```
select_context(ordered=58, top_n=12)  ->  chose 12
   walked positions used: 1..14     (the walk stops the moment 12 slots are full)
   first TABLE candidate in the pool: position 21
   chosen with tables: 0 of 12      pool holds 22 tables and 36 prose passages
   target: position 45, is_table=True  -> never reached
```

**It is not a token-length cut.** `select_context` has no notion of tokens; the window is exactly 12
slots and it was filled. Token budgeting happens later, in the answer layer's prompt assembly.

---

## The score arithmetic that decides it

| quantity | value |
| --- | --- |
| target score | **0.30324606239931556** |
| weakest passage the cut DID admit | 0.31498632925714515 (position 14) |
| 12th score under a pure score ordering | 0.3639565407619422 |
| target rank under a pure score ordering | **28 of 58** |
| strongest candidate the cut did NOT admit | 0.398046817551371 (a table, position 21) |

**Counterfactual (computed, never consumed by the pipeline):** the identical cut with
`max_table_share=1.0`, which makes `table_cap == top_n` and therefore takes the plain top-N branch
instead of deferring every table behind every prose passage —

```
{"policy": "max_table_share=1.0 (table deferral disabled)",
 "chosen_size": 12, "target_chosen": false, "control_chosen": false}
```

**The table deferral is not what kills it.** With the deferral lifted the target is still cut, because
its score is 16 places below where any 12-slot window would end.

---

## Verdicts

### `TRACER_CHUNK_ID: d1d75672f2dbc333`

### `FIRST_DROPPED_STAGE: 上下文截断 (Context Selection — select_context's 12-slot cut)`

Not single-route pruning (admitted by 2 of 8 routes, at page ranks 4 and 16), not merge/de-duplication
(survived at merged rank 28), not the reranker (none is configured), and not a token limit
(`select_context` considers no tokens at all).

### `DROP_REASON_DETAIL`

The window is 12 slots and the target's degraded lexical score, **0.30325**, ranks **28th of the 58
merged candidates**. The 12th slot costs **0.36396** under a pure score ordering — and even under the
actual diversity policy, whose reservations let a weaker passage in, the weakest admitted passage
still scores **0.31499**. The target is below every slot on score alone, by **+0.0117** against the
policy cut and 16 places against a score cut; the counterfactual confirms that disabling the table
deferral does not recover it.

One rule makes the death *silent* rather than *ordered*, and it is worth naming separately because it
affects other chunks more than this one: `select_context` step 3 runs the branch
`if table_cap < top_n:` (here `max_table_share = 0.5` ⇒ `table_cap = 6 < 12`), which **walks every
non-table passage first and only then starts on tables**. With 36 prose candidates against 12 slots,
the window closed at walked position 14 — before the table pass began — so the target was never even
compared. The table cap of 6 was never the binding constraint: **zero** tables were chosen.
Consequently **eight table candidates outscoring the weakest admitted prose passage (0.39805, 0.39766,
0.38241, 0.37548, 0.36686, 0.35329, 0.35085, 0.35085) were all dropped**, which is a pool-level
observation, not just this chunk's.

### `NEXT_RECOVER_RECOMMENDATION`

Ordered by what the measurements actually support, and explicitly **not** a tuning proposal:

1. **Treat this certificate as a DEGRADED-MODE fact and re-measure it when G4 unblocks.** The 0.30325
   is a pure lexical score with no dense component. On the healthy path the same passage also carries
   a vector similarity and its rank is unmeasured — so before any change is designed, the rank must be
   re-taken with the dense leg healthy. Recommending a retrieval change off a degraded-mode rank would
   be tuning to a state that is itself a provider outage.
2. **If the product rule is "normative table evidence must be represented", fix that as a POLICY
   decision with its measured cost, not as a parameter nudge.** The measurement is that the window
   admits 12 prose passages and 0 tables while 8 table candidates outscore its weakest member. A
   reserved table slot (the same mechanism `min_prose` already uses for prose, and step 1b already uses
   for compared documents) is the targeted shape; the operator's Top-30/0.55/reranker freeze is
   untouched by it, and it needs its own authorisation and its own recall-neutrality evidence.
3. **Raise the target's own score by improving route recall at build time, not by widening anything.**
   The route that ranked it 4th — `Q/GDW 73286.3-2026 标准表 1 三芯…` — is the shape that works: it
   names the standard part designation and the table. The deterministic route builder already has a
   designation-anchored route and a value-pairing helper; extending the profiler vocabulary under a
   bumped version to emit a designation + table-caption route is the versioned, reviewable path this
   project uses, and it addresses the score, which is what actually kills the chunk.
4. **Do not** widen `final_top_n`, lower the 0.55 threshold, or touch the reranker: the first is a
   window change this window forbids (and would need ~28 slots for this chunk), the threshold does not
   apply in degraded mode at all, and there is no reranker configured to change.
5. **The control behaved correctly and must stay out.** `b5aaf72bcd33d44a` is at ES rank 38, died at
   the same stage for the same reason (table, merged rank 9 → cut-order 29 → not chosen), and on the
   control question that names it, it survives as the first returned passage. That contrast — same
   chunk, in window for its own question and out of window for the composite one — is preserved.

---

## Artifacts

* tracer: `deploy/repair_gates/trace_target_chunk.py` (observation only)
* raw trace: `deploy/repair_gates/target_chunk_trace_result.json`
* renderer: the summary above is produced from that JSON; no pipeline code was touched, and
  `git diff` over `rag/` is empty for this window.
