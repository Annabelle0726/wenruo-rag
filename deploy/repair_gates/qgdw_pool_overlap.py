"""Cross-reference the previously captured attribution pool against the current 45-chunk pool.

Both artifacts are already on disk; nothing is re-retrieved. Output goes to a file so no console
codec can truncate the non-ASCII document names.
"""
import json
import pathlib

OUT = pathlib.Path("deploy/repair_gates/qgdw_pool_overlap.txt")
lines = []


def emit(text=""):
    lines.append(str(text))


attr = json.loads(pathlib.Path("deploy/repair_gates/attribution_matrix_result.json").read_text(encoding="utf-8"))
now = json.loads(pathlib.Path("deploy/repair_gates/trace_qgdw_now.json").read_text(encoding="utf-8"))
now_prof = now["trace"]["selection"][0]["ordered_profile"]
now_ids = {e["chunk_id"] for e in now_prof}
emit(f"current captured pool: {len(now_prof)} chunks, ids={len(now_ids)}")

for i, q in enumerate(attr["queries"]):
    pb = q.get("pool_before") or []
    pa = q.get("pool_after") or []
    emit()
    emit(f"--- attribution query[{i}] kind={q.get('kind')!r} pool_before={len(pb)} pool_after={len(pa)}")
    if pb and isinstance(pb[0], dict):
        emit(f"    pool_before fields: {sorted(pb[0])}")
    if pa and isinstance(pa[0], dict):
        emit(f"    pool_after  fields: {sorted(pa[0])}")
    pb_ids = {str(c.get("id") or c.get("chunk_id")) for c in pb if isinstance(c, dict)}
    emit(f"    pool_before ids={len(pb_ids)} overlap_with_current={len(pb_ids & now_ids)}")
    if pb_ids & now_ids:
        overlap = len(pb_ids & now_ids)
        emit(f"    INTERSECTION DETAIL: {overlap} shared / {len(now_ids)} current")
        missing = sorted(now_ids - pb_ids)
        emit(f"    in current but NOT in this attribution pool: {len(missing)}")

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT, len(lines), "lines")
