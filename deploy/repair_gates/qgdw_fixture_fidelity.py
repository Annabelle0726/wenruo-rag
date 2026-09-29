"""Fidelity probe for the gate fixture: does the DEPLOYED adjustment pass, driven from the
pre-adjustment (similarity) order, reproduce the CAPTURED deployed order?

If yes, the gate can derive the order symmetrically. If no, the gate must feed the captured order for
the RED arm (the capture IS the deployed code's output) and derive only the GREEN arm, and the gap must
be stated rather than hidden.

Synthetic bodies only; no retrieval, no ES.
"""
import json
import pathlib
import sys

sys.path.insert(0, "/ragflow")

from rag.retrieval.rerank import DiversityPolicy, apply_rank_adjustments, select_context
from rag.retrieval import rerank

POOL = pathlib.Path("/gates/trace_qgdw_now.json")
CONTROL, TARGET, TOP_N = "b5aaf72bcd33d44a", "d1d75672f2dbc333", 12


def table_body(filled, empty):
    return ("<table><caption>表1 电缆结构技术参数表</caption><tr><th>项目</th><th>值</th></tr><tr>"
            + "".join(f"<td>v{i}</td>" for i in range(filled))
            + "".join("<td></td>" for _ in range(empty)) + "</tr></table>")


def mk(cid, doc, sim, is_table):
    if is_table:
        body = table_body(5, 1)
        dt = "table"
    else:
        body = f"条款正文 {cid}：内衬层厚度应不小于 1.5mm。"
        dt = "text"
    return {"chunk_id": cid, "doc_id": doc, "docnm_kwd": doc, "doc_type_kwd": dt,
            "content_with_weight": body, "similarity": sim, "retrieval_routes": []}


cap = json.loads(POOL.read_text(encoding="utf-8"))["trace"]["selection"][0]
recorded = cap["policy"]
policy = DiversityPolicy(min_prose=recorded["min_prose"], max_table_share=recorded["max_table_share"],
                         table_penalty=rerank.TABLE_PENALTY,
                         max_auxiliary_document_share=recorded["max_auxiliary_document_share"],
                         core_document_boost=rerank.CORE_DOCUMENT_BOOST,
                         core_documents=frozenset(recorded["core_documents"]),
                         max_document_share=recorded["max_document_share"],
                         compared_documents=frozenset(recorded["compared_documents"]),
                         question_values=frozenset())

captured_order = [e["chunk_id"] for e in sorted(cap["ordered_profile"], key=lambda e: e["position"])]
sim_order = [e["chunk_id"] for e in sorted(cap["ordered_profile"], key=lambda e: (-e["similarity"], e["position"]))]
pool_by_id = {e["chunk_id"]: mk(e["chunk_id"], e["document_key"], e["similarity"], e["is_table"])
              for e in cap["ordered_profile"]}

derived = [c["chunk_id"] for c in apply_rank_adjustments([pool_by_id[i] for i in sim_order], policy)]
matched = sum(1 for a, b in zip(captured_order, derived) if a == b)
print("captured_order == derived_order :", captured_order == derived)
print("positional agreement            :", matched, "/", len(captured_order))
first_gap = next((n for n, (a, b) in enumerate(zip(captured_order, derived), 1) if a != b), None)
print("first differing position        :", first_gap)
if first_gap:
    print("  captured:", captured_order[first_gap - 1:first_gap + 3])
    print("  derived :", derived[first_gap - 1:first_gap + 3])

for label, ordered in (("CAPTURED_ORDER", captured_order), ("DERIVED_ORDER", derived)):
    ids = [c["chunk_id"] for c in select_context([pool_by_id[i] for i in ordered], TOP_N, policy)]
    tables = sum(1 for i in ids if pool_by_id[i]["doc_type_kwd"] == "table")
    print(f"{label}: chosen={len(ids)} tables={tables} prose={len(ids)-tables} "
          f"control_selected={CONTROL in ids} target_selected={TARGET in ids}")
