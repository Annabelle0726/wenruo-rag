"""Per-leg rank profile for the two authoritative chunks under the LIVE route queries. Read-only.

Verifies the doc-filter strip actually took effect, then measures each chunk on:
  * hybrid   - the query as issued (query_string + knn)
  * lexical  - the query_string alone
  * dense    - the knn alone
each at a 300 window so both chunks are visible, plus the count of Part 3 chunks that reach the live
30 window with and without the document scope.
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
PART3 = "f18db09cba1211f18bee33eac9b39c66"
BIG = 300
es = settings.docStoreConn.es

calls = json.loads(pathlib.Path("/tmp/route_queries.json").read_text(encoding="utf-8"))["calls"]


def strip_doc(body):
    out = copy.deepcopy(body)
    bo = out["query"]["bool"]
    kept = []
    for f in bo.get("filter") or []:
        if "doc_id" in ((f or {}).get("terms") or {}):
            continue
        kept.append(f)
    bo["filter"] = kept
    return out


def hit_ranks(body, ids):
    res = es.search(index=INDEX, body=body)
    hits = res["hits"]["hits"]
    pos = {h["_id"]: (n, round(float(h["_score"]), 6)) for n, h in enumerate(hits, 1)}
    out = {"of": len(hits)}
    for name, cid in ids.items():
        out[name] = {"rank": pos[cid][0], "score": pos[cid][1]} if cid in pos else {"rank": None, "score": None}
    return out


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
    lex_q = body["query"]
    row = {
        "route": qs[:100],
        "doc_filter_on_issue": [t for f in ((body.get("query") or {}).get("bool", {}).get("filter") or [])
                                for t in ((f or {}).get("terms") or {}).get("doc_id", [])],
        "doc_filter_after_strip": [t for f in ((strip_doc(body).get("query") or {}).get("bool", {}).get("filter") or [])
                                   for t in ((f or {}).get("terms") or {}).get("doc_id", [])],
        "hybrid_300": hit_ranks({"query": lex_q, "knn": knn, "size": BIG, "_source": False},
                                {"target": TARGET, "control": CONTROL}),
        "lexical_300": hit_ranks({"query": lex_q, "size": BIG, "_source": False},
                                 {"target": TARGET, "control": CONTROL}),
        "dense_300": hit_ranks({"knn": dense, "size": BIG, "_source": False},
                               {"target": TARGET, "control": CONTROL}),
    }
    # how many Part 3 chunks reach a 30 window with / without the doc scope
    for label, b in (("scoped", body), ("unscoped", strip_doc(body))):
        r = es.search(index=INDEX, body={"query": b["query"], "knn": knn, "size": 30, "_source": False})
        tops = [h["_id"] for h in r["hits"]["hits"]]
        row[f"part3_in_top30_{label}"] = sum(1 for cid in tops if cid == PART3) + \
            (1 if any(h == TARGET for h in tops) else 0)
        row[f"target_in_top30_{label}"] = TARGET in tops
        row[f"control_in_top30_{label}"] = CONTROL in tops
    rows.append(row)

print(f"distinct live route queries: {len(rows)}")
for r in rows:
    print(f"\n  route: {r['route'][:76]}")
    print(f"    doc_filter on issue : {[d[:8] for d in r['doc_filter_on_issue']]}  "
          f"after strip: {[d[:8] for d in r['doc_filter_after_strip']]}  "
          f"(strip effective: {r['doc_filter_after_strip'] == []})")
    h, l, dd = r["hybrid_300"], r["lexical_300"], r["dense_300"]
    print(f"    HYBRID 300 : TARGET rank={h['target']['rank']} score={h['target']['score']} | "
          f"CONTROL rank={h['control']['rank']} score={h['control']['score']} of {h['of']}")
    print(f"    LEXICAL 300: TARGET rank={l['target']['rank']} score={l['target']['score']} | "
          f"CONTROL rank={l['control']['rank']} score={l['control']['score']} of {l['of']}")
    print(f"    DENSE 300  : TARGET rank={dd['target']['rank']} score={dd['target']['score']} | "
          f"CONTROL rank={dd['control']['rank']} score={dd['control']['score']} of {dd['of']}")
    print(f"    top30 scoped:  target={r['target_in_top30_scoped']} control={r['control_in_top30_scoped']}")
    print(f"    top30 unscoped:target={r['target_in_top30_unscoped']} control={r['control_in_top30_unscoped']}")

pathlib.Path("/tmp/leg_profiles.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
