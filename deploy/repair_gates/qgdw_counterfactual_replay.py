"""Offline replay of the DEPLOYED ordering + selection on the FROZEN captured 45-chunk pool.

No retrieval, no product code executed, no parameter changed. Input is only
`trace_qgdw_now.json` (the pool captured from the deployed image) plus the deployed constants read
from the deployed `rag/retrieval/rerank.py`.

IDENTIFIABILITY, stated up front because it decides which variants are evidence and which are not:

* The capture records the deployed ORDER (positions 1..45) with `similarity`, `is_table`, `is_prose`,
  `document_key` per chunk. It does NOT record `is_hollow_table`, `carries_question_value`,
  `paired_value_with_result` or the deployed `rank_score`.
* Therefore the *total* table-side demotion is observable (order vs similarity order), but the SPLIT
  between TABLE_PENALTY (0.85), HOLLOW_TABLE_PENALTY (0.6) and VALUE_LIST_PENALTY (0.8) is NOT
  separately identifiable from this capture. Variants B and C are run under an order-consistent factor
  witness and are reported as NON-IDENTIFIABLE; variant D neutralises ALL table-specific factors and is
  fully identifiable (it reduces to ordering by `similarity x core_document_boost`, and core membership
  IS recorded via `document_key` against the recorded `core_documents`).

Selection is re-implemented from the deployed `select_context` source, and is accepted only if it
reproduces the captured baseline window exactly.
"""
import json
import math
import pathlib

TRACE = pathlib.Path("deploy/repair_gates/trace_qgdw_now.json")
OUT_TXT = pathlib.Path("deploy/repair_gates/qgdw_counterfactual_report.txt")
OUT_JSON = pathlib.Path("deploy/repair_gates/qgdw_counterfactual_result.json")

TARGET, CONTROL = "d1d75672f2dbc333", "b5aaf72bcd33d44a"
TOP_N = 12

# Deployed constants.
TABLE_PENALTY = 0.85
HOLLOW_TABLE_PENALTY = 0.6
VALUE_LIST_PENALTY = 0.8
VALUE_PAIRING_BOOST = 1.3
CORE_DOCUMENT_BOOST = 1.15
MAX_TABLE_SHARE = 0.5
MAX_AUXILIARY_DOCUMENT_SHARE = 0.4
MAX_COMPARED_DOCUMENT_SHARE = 0.5
MAX_HOLLOW_TABLE_PER_DOCUMENT_SHARE = 0.25
MIN_PROSE_PASSAGES = 4

lines = []


def emit(text=""):
    lines.append(str(text))


d = json.loads(TRACE.read_text(encoding="utf-8"))
sel = d["trace"]["selection"][0]
pool = sorted(sel["ordered_profile"], key=lambda e: e["position"])
policy = sel["policy"]
core_docs = set(policy["core_documents"])
compared_docs = set(policy["compared_documents"])
for e in pool:
    e["is_core"] = (not e["document_key"]) or (e["document_key"] in core_docs)

pre_order = sorted(pool, key=lambda e: e["similarity"], reverse=True)
pre_rank = {e["chunk_id"]: i for i, e in enumerate(pre_order, 1)}
captured_ids = [e["chunk_id"] for e in pool]
observed_window = [e["chunk_id"] for e in pool if e["chosen"]]

# ---- order-consistent factor witness (used ONLY for B/C; degenerate by construction) -----------------
def witness_factors(is_table, is_core):
    core = CORE_DOCUMENT_BOOST if is_core else 1.0
    if not is_table:
        return {"core": core, "pairing": 1.0, "table_penalty": 1.0, "hollow": 1.0, "value_list": 1.0}
    return {"core": core, "pairing": 1.0, "table_penalty": TABLE_PENALTY, "hollow": 1.0, "value_list": 1.0}


WITNESS = {e["chunk_id"]: witness_factors(e["is_table"], e["is_core"]) for e in pool}


def order_by(multiplier):
    scored = [(e["similarity"] * multiplier(e), i, e) for i, e in enumerate(pool)]
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [e for _, _, e in scored]


# ---- deployed select_context, re-implemented ---------------------------------------------------------
def select(order, top_n=TOP_N, prose_first=True, table_share=MAX_TABLE_SHARE,
           auxiliary_share=MAX_AUXILIARY_DOCUMENT_SHARE, compared_share=MAX_COMPARED_DOCUMENT_SHARE,
           min_prose=MIN_PROSE_PASSAGES):
    table_cap = top_n if table_share >= 1.0 else min(top_n, math.ceil(top_n * table_share))
    document_cap = 0 if auxiliary_share >= 1.0 else max(1, min(top_n, math.ceil(top_n * auxiliary_share)))
    every_document_cap = 0 if compared_share >= 1.0 else max(1, min(top_n, math.ceil(top_n * compared_share)))
    hollow_per_document_cap = max(1, min(top_n, math.ceil(top_n * MAX_HOLLOW_TABLE_PER_DOCUMENT_SHARE)))

    chosen, chosen_keys = [], set()
    table_count = 0
    document_counts, hollow_counts = {}, {}
    blockers = {}

    def bucket(chunk):
        return chunk["document_key"] or f"chunk:{chunk['chunk_id']}"

    def why_blocked(chunk):
        count = document_counts.get(bucket(chunk), 0)
        if every_document_cap and count >= every_document_cap:
            return f"compared_document_cap({every_document_cap})"
        if document_cap and not chunk["is_core"] and count >= document_cap:
            return f"auxiliary_document_cap({document_cap})"
        if chunk["is_table"] and table_count >= table_cap:
            return f"table_cap({table_cap})"
        return None

    def take(chunk, ignore_table_quota=False):
        nonlocal table_count
        if len(chosen) >= top_n or chunk["chunk_id"] in chosen_keys:
            return False
        if not ignore_table_quota:
            reason = why_blocked(chunk)
            if reason:
                blockers.setdefault(chunk["chunk_id"], reason)
                return False
        chosen.append(chunk["chunk_id"])
        chosen_keys.add(chunk["chunk_id"])
        if chunk["is_table"]:
            table_count += 1
        document_counts[bucket(chunk)] = document_counts.get(bucket(chunk), 0) + 1
        return True

    # 1b. one reserved slot per compared document
    for key in {e["document_key"] for e in order if e["document_key"] in compared_docs}:
        for chunk in [c for c in order if c["document_key"] == key]:
            if take(chunk):
                break

    # 2. prose floor
    if min_prose > 0:
        taken = sum(1 for c in order if c["chunk_id"] in chosen_keys and not c["is_table"])
        for chunk in order:
            if taken >= min_prose or len(chosen) >= top_n:
                break
            if not chunk["is_table"] and take(chunk):
                taken += 1

    # 3/4. the fill
    if table_cap < top_n and prose_first:
        for chunk in order:
            if len(chosen) >= top_n:
                break
            if not chunk["is_table"]:
                take(chunk)
        table_only = not any(not c["is_table"] for c in order)
        for chunk in order:
            if len(chosen) >= top_n:
                break
            take(chunk, ignore_table_quota=table_only and chunk["is_table"])
    else:
        for chunk in order:
            if len(chosen) >= top_n:
                break
            take(chunk)

    # `select_context` returns the selection in `ordered` order.
    return [c["chunk_id"] for c in order if c["chunk_id"] in chosen_keys], blockers


def report(name, order, chosen, blockers, note):
    by_id = {e["chunk_id"]: e for e in order}
    adj_rank = {cid: i for i, cid in enumerate([e["chunk_id"] for e in order], 1)}
    sel = set(chosen)
    selected_chunks = [by_id[c] for c in chosen]
    tables = sum(1 for c in selected_chunks if c["is_table"])
    rows = {}
    for cid, label in ((TARGET, "target"), (CONTROL, "control")):
        rows[label] = {
            "pre_adjustment_rank": pre_rank[cid],
            "adjusted_rank": adj_rank[cid],
            "inside_top12_before_selection": adj_rank[cid] <= TOP_N,
            "selected": cid in sel,
            "blocked_by": None if cid in sel else (blockers.get(cid) or "outside_top_n_fill"),
        }
    return {
        "variant": name, "note": note,
        "final_size": len(chosen),
        "tables_in_final": tables,
        "prose_in_final": len(chosen) - tables,
        "weakest_selected_similarity": min((c["similarity"] for c in selected_chunks), default=None),
        "authoritative_tables_selected": sum(1 for cid in (TARGET, CONTROL) if cid in sel),
        "target": rows["target"], "control": rows["control"],
        "final_ids": chosen,
    }


# ---- validations -------------------------------------------------------------------------------------
emit("=== VALIDATION 1: pre-adjustment pool order ===")
emit(f"  recorded pre-adjustment ranks: target={d['trace']['merges'][0]['target_pool_rank']} "
     f"control={d['trace']['rerank'][0]['control_pool_rank']}")
emit(f"  similarity-order ranks        : target={pre_rank[TARGET]} control={pre_rank[CONTROL]}")
pre_ok = (pre_rank[TARGET] == d["trace"]["merges"][0]["target_pool_rank"]
          and pre_rank[CONTROL] == d["trace"]["rerank"][0]["control_pool_rank"])
emit(f"  PRE_ORDER_IS_SIMILARITY_ORDER = {pre_ok}")
emit()

emit("=== VALIDATION 2: selection replay vs captured window ===")
baseline_chosen, baseline_blockers = select(pool, prose_first=True)
emit(f"  captured ({len(observed_window)}): {observed_window}")
emit(f"  replayed ({len(baseline_chosen)}): {baseline_chosen}")
sel_ok = observed_window == baseline_chosen
emit(f"  SELECTION_REPLAY_MATCHES_CAPTURE = {sel_ok}")
emit()

# ---- variants ----------------------------------------------------------------------------------------
variants = {}

variants["A_BASELINE"] = report("A_BASELINE", pool, baseline_chosen, baseline_blockers,
                                "captured deployed order + deployed prose-first selection")

# B / C: table factors split by an order-consistent witness -> NOT separately identifiable.
def order_with(neutralise):
    def mult(e):
        f = dict(WITNESS[e["chunk_id"]])
        value = 1.0
        for key in ("core", "pairing", "table_penalty", "hollow", "value_list"):
            value *= 1.0 if key in neutralise else f[key]
        return value
    return order_by(mult)


ob = order_with({"table_penalty"})
variants["B_TABLE_PENALTY_ONLY_NEUTRALISED"] = report(
    "B_TABLE_PENALTY_ONLY_NEUTRALISED", ob, *select(ob, prose_first=True),
    "table_penalty removed; NON-IDENTIFIABLE split (see header)")

oc = order_with({"value_list"})
variants["C_VALUE_LIST_ONLY_NEUTRALISED"] = report(
    "C_VALUE_LIST_ONLY_NEUTRALISED", oc, *select(oc, prose_first=True),
    "value_list removed; NON-IDENTIFIABLE split (see header)")

# D: all table-specific factors off -> order by similarity x core_document_boost (identifiable).
def mult_d(e):
    return (CORE_DOCUMENT_BOOST if e["is_core"] else 1.0)


od = order_by(mult_d)
variants["D_ALL_TABLE_PENALTIES_NEUTRALISED"] = report(
    "D_ALL_TABLE_PENALTIES_NEUTRALISED", od, *select(od, prose_first=True),
    "similarity x core boost, prose-first kept")

# E: captured scores, prose-first relaxed only.
ve, eb = select(pool, prose_first=False)
variants["E_PROSE_FIRST_RELAXED_ONLY"] = report(
    "E_PROSE_FIRST_RELAXED_ONLY", pool, ve, eb,
    "captured adjusted order, score fill, caps unchanged")

# F: D + E.
vf, fb = select(od, prose_first=False)
variants["F_COMBINED"] = report(
    "F_COMBINED", od, vf, fb, "no table-specific penalties + score fill")

# G: pure score control.
og = order_by(lambda e: 1.0)
vg, gb = select(og, prose_first=False, table_share=1.0, auxiliary_share=1.0, compared_share=1.0, min_prose=0)
variants["G_PURE_SCORE"] = report(
    "G_PURE_SCORE", og, vg, gb, "raw similarity top-12, no penalties, no caps, no prose-first")

for key in ("A_BASELINE", "B_TABLE_PENALTY_ONLY_NEUTRALISED", "C_VALUE_LIST_ONLY_NEUTRALISED",
            "D_ALL_TABLE_PENALTIES_NEUTRALISED", "E_PROSE_FIRST_RELAXED_ONLY", "F_COMBINED", "G_PURE_SCORE"):
    r = variants[key]
    emit(f"--- {key}")
    emit(f"    {r['note']}")
    emit(f"    final: {r['final_size']} = {r['prose_in_final']} prose / {r['tables_in_final']} tables"
         f" | weakest selected sim={r['weakest_selected_similarity']:.6f}"
         f" | authoritative tables selected={r['authoritative_tables_selected']}/2")
    for label in ("target", "control"):
        row = r[label]
        emit(f"    {label.upper():8s} pre-rank={row['pre_adjustment_rank']:2d} adjusted-rank={row['adjusted_rank']:2d} "
             f"inside_top12_before_selection={str(row['inside_top12_before_selection']):5s} "
             f"selected={str(row['selected']):5s} blocked_by={row['blocked_by']}")
    emitted = sorted(set(r["final_ids"]))
    emit(f"    table ids in final: {[c for c in r['final_ids'] if next(e for e in pool if e['chunk_id']==c)['is_table']]}")
    emit()

emit("=== IDENTIFIABILITY NOTE ===")
emit("  B and C cannot be separated as causes from this capture: the capture holds no per-chunk")
emit("  is_hollow_table / carries_question_value / paired_value_with_result flags, so the total table-side")
emit("  demotion is observable but its split across TABLE_PENALTY / HOLLOW_TABLE_PENALTY /")
emit("  VALUE_LIST_PENALTY is not. D neutralises ALL table-specific factors and is therefore the")
emit("  identifiable bound on the whole score-side lever.")

OUT_TXT.write_text("\n".join(lines), encoding="utf-8")
OUT_JSON.write_text(json.dumps({"validations": {"pre_order_is_similarity_order": pre_ok,
                                                "selection_replay_matches_capture": sel_ok},
                                "variants": variants}, ensure_ascii=False, indent=1), encoding="utf-8")
print("written", OUT_TXT)
print("SELECTION_REPLAY_MATCHES_CAPTURE =", sel_ok)
