"""Three-core evidence check: does ANY final passage carry Part 3 / Q/GDW 73286.3 Table 1 content?"""
import json
import pathlib

A = json.loads(pathlib.Path("deploy/repair_gates/ab_A_production.json").read_text(encoding="utf-8"))
B = json.loads(pathlib.Path("deploy/repair_gates/ab_out/ab_B.json").read_text(encoding="utf-8"))
MARKERS = ["73286.3", "三芯", "第3部分", "第 3 部分", "73286.3-2026"]

for label, d in (("A", A), ("B", B)):
    print(f"=== arm {label}")
    hits = []
    for n, p in enumerate(d["passages"], 1):
        found = [m for m in MARKERS if m in p["body_head"] or m in p["document"]]
        if found:
            hits.append((n, p["chunk_id"], found))
    print(f"  passages carrying three-core markers: {hits if hits else 'NONE'}")
    ans = d["answer"]
    print(f"  answer mentions three-core topic   : {('三芯' in ans) or ('73286.3' in ans)}")
    print(f"  answer states three-core unavailable: "
          f"{any(k in ans for k in ('未收录', '暂未收录', '没有收录', '查不到', '无法为您提供'))}")
    print(f"  answer states single-core count    : {('10' in ans and '规格' in ans)}")
    print(f"  answer states single-core range    : {('400' in ans and '2000' in ans)}")
