"""Citation grounding for the chain acceptance answer. Read-only.

Binds every [ID:n] marker in the final answer to the chunk the assistant itself
numbered it over (`_rag_cite_chunk_ids`, i.e. the composer's cite pool in label
order), then verifies from Elasticsearch that the cited passage actually carries
the facts the sentence asserts — so a citation is checked against the corpus, not
against the wording of the answer.

usage: python citation_grounding_chain.py <agentic_chain_acceptance.json> <label>
"""
import hashlib
import json
import pathlib
import re
import sys

sys.path.insert(0, "/ragflow")

from common import settings  # noqa: E402

settings.init_settings()

path = pathlib.Path(sys.argv[1])
label = sys.argv[2] if len(sys.argv) > 2 else "run"
data = json.loads(path.read_text(encoding="utf-8"))

answer = data.get("final_answer") or ""
ev = data["boundaries"]["B7_compose_evidence"]
cite_ids = [str(c) for c in ev.get("cite_chunk_ids") or []]
INDEX = None

TARGET_FAMILY = [400, 500, 630, 800, 1000, 1200, 1400, 1600]
CONTROL_FAMILY = [400, 500, 630, 800, 1000, 1200, 1400, 1600, 1800, 2000]

es = settings.docStoreConn.es
if INDEX is None:
    # The KB index is named for the owning tenant: ragflow_<tenant_id>.
    from api.db.services.knowledgebase_service import KnowledgebaseService

    kb = KnowledgebaseService.get_by_id(data["runtime"]["kb_ids"][0])[1]
    INDEX = getattr(kb, "index_name", None) or ("ragflow_" + kb.tenant_id)

print("=== CITATION GROUNDING :: %s ===" % label)
print("index            :", INDEX)
print("answer chars     :", len(answer))
print("cite pool        : %d chunk(s)" % len(cite_ids))
print("cite pool ids    :", cite_ids)
print()

markers = sorted({int(m) for m in re.findall(r"\[ID:\s*(\d+)\]", answer)})
print("markers used     :", ["[ID:%d]" % m for m in markers])
out_of_range = [m for m in markers if m < 1 or m > len(cite_ids)]
print("markers outside the cite pool :", out_of_range)
print()


def fetch(cid):
    try:
        src = es.get(index=INDEX, id=cid)["_source"]
    except Exception as exc:  # noqa: BLE001
        return None, "fetch-error:%s" % type(exc).__name__
    return src, None


def families(text):
    three = sorted({int(v) for v in re.findall(r"3\s*[×x]\s*(\d{3,4})", text)})
    one = sorted({int(v) for v in re.findall(r"1\s*[×x]\s*(\d{3,4})", text)})
    return three, one


rows = []
for n, cid in enumerate(cite_ids, 1):
    src, err = fetch(cid)
    if err:
        rows.append((n, cid, "ERR " + err, [], [], "", ""))
        continue
    content = str(src.get("content_with_weight") or "")
    text = " ".join(re.sub(r"<[^>]+>", " ", content).split())
    three, one = families(text)
    rows.append((n, cid, "ok", three, one,
                 str(src.get("docnm_kwd") or "")[-46:],
                 hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]))

print("=== cite pool, label order (this IS the [ID:n] numbering basis) ===")
for n, cid, status, three, one, doc, chash in rows:
    cited = "[ID:%d]" % n in answer or "[ID:%d]" % n in answer
    flag = ""
    if three == TARGET_FAMILY:
        flag = "  <<< carries the 8 THREE-CORE specs 3x400..3x1600"
    elif one == CONTROL_FAMILY:
        flag = "  <<< carries the 10 SINGLE-CORE specs 1x400..1x2000"
    print("  [ID:%2d] %s %s 3x=%s 1x=%s%s" % (n, cid, status, three or "-", one or "-", flag))
    print("           doc=%r content_sha=%s" % (doc, chash))

print()
print("=== per-marker binding ===")
for m in markers:
    if m < 1 or m > len(rows):
        print("  [ID:%d] -> OUT OF RANGE" % m)
        continue
    n, cid, status, three, one, doc, chash = rows[m - 1]
    three_ok = three == TARGET_FAMILY
    one_ok = one == CONTROL_FAMILY
    print("  [ID:%d] -> %s  three_core_exact=%s single_core_exact=%s" % (m, cid, three_ok, one_ok))

print()
three_cite = [m for m in markers if 1 <= m <= len(rows) and rows[m - 1][3] == TARGET_FAMILY]
one_cite = [m for m in markers if 1 <= m <= len(rows) and rows[m - 1][4] == CONTROL_FAMILY]
print("markers bound to a passage carrying exactly 3x400..3x1600 :", ["[ID:%d]" % m for m in three_cite])
print("markers bound to a passage carrying exactly 1x400..1x2000 :", ["[ID:%d]" % m for m in one_cite])

claims_three = "3\u00d7400" in answer and "3\u00d71600" in answer
claims_one = "1\u00d7400" in answer and "1\u00d72000" in answer
claims_three_count = bool(re.search(r"8\s*(种|个)?\s*规格|8 \u79cd", answer))
claims_one_count = bool(re.search(r"10\s*(种|个)?\s*规格|10 \u79cd", answer))
print()
print("answer asserts three-core 3x400..3x1600 :", claims_three)
print("answer asserts single-core 1x400..1x2000:", claims_one)
print("answer asserts a count of 8             :", claims_three_count)
print("answer asserts a count of 10            :", claims_one_count)
print()
print("GROUNDED = every asserted fact family has a marker bound to a carrying passage")
print("  three-core claim grounded :", (not claims_three) or bool(three_cite))
print("  single-core claim grounded:", (not claims_one) or bool(one_cite))
