"""Stage aggregation for the binding trace: where does the TARGET first disappear?"""
import json
import pathlib
from collections import OrderedDict

d = json.loads(pathlib.Path("deploy/repair_gates/binding_trace.json").read_text(encoding="utf-8"))
trace = d["stage_trace"]

print("=== ALL S1 raw ES windows ===")
windows = [s for s in trace if s["stage"] == "S1_raw_ES_window"]
for n, s in enumerate(windows, 1):
    print(f"  win{n:2d}: returned={s['count']:3d} target_rank={s['target_rank']} control_rank={s['control_rank']}")
print(f"  windows total={len(windows)}  any window containing target: "
      f"{any(s['target_rank'] for s in windows)}")

print()
print("=== stage aggregation (per boundary, across all calls) ===")
agg = OrderedDict()
for s in trace:
    a = agg.setdefault(s["stage"], {"calls": 0, "max_n": 0, "target": [], "control": []})
    a["calls"] += 1
    a["max_n"] = max(a["max_n"], s["count"])
    if s["target_rank"]:
        a["target"].append(s["target_rank"])
    if s["control_rank"]:
        a["control"].append(s["control_rank"])
for stage, a in agg.items():
    print(f"  {stage:24s} calls={a['calls']:3d} max_n={a['max_n']:4d} "
          f"TARGET_present={bool(a['target'])} ranks={a['target'][:8]} | "
          f"CONTROL_present={bool(a['control'])} ranks={a['control'][:8]}")

print()
print("=== model context (kb_prompt) ===")
kb = d["kb_prompt"]
print(f"  blocks={kb.get('block_count')} chars={kb.get('chars')} sha256={kb.get('sha256')}")
print(f"  3x400 (three-core Table 1) present : {kb.get('has_3x400')}")
print(f"  1x400 (single-core Table 1) present: {kb.get('has_1x400')}")
print(f"  mentions 73286.3 : {kb.get('mentions_73286_3')}   mentions 第3部分: {kb.get('mentions_part3')}")

print()
print("=== final context ===")
print(f"  size={d['context_size']} answer_len={d['answer_length']}")
for n, c in enumerate(d["chunks"], 1):
    print(f"   {n:2d}. {'TABLE' if c['is_table'] else 'prose'} {c['chunk_id']} "
          f"sha={c['content_sha256'][:16]} doc={c['document'][:50]}")
print(f"  target in final context: {any(c['chunk_id'] == 'd1d75672f2dbc333' for c in d['chunks'])}")
print(f"  control in final context: {any(c['chunk_id'] == 'b5aaf72bcd33d44a' for c in d['chunks'])}")
