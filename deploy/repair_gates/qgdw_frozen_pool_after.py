"""Frozen-pool composition of the repaired pipeline, with the reason each excluded passage was passed over.

Reports the DEPLOYED (RED) and REPAIRED (GREEN) outcomes side by side on the frozen 45-chunk capture,
including how deep into the ordered pool the window had to reach and which rule excluded the rest. Run
against whichever `rerank.py` is mounted; nothing is asserted here - the gates assert.
"""
import json
import math
import pathlib
import sys

sys.path.insert(0, "/ragflow")

from rag.retrieval import rerank
from rag.retrieval.rerank import DiversityPolicy, apply_rank_adjustments, select_context

POOL = pathlib.Path("/gates/trace_qgdw_now.json")
CONTROL, TARGET, TOP_N, TABLE_CAP = "b5aaf72bcd33d44a", "d1d75672f2dbc333", 12, 6


def body(is_table):
    if is_table:
        return ("<table><caption>技术参数表</caption><tr><th>项目</th><th>值</th></tr><tr>"
                + "".join(f"<td>v{i}</td>" for i in range(5)) + "<td></td></tr></table>")
    return "条款正文：内衬层厚度应不小于 1.5mm。"


cap = json.loads(POOL.read_text(encoding="utf-8"))["trace"]["selection"][0]
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
         "doc_type_kwd": "table" if e["is_table"] else "text", "content_with_weight": body(e["is_table"]),
         "similarity": e["similarity"], "retrieval_routes": []} for e in pre]

ordered = apply_rank_adjustments([dict(c) for c in pool], policy)
pos = {c["chunk_id"]: n for n, c in enumerate(ordered, 1)}
chosen = [c["chunk_id"] for c in select_context(ordered, TOP_N, policy)]
by_id = {c["chunk_id"]: c for c in ordered}

print("TABLE_PENALTY =", rerank.TABLE_PENALTY, "| HOLLOW =", rerank.HOLLOW_TABLE_PENALTY,
      "| table_cap =", min(TOP_N, math.ceil(TOP_N * policy.max_table_share)))
print("window size:", len(chosen),
      "| tables:", sum(1 for i in chosen if by_id[i]["doc_type_kwd"] == "table"),
      "| prose:", sum(1 for i in chosen if by_id[i]["doc_type_kwd"] == "text"))
print("deepest chosen ordered position:", max(pos[i] for i in chosen))
print(f"CONTROL {CONTROL}: ordered_pos={pos[CONTROL]} selected={CONTROL in chosen}")
print(f"TARGET  {TARGET}: ordered_pos={pos[TARGET]} selected={TARGET in chosen}")
print("\nchosen (ordered position, type, similarity):")
for i in sorted(chosen, key=lambda c: pos[c]):
    c = by_id[i]
    print(f"   pos{pos[i]:2d} {c['doc_type_kwd']:5s} sim={c['similarity']:.6f} {i}")
print("\nexcluded tables that ranked above the deepest chosen position:")
deepest = max(pos[i] for i in chosen)
for c in ordered:
    if c["doc_type_kwd"] == "table" and c["chunk_id"] not in chosen and pos[c["chunk_id"]] < deepest:
        print(f"   pos{pos[c['chunk_id']]:2d} sim={c['similarity']:.6f} {c['chunk_id']}")
