"""Replay each captured route query with a large window and split it into its lexical / dense / hybrid legs.

READ-ONLY: the same query bodies the live request issued, re-issued with size/k raised to 300 so the two
authoritative chunks can be compared on identical terms. Also runs ES `_explain` for both chunk ids
against each route's lexical clause, which names the terms that actually matched.

Nothing is modified: no query text, no weight, no window in the live path - only the replay window.
"""
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

out = []


def rank_score(body, cid):
    try:
        res = es.search(index=INDEX, body=body)
        hits = res["hits"]["hits"]
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"[:160]}
    for n, h in enumerate(hits, 1):
        if h["_id"] == cid:
            return {"rank": n, "score": round(float(h["_score"]), 6), "of": len(hits)}
    return {"rank": None, "score": None, "of": len(hits)}


def match_text(body):
    """The literal text of the route query, lifted from the lexical clause."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            if "match" in node and isinstance(node["match"], dict):
                for field, spec in node["match"].items():
                    if isinstance(spec, dict) and "query" in spec:
                        found.append(f"{field}={spec['query']}")
                    elif isinstance(spec, str):
                        found.append(f"{field}={spec}")
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(body.get("query"))
    return found


def explain_terms(cid, lex_query):
    try:
        res = es.explain(index=INDEX, id=cid, query=lex_query)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"[:160]}
    details = res.get("explanation") or {}
    terms = []

    def walk(node):
        if isinstance(node, dict):
            desc = str(node.get("description") or "")
            if "weight(" in desc and "in" in desc:
                terms.append(desc[:90])
            for v in node.get("details") or []:
                walk(v)

    walk(details)
    return {"matched_weight_clauses": terms[:14], "matched_count": len(terms)}


seen = {}
for n, call in enumerate(calls, 1):
    body = call.get("body") or {}
    if not isinstance(body, dict) or "query" not in body:
        continue
    key = json.dumps(match_text(body), ensure_ascii=False)
    if key in seen:
        seen[key]["calls_with_this_query"] += 1
        continue
    lex = body.get("query")
    knn = body.get("knn")
    record = {
        "route_index": n,
        "calls_with_this_query": 1,
        "route_query_text": match_text(body),
        "live_window_size": body.get("size"),
        "has_knn": bool(knn),
        "live_target_rank": call.get("target_rank"),
        "live_control_rank": call.get("control_rank"),
    }
    record["hybrid"] = {"control": rank_score({"query": lex, **({"knn": knn} if knn else {}), "size": BIG, "_source": False}, CONTROL),
                        "target": rank_score({"query": lex, **({"knn": knn} if knn else {}), "size": BIG, "_source": False}, TARGET)}
    record["lexical_only"] = {"control": rank_score({"query": lex, "size": BIG, "_source": False}, CONTROL),
                              "target": rank_score({"query": lex, "size": BIG, "_source": False}, TARGET)}
    if knn:
        dense_knn = dict(knn)
        dense_knn["k"] = BIG
        if "num_candidates" in dense_knn:
            dense_knn["num_candidates"] = max(BIG, int(dense_knn["num_candidates"]))
        record["dense_only"] = {"control": rank_score({"knn": dense_knn, "size": BIG, "_source": False}, CONTROL),
                                "target": rank_score({"knn": dense_knn, "size": BIG, "_source": False}, TARGET)}
    record["explain"] = {"control": explain_terms(CONTROL, lex), "target": explain_terms(TARGET, lex)}
    seen[key] = record
    out.append(record)

pathlib.Path("/tmp/route_rank_profiles.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"distinct route queries: {len(out)} (from {len(calls)} calls)")
for r in out:
    h, l, d = r["hybrid"], r["lexical_only"], r.get("dense_only", {})
    print(f"  route{r['route_index']:2d} x{r['calls_with_this_query']:2d} q={str(r['route_query_text'])[:70]}")
    print(f"      hybrid   C={h['control'].get('rank')}/{h['control'].get('score')}  T={h['target'].get('rank')}/{h['target'].get('score')} of {h['control'].get('of')}")
    print(f"      lexical  C={l['control'].get('rank')}/{l['control'].get('score')}  T={l['target'].get('rank')}/{l['target'].get('score')}")
    if d:
        print(f"      dense    C={d['control'].get('rank')}/{d['control'].get('score')}  T={d['target'].get('rank')}/{d['target'].get('score')}")
