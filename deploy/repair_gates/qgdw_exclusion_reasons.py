"""Why is each table excluded, per fill mode? Offline, same frozen pool.

Reports the exclusion reason for every table sitting in the first 20 positions of each ordering, under
(a) the deployed prose-first fill and (b) the score fill. This decides whether the table exclusion is
caused by the prose-first discrimination or by a document quota, which are different rules.
"""
import json
import math
import pathlib

TRACE = pathlib.Path("deploy/repair_gates/trace_qgdw_now.json")
OUT = pathlib.Path("deploy/repair_gates/qgdw_exclusion_reasons.txt")

TARGET, CONTROL = "d1d75672f2dbc333", "b5aaf72bcd33d44a"
TOP_N = 12
CORE_DOCUMENT_BOOST = 1.15
MAX_TABLE_SHARE = 0.5
MAX_AUXILIARY_DOCUMENT_SHARE = 0.4
MAX_COMPARED_DOCUMENT_SHARE = 0.5
MIN_PROSE_PASSAGES = 4

d = json.loads(TRACE.read_text(encoding="utf-8"))
pool = sorted(d["trace"]["selection"][0]["ordered_profile"], key=lambda e: e["position"])
policy = d["trace"]["selection"][0]["policy"]
core_docs = set(policy["core_documents"])
compared_docs = set(policy["compared_documents"])
for e in pool:
    e["is_core"] = (not e["document_key"]) or (e["document_key"] in core_docs)

lines = []


def emit(text=""):
    lines.append(str(text))


def run(order, prose_first):
    table_cap = min(TOP_N, math.ceil(TOP_N * MAX_TABLE_SHARE))
    document_cap = max(1, min(TOP_N, math.ceil(TOP_N * MAX_AUXILIARY_DOCUMENT_SHARE)))
    every_document_cap = max(1, min(TOP_N, math.ceil(TOP_N * MAX_COMPARED_DOCUMENT_SHARE)))

    chosen, keys = [], set()
    table_count = 0
    counts = {}
    reasons = {}

    def bucket(c):
        return c["document_key"] or f"chunk:{c['chunk_id']}"

    def reason(c):
        if counts.get(bucket(c), 0) >= every_document_cap:
            return f"compared_document_cap({every_document_cap}) on {bucket(c)[:8]}"
        if not c["is_core"] and counts.get(bucket(c), 0) >= document_cap:
            return f"auxiliary_document_cap({document_cap})"
        if table_count >= table_cap:
            return f"table_cap({table_cap})"
        return None

    def take(c):
        nonlocal table_count
        if len(chosen) >= TOP_N or c["chunk_id"] in keys:
            return False
        r = reason(c)
        if r:
            reasons[c["chunk_id"]] = r
            return False
        chosen.append(c["chunk_id"]); keys.add(c["chunk_id"])
        if c["is_table"]:
            table_count += 1
        counts[bucket(c)] = counts.get(bucket(c), 0) + 1
        return True

    for key in {e["document_key"] for e in order if e["document_key"] in compared_docs}:
        for c in [x for x in order if x["document_key"] == key]:
            if take(c):
                break
    taken = sum(1 for c in order if c["chunk_id"] in keys and not c["is_table"])
    for c in order:
        if taken >= MIN_PROSE_PASSAGES or len(chosen) >= TOP_N:
            break
        if not c["is_table"] and take(c):
            taken += 1

    if prose_first:
        for c in order:
            if len(chosen) >= TOP_N:
                break
            if not c["is_table"]:
                if reason(c) is None:
                    take(c)
        for c in order:
            if len(chosen) >= TOP_N:
                break
            take(c)
    else:
        for c in order:
            if len(chosen) >= TOP_N:
                break
            take(c)
    return chosen, reasons


def order_sim_core():
    scored = [(e["similarity"] * (CORE_DOCUMENT_BOOST if e["is_core"] else 1.0), i, e)
              for i, e in enumerate(pool)]
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [e for _, _, e in scored]


for label, order in (("DEPLOYED_ORDER", pool), ("SIMx_CORE_ORDER", order_sim_core())):
    emit(f"===== {label} =====")
    for fill, prose_first in (("prose_first", True), ("score_fill", False)):
        chosen, reasons = run(order, prose_first)
        emit(f"  -- fill={fill}: {len(chosen)} chosen = "
             f"{sum(1 for c in chosen if not next(e for e in pool if e['chunk_id']==c)['is_table'])} prose / "
             f"{sum(1 for c in chosen if next(e for e in pool if e['chunk_id']==c)['is_table'])} tables")
        for pos, c in enumerate(order[:20], 1):
            if not c["is_table"]:
                continue
            tag = ""
            if c["chunk_id"] == TARGET:
                tag = "  <--TARGET"
            elif c["chunk_id"] == CONTROL:
                tag = "  <--CONTROL"
            status = "SELECTED" if c["chunk_id"] in chosen else f"EXCLUDED: {reasons.get(c['chunk_id'], 'window filled first')}"
            emit(f"     pos{pos:2d} table {c['chunk_id']} sim={c['similarity']:.6f} -> {status}{tag}")
    emit()

OUT.write_text("\n".join(lines), encoding="utf-8")
print("written", OUT)
