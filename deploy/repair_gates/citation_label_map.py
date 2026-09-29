"""Which passage in the AFTER context actually carries the 8 three-core specs? Read-only.

Searches every passage of the repaired-run context for the 3x400..3x1600 family, and reports the
label each chunk would receive under the assistant's 1-based prompt labelling (the order the pipeline
hands the passages to `kb_prompt`), so the cited [ID:2] can be bound to a chunk with evidence.
"""
import json
import pathlib
import re
import sys

sys.path.insert(0, "/ragflow")

from common import settings  # noqa: E402

settings.init_settings()

INDEX = "ragflow_a9e28731ab7011f19b833887d563fb04"
CONTEXT = ['255c187f4e228542', 'd4d2304290d345b0', '423069af31359e65', 'd5f07f5d24ec3cc7',
           'ab96130b7a5d5c8f', 'c7347587e61a3532', 'a14eb97907268118', '980ed72de1325b3d',
           '43e96b415797394b', 'a0bd8a6bde77b17e', '9fa9e164a3e3ca7a', '8065ad3f4096ca30']
EXPECTED = [400, 500, 630, 800, 1000, 1200, 1400, 1600]

es = settings.docStoreConn.es
hits = []
for cid in CONTEXT:
    try:
        src = es.get(index=INDEX, id=cid)["_source"]
    except Exception as exc:  # noqa: BLE001
        print(f"  {cid}: fetch error {type(exc).__name__}")
        continue
    content = str(src.get("content_with_weight") or "")
    text = " ".join(re.sub(r"<[^>]+>", " ", content).split())
    three = sorted({int(v) for v in re.findall(r"3\s*[×x]\s*(\d{3,4})", text)})
    caption = (re.search(r"<caption[^>]*>(.*?)</caption>", content, re.S) or [None, "-"])[1]
    hits.append((cid, three, caption, str(src.get("docnm_kwd") or "")[-40:]))

print("=== context passages and the three-core 3xNNN family they carry ===")
for n, (cid, three, caption, doc) in enumerate(hits, 1):
    mark = "  <<< CARRIES THE 8 SPECS" if three == EXPECTED else ""
    print(f"  [ID:{n:2d}] {cid}  3xNNN={three}  caption={caption[:38]!r}{mark}")

carriers = [cid for cid, three, _c, _d in hits if three == EXPECTED]
print()
print("passages carrying exactly 3x400..3x1600 :", carriers)
print("their prompt labels                      :",
      [f"[ID:{n}]" for n, (cid, three, _c, _d) in enumerate(hits, 1) if three == EXPECTED])
print("any passage carrying ANY 3xNNN          :",
      [f"[ID:{n}]" for n, (cid, three, _c, _d) in enumerate(hits, 1) if three])
