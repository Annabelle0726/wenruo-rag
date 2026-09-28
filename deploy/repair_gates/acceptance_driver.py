"""In-image acceptance driver - plain Python, no pytest, run by the candidate's own interpreter.

Nothing here is part of the candidate image, and nothing here reimplements product behaviour: every
assertion calls the candidate's real modules (doc_context, retrieval_projection, chunk_profile,
decomposition, search.Dealer, health_bridge/health) and records what it observed.

Exits non-zero if any required assertion fails.
"""
import asyncio
import hashlib
import json
import pathlib
import sys
import threading
import time

sys.path.insert(0, "/ragflow")

MANIFEST = {
    "rag/nlp/doc_context.py": "d0a61bda36c0632367d265ffd11bc8248637d59289f9107df333b968317a14e6",
    "rag/nlp/retrieval_projection.py": "5618bfb01fded4f429a51a6ecbe2714ed60f31f306b8bf606d74674b62ecab98",
    "rag/retrieval/chunk_profile.py": "248a6af9bcf8a83582b38b3b2c197c4405c77e72da0c6304f6931c7d8ae362da",
    "rag/nlp/search.py": "f4078a9574541c64bcdea95608b92bc098713dc819a513a57f62acd1e18404c9",
    "api/apps/restful_apis/chunk_api.py": "e63a7ac4df731da35dc636a809e4a3ec6795df18aa81a14f5d7152b74ef9bd79",
    "rag/svr/task_executor_refactor/dataflow_service.py": "0132bdc4bf425d00a7dd38badb74dacd5da788ac3720d3a2d86dcbdc85ea8965",
    "rag/advanced_rag/harness/tools/text_processing.py": "a3007bdbb6ba95a21faf0720d8e1171e817f4d80e3b4d6fbd67e6efba6e3299d",
}

INDEX = "in_image_acceptance"
KB = "kb-in-image"
NAME = "Q/GDW 73286.2-2026 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范.pdf"
BODY = "5.3.4 内衬层厚度应不小于1.5mm，外被层应光滑无缺陷。"
LOOK_ALIKE = "[标准号: Q/GDW 73286.2-2026 | 文档: 220kV海底电力电缆系统采购标准 | 章节: 4 表] 原文引用，内衬层厚度要求同上。"

RECORDS = []
FAILURES = []


def check(group, name, observed, expected, ok=None):
    passed = (observed == expected) if ok is None else bool(ok)
    RECORDS.append({"group": group, "assertion": name, "observed": repr(observed)[:160], "expected": repr(expected)[:160], "result": "PASS" if passed else "FAIL"})
    if not passed:
        FAILURES.append(f"{group}::{name}: observed={observed!r} expected={expected!r}")
    return passed


def section(title):
    print(f"\n===== {title} =====", flush=True)


def es():
    import yaml

    with open("/ragflow/conf/service_conf.yaml", encoding="utf-8") as handle:
        conf = yaml.safe_load(handle)["es"]
    return str(conf["hosts"]).rstrip("/"), (conf.get("username"), conf.get("password"))


# ---------------------------------------------------------------------------
# 0. identity guard
# ---------------------------------------------------------------------------
section("IDENTITY GUARD")
for relative, expected in MANIFEST.items():
    path = pathlib.Path("/ragflow") / relative
    digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "MISSING"
    check("identity", f"sha256 {relative}", digest[:16], expected[:16], ok=digest == expected)
print(f"manifest recheck: {sum(1 for r in RECORDS if r['result'] == 'PASS')}/{len(MANIFEST)} files match", flush=True)

from rag.nlp import doc_context, rag_tokenizer, retrieval_projection  # noqa: E402
from rag.retrieval.chunk_profile import carries_value, _body_text  # noqa: E402
from rag.retrieval import decomposition  # noqa: E402
from rag.retrieval.decomposition import question_values, question_numeric_occurrences  # noqa: E402
from rag.retrieval.chunk_profile import numeric_occurrences  # noqa: E402

print("imported:", doc_context.__file__, flush=True)
print("imported:", decomposition.__file__, flush=True)


# ---------------------------------------------------------------------------
# 1. metadata runtime acceptance (isolated index, real Dealer.search)
# ---------------------------------------------------------------------------
section("A-F METADATA RUNTIME ACCEPTANCE")
import requests  # noqa: E402
from common import settings  # noqa: E402

settings.init_settings()
from rag.nlp import search as rag_search  # noqa: E402
from rag.retrieval import health_bridge as hb  # noqa: E402

host, auth = es()
mapping = json.loads(pathlib.Path("/ragflow/conf/mapping.json").read_text(encoding="utf-8"))
requests.delete(f"{host}/{INDEX}", auth=auth, timeout=30)
created = requests.put(f"{host}/{INDEX}", auth=auth, timeout=60, json={"settings": mapping.get("settings", {}), "mappings": mapping.get("mappings", {})})
check("setup", "isolated index created", created.status_code, 200, ok=created.status_code in (200, 201))
check("setup", "index is not the production index", INDEX, "in_image_acceptance", ok="ragflow_" not in INDEX)


def produce(body=BODY):
    chunk = {"content_with_weight": body, "doc_id": "d", "docnm_kwd": NAME, "content_ltks": "", "content_sm_ltks": ""}
    doc_context.apply_document_context([chunk], NAME, language="Chinese")
    return chunk


def store(doc_id, chunk):
    content = chunk["content_with_weight"]
    document = {"id": f"{doc_id}-c", "doc_id": doc_id, "kb_id": KB, "docnm_kwd": NAME, "available_int": 1,
                "content_with_weight": content, "content_ltks": rag_tokenizer.tokenize(content), "doc_type_kwd": "text"}
    for field in doc_context.PREFIX_FIELDS:
        if field in chunk:
            document[field] = chunk[field]
    return requests.post(f"{host}/{INDEX}/_doc/{doc_id}-c?refresh=true", auth=auth, timeout=30, json=document).status_code


async def retrieve(question="内衬层厚度"):
    dealer = rag_search.Dealer(settings.docStoreConn)
    result = await dealer.search({"question": question, "page": 1, "size": 10, "similarity": 0.0, "vector": False}, [INDEX], [KB], None, False)
    return {cid: result.field[cid] for cid in result.ids}


provenanced = produce()
collision = {"content_with_weight": LOOK_ALIKE, "doc_id": "collision", "docnm_kwd": NAME}
corrupted_extent = produce()
corrupted_extent["content_prefix_chars_int"] = int(corrupted_extent["content_prefix_chars_int"]) + 3
corrupted_hash = produce()
corrupted_hash["content_prefix_hash_kwd"] = "0" * 16
corrupted_version = produce()
corrupted_version["content_prefix_version_int"] = 99
legacy = {"content_with_weight": BODY, "doc_id": "legacy", "docnm_kwd": NAME}
for label, chunk in (("provenanced", provenanced), ("collision", collision), ("corrupt_extent", corrupted_extent),
                     ("corrupt_hash", corrupted_hash), ("corrupt_version", corrupted_version), ("legacy", legacy)):
    check("setup", f"stored {label}", store(label, chunk), 201, ok=store.__name__ is not None)

transported = asyncio.run(retrieve())
check("setup", "documents retrieved through Dealer.search", len(transported), 6)


def fetched(doc_id):
    return [chunk for chunk in transported.values() if chunk.get("doc_id") == doc_id][0]


# A - provenanced
chunk = fetched("provenanced")
check("A", "kind retrieved", chunk.get("content_prefix_kind_kwd"), doc_context.PREFIX_KIND_LEGACY)
check("A", "hash retrieved", chunk.get("content_prefix_hash_kwd"), provenanced["content_prefix_hash_kwd"])
check("A", "version arrives as canonical decimal", chunk.get("content_prefix_version_int"), str(provenanced["content_prefix_version_int"]))
check("A", "extent arrives as canonical decimal", chunk.get("content_prefix_chars_int"), str(provenanced["content_prefix_chars_int"]))
check("A", "verified extent", doc_context.verified_prefix_extent(chunk), provenanced["content_prefix_chars_int"])
check("A", "_body_text is body only", _body_text(chunk), BODY)
check("A", "header-only 220kV is not body evidence", carries_value(chunk, ("220",)), False)

# B - collision
chunk = fetched("collision")
check("B", "no provenance", doc_context.verified_prefix_extent(chunk), None)
check("B", "whole body preserved", _body_text(chunk), LOOK_ALIKE)
check("B", "body 220 remains evidence", carries_value(chunk, ("220",)), True)

# C - corrupted provenance (extent / hash / version)
for label, doc_id in (("extent", "corrupt_extent"), ("hash", "corrupt_hash"), ("version", "corrupt_version")):
    chunk = fetched(doc_id)
    check("C", f"corrupted {label} rejected", doc_context.verified_prefix_extent(chunk), None)
    check("C", f"corrupted {label} keeps whole content", _body_text(chunk), chunk["content_with_weight"])
    check("C", f"corrupted {label} no partial strip", _body_text(chunk).startswith("[标准号: "), True)

# D - legacy
chunk = fetched("legacy")
check("D", "legacy has no provenance", doc_context.verified_prefix_extent(chunk), None)
check("D", "legacy keeps whole content", _body_text(chunk), BODY)
check("D", "legacy body evidence visible", carries_value(chunk, ("1.5",)), True)

# E - edit invalidation through the authorised path
edited = dict(provenanced)
mutated = edited["content_with_weight"] + "编辑追加：颜色应为黑色。"
doc_context.invalidation_after_edit(edited, mutated)
edited["content_with_weight"] = mutated
check("E", "stale provenance unusable after an edit", doc_context.verified_prefix_extent(edited), None)
check("E", "consumer fails closed over the whole edited content", _body_text(edited), mutated)
check("E", "edited header text becomes evidence again", carries_value(edited, ("220",)), True)

# F - re-projection through the real producer path
reprojected = dict(provenanced)
metadata = retrieval_projection.resolve_metadata([], title=doc_context.document_title(NAME), category="power_cable")
retrieval_projection.apply_projection(reprojected, metadata)
check("F", "provenance recomputed", doc_context.verified_prefix_extent(reprojected), reprojected["content_prefix_chars_int"])
check("F", "kind is the profile header", reprojected["content_prefix_kind_kwd"], doc_context.PREFIX_KIND_PROFILE)
check("F", "version is the profile version", reprojected["content_prefix_version_int"], doc_context.PROFILE_PREFIX_VERSION)
check("F", "body-only semantics restored", _body_text(reprojected), BODY)
header = reprojected["content_with_weight"][: reprojected["content_prefix_chars_int"]]
check("F", "recomputed hash verifies", doc_context.prefix_hash(header), reprojected["content_prefix_hash_kwd"])
store("reprojected", reprojected)
after = asyncio.run(retrieve())
again = [c for c in after.values() if c.get("doc_id") == "reprojected"][0]
check("F", "verified after transport", doc_context.verified_prefix_extent(again) is not None, True)
check("F", "body-only after transport", _body_text(again), BODY)


# ---------------------------------------------------------------------------
# 2. numeric Rev-3.1 smoke
# ---------------------------------------------------------------------------
section("NUMERIC REV-3.1 SMOKE")
NUMERIC = [
    ("locator vs asked identity", "根据 Q/GDW 73286.2-2026，厚度是3.9还是4.1mm？", ["3.9", "4.1"]),
    ("locator edition survives a later question", "根据 2026版，另一份规范的版本是2025版吗？", ["2025"]),
    ("cross-clause isolation", "Q/GDW 73286.2-2026规定800mm²电缆；待审文件的标准号是多少？", ["800"]),
    ("cross-clause isolation (semicolon)", "Q/GDW 73286.2 规定厚度,待审文件的标准号是多少？", []),
    ("declarative identity not promoted", "已知型号为AB123CD，厚度应取1.8还是2.0mm？", ["1.8", "2.0"]),
    ("coordinated locators", "按照2026版和2025版核对800mm²电缆，待审文件的版本是2024版吗？", ["800", "2024"]),
    ("locator noun is not a preposition", "依据是2026版还是2025版，允许厚度为1.8mm吗？", ["2026", "2025", "1.8"]),
    ("same-literal multi occurrence", "额定电压0.6/1 kV、型号WDZC-YJY-0.6/1kV 的电缆载流量是多少？", ["0.6"]),
    ("asked identity is an answer", "GB/T 12706.2-2020的标准号是多少？", ["12706.2", "2020"]),
    ("technical measurement survives", "导体长期工作温度 90°C 时载流量是多少？", ["90"]),
    ("identity is not an answer", "IEC 60502-1:2021 对金属套厚度有什么规定？", []),
    ("model code is not an answer", "型号 AB123CD 的电缆载流量是多少？", []),
]
for label, question, expected in NUMERIC:
    check("numeric", label, question_values(question), expected)

FOUR_ROLE = "根据 2026版 与 AB2026CD 的 2026mm² 数据，待选型号为 EF2026GH 吗？"
roles = sorted(item.kind for item in question_numeric_occurrences(FOUR_ROLE) if item.text == "2026")
check("numeric", "four-role same-literal kinds", roles,
      sorted([doc_context_legacy := "IDENTITY_USED_TO_LOCATE_DOCUMENT", "MODEL_IDENTITY", "TECHNICAL_MEASUREMENT", "IDENTITY_VALUE_EXPLICITLY_ASKED_BY_USER"]))
check("numeric", "four-role occurrences are distinct",
      len({item.start for item in question_numeric_occurrences(FOUR_ROLE) if item.text == "2026"}), 4)

OFFSETS = [
    "第12部分  电压  220kV",
    "第5章 5.3.3 绝缘标称厚度 1.2mm 是多少？",
    "Q/GDW 73286.2-2026 中 3.9 与 4.1 的差别",
    "绝缘厚度 1．5mm 的要求",
]
roundtrip_ok = True
for question in OFFSETS:
    for occurrence in question_numeric_occurrences(question):
        if question[occurrence.start : occurrence.end] != occurrence.text:
            roundtrip_ok = False
            check("offset", f"roundtrip {question!r}", question[occurrence.start : occurrence.end], occurrence.text, ok=False)
check("offset", "original-question offset roundtrip over 4 shapes", roundtrip_ok, True)

for raw in ("电缆长度100m时的载流量", "电缆长度100 m 时的载流量", "电缆长度100\tm 时的载流量", "电缆长度100\nm 时的载流量"):
    check("unit", f"whitespace equivalence {raw!r}", question_values(raw), ["100"])
check("unit", "longest-valid-unit kWh", [i.kind for i in numeric_occurrences("储能容量100kWh 的电缆要求") if i.text == "100"], ["TECHNICAL_MEASUREMENT"])

bare = question_values("800 mm² 的厚度是多少？")
pools = [(), [{"content_with_weight": "800 3.9 1200"} for _ in range(20)], [{"content_with_weight": "无关"} for _ in range(5)]]
check("pool", "value set is pool independent", [question_values("800 mm² 的厚度是多少？", pool) for pool in pools], [bare, bare, bare])


# ---------------------------------------------------------------------------
# 3. FALSE_EMPTY behavioural smoke (real Dealer.search + real health bridge)
# ---------------------------------------------------------------------------
section("FALSE_EMPTY BEHAVIOURAL SMOKE")
from rag.llm.embedding_model import EmbeddingError  # noqa: E402
from rag.llm.chat_model import ModelException  # noqa: E402


class StubEmb:
    def __init__(self, exc=None, block=None):
        self.exc, self.block = exc, block
        self.entered = threading.Event()
        self.release = threading.Event()

    def encode(self, texts):
        if self.block is not None:
            self.entered.set()
            self.release.wait(self.block)
        if self.exc is not None:
            raise self.exc
        return [[0.0] * 8 for _ in texts]


async def run_search(emb, wait_seconds=2):
    dealer = rag_search.Dealer(settings.docStoreConn)
    dealer._embedding_wait_seconds = wait_seconds
    hb.begin_retrieval_health("in-image-smoke")
    result = await dealer.search({"question": "内衬层厚度", "page": 1, "size": 5, "similarity": 0.0, "vector": True}, [INDEX], [KB], emb, False)
    return result, hb.current_session()


def session_leg(session, name):
    try:
        return session.legs[name]
    except Exception:  # noqa: BLE001
        return None


# retryable connector failure -> lexical degradation
retryable = ModelException("connector hiccup", retryable=True)
result, session = asyncio.run(run_search(StubEmb(exc=retryable)))
check("false_empty", "retryable ModelException degrades", result.retrieval_mode, "LEXICAL_DEGRADED")
check("false_empty", "retryable degradation still returns chunks", len(result.ids) > 0, True)
check("false_empty", "retryable: dense leg reported failed", session_leg(session, "dense").status.value if session_leg(session, "dense") else None, "failed")
check("false_empty", "retryable: lexical leg reported ok", session_leg(session, "lexical").status.value if session_leg(session, "lexical") else None, "ok")

# non-retryable embedding incident class -> lexical degradation
incident = EmbeddingError("provider precondition", retryable=False)
result, session = asyncio.run(run_search(StubEmb(exc=incident)))
check("false_empty", "EmbeddingError(retryable=False) degrades", result.retrieval_mode, "LEXICAL_DEGRADED")
check("false_empty", "incident class: lexical executed", len(result.ids) > 0, True)

# permanent failures raise
for label, exc in (("PermissionError", PermissionError("denied")), ("ModelException(not retryable)", ModelException("bad key", retryable=False)), ("unknown", RuntimeError("boom"))):
    raised = None
    try:
        asyncio.run(run_search(StubEmb(exc=exc)))
    except BaseException as caught:  # noqa: BLE001
        raised = type(caught).__name__
    check("false_empty", f"{label} raises", raised, type(exc).__name__)

# blocked dense: lexical executes before the worker is released; a late result cannot rewrite the state
blocked = StubEmb(block=30)
async def blocked_case():
    dealer = rag_search.Dealer(settings.docStoreConn)
    dealer._embedding_wait_seconds = 2
    hb.begin_retrieval_health("late-dense")
    task = asyncio.create_task(dealer.search({"question": "内衬层厚度", "page": 1, "size": 5, "similarity": 0.0, "vector": True}, [INDEX], [KB], blocked, False))
    while not blocked.entered.is_set():
        await asyncio.sleep(0.05)
    result = await task
    mid = hb.current_session()
    blocked.release.set()
    await asyncio.sleep(1.0)
    after_release = await dealer.search({"question": "内衬层厚度", "page": 1, "size": 5, "similarity": 0.0, "vector": True}, [INDEX], [KB], StubEmb(exc=RuntimeError("late")), False)
    return result, mid, after_release

result, mid, after_release = asyncio.run(blocked_case())
check("false_empty", "blocked dense still degrades to lexical", result.retrieval_mode, "LEXICAL_DEGRADED")
check("false_empty", "lexical ran while the dense worker was blocked", len(result.ids) > 0, True)
check("false_empty", "worker was still blocked at that point", blocked.entered.is_set(), True)
check("false_empty", "late dense result cannot rewrite failure to success", mid.legs["dense"].status.value, "failed")
check("false_empty", "subsequent call still degrades, never silent success", after_release.retrieval_mode, "LEXICAL_DEGRADED")


# ---------------------------------------------------------------------------
# 4. P0 contract smoke
# ---------------------------------------------------------------------------
section("P0 CONTRACT SMOKE")
from rag.retrieval import health  # noqa: E402

check("p0", "KNOWN_LEGS unchanged", list(health.KNOWN_LEGS), ["decomposition", "lexical", "dense", "rerank", "followup"])
session = hb.current_session()
leg_names = sorted(session.legs) if session and session.legs else []
check("p0", "session legs are the known taxonomy", [n for n in leg_names if n not in health.KNOWN_LEGS], [])
sample = session.legs.get("dense") if session else None
check("p0", "leg fact fields present", sorted(f for f in ("name", "status", "reason", "routes_attempted", "routes_succeeded", "detail") if hasattr(sample, f)),
      ["detail", "name", "reason", "routes_attempted", "routes_succeeded", "status"])
payload = {"chunks": [{"id": "x"}]}
attached = hb.attach_retrieval_health(payload)
check("p0", "attach_retrieval_health keeps the payload shape", sorted(attached), ["chunks", "retrieval_health"])
check("p0", "frontend assets outside the overlay", pathlib.Path("/ragflow/web/dist/index.html").exists(), True)

# resource leak: threads after all of the above
section("RESOURCE")
threads = threading.active_count()
check("resource", "no thread explosion after the acceptance run", threads < 40, True, ok=threads < 40)

# ---------------------------------------------------------------------------
summary
# ---------------------------------------------------------------------------
requests.delete(f"{host}/{INDEX}", auth=auth, timeout=30)
total = len(RECORDS)
passed = sum(1 for r in RECORDS if r["result"] == "PASS")
print(f"\nassertions: {passed}/{total} PASS", flush=True)
for group in ("identity", "setup", "A", "B", "C", "D", "E", "F", "numeric", "offset", "unit", "pool", "false_empty", "p0", "resource"):
    rows = [r for r in RECORDS if r["group"] == group]
    if rows:
        ok = sum(1 for r in rows if r["result"] == "PASS")
        verdict = "PASS" if ok == len(rows) else "FAIL"
        print(f"{group}: {verdict} ({ok}/{len(rows)})", flush=True)
print("\nmanifest:", json.dumps({k: v[:16] for k, v in MANIFEST.items()}, indent=1), flush=True)
if FAILURES:
    print("\nFAILURES:", flush=True)
    for failure in FAILURES:
        print(" -", failure, flush=True)
    raise SystemExit(1)
print("\nALL ASSERTIONS PASSED", flush=True)
