"""Per-term attribution for the two authoritative Table 1 chunks under the LIVE route queries. Read-only.

For the exact original question and each distinct live route query clause:
  * the route query text, verbatim;
  * ES `_explain` for BOTH chunk ids -> the terms that actually matched, with their BM25 weights;
  * per-leg scores: lexical (boost restored to 1.0), dense (the knn clause), hybrid (as issued);
  * which query terms each chunk matches / misses, and which discriminate;
  * the header/document-metadata contribution, measured by locating each matched term in the injected
    prefix vs the passage body separately, using the producer's own prefix boundary.

The document scope is REMOVED from both sites (query.bool.filter and knn.filter) so the two chunks are
comparable; the scope's own effect is reported separately. Nothing is modified in the live path.
"""
import copy
import json
import pathlib
import re
import sys

sys.path.insert(0, "/ragflow")

from common import settings  # noqa: E402

settings.init_settings()

from rag.retrieval.chunk_profile import _body_text  # noqa: E402

INDEX = "ragflow_a9e28731ab7011f19b833887d563fb04"
TARGET, CONTROL = "d1d75672f2dbc333", "b5aaf72bcd33d44a"
BIG = 400
es = settings.docStoreConn.es

calls = json.loads(pathlib.Path("/tmp/route_queries.json").read_text(encoding="utf-8"))["calls"]

DISCRIMINATORS = ["gdw", "73286", "2026", "2", "3", "1", "单芯", "三芯", "标准表", "标准", "导体",
                  "标称", "截面", "规定", "根据", "技术", "规范", "电缆", "海底", "220"]


def strip_doc(body):
    out = copy.deepcopy(body)
    for site in (out.get("query"), (out.get("knn") or {}).get("filter")):
        node = site.get("bool") if isinstance(site, dict) and "bool" in site else site
        if isinstance(node, dict) and isinstance(node.get("filter"), list):
            node["filter"] = [f for f in node["filter"]
                              if "doc_id" not in ((f or {}).get("terms") or {})]
    return out


def lex_clause(body):
    for m in ((body.get("query") or {}).get("bool", {}).get("must") or []):
        if isinstance(m, dict) and isinstance(m.get("query_string"), dict):
            return m["query_string"]
    return None


def matched_terms(cid, query_string):
    """Parse ES _explain into (term -> weight) for the terms that matched this chunk."""
    try:
        # `query` is a URL parameter name for this API, so the query must go in the BODY.
        res = es.explain(index=INDEX, id=cid,
                         body={"query": {"bool": {"must": [{"query_string": query_string}]}}})
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"[:120]}
    terms = {}

    def walk(node):
        if not isinstance(node, dict):
            return
        desc = str(node.get("description") or "")
        m = re.match(r"weight\(([^:]+):([^ ]+) in \d+\)", desc)
        value = node.get("value")
        if m and isinstance(value, (int, float)) and not isinstance(value, bool) and value:
            key = m.group(2)
            terms[key] = terms.get(key, 0.0) + float(value)
        for child in node.get("details") or []:
            walk(child)

    walk(res.get("explanation") or {})
    return terms


def probe(body, cid):
    res = es.search(index=INDEX, body=body)
    hits = res["hits"]["hits"]
    for n, h in enumerate(hits, 1):
        if h["_id"] == cid:
            return {"rank": n, "score": round(float(h["_score"]), 6), "of": len(hits)}
    return {"rank": None, "score": None, "of": len(hits)}


# Header vs body term location. NEITHER chunk carries provenance, so `_body_text` fails closed and
# returns the whole content (prefix length 0) - the producer's boundary cannot separate the injected
# prefix here. The literal ingest prefix is a leading bracketed block, so that marker is used instead.
contents = {}
for name, cid in (("target", TARGET), ("control", CONTROL)):
    src = es.get(index=INDEX, id=cid)["_source"]
    full = str(src.get("content_with_weight") or "")
    body = _body_text(src)
    marker = re.match(r"^\[[^\]]*\]\s*", full)
    header = marker.group(0) if marker else ""
    rest = full[len(header):]
    contents[name] = {"full": full, "body": body, "prefix": header, "rest": rest,
                      "provenance_present": "content_prefix_kind_kwd" in src,
                      "terms_in_prefix": {t for t in DISCRIMINATORS if t in header},
                      "terms_in_body": {t for t in DISCRIMINATORS if t in rest}}

seen, rows = set(), []
for c in calls:
    body = c.get("body") or {}
    if not isinstance(body, dict) or body.get("size") != 30:
        continue
    qs = lex_clause(body)
    if not qs:
        continue
    key = qs["query"][:60]
    if key in seen:
        continue
    seen.add(key)
    un = strip_doc(body)
    lex_q = un["query"]
    knn = un.get("knn") or {}
    dense = dict(knn)
    dense["k"] = BIG
    if "num_candidates" in dense:
        dense["num_candidates"] = max(BIG, int(dense["num_candidates"]))
    tc = lex_clause(un)
    tc = dict(tc, boost=1.0, minimum_should_match="0%")
    row = {
        "route_query_string": qs["query"],
        "lexical_true": {"target": probe({"query": {"bool": {"must": [{"query_string": tc}]}}, "size": BIG, "_source": False}, TARGET),
                         "control": probe({"query": {"bool": {"must": [{"query_string": tc}]}}, "size": BIG, "_source": False}, CONTROL)},
        "dense": {"target": probe({"knn": dense, "size": BIG, "_source": False}, TARGET),
                  "control": probe({"knn": dense, "size": BIG, "_source": False}, CONTROL)},
        "hybrid": {"target": probe({"query": lex_q, "knn": dense, "size": BIG, "_source": False}, TARGET),
                   "control": probe({"query": lex_q, "knn": dense, "size": BIG, "_source": False}, CONTROL)},
        "explain_terms": {"target": matched_terms(TARGET, tc), "control": matched_terms(CONTROL, tc)},
    }
    rows.append(row)

print(f"distinct live route queries: {len(rows)}")
print()
print("=== header vs body term location (producer prefix boundary) ===")
for name in ("target", "control"):
    c = contents[name]
    print(f"  {name}: full={len(c['full'])} body={len(c['body'])} prefix={len(c['prefix'])}")
    print(f"     discriminators in PREFIX only: {sorted(c['terms_in_prefix'] - c['terms_in_body'])}")
    print(f"     discriminators in BODY      : {sorted(c['terms_in_body'])}")

for n, r in enumerate(rows, 1):
    et, ec = r["explain_terms"]["target"], r["explain_terms"]["control"]
    tset, cset = set(et if isinstance(et, dict) else {}), set(ec if isinstance(ec, dict) else {})
    print(f"\n=== route {n}: {r['route_query_string'][:88]}")
    l, d, h = r["lexical_true"], r["dense"], r["hybrid"]
    print(f"  lexical(true BM25) T={l['target']['rank']}/{l['target']['score']}  C={l['control']['rank']}/{l['control']['score']} of {l['control']['of']}")
    print(f"  dense              T={d['target']['rank']}/{d['target']['score']}  C={d['control']['rank']}/{d['control']['score']} of {d['control']['of']}")
    print(f"  hybrid(as issued)  T={h['target']['rank']}/{h['target']['score']}  C={h['control']['rank']}/{h['control']['score']} of {h['control']['of']}")
    def _numeric(d):
        if not isinstance(d, dict):
            return []
        return sorted(((k, v) for k, v in d.items() if isinstance(v, (int, float)) and not isinstance(v, bool)),
                      key=lambda kv: -kv[1])
    tn, cn = _numeric(et), _numeric(ec)
    print(f"  matched terms TARGET : {[(k, round(v, 3)) for k, v in tn[:8]] if tn else et}")
    print(f"  matched terms CONTROL: {[(k, round(v, 3)) for k, v in cn[:8]] if cn else ec}")
    print(f"  matched ONLY by CONTROL (target misses): {sorted(cset - tset)}")
    print(f"  matched ONLY by TARGET (control misses): {sorted(tset - cset)}")

pathlib.Path("/tmp/per_term_attribution.json").write_text(
    json.dumps({"rows": rows, "header_body": {k: {"prefix_chars": len(contents[k]["prefix"]),
                                                  "terms_prefix_only": sorted(contents[k]["terms_in_prefix"] - contents[k]["terms_in_body"]),
                                                  "terms_in_body": sorted(contents[k]["terms_in_body"])}
                                              for k in contents}},
               ensure_ascii=False, indent=1), encoding="utf-8")
