import json
import pathlib

d = json.loads(pathlib.Path("deploy/repair_gates/trace_qgdw_now.json").read_text(encoding="utf-8"))
print("top keys:", sorted(d))
for key in ("es_windows", "search_results", "route_pages", "route_results", "merges", "rerank",
            "selection", "rank_adjustments"):
    val = d["trace"].get(key)
    print(f"\n=== trace[{key}] : {type(val).__name__} len={len(val) if hasattr(val, '__len__') else '-'}")
    if isinstance(val, list) and val:
        first = val[0]
        if isinstance(first, dict):
            print("  keys:", sorted(first))
            for k in sorted(first):
                v = first[k]
                if isinstance(v, list):
                    print(f"    {k}: list[{len(v)}] head={json.dumps(v[:2], ensure_ascii=False)[:180]}")
                else:
                    print(f"    {k}: {json.dumps(v, ensure_ascii=False)[:180]}")
