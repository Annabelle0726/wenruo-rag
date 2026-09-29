import json
import pathlib

d = json.loads(pathlib.Path("deploy/repair_gates/metadata_acceptance.json").read_text(encoding="utf-8"))
print("=== FINAL ANSWER ===")
print(d["D_answer"])
print()
print(f"=== FINAL CONTEXT ( {d['D_context_size']} chunks, {d['D_context_tables']} tables ) ===")
for n, c in enumerate(d["D_context"], 1):
    kind = "TABLE" if c["is_table"] else "prose"
    print(f"  {n:2d}. {kind:5s} {c['chunk_id']} {c['document'][:46]}")
print()
print("target d1d75672f2dbc333 in context:", any(c["chunk_id"] == "d1d75672f2dbc333" for c in d["D_context"]))
print("control b5aaf72bcd33d44a in context:", any(c["chunk_id"] == "b5aaf72bcd33d44a" for c in d["D_context"]))
print()
print("=== context body heads (200 chars each) ===")
for n, c in enumerate(d["D_context"], 1):
    print(f"  {n:2d}. {c['chunk_id']}: {c['body_head'][:200]}")
