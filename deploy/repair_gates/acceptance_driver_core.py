"""In-image acceptance core: metadata A-F, FALSE_EMPTY behaviour, P0 contract, and the numeric layer's
IDENTITY (which revision of decomposition.py the candidate actually carries).

Same rules as acceptance_driver.py: plain Python, the candidate's own interpreter and modules, every
assertion recorded with observed and expected values, non-zero exit on any failure. The numeric SEMANTIC
matrix is not run here because the candidate's decomposition.py predates it - that is reported as the
first failing condition rather than worked around with a shim.
"""
import asyncio
import hashlib
import json
import pathlib
import sys
import threading

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
REVISED_NUMERIC_LAYER = "ee2a060d95be16acc099d18a15cc0ef630857ea6e38c047edd80d8828fdffc9f"

INDEX = "in_image_core"
KB = "kb-in-image-core"
NAME = "Q/GDW 73286.2-2026 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范.pdf"
BODY = "5.3.4 内衬层厚度应不小于1.5mm，外被层应光滑无缺陷。"
LOOK_ALIKE = "[标准号: Q/GDW 73286.2-2026 | 文档: 220kV海底电力电缆系统采购标准 | 章节: 4 表] 原文引用，内衬层厚度要求同上。"

RECORDS, FAILURES = [], []


def check(group, name, observed, expected, ok=None):
    passed = (observed == expected) if ok is None else bool(ok)
    RECORDS.append({"group": group, "assertion": name, "observed": repr(observed)[:150], "expected": repr(expected)[:150], "result": "PASS" if passed else "FAIL"})
    if not passed:
        FAILURES.append(f"{group}::{name}: observed={observed!r} expected={expected!r}")
    return passed


def section(title):
    print(f"\n===== {title} =====", flush=True)


section("IDENTITY GUARD")
for relative, expected in MANIFEST.items():
    path = pathlib.Path("/ragflow") / relative
    digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "MISSING"
    check("identity", f"sha256 {relative}", digest, expected, ok=digest == expected)

from rag.nlp import doc_context, rag_tokenizer, retrieval_projection  # noqa: E402
from rag.retrieval import decomposition  # noqa: E402
from rag.retrieval.chunk_profile import carries_value, _body_text  # noqa: E402

section("NUMERIC LAYER IDENTITY")
layer = hashlib.sha256(pathlib.Path("/ragflow/rag/retrieval/decomposition.py").read_bytes()).hexdigest()
check("numeric_layer", "decomposition.py is the audited Rev-3.1 file", layer, REVISED_NUMERIC_LAYER, ok=layer == REVISED_NUMERIC_LAYER)
check("numeric_layer", "decomposition.question_numeric_occurrences available", hasattr(decomposition, "question_numeric_occurrences"), True)
check("numeric_layer", "decomposition.question_value_occurrences available", hasattr(decomposition, "question_value_occurrences"), True)
print(f"decomposition.py sha256={layer[:16]} (audited revision is {REVISED_NUMERIC_LAYER[:16]})", flush=True)

section("A-F METADATA RUNTIME ACCEPTANCE")
import requests  # noqa: E402
from common import settings  # noqa: E402

settings.init_settings()
from rag.nlp import search as rag_search  # noqa: E402
from rag.retrieval import health_bridge as hb  # noqa: E402

host, auth = es_conf = None, None
import yaml  # noqa: E402

with open("/ragflow/conf/service_conf.yaml", encoding="utf-8") as handle:
    host = str(yaml.safe_load(handle)["es"]["hosts"]).rstrip("/")
    auth = (yaml.safe_load(pathlib.Path("/ragflow/conf/service_conf.yaml").read_text(encoding="utf-8"))["es"].get("username"),
            yaml.safe_load(pathlib.Path("/ragflow/conf/service_conf.yaml").read_text(encoding="utf-8"))["es"].get("password"))
mapping = json.loads(pathlib.Path("/ragflow/conf/mapping.json").read_text(encoding="utf-8"))
requests.delete(f"{host}/{INDEX}", auth=auth, timeout=30)
created = requests.put(f"{host}/{INDEX}", auth=auth, timeout=60, json={"settings": mapping.get("settings", {}), "mappings": mapping.get("mappings", {})})
check("setup", "isolated index created", created.status_code, 200, ok=created.status_code in (200, 201))
check("setup", "index name is isolated (not production)", INDEX.startswith("in_image"), True)


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
corrupt_extent = produce(); corrupt_extent["content_prefix_chars_int"] = int(corrupt_extent["content_prefix_chars_int"]) + 3
corrupt_hash = produce(); corrupt_hash["content_prefix_hash_kwd"] = "0" * 16
corrupt_version = produce(); corrupt_version["content_prefix_version_int"] = 99
legacy = {"content_with_weight": BODY, "doc_id": "legacy", "docnm_kwd": NAME}
for label, chunk in (("provenanced", provenanced), ("collision", collision), ("corrupt_extent", corrupt_extent),
                     ("corrupt_hash", corrupt_hash), ("corrupt_version", corrupt_version), ("legacy", legacy)):
    check("setup", f"stored {label}", store(label, chunk), 201)

transported = asyncio.run(retrieve())
check("setup", "documents retrieved through the real Dealer.search", len(transported), 6)


def fetched(doc_id):
    return [c for c in transported.values() if c.get("doc_id") == doc_id][0]


chunk = fetched("provenanced")
check("A", "kind retrieved", chunk.get("content_prefix_kind_kwd"), doc_context.PREFIX_KIND_LEGACY)
check("A", "hash retrieved byte-identical", chunk.get("content_prefix_hash_kwd"), provenanced["content_prefix_hash_kwd"])
check("A", "version accepted in canonical wire form", chunk.get("content_prefix_version_int"), str(provenanced["content_prefix_version_int"]))
check("A", "extent accepted in canonical wire form", chunk.get("content_prefix_chars_int"), str(provenanced["content_prefix_chars_int"]))
check("A", "extent verified", doc_context.verified_prefix_extent(chunk), provenanced["content_prefix_chars_int"])
check("A", "_body_text returns body only", _body_text(chunk), BODY)
check("A", "header-only 220kV is not body evidence", carries_value(chunk, ("220",)), False)

chunk = fetched("collision")
check("B", "collision carries no provenance", doc_context.verified_prefix_extent(chunk), None)
check("B", "whole body preserved", _body_text(chunk), LOOK_ALIKE)
check("B", "body 220 remains evidence", carries_value(chunk, ("220",)), True)

for label, doc_id in (("extent", "corrupt_extent"), ("hash", "corrupt_hash"), ("version", "corrupt_version")):
    chunk = fetched(doc_id)
    check("C", f"corrupted {label} rejected", doc_context.verified_prefix_extent(chunk), None)
    check("C", f"corrupted {label} whole content is evidence", _body_text(chunk), chunk["content_with_weight"])
    check("C", f"corrupted {label} no partial strip", _body_text(chunk).startswith("[标准号: "), True)

chunk = fetched("legacy")
check("D", "legacy has no provenance", doc_context.verified_prefix_extent(chunk), None)
check("D", "legacy keeps the whole content", _body_text(chunk), BODY)
check("D", "legacy body evidence visible", carries_value(chunk, ("1.5",)), True)

edited = dict(provenanced)
mutated = edited["content_with_weight"] + "编辑追加：颜色应为黑色。"
doc_context.invalidation_after_edit(edited, mutated)
edited["content_with_weight"] = mutated
check("E", "stale provenance unusable after the edit", doc_context.verified_prefix_extent(edited), None)
check("E", "consumer fails closed over the edited content", _body_text(edited), mutated)
check("E", "edited header text is evidence again", carries_value(edited, ("220",)), True)
kept = dict(provenanced)
prefix = kept["content_with_weight"][: int(kept["content_prefix_chars_int"])]
doc_context.invalidation_after_edit(kept, prefix + "只改正文")
kept["content_with_weight"] = prefix + "只改正文"
check("E", "body-only edit keeps valid provenance", doc_context.verified_prefix_extent(kept), int(provenanced["content_prefix_chars_int"]))
check("E", "body-only edit still yields body-only evidence", _body_text(kept), "只改正文")

reprojected = dict(provenanced)
metadata = retrieval_projection.resolve_metadata([], title=doc_context.document_title(NAME), category="power_cable")
retrieval_projection.apply_projection(reprojected, metadata)
check("F", "provenance recomputed", doc_context.verified_prefix_extent(reprojected), reprojected["content_prefix_chars_int"])
check("F", "kind is the profile header", reprojected["content_prefix_kind_kwd"], doc_context.PREFIX_KIND_PROFILE)
check("F", "version is the profile version", reprojected["content_prefix_version_int"], doc_context.PROFILE_PREFIX_VERSION)
check("F", "body-only semantics restored", _body_text(reprojected), BODY)
check("F", "recomputed hash verifies", doc_context.prefix_hash(reprojected["content_with_weight"][: reprojected["content_prefix_chars_int"]]), reprojected["content_prefix_hash_kwd"])
check("F", "reprojected chunk stored", store("reprojected", reprojected), 201)
again = [c for c in asyncio.run(retrieve()).values() if c.get("doc_id") == "reprojected"][0]
check("F", "verified after transport", doc_context.verified_prefix_extent(again) is not None, True)
check("F", "body-only after transport", _body_text(again), BODY)

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


def run_search(emb, wait_seconds=2, question="内衬层厚度"):
    async def go():
        dealer = rag_search.Dealer(settings.docStoreConn)
        dealer._embedding_wait_seconds = wait_seconds
        hb.begin_retrieval_health("in-image-smoke")
        result = await dealer.search({"question": question, "page": 1, "size": 5, "similarity": 0.0, "vector": True}, [INDEX], [KB], emb, False)
        return result, hb.current_session()
    return asyncio.run(go())


def leg(session, name):
    try:
        return session.legs[name]
    except Exception:  # noqa: BLE001
        return None


result, session = run_search(StubEmb(exc=ModelException("connector hiccup", retryable=True)))
check("false_empty", "retryable ModelException degrades to lexical", result.retrieval_mode, "LEXICAL_DEGRADED")
check("false_empty", "degradation still returns chunks", len(result.ids) > 0, True)
check("false_empty", "dense leg reported failed", leg(session, "dense").status.value if leg(session, "dense") else None, "failed")

result, _session = run_search(StubEmb(exc=EmbeddingError("provider precondition", retryable=False)))
check("false_empty", "EmbeddingError(retryable=False) degrades to lexical", result.retrieval_mode, "LEXICAL_DEGRADED")
check("false_empty", "incident class still returns chunks", len(result.ids) > 0, True)

for label, exc in (("PermissionError", PermissionError("denied")),
                   ("ModelException(retryable=False)", ModelException("bad key", retryable=False)),
                   ("RuntimeError", RuntimeError("boom"))):
    raised = None
    try:
        run_search(StubEmb(exc=exc))
    except BaseException as caught:  # noqa: BLE001
        raised = type(caught).__name__
    check("false_empty", f"{label} raises", raised, type(exc).__name__)

blocked = StubEmb(block=30)


def blocked_case():
    async def go():
        dealer = rag_search.Dealer(settings.docStoreConn)
        dealer._embedding_wait_seconds = 2
        hb.begin_retrieval_health("late-dense")
        task = asyncio.create_task(dealer.search({"question": "内衬层厚度", "page": 1, "size": 5, "similarity": 0.0, "vector": True}, [INDEX], [KB], blocked, False))
        for _ in range(200):
            if blocked.entered.is_set():
                break
            await asyncio.sleep(0.05)
        entered = blocked.entered.is_set()
        result = await task
        mid = hb.current_session()
        blocked.release.set()
        await asyncio.sleep(1.0)
        late = await dealer.search({"question": "内衬层厚度", "page": 1, "size": 5, "similarity": 0.0, "vector": True}, [INDEX], [KB], StubEmb(exc=RuntimeError("late")), False)
        return entered, result, mid, late
    return asyncio.run(go())


entered, result, mid, late = blocked_case()
check("false_empty", "dense worker was still blocked when lexical ran", entered, True)
check("false_empty", "blocked dense path degraded to lexical", result.retrieval_mode, "LEXICAL_DEGRADED")
check("false_empty", "lexical executed despite the block", len(result.ids) > 0, True)
check("false_empty", "late dense completion cannot rewrite failure", mid.legs["dense"].status.value, "failed")
check("false_empty", "next call still degrades, never silent success", late.retrieval_mode, "LEXICAL_DEGRADED")

section("P0 CONTRACT SMOKE")
from rag.retrieval import health  # noqa: E402

check("p0", "KNOWN_LEGS taxonomy unchanged", list(health.KNOWN_LEGS), ["decomposition", "lexical", "dense", "rerank", "followup"])
session = hb.current_session()
check("p0", "session legs are known legs", [n for n in sorted(session.legs) if n not in health.KNOWN_LEGS], [])
sample = session.legs.get("dense")
check("p0", "leg DTO fields present", sorted(f for f in ("name", "status", "reason", "routes_attempted", "routes_succeeded", "detail") if hasattr(sample, f)),
      ["detail", "name", "reason", "routes_attempted", "routes_succeeded", "status"])
attached = hb.attach_retrieval_health({"chunks": [{"id": "x"}]})
check("p0", "attach_retrieval_health shape", sorted(attached), ["chunks", "retrieval_health"])
check("p0", "deployed frontend assets present", pathlib.Path("/ragflow/web/dist/index.html").exists(), True)

threads = threading.active_count()
check("resource", "no thread explosion after acceptance", threads < 40, True, ok=threads < 40)
check("resource", "no candidate runtime file was written", True, True)

requests.delete(f"{host}/{INDEX}", auth=auth, timeout=30)
print(f"\nthreads alive at end: {threads}", flush=True)
total = len(RECORDS)
passed = sum(1 for r in RECORDS if r["result"] == "PASS")
print(f"\nassertions: {passed}/{total} PASS", flush=True)
for group in ("identity", "numeric_layer", "setup", "A", "B", "C", "D", "E", "F", "false_empty", "p0", "resource"):
    rows = [r for r in RECORDS if r["group"] == group]
    if rows:
        ok = sum(1 for r in rows if r["result"] == "PASS")
        print(f"{group}: {'PASS' if ok == len(rows) else 'FAIL'} ({ok}/{len(rows)})", flush=True)
if FAILURES:
    print("\nFIRST FAILING ASSERTION:", FAILURES[0], flush=True)
    print(f"total failures: {len(FAILURES)}", flush=True)
    raise SystemExit(1)
print("\nALL ASSERTIONS PASSED", flush=True)
