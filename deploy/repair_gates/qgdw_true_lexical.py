"""True lexical relevance: the same query_string with the zeroing `boost` restored to 1.0.

With `query.bool.boost = 0.0` every lexical score is 0.0 and the returned order is an arbitrary tie
break, so lexical RANKS taken from that leg say nothing about term matching. This runs the identical
query_string - document scope removed, knn removed, boost set to 1.0 - so BM25 can be compared.
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
BIG = 400
es = settings.docStoreConn.es

calls = json.loads(pathlib.Path("/tmp/route_queries.json").read_text(encoding="utf-8"))["calls"]


def build(body):
    out = copy.deepcopy(body)
    bo = out["query"]["bool"]
    bo["filter"] = [f for f in (bo.get("filter") or [])
                    if "doc_id" not in ((f or {}).get("terms") or {})]
    bo["boost"] = 1.0                      # restore the lexical contribution
    for m in bo.get("must") or []:
        if isinstance(m, dict) and isinstance(m.get("query_string"), dict):
            m["query_string"]["boost"] = 1.0
    return out["query"]


def probe(query, cid):
    res = es.search(index=INDEX, body={"query": query, "size": BIG, "_source": False})
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
    q = build(body)
    t, ctl = probe(q, TARGET), probe(q, CONTROL)
    print(f"route: {qs[:66]}")
    print(f"   TRUE LEXICAL (boost=1.0, unscoped): TARGET {t['rank']}/{t['score']}   "
          f"CONTROL {ctl['rank']}/{ctl['score']}   of {ctl['of']}")
