"""Post-metadata-repair rank of the authoritative chunks, under the NEW scope.

Re-uses the route clauses already captured from the live request (the metadata repair changes the SCOPE,
not the query clauses) and applies the scope the repaired filter now produces:
doc_id in {Part 2, Part 3}, set at BOTH filter sites. Measured at size 300 so a rank below 30 is visible.
"""
import copy
import json
import pathlib
import sys

sys.path.insert(0, "/ragflow")

from common import settings  # noqa: E402

settings.init_settings()

INDEX = "ragflow_a9e28731ab7011f19b833887d563fb04"
TARGET, CONTROL = "d1d75672f2dbc333", "b5aaf72bcd33d44a"
PART2, PART3 = "28668474ba1b11f1be9555eabe501d5b", "f18db09cba1211f18bee33eac9b39c66"
NEW_SCOPE = [PART2, PART3]
BIG = 300
es = settings.docStoreConn.es

calls = json.loads(pathlib.Path("/tmp/route_queries.json").read_text(encoding="utf-8"))["calls"]


def with_scope(body):
    out = copy.deepcopy(body)
    for site in (out.get("query"), (out.get("knn") or {}).get("filter")):
        node = site.get("bool") if isinstance(site, dict) and "bool" in site else site
        if isinstance(node, dict):
            for f in node.get("filter") or []:
                t = f.get("terms") if isinstance(f, dict) else None
                if isinstance(t, dict) and "doc_id" in t:
                    t["doc_id"] = list(NEW_SCOPE)
    return out


def probe(body, cid):
    res = es.search(index=INDEX, body=body)
    hits = res["hits"]["hits"]
    for n, h in enumerate(hits, 1):
        if h["_id"] == cid:
            return {"rank": n, "score": round(float(h["_score"]), 6), "of": len(hits)}
    return {"rank": None, "score": None, "of": len(hits)}


seen, rows = set(), []
for c in calls:
    body = c.get("body") or {}
    if not isinstance(body, dict) or body.get("size") != 30:
        continue
    qs = ""
    for m in ((body.get("query") or {}).get("bool", {}).get("must") or []):
        qs = ((m or {}).get("query_string") or {}).get("query", "") or qs
    if not qs or qs[:60] in seen:
        continue
    seen.add(qs[:60])
    scoped = with_scope(body)
    knn = scoped.get("knn") or {}
    dense = dict(knn)
    dense["k"] = BIG
    if "num_candidates" in dense:
        dense["num_candidates"] = max(BIG, int(dense["num_candidates"]))
    hybrid = probe({"query": scoped["query"], "knn": dense, "size": BIG, "_source": False}, TARGET)
    hybrid_c = probe({"query": scoped["query"], "knn": dense, "size": BIG, "_source": False}, CONTROL)
    as_issued = probe({"query": body["query"], "knn": body.get("knn"), "size": 30, "_source": False}, TARGET)
    rows.append({"route": qs[:70], "as_issued_30": as_issued,
                 "new_scope_300_target": hybrid, "new_scope_300_control": hybrid_c})
    print(f"route: {qs[:66]}")
    print(f"   as issued (old scope) in 30 : target rank {as_issued['rank']}")
    print(f"   NEW scope (P2+P3) in 300    : target {hybrid['rank']}/{hybrid['score']}  "
          f"control {hybrid_c['rank']}/{hybrid_c['score']}  of {hybrid_c['of']}")

ranks = [r["new_scope_300_target"]["rank"] for r in rows]
print()
print(f"TARGET post-repair ranks (NEW scope, 300 window): {ranks}")
if ranks and all(r is not None for r in ranks):
    print(f"best={min(ranks)} worst={max(ranks)} -> inside Top-30 on "
          f"{sum(1 for r in ranks if r <= 30)}/{len(ranks)} routes")
pathlib.Path("/tmp/post_repair_ranks.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
