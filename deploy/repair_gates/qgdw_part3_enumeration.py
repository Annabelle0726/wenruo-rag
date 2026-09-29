"""Does the pinned Part 3 chunk hold the FULL Table 1 conductor enumeration, or one row-batch part?

Read-only. Queries only the Part 3 document's own chunks for the 3xNNNN section family and for siblings
of the same table, so THREE_CORE_VALUES can be stated from the corpus rather than from one part.
"""
import json
import re
import sys

sys.path.insert(0, "/ragflow")

from common import settings  # noqa: E402

settings.init_settings()

INDEX = "ragflow_a9e28731ab7011f19b833887d563fb04"
PART3_DOC = "f18db09cba1211f18bee33eac9b39c66"
TARGET = "d1d75672f2dbc333"

es = settings.docStoreConn.es
body = {"size": 200, "query": {"term": {"doc_id": PART3_DOC}}, "_source": ["content_with_weight", "doc_type_kwd"]}
res = es.search(index=INDEX, body=body)
hits = res["hits"]["hits"]
print(f"Part 3 doc chunks in index: {len(hits)} (returned {len(hits)})")

ALL3 = {}
for hit in hits:
    cid = hit["_id"]
    content = str((hit["_source"] or {}).get("content_with_weight") or "")
    text = " ".join(re.sub(r"<[^>]+>", " ", content).split())
    found = sorted({int(x) for x in re.findall(r"3\s*[×x]\s*(\d{3,4})", text)})
    for v in found:
        ALL3.setdefault(v, []).append(cid)
    if cid == TARGET:
        print(f"  TARGET part: sections={found}")

print()
print("=== 3xNNNN nominal sections found anywhere in the Part 3 document ===")
for v in sorted(ALL3):
    print(f"  3x{v}: held by {len(ALL3[v])} chunk(s); target holds it: {TARGET in ALL3[v]}")

union = sorted(ALL3)
print()
print(f"UNION section values  : {['3x%d' % v for v in union]}")
print(f"UNION count           : {len(union)}")
print(f"UNION min/max         : {union[0] if union else None} .. {union[-1] if union else None}")
print(f"TARGET-ONLY subset    : target holds {len([v for v in union if TARGET in ALL3[v]])} of {len(union)}")
missing = [v for v in union if TARGET not in ALL3[v]]
print(f"values NOT in target  : {missing}")
