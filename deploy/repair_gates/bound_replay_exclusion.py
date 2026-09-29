"""Which rule excluded the target from the bound replay's select_context output? Read-only.

Takes the ordered pool captured in the bound replay (B3), resolves each passage's document, and reports
the target's position WITHIN its own compared document's ordering together with the quota arithmetic that
applies, so the exclusion is attributed to a named rule rather than to a count.
"""
import collections
import json
import math
import pathlib
import sys

sys.path.insert(0, "/ragflow")

from common import settings

settings.init_settings()

INDEX = "ragflow_a9e28731ab7011f19b833887d563fb04"
TARGET, CONTROL = "d1d75672f2dbc333", "b5aaf72bcd33d44a"
PART2, PART3 = "28668474ba1b11f1be9555eabe501d5b", "f18db09cba1211f18bee33eac9b39c66"

d = json.loads(pathlib.Path("/tmp/agentic_bound_replay.json").read_text(encoding="utf-8"))
ordered = d["boundaries"]["B3_ordered_pool"]["calls"][0]["ids"]
selected = d["boundaries"]["B4_select_context"]["calls"][0]["ids"]
policy = d["policy"]
top_n = d["runtime"]["final_top_n"]

es = settings.docStoreConn.es
docs = {}
for cid in ordered:
    try:
        docs[cid] = str(es.get(index=INDEX, id=cid)["_source"].get("doc_id") or "")
    except Exception:  # noqa: BLE001
        docs[cid] = "?"

p3 = [c for c in ordered if docs.get(c) == PART3]
p2 = [c for c in ordered if docs.get(c) == PART2]
cap = math.ceil(top_n * policy["max_document_share"])
table_cap = math.ceil(top_n * policy["max_table_share"])

print(f"ordered pool      : {len(ordered)}  (Part 3: {len(p3)}, Part 2: {len(p2)})")
print(f"select_context out: {len(selected)}")
print(f"quotas            : every_document_cap=ceil({top_n}x{policy['max_document_share']})={cap}"
      f"  table_cap=ceil({top_n}x{policy['max_table_share']})={table_cap}"
      f"  min_prose={policy['min_prose']}")
print(f"compared docs     : {[x[:8] for x in policy['compared_documents']]}")
print()
print("ordered pool with document (position | id | doc):")
for n, cid in enumerate(ordered, 1):
    tag = ""
    if cid == TARGET:
        tag = "   <<<< TARGET"
    if cid == CONTROL:
        tag = "   <<<< CONTROL"
    sel = "SELECTED" if cid in selected else "        "
    print(f"  {n:2d} {sel} {cid} {docs.get(cid,'?')[:8]}{tag}")
print()
print(f"TARGET overall position      : {(ordered.index(TARGET)+1) if TARGET in ordered else None}")
print(f"TARGET position WITHIN Part 3: {(p3.index(TARGET)+1) if TARGET in p3 else 'not in Part 3'}"
      f"   (Part 3 got {sum(1 for c in selected if docs.get(c) == PART3)} slots)")
print(f"CONTROL position WITHIN Part 2: {(p2.index(CONTROL)+1) if CONTROL in p2 else 'not in Part 2'}"
      f"   (Part 2 got {sum(1 for c in selected if docs.get(c) == PART2)} slots)")
print()
sel_docs = collections.Counter(docs.get(c, "?")[:8] for c in selected)
print("selected per document:", dict(sel_docs))
