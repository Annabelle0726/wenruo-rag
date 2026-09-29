"""Offline counterfactual over the RECORDED ordered pool. No re-retrieval, no parameter change.

Re-orders the captured 45-chunk pool by `similarity` alone (the value the model actually produced) and
reports where the authoritative passages land, then compares against the deployed ordering pass and the
final 12-slot window. This isolates how much of the loss is caused by the ordering nudges rather than by
the model's own relevance judgement.
"""
import json
import pathlib

TRACE = pathlib.Path("deploy/repair_gates/trace_qgdw_now.json")
TARGET, CONTROL = "d1d75672f2dbc333", "b5aaf72bcd33d44a"
TOP_N = 12

d = json.loads(TRACE.read_text(encoding="utf-8"))
prof = d["trace"]["selection"][0]["ordered_profile"]

by_similarity = sorted(prof, key=lambda e: e["similarity"], reverse=True)
sim_rank = {e["chunk_id"]: i for i, e in enumerate(by_similarity, 1)}
deployed_rank = {e["chunk_id"]: e["position"] for e in prof}

print("=== deployed ordering vs pure-similarity ordering ===")
for chunk_id, label in ((TARGET, "TARGET  d1d75672f2dbc333"), (CONTROL, "CONTROL b5aaf72bcd33d44a")):
    row = next(e for e in prof if e["chunk_id"] == chunk_id)
    print(f"{label}: is_table={row['is_table']} similarity={row['similarity']:.6f} "
          f"deployed_position={deployed_rank[chunk_id]:2d} pure_score_rank={sim_rank[chunk_id]:2d} "
          f"in_top12_deployed={deployed_rank[chunk_id] <= TOP_N} "
          f"in_top12_pure_score={sim_rank[chunk_id] <= TOP_N}")

print()
print("=== final 12-slot window composition (deployed) ===")
chosen = [e for e in prof if e["chosen"]]
print(f"chosen={len(chosen)} tables={sum(1 for e in chosen if e['is_table'])} "
      f"prose={sum(1 for e in chosen if not e['is_table'])}")
print("weakest chosen similarity :", min(e["similarity"] for e in chosen))
tables_pool = [e for e in prof if e["is_table"]]
print(f"pool tables={len(tables_pool)} pool prose={len(prof) - len(tables_pool)}")
print("first table at deployed position:", min(e["position"] for e in tables_pool))

print()
print("=== would pure-similarity ordering have admitted the authoritative tables? ===")
top12_sim = by_similarity[:TOP_N]
print(f"tables inside pure-score top-12: {sum(1 for e in top12_sim if e['is_table'])}")
for e in top12_sim:
    mark = ""
    if e["chunk_id"] == TARGET:
        mark = "  <-- TARGET"
    elif e["chunk_id"] == CONTROL:
        mark = "  <-- CONTROL"
    print(f"  {e['position']:2d}->{sim_rank[e['chunk_id']]:2d} table={str(e['is_table']):5s} "
          f"sim={e['similarity']:.6f} chosen_now={e['chosen']}{mark}")

print()
print("=== how many passages outrank the control/target, by each order ===")
for chunk_id, label in ((CONTROL, "CONTROL"), (TARGET, "TARGET")):
    row = next(e for e in prof if e["chunk_id"] == chunk_id)
    higher_sim = sum(1 for e in prof if e["similarity"] > row["similarity"])
    higher_sim_tables = sum(1 for e in prof if e["similarity"] > row["similarity"] and e["is_table"])
    print(f"{label}: outranked by {higher_sim} on similarity ({higher_sim_tables} of them tables); "
          f"deployed position {row['position']}")
