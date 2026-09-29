import json
import pathlib

d = json.loads(pathlib.Path("deploy/repair_gates/attribution_matrix_result.json").read_text(encoding="utf-8"))
print("helper_constants:", json.dumps(d["helper_constants"], ensure_ascii=False))
print("parameters_used:", json.dumps(d["parameters_used"], ensure_ascii=False))
print()
for i, q in enumerate(d["queries"]):
    keys = sorted(q)
    qtext = str(q.get("question") or q.get("query") or "")[:60]
    pool = q.get("pool") or []
    ordered = q.get("ordered") or []
    print(f"query[{i}] keys={keys}")
    print(f"   question={qtext!r}")
    print(f"   pool={len(pool)} ordered={len(ordered)} chosen={len(q.get('chosen') or [])}")
    if pool and isinstance(pool[0], dict):
        print(f"   pool[0] fields={sorted(pool[0])}")
    if ordered and isinstance(ordered[0], dict):
        print(f"   ordered[0] fields={sorted(ordered[0])}")
    print()
