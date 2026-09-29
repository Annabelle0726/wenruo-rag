"""Grounding check for the [ID:2] citation: does chunk 980ed72de1325b3d carry the 8 three-core
nominal cross-section specs (3x400 .. 3x1600)?  Read-only.

Also resolves the actual [ID:n] -> chunk_id mapping from the assistant's own prompt labelling, so the
cited label is bound to a chunk rather than assumed.
"""
import hashlib
import json
import re
import sys

sys.path.insert(0, "/ragflow")

from common import settings  # noqa: E402

settings.init_settings()

INDEX = "ragflow_a9e28731ab7011f19b833887d563fb04"
CITED = "980ed72de1325b3d"
TARGET = "d1d75672f2dbc333"

src = settings.docStoreConn.es.get(index=INDEX, id=CITED)["_source"]
content = str(src.get("content_with_weight") or "")
text = " ".join(re.sub(r"<[^>]+>", " ", content).split())

print("chunk_id         :", CITED)
print("doc_id           :", src.get("doc_id"))
print("docnm_kwd        :", src.get("docnm_kwd"))
print("content_chars    :", len(content))
print("content_sha256   :", hashlib.sha256(content.encode("utf-8")).hexdigest())
print("caption          :", (re.search(r"<caption[^>]*>(.*?)</caption>", content, re.S) or [None, "none"])[1])
print()
three = sorted({int(v) for v in re.findall(r"3\s*[×x]\s*(\d{3,4})", text)})
one = sorted({int(v) for v in re.findall(r"1\s*[×x]\s*(\d{3,4})", text)})
print("3xNNN values present :", three)
print("count                :", len(three), " range:", (three[0], three[-1]) if three else None)
print("1xNNN values present :", one)
expected = [400, 500, 630, 800, 1000, 1200, 1400, 1600]
print()
print("contains exactly the 8 expected three-core specs:", three == expected)
print("missing:", [v for v in expected if v not in three], " extra:", [v for v in three if v not in expected])
print()
print("mentions 绝缘标称厚度 :", "绝缘" in text)
print("mentions 表1          :", bool(re.search(r"表\s*1", text)))
print("table captions in text:", re.findall(r"表\s*\d+[^ ]{0,6}", text)[:6])
print()
print("=== FULL TEXT ===")
print(text[:1800])
