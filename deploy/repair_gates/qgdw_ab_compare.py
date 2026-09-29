"""Side-by-side A/B comparison of the two captured end-to-end runs."""
import json
import pathlib

A = json.loads(pathlib.Path("deploy/repair_gates/ab_A_production.json").read_text(encoding="utf-8"))
B = json.loads(pathlib.Path("deploy/repair_gates/ab_out/ab_B.json").read_text(encoding="utf-8"))

out = []


def e(t=""):
    out.append(str(t))


e("=" * 100)
e("ARM A - PRODUCTION (old rerank.py)")
e(f"  rerank sha256 : {A['rerank_sha256']}")
e(f"  answer_length : {A['answer_length']}   context={A['context_size']} "
  f"({A['context_tables']} tables / {A['context_prose']} prose)")
e(f"  health        : {json.dumps(A['retrieval_health'], ensure_ascii=False)}")
e(f"  control       : {A['control_present']}   target: {A['target_present']}")
e(f"  section passages: {A['passages_with_section_table']}")
e("  context ids in order:")
for n, c in enumerate(A["context_chunk_ids_in_order"], 1):
    p = next(x for x in A["passages"] if x["chunk_id"] == c)
    e(f"    {n:2d}. {'TABLE' if p['is_table'] else 'prose'} {c}  {p['document'][:60]}")
e()
e("  ANSWER (production):")
e(A["answer"])
e()
e("=" * 100)
e("ARM B - CANDIDATE (repaired rerank.py)")
e(f"  rerank sha256 : {B['rerank_sha256']}")
e(f"  answer_length : {B['answer_length']}   context={B['context_size']} "
  f"({B['context_tables']} tables / {B['context_prose']} prose)")
e(f"  health        : {json.dumps(B['retrieval_health'], ensure_ascii=False)}")
e(f"  control       : {B['control_present']}   target: {B['target_present']}")
e(f"  section passages: {B['passages_with_section_table']}")
e("  context ids in order:")
for n, c in enumerate(B["context_chunk_ids_in_order"], 1):
    p = next(x for x in B["passages"] if x["chunk_id"] == c)
    e(f"    {n:2d}. {'TABLE' if p['is_table'] else 'prose'} {c}  {p['document'][:60]}")
e()
e("  ANSWER (candidate):")
e(B["answer"])
e()
e("=" * 100)
e("CONTEXT DIFF")
ia, ib = A["context_chunk_ids_in_order"], B["context_chunk_ids_in_order"]
e(f"  identical order            : {ia == ib}")
e(f"  identical as a set         : {set(ia) == set(ib)}")
e(f"  only in A                  : {sorted(set(ia) - set(ib))}")
e(f"  only in B                  : {sorted(set(ib) - set(ia))}")
e(f"  same order, shared prefix  : {sum(1 for x, y in zip(ia, ib) if x == y)}/12 positions equal")
e()
e("EVIDENCE PASSAGE CONTENT (the passages that hold a conductor nominal-section table)")
for arm, data in (("A", A), ("B", B)):
    for cid in data["passages_with_section_table"]:
        p = next(x for x in data["passages"] if x["chunk_id"] == cid)
        e(f"  [{arm}] {cid} table={p['is_table']} probes={p['probe_hits']}")
        e(f"      {p['body_head'][:760]}")
e()
e("ALL FINAL PASSAGES: probe hits (does the passage even name conductor nominal sections?)")
for arm, data in (("A", A), ("B", B)):
    e(f"  --- arm {arm}")
    for n, p in enumerate(data["passages"], 1):
        e(f"    {n:2d}. {'T' if p['is_table'] else 'p'} {p['chunk_id']} section_table={p['has_section_table']} "
          f"hits={p['probe_hits']}")

pathlib.Path("deploy/repair_gates/ab_comparison.txt").write_text("\n".join(out), encoding="utf-8")
print("written deploy/repair_gates/ab_comparison.txt", len(out), "lines")
