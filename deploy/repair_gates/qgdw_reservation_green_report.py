"""Frozen-pool GREEN report for the reservation contract fix. Real product functions, no replica.

Reports window composition, per-document slots, CONTROL/TARGET outcome, the deepest ordered position
reached, and whether the score fill executed at all. Read-only; nothing asserted here (the gates assert).
"""
import json
import pathlib
import sys

sys.path.insert(0, "/ragflow")

from rag.retrieval import rerank
from rag.retrieval.rerank import DiversityPolicy, apply_rank_adjustments, select_context
from rag.retrieval.chunk_profile import document_key, is_table_chunk

POOL_FILE = pathlib.Path("/gates/trace_qgdw_now.json")
CONTROL, TARGET, TOP_N = "b5aaf72bcd33d44a", "d1d75672f2dbc333", 12


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
sim_order = sorted(pool, key=lambda c: -c["similarity"])
pure_rank = {c["chunk_id"]: n for n, c in enumerate(sim_order, 1)}
pure_frontier = sim_order[TOP_N - 1]["similarity"]

chosen = [c["chunk_id"] for c in select_context(ordered, TOP_N, policy)]
tables = sum(1 for c in chosen if is_table_chunk(by_id[c]))
counts, tables_by_doc = {}, {}
for c in chosen:
    d = document_key(by_id[c])
    counts[d] = counts.get(d, 0) + 1
    tables_by_doc[d] = tables_by_doc.get(d, 0) + (1 if is_table_chunk(by_id[c]) else 0)

print("=== FROZEN POOL, RESERVATION CONTRACT FIXED ===")
print(f"  compared documents       : {sorted(policy.compared_documents)}")
print(f"  window                   : {len(chosen)} (top_n={TOP_N}) | {tables} tables / {len(chosen)-tables} prose")
print(f"  table cap                : {min(TOP_N, -(-TOP_N * policy.max_table_share // 1))} (tables {tables})")
print(f"  prose floor              : {policy.min_prose} (prose {len(chosen)-tables})")
print(f"  deepest ordered position : {max(o_pos[c] for c in chosen)} of {len(ordered)}")
print(f"  pure-score frontier sim  : {pure_frontier:.6f}")
print(f"  slots per document       : {counts}")
print(f"  tables per document      : {tables_by_doc}")
print(f"  CONTROL {CONTROL}: ordered {o_pos[CONTROL]} pure {pure_rank[CONTROL]} selected={CONTROL in chosen}")
print(f"  TARGET  {TARGET}: ordered {o_pos[TARGET]} pure {pure_rank[TARGET]} selected={TARGET in chosen}")
below = [c for c in chosen if pure_rank[c] > TOP_N]
print(f"  below-frontier selections: {len(below)} -> {[(c, o_pos[c], round(by_id[c]['similarity'],6)) for c in below]}")
print("  chosen in ordered order:")
for c in sorted(chosen, key=lambda x: o_pos[x]):
    print(f"    sel{o_pos[c]:2d} {by_id[c]['doc_type_kwd']:5s} doc={document_key(by_id[c])[:8]} "
          f"sim={by_id[c]['similarity']:.6f} {c}")
print(f"  documents NOT compared that appear in the window: "
      f"{sorted(set(counts) - set(policy.compared_documents))}")
