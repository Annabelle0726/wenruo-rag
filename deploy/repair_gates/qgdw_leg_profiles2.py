"""Corrected per-leg profile: SCOPED (as issued) and UNSCOPED (doc_id term removed) at a 300 window.

The earlier probe reused the scoped query for the 300-window legs, so every "target None" it printed for
the legs was the doc filter talking, not the ranking. This measures both.
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


def strip_doc(body):
    out = copy.deepcopy(body)
    bo = out["query"]["bool"]
    bo["filter"] = [f for f in (bo.get("filter") or [])
                    if "doc_id" not in ((f or {}).get("terms") or {})]
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
    knn = body.get("knn") or {}
    dense = dict(knn)
    dense["k"] = BIG
    if "num_candidates" in dense:
        dense["num_candidates"] = max(BIG, int(dense["num_candidates"]))
    un = strip_doc(body)
    row = {"route": qs[:95]}
    for label, b in (("scoped", body), ("unscoped", un)):
        lex_q = b["query"]
        row[label] = {
            "hybrid": {"target": probe({"query": lex_q, "knn": knn, "size": BIG, "_source": False}, TARGET),
                       "control": probe({"query": lex_q, "knn": knn, "size": BIG, "_source": False}, CONTROL)},
            "lexical": {"target": probe({"query": lex_q, "size": BIG, "_source": False}, TARGET),
                        "control": probe({"query": lex_q, "size": BIG, "_source": False}, CONTROL)},
            "dense": {"target": probe({"knn": dense, "size": BIG, "_source": False}, TARGET),
                      "control": probe({"knn": dense, "size": BIG, "_source": False}, CONTROL)},
        }
    rows.append(row)

for r in rows:
    print(f"\n=== route: {r['route'][:74]}")
    for label in ("scoped", "unscoped"):
        d = r[label]
        print(f"  {label.upper():9s} hybrid  T={d['hybrid']['target']['rank']}/{d['hybrid']['target']['score']}"
              f"  C={d['hybrid']['control']['rank']}/{d['hybrid']['control']['score']} of {d['hybrid']['control']['of']}")
        print(f"  {'':9s} lexical T={d['lexical']['target']['rank']}/{d['lexical']['target']['score']}"
              f"  C={d['lexical']['control']['rank']}/{d['lexical']['control']['score']} of {d['lexical']['control']['of']}")
        print(f"  {'':9s} dense   T={d['dense']['target']['rank']}/{d['dense']['target']['score']}"
              f"  C={d['dense']['control']['rank']}/{d['dense']['control']['score']} of {d['dense']['control']['of']}")

pathlib.Path("/tmp/leg_profiles2.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
