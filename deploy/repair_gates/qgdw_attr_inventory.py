import json
import pathlib

p = pathlib.Path("deploy/repair_gates/attribution_matrix_result.json")
print("exists:", p.exists(), "bytes:", p.stat().st_size if p.exists() else 0)
d = json.loads(p.read_text(encoding="utf-8"))
print("top type:", type(d).__name__)
if isinstance(d, dict):
    print("top keys:", sorted(d))
    for k in sorted(d):
        v = d[k]
        print(f"  {k}: {type(v).__name__} len={len(v) if hasattr(v, '__len__') else '-'}")
elif isinstance(d, list):
    print("list len:", len(d))
    print("first keys:", sorted(d[0]) if isinstance(d[0], dict) else type(d[0]))
