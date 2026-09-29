import json
import pathlib

G = pathlib.Path("deploy/repair_gates")
for label, name in (("BEFORE", "qgdw_effect_before.json"), ("AFTER", "qgdw_effect_after.json")):
    p = G / name
    txt = p.read_text(encoding="utf-8", errors="replace")
    start = txt.find("{")
    try:
        d = json.loads(txt[start:])
    except Exception as exc:  # noqa: BLE001
        print(f"=== arm {label}: could not parse ({exc}); first 300 chars ===\n{txt[:300]}")
        continue
    print(f"=== arm {label} ===")
    print("  model decision      :", json.dumps(d.get("A_model_decision"), ensure_ascii=False))
    print("  resolved scope      :", json.dumps(d.get("A_resolved_scope"), ensure_ascii=False))
    print("  final scope         :", json.dumps(d.get("A_final_scope"), ensure_ascii=False))
    print("  calls / with filter :", d.get("B_calls_total"), "/", d.get("B_calls_with_doc_filter"))
    print("  filter sets         :", json.dumps(d.get("B_distinct_doc_filter_sets"), ensure_ascii=False)[:160])
    print("  target raw ranks    :", d.get("C_target_raw_ranks"))
    print("  control raw ranks   :", d.get("C_control_raw_ranks"))
    print("  target in any window:", d.get("C_target_in_any_window"), " in Top-30:", d.get("C_target_in_top30"))
    print("  context size/tables :", d.get("D_context_size"), "/", d.get("D_context_tables"))
    ids = [c["chunk_id"] for c in d.get("D_context", [])]
    print("  context ids         :", ids)
    print("  TARGET in context   :", "d1d75672f2dbc333" in ids)
    print("  CONTROL in context  :", "b5aaf72bcd33d44a" in ids)
    print("  answer length       :", d.get("D_answer_length"))
    print("  ANSWER:", (d.get("D_answer") or "")[:600].replace("\n", " "))
    print()
