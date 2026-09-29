import json
import pathlib

d = json.loads(pathlib.Path("deploy/repair_gates/trace_qgdw_now.json").read_text(encoding="utf-8"))
s = d["trace"]["selection"][0]
prof = s["ordered_profile"]
print("ordered_profile entries:", len(prof))
print("fields:", sorted(prof[0]))
print()

WATCH = {1, 2, 12, 13, 14, 16, 27, 39}
TARGET, CONTROL = "d1d75672f2dbc333", "b5aaf72bcd33d44a"
extra_keys = [k for k in prof[0] if k not in ("position", "chunk_id", "is_table", "is_prose", "similarity", "document", "document_key", "chosen")]
print("extra fields:", extra_keys)
print()

for e in prof:
    if e["position"] in WATCH or e["chunk_id"] in (TARGET, CONTROL):
        tag = "  <-- TARGET" if e["chunk_id"] == TARGET else ("  <-- CONTROL" if e["chunk_id"] == CONTROL else "")
        print(f'pos={e["position"]:2d} table={str(e["is_table"]):5s} chosen={str(e.get("chosen")):5s} '
              f'sim={e["similarity"]:.6f} {e["chunk_id"]}{tag}')
        if extra_keys:
            print("      ", json.dumps({k: e[k] for k in extra_keys}, ensure_ascii=False)[:200])

print()
print("=== policy constants as recorded ===")
print(json.dumps(s["policy"], ensure_ascii=False))
print("=== quotas ===")
print(json.dumps(s["quotas"], ensure_ascii=False))
print("=== score_margin ===")
print(json.dumps(s["score_margin"], ensure_ascii=False))
print("=== counterfactual ===")
print(json.dumps(s["counterfactual_table_deferral_disabled"], ensure_ascii=False))
print("=== rank_adjustments ===")
print(json.dumps(d["trace"]["rank_adjustments"][0], ensure_ascii=False))
