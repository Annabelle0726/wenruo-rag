"""Do the two authoritative chunks carry the dense vector the knn leg searches? Read-only."""
import json
import sys

sys.path.insert(0, "/ragflow")

from common import settings  # noqa: E402

settings.init_settings()

INDEX = "ragflow_a9e28731ab7011f19b833887d563fb04"
TARGET, CONTROL = "d1d75672f2dbc333", "b5aaf72bcd33d44a"
VEC = "q_3072_vec"

es = settings.docStoreConn.es
for name, cid in (("TARGET (Part3)", TARGET), ("CONTROL(Part2)", CONTROL)):
    src = es.get(index=INDEX, id=cid)["_source"]
    vec = src.get(VEC)
    print(f"{name} {cid}")
    print(f"   has {VEC}          : {VEC in src}")
    print(f"   vector type/length : {type(vec).__name__} / {len(vec) if hasattr(vec, '__len__') else '-'}")
    print(f"   vector all-zero    : {bool(vec) and all(v == 0 for v in vec[:50]) if isinstance(vec, list) else 'n/a'}")
    print(f"   vector head        : {[round(float(v), 4) for v in vec[:5]] if isinstance(vec, list) else None}")
    print(f"   other vector fields: {sorted(k for k in src if 'vec' in k)}")
    print(f"   doc_id             : {src.get('doc_id')}")
    print()

# How many chunks in the KB carry the vector at all?
kb = "9463d93eb97511f1938f2592e9bc6fe4"
try:
    res = es.count(index=INDEX, body={"query": {"bool": {"filter": [
        {"terms": {"kb_id": [kb]}},
        {"exists": {"field": VEC}}]}}})
    with_vec = res["count"]
except Exception as exc:  # noqa: BLE001
    with_vec = f"error {type(exc).__name__}"
res = es.count(index=INDEX, body={"query": {"terms": {"kb_id": [kb]}}})
print(f"KB chunks total                : {res['count']}")
print(f"KB chunks with {VEC}      : {with_vec}")
part3 = es.count(index=INDEX, body={"query": {"bool": {"filter": [
    {"terms": {"doc_id": ["f18db09cba1211f18bee33eac9b39c66"]}}]}}})["count"]
part3v = es.count(index=INDEX, body={"query": {"bool": {"filter": [
    {"terms": {"doc_id": ["f18db09cba1211f18bee33eac9b39c66"]}},
    {"exists": {"field": VEC}}]}}})["count"]
part2 = es.count(index=INDEX, body={"query": {"bool": {"filter": [
    {"terms": {"doc_id": ["28668474ba1b11f1be9555eabe501d5b"]}}]}}})["count"]
part2v = es.count(index=INDEX, body={"query": {"bool": {"filter": [
    {"terms": {"doc_id": ["28668474ba1b11f1be9555eabe501d5b"]}},
    {"exists": {"field": VEC}}]}}})["count"]
print(f"Part 3 doc chunks / with vector: {part3} / {part3v}")
print(f"Part 2 doc chunks / with vector: {part2} / {part2v}")
