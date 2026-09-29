"""Is quota-driven deepening below the global score frontier intended, or an unintended consequence?

READ-ONLY. Frozen 45-chunk pool only. No retrieval, no product change, no parameter change.

The instrumented replica is VALIDATED against the real repaired `select_context` before any attribution
from it is used. It also records WHICH STEP took each passage (compared-document reservation / prose
floor / score fill), because that decides whether a below-frontier passage is pulled in by the fill or
by a reservation - the two contracts differ exactly there.
"""
import json
import math
import pathlib
import sys

sys.path.insert(0, "/ragflow")

from rag.retrieval import rerank
from rag.retrieval.rerank import DiversityPolicy, apply_rank_adjustments, select_context
from rag.retrieval.chunk_profile import document_key, is_hollow_table, is_table_chunk

POOL_FILE = pathlib.Path("/gates/trace_qgdw_now.json")
CONTROL, TARGET, TOP_N = "b5aaf72bcd33d44a", "d1d75672f2dbc333", 12

lines = []


def emit(t=""):
    lines.append(str(t))


def body(is_table):
    if is_table:
        return ("<table><caption>技术参数表</caption><tr><th>项目</th><th>值</th></tr><tr>"
                + "".join(f"<td>v{i}</td>" for i in range(5)) + "<td></td></tr></table>")
    return "条款正文：内衬层厚度应不小于 1.5mm。"


cap = json.loads(POOL_FILE.read_text(encoding="utf-8"))["trace"]["selection"][0]
rec = cap["policy"]
policy = DiversityPolicy(min_prose=rec["min_prose"], max_table_share=rec["max_table_share"],
                         table_penalty=rerank.TABLE_PENALTY,
                         max_auxiliary_document_share=rec["max_auxiliary_document_share"],
                         core_document_boost=rerank.CORE_DOCUMENT_BOOST,
                         core_documents=frozenset(rec["core_documents"]),
                         max_document_share=rec["max_document_share"],
                         compared_documents=frozenset(rec["compared_documents"]),
                         question_values=frozenset())

pre = sorted(cap["ordered_profile"], key=lambda e: (-e["similarity"], e["position"]))
pool = [{"chunk_id": e["chunk_id"], "doc_id": e["document_key"], "docnm_kwd": e["document_key"],
         "doc_type_kwd": "table" if e["is_table"] else "text",
         "content_with_weight": body(e["is_table"]), "similarity": e["similarity"],
         "retrieval_routes": []} for e in pre]

ordered = apply_rank_adjustments([dict(c) for c in pool], policy)
o_pos = {c["chunk_id"]: n for n, c in enumerate(ordered, 1)}
by_id = {c["chunk_id"]: c for c in ordered}


def replica(ordered, top_n, policy, fill_limit=None, reserve_limit=None):
    table_cap = top_n if policy.max_table_share >= 1.0 else min(top_n, math.ceil(top_n * policy.max_table_share))
    document_cap = 0 if policy.max_auxiliary_document_share >= 1.0 else max(1, min(top_n, math.ceil(top_n * policy.max_auxiliary_document_share)))
    every_document_cap = 0 if policy.max_document_share >= 1.0 else max(1, min(top_n, math.ceil(top_n * policy.max_document_share)))
    hollow_per_document_cap = max(1, min(top_n, math.ceil(top_n * rerank.MAX_HOLLOW_TABLE_PER_DOCUMENT_SHARE)))

    chosen, keys, table_count = [], set(), 0
    counts, hollow_counts, blocked, taken_by = {}, {}, {}, {}

    def bucket(c):
        return document_key(c) or f"chunk:{c['chunk_id']}"

    def doc_blocked(c):
        n = counts.get(bucket(c), 0)
        if every_document_cap and n >= every_document_cap:
            return "compared-document cap"
        if is_hollow_table(c) and hollow_counts.get(bucket(c), 0) >= hollow_per_document_cap:
            return "hollow cap"
        if document_cap and not policy.is_core_document(c) and n >= document_cap:
            return "auxiliary cap"
        return None

    def reason(c):
        if is_table_chunk(c) and table_count >= table_cap:
            return "table cap"
        return doc_blocked(c)

    def take(c, step, ignore_table_quota=False):
        nonlocal table_count
        if len(chosen) >= top_n or c["chunk_id"] in keys:
            return False
        if not ignore_table_quota:
            r = reason(c)
            if r:
                blocked.setdefault(c["chunk_id"], r)
                return False
        chosen.append(c["chunk_id"])
        keys.add(c["chunk_id"])
        taken_by[c["chunk_id"]] = step
        if is_table_chunk(c):
            table_count += 1
            if is_hollow_table(c):
                hollow_counts[bucket(c)] = hollow_counts.get(bucket(c), 0) + 1
        counts[bucket(c)] = counts.get(bucket(c), 0) + 1
        return True

    reserve_scope = ordered if reserve_limit is None else ordered[:reserve_limit]
    for key in [document_key(c) for c in reserve_scope if policy.is_compared_document(c)]:
        for c in [x for x in reserve_scope if document_key(x) == key]:
            if take(c, "compared-document reservation"):
                break
    if policy.min_prose > 0:
        taken = sum(1 for c in ordered if c["chunk_id"] in keys and not is_table_chunk(c))
        for c in ordered:
            if taken >= policy.min_prose or len(chosen) >= top_n:
                break
            if not is_table_chunk(c) and take(c, "prose floor"):
                taken += 1
    fill_scope = ordered if fill_limit is None else ordered[:fill_limit]
    table_only = not any(not is_table_chunk(c) for c in ordered)
    for c in fill_scope:
        if len(chosen) >= top_n:
            break
        take(c, "score fill", ignore_table_quota=table_only and is_table_chunk(c))
    return [c for c in ordered if c["chunk_id"] in keys], blocked, taken_by, table_cap


real = [c["chunk_id"] for c in select_context(ordered, TOP_N, policy)]
cur_chunks, blocked, taken_by, table_cap = replica(ordered, TOP_N, policy)
cur = [c["chunk_id"] for c in cur_chunks]
emit("=== VALIDATION ===")
emit(f"  REPLICA_MATCHES_REAL = {real == cur}   (window {len(real)} vs {len(cur)})")
emit()

sim_order = sorted(pool, key=lambda c: -c["similarity"])
pure_frontier = sim_order[TOP_N - 1]["similarity"]
pure_rank = {c["chunk_id"]: n for n, c in enumerate(sim_order, 1)}
emit("=== GLOBAL_SCORE_FRONTIER ===")
emit(f"  pure-score position 12 cutoff similarity = {pure_frontier:.6f}")
emit(f"  selection-order position 12 rank_score   = {ordered[TOP_N-1]['rank_score']:.6f}")
emit(f"  pool={len(ordered)} top_n={TOP_N} table_cap={table_cap} min_prose={policy.min_prose}")
emit()

emit("=== CURRENT (repaired) WINDOW: position, frontier, and TAKING STEP ===")
below = []
for cid in sorted(cur, key=lambda c: o_pos[c]):
    c = by_id[cid]
    is_below = pure_rank[cid] > TOP_N
    if is_below:
        below.append(cid)
    emit(f"  sel{o_pos[cid]:2d} pure{pure_rank[cid]:2d} sim={c['similarity']:.6f} {c['doc_type_kwd']:5s} "
         f"| {'BELOW-FRONTIER' if is_below else 'within-frontier '} | step={taken_by[cid]:26s} | {cid}")
emit(f"  deepest selection position = {max(o_pos[c] for c in cur)} of {len(ordered)}")
emit(f"  BELOW_FRONTIER_SELECTIONS = {len(below)}")
for cid in below:
    emit(f"    {cid}  pure_pos={pure_rank[cid]}  sim={by_id[cid]['similarity']:.6f}  taken_by={taken_by[cid]}")
emit()

emit("=== DEEPENING_CAUSE_BY_CHUNK (quota that skipped higher-scoring candidates) ===")
for cid in below:
    deep = o_pos[cid]
    skipped = {}
    for other in ordered:
        oid = other["chunk_id"]
        if o_pos[oid] >= deep or oid in cur:
            continue
        r = blocked.get(oid)
        if r:
            skipped.setdefault(r, []).append((o_pos[oid], other["similarity"]))
    emit(f"  {cid} (sel pos {deep}, pure pos {pure_rank[cid]}, taken_by={taken_by[cid]})")
    if not skipped:
        emit("     no higher-scoring candidate skipped by a quota")
    for r in sorted(skipped):
        rows = sorted(skipped[r])
        emit(f"     {r}: {len(rows)} skipped, highest sim {rows[0][1]:.6f} at pos {rows[0][0]}")
emit()

emit("=== EXISTING_DEEPENING_BOUND ===")
src = pathlib.Path("/ragflow/rag/retrieval/rerank.py").read_text(encoding="utf-8", errors="replace")
emit(f"  fill scope in code            : iterates `for chunk in ordered` (whole pool)")
emit(f"  termination                   : len(chosen) >= top_n")
emit(f"  deepest selection observed    : pos {max(o_pos[c] for c in cur)} of {len(ordered)}")
emit(f"  'threshold' appears in rerank.py : {'threshold' in src}")
emit(f"  any frontier/floor constant     : {'frontier' in src or 'SCORE_FLOOR' in src}")
emit()

for label, kwargs in (("B_fill_limited_only", {"fill_limit": TOP_N}),
                      ("B_strict_reservations_also_limited", {"fill_limit": TOP_N, "reserve_limit": TOP_N})):
    ch, bl, tb, _ = replica(ordered, TOP_N, policy, **kwargs)
    ids = [c["chunk_id"] for c in ch]
    tables = sum(1 for c in ids if by_id[c]["doc_type_kwd"] == "table")
    docs = {}
    for c in ids:
        docs[by_id[c]["doc_id"][:8]] = docs.get(by_id[c]["doc_id"][:8], 0) + 1
    emit(f"=== {label} ===")
    emit(f"  window={len(ids)} (top_n={TOP_N}) shortfall={TOP_N - len(ids)} "
         f"| {tables} tables / {len(ids) - tables} prose | deepest pos={max((o_pos[c] for c in ids), default=0)}")
    emit(f"  CONTROL selected={CONTROL in ids} (sel pos {o_pos[CONTROL]}, pure {pure_rank[CONTROL]})")
    emit(f"  TARGET  selected={TARGET in ids} (sel pos {o_pos[TARGET]}, pure {pure_rank[TARGET]})")
    emit(f"  compared-doc representation = {docs}")
    emit(f"  steps used = {sorted(set(tb[c] for c in ids))}")
    emit()

emit("=== CRITICAL_ACCEPTANCE ===")
emit(f"  CURRENT                     CONTROL={CONTROL in cur}  TARGET={TARGET in cur}")
for label, kwargs in (("B_fill_limited_only", {"fill_limit": TOP_N}),
                      ("B_strict", {"fill_limit": TOP_N, "reserve_limit": TOP_N})):
    ch, _, _, _ = replica(ordered, TOP_N, policy, **kwargs)
    ids = [c["chunk_id"] for c in ch]
    emit(f"  {label:27s} CONTROL={CONTROL in ids}  TARGET={TARGET in ids}")

print("\n".join(lines))
pathlib.Path("/tmp/qgdw_deepening_report.txt").write_text("\n".join(lines), encoding="utf-8")
