"""Is the document scope the SOLE decisive cause? Read-only.

For each distinct live route query: run it exactly as issued (doc-scoped, size 30), then run the SAME
query with ONLY the doc_id term removed (everything else identical - same query_string, same knn, same
size). If the Part 3 chunk enters the live 30-window once the scope is lifted, the scope is the cause and
the ranking legs are not.
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
es = settings.docStoreConn.es

calls = json.loads(pathlib.Path("/tmp/route_queries.json").read_text(encoding="utf-8"))["calls"]


def strip_doc_filter(body):
    out = copy.deepcopy(body)
    bo = (out.get("query") or {}).get("bool") or {}
    newf = []
    for f in (bo.get("filter") or []):
        terms = (f or {}).get("terms") or {}
        if "doc_id" in terms:
            continue
        newf.append(f)
    bo["filter"] = newf
    return out


def probe(body, cid):
    try:
        res = es.search(index=INDEX, body=body)
        hits = res["hits"]["hits"]
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"[:120]}
    for n, h in enumerate(hits, 1):
        if h["_id"] == cid:
            return {"rank": n, "score": round(float(h["_score"]), 6), "of": len(hits)}
    return {"rank": None, "score": None, "of": len(hits)}


seen, rows = set(), []
for c in calls:
    body = c.get("body") or {}
    if not isinstance(body, dict) or "query" not in body or body.get("size") != 30:
        continue
    bo = (body.get("query") or {}).get("bool") or {}
    qs = ""
    for m in (bo.get("must") or []):
        qs = ((m or {}).get("query_string") or {}).get("query", "") or qs
    if not qs or qs[:70] in seen:
        continue
    seen.add(qs[:70])
    scoped = body
    unscoped = strip_doc_filter(body)
    rows.append({
        "route": qs[:110],
        "scoped_target": probe(scoped, TARGET),
        "scoped_control": probe(scoped, CONTROL),
        "unscoped_target": probe(unscoped, TARGET),
        "unscoped_control": probe(unscoped, CONTROL),
    })

print("=== live route queries: scoped (as issued) vs unscoped (doc_id filter removed) ===")
for r in rows:
    st, sc = r["scoped_target"], r["scoped_control"]
    ut, uc = r["unscoped_target"], r["unscoped_control"]
    print(f"  route: {r['route'][:78]}")
    print(f"     SCOPED   TARGET={st.get('rank')} score={st.get('score')} | CONTROL={sc.get('rank')} score={sc.get('score')} of {sc.get('of')}")
    print(f"     UNSCOPED TARGET={ut.get('rank')} score={ut.get('score')} | CONTROL={uc.get('rank')} score={uc.get('score')} of {uc.get('of')}")
    print(f"     -> target enters the live 30-window when unscoped: "
          f"{bool(ut.get('rank') and ut['rank'] <= 30)}")

enters = sum(1 for r in rows if r["unscoped_target"].get("rank") and r["unscoped_target"]["rank"] <= 30)
print()
print(f"routes where TARGET would be inside the 30-window once the doc scope is lifted: {enters}/{len(rows)}")
print(f"routes where TARGET is inside the 30-window as issued: "
      f"{sum(1 for r in rows if r['scoped_target'].get('rank') and r['scoped_target']['rank'] <= 30)}/{len(rows)}")

pathlib.Path("/tmp/scope_counterfactual.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
