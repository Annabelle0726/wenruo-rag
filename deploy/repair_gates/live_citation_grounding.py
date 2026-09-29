"""Ground the citations of the just-produced live answer against the context it was given.

Reads the deployment-time acceptance capture (context ids + answer) and, for every context passage,
reports which nominal-section family it carries, so each [ID:n] the answer cites can be bound to a
passage that actually holds those values.
"""
import json
import pathlib
import re
import sys

sys.path.insert(0, "/ragflow")

from common import settings

settings.init_settings()

INDEX = "ragflow_a9e28731ab7011f19b833887d563fb04"
data = json.loads(pathlib.Path("/tmp/metadata_acceptance.json").read_text(encoding="utf-8"))
context = [c["chunk_id"] for c in data["D_context"]]
answer = data["D_answer"]

es = settings.docStoreConn.es
print(f"context passages: {len(context)}   answer chars: {len(answer)}")
print()
for n, cid in enumerate(context, 1):
    try:
        src = es.get(index=INDEX, id=cid)["_source"]
    except Exception as exc:  # noqa: BLE001
        print(f"  [ID:{n:2d}] {cid}  fetch error {type(exc).__name__}")
        continue
    text = " ".join(re.sub(r"<[^>]+>", " ", str(src.get("content_with_weight") or "")).split())
    three = sorted({int(v) for v in re.findall(r"3\s*[×x]\s*(\d{3,4})", text)})
    one = sorted({int(v) for v in re.findall(r"1\s*[×x]\s*(\d{3,4})", text)})
    doc = str(src.get("docnm_kwd") or "")[-28:]
    tag = ""
    if three == [400, 500, 630, 800, 1000, 1200, 1400, 1600]:
        tag = "  <<< THREE-CORE 8-spec family"
    if one == [400, 500, 630, 800, 1000, 1200, 1400, 1600, 1800, 2000]:
        tag += "  <<< SINGLE-CORE 10-spec family"
    print(f"  [ID:{n:2d}] {cid}  1x={one}  3x={three}  {doc}{tag}")

print()
print("cited labels in the answer:", sorted(set(re.findall(r"\[ID:(\d+)\]", answer))))
