"""Final measurement: strip the document scope where it is applied in BOTH legs, and re-profile.

The scope appears twice in every live route query - in `query.bool.filter` AND inside `knn.filter` - so
an "unscoped" test that removes only the first leaves the dense leg still restricted to Part 2. This
removes the doc_id term from both sites and nothing else, then measures the two chunks on each leg.
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
BIG = 300
es = settings.docStoreConn.es

calls = json.loads(pathlib.Path("/tmp/route_queries.json").read_text(encoding="utf-8"))["calls"]


def strip_all_doc(body):
    out = copy.deepcopy(body)

    def clean(container):
        if not isinstance(container, dict):
            return
        for key in ("bool",):
            node = container.get(key)
            if isinstance(node, dict) and isinstance(node.get("filter"), list):
                node["filter"] = [f for f in node["filter"]
                                  if "doc_id" not in ((f or {}).get("terms") or {})]

    clean(out.get("query"))
    knn = out.get("knn")
    if isinstance(knn, dict):
        clean(knn.get("filter"))
    return out


def probe(body, cid):
    res = es.search(index=INDEX, body=body)
    hits = res["hits"]["hits"]
    for n, h in enumerate(hits, 1):
        if h["_id"] == cid:
            return {"rank": n, "score": round(float(h["_score"]), 6), "of": len(hits)}
    return {"rank": None, "score": None, "of": len(hits)}


seen = set()
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
    un = strip_all_doc(body)
    knn = un.get("knn")
    dense = dict(knn) if knn else None
    if dense:
        dense["k"] = BIG
        if "num_candidates" in dense:
            dense["num_candidates"] = max(BIG, int(dense["num_candidates"]))
    lex_q = un["query"]
    checks = {"SCOPED/as-issued target present": probe({"query": body["query"], "knn": knn, "size": 30, "_source": False}, TARGET)["rank"]}
    h = {"target": probe({"query": lex_q, "knn": dense, "size": BIG, "_source": False}, TARGET),
         "control": probe({"query": lex_q, "knn": dense, "size": BIG, "_source": False}, CONTROL)}
    l = {"target": probe({"query": lex_q, "size": BIG, "_source": False}, TARGET),
         "control": probe({"query": lex_q, "size": BIG, "_source": False}, CONTROL)}
    d = {"target": probe({"knn": dense, "size": BIG, "_source": False}, TARGET),
         "control": probe({"knn": dense, "size": BIG, "_source": False}, CONTROL)}
    print(f"\n=== route: {qs[:70]}")
    print(f"  as-issued (Part2 scope) : TARGET rank {checks['SCOPED/as-issued target present']} (None = filtered out)")
    print(f"  FULLY UNSCOPED hybrid   : T={h['target']['rank']}/{h['target']['score']}  C={h['control']['rank']}/{h['control']['score']} of {h['control']['of']}")
    print(f"  FULLY UNSCOPED lexical  : T={l['target']['rank']}/{l['target']['score']}  C={l['control']['rank']}/{l['control']['score']} of {l['control']['of']}")
    print(f"  FULLY UNSCOPED dense    : T={d['target']['rank']}/{d['target']['score']}  C={d['control']['rank']}/{d['control']['score']} of {d['control']['of']}")
    print(f"  TARGET in top-30 unscoped: hybrid={bool(h['target']['rank'] and h['target']['rank']<=30)} "
          f"dense={bool(d['target']['rank'] and d['target']['rank']<=30)}")
