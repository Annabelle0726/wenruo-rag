"""In-image acceptance driver for the corrected candidate - plain Python, candidate interpreter.

Group verdicts print IMMEDIATELY as each group completes, so a later failure cannot erase earlier evidence.
Identity guards run before any behavioural test. Every assertion calls the candidate's real modules.
"""
import asyncio
import hashlib
import json
import pathlib
import sys
import threading
import traceback

sys.path.insert(0, "/ragflow")

MANIFEST = {
    "rag/nlp/doc_context.py": "d0a61bda36c0632367d265ffd11bc8248637d59289f9107df333b968317a14e6",
    "rag/nlp/retrieval_projection.py": "5618bfb01fded4f429a51a6ecbe2714ed60f31f306b8bf606d74674b62ecab98",
    "rag/retrieval/chunk_profile.py": "248a6af9bcf8a83582b38b3b2c197c4405c77e72da0c6304f6931c7d8ae362da",
    "rag/retrieval/decomposition.py": "ee2a060d95be16acc099d18a15cc0ef630857ea6e38c047edd80d8828fdffc9f",
    "rag/nlp/search.py": "abdf9a25813c00dda59b393ae3cd29143a33e98409e9cbfa056a92b8c7ea6912",
    "api/apps/restful_apis/chunk_api.py": "e63a7ac4df731da35dc636a809e4a3ec6795df18aa81a14f5d7152b74ef9bd79",
    "rag/svr/task_executor_refactor/dataflow_service.py": "0132bdc4bf425d00a7dd38badb74dacd5da788ac3720d3a2d86dcbdc85ea8965",
    "rag/advanced_rag/harness/tools/text_processing.py": "a3007bdbb6ba95a21faf0720d8e1171e817f4d80e3b4d6fbd67e6efba6e3299d",
    # The ninth file. Its hash is the CLEAN reconstructed version: production baseline plus ONLY the
    # authorised quote-health repair, and NOT the unrelated `generic_fallback` prompt branch.
    "api/db/services/dialog_service.py": "91b8bfc6254e70e631065f3ed1bdc3ef1c11ba2a204b4c869fd9ae271171e726",
}
FROZEN = {
    "rerank.py": "1152c59a782766bfb219474cc9a00b7df5168c08c802d280252d8965af3e25cc",
    "multi_route.py": "9a08bf97d5ca2692d7a25ad3d47f21673991e6f2008458685c6809158d1e3932",
    "query_router.py": "51bf6a62d77f943f406138d2d547048c13f6c5c7dc921cffbfe8e044496991c1",
    "pipeline.py": "c9174c52926de66bceb4b033d9c5dd24b928284da820d964072f7dcd46effae7",
    "health.py": "ff04f8f6f07a8f01e761473209394ceeb8b797701f9103392f34401ec1d4cee4",
    "health_bridge.py": "baad7915bed0102b60bf6b86e0cf18d318fdef98f35f02cfe26f46eb939f7e10",
    "health_producers.py": "9f3d2c79d8c2237357388d7dd6c3094ba317ab9c9721ce6b3673beb640493be3",
}
TENANT = "accepttenant"
INDEX = f"ragflow_{TENANT}"
KB = "kb-accept"
NAME = "Q/GDW 73286.2-2026 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范.pdf"
BODY = "5.3.4 内衬层厚度应不小于1.5mm，外被层应光滑无缺陷。"
LOOK_ALIKE = "[标准号: Q/GDW 73286.2-2026 | 文档: 220kV海底电力电缆系统采购标准 | 章节: 4 表] 原文引用，内衬层厚度要求同上。"

FAILURES = []
GROUP_RESULT = {}
#: Per-tag assertion accounting. A group's verdict is derived from ITS OWN counts, never from the absence
#: of a failure line: PASS requires at least one executed assertion and zero failures, ABORTED is reported
#: for a tag whose assertions started but whose group never closed.
CHECK_COUNTS = {}
CLOSED_TAGS = set()


def check(g, label, observed, expected, ok=None):
    passed = (observed == expected) if ok is None else bool(ok)
    slot = CHECK_COUNTS.setdefault(g, {"executed": 0, "failed": 0})
    slot["executed"] += 1
    if not passed:
        slot["failed"] += 1
        FAILURES.append(f"{g}::{label}: observed={observed!r} expected={expected!r}")
    print(f"  [{'PASS' if passed else 'FAIL'}] {g}::{label}: observed={observed!r} expected={expected!r}", flush=True)
    return passed


def verdict_for(slot):
    """The three-state rule, as a function so the helper itself can be self-tested."""
    if slot["executed"] == 0:
        return "ABORTED"
    return "FAIL" if slot["failed"] else "PASS"


def group(label, tag=None):
    if tag is None and label.startswith("GROUP_"):
        slot = {"executed": sum(s["executed"] for s in CHECK_COUNTS.values()),
                "failed": sum(s["failed"] for s in CHECK_COUNTS.values())}
    else:
        slot = CHECK_COUNTS.get(tag or label, {"executed": 0, "failed": 0})
        CLOSED_TAGS.add(tag or label)
    GROUP_RESULT[label] = verdict_for(slot)
    print(f"VERDICT {label} = {GROUP_RESULT[label]}   assertions={slot['executed']} failed={slot['failed']}", flush=True)
    return GROUP_RESULT[label] == "PASS"


def _self_test_verdict_helper():
    """Proof that the helper cannot report PASS by default."""
    cases = [("all pass", {"executed": 3, "failed": 0}, "PASS"),
             ("one failure", {"executed": 3, "failed": 1}, "FAIL"),
             ("exception before completion", {"executed": 0, "failed": 0}, "ABORTED")]
    results = [(name, verdict_for(slot), expected) for name, slot, expected in cases]
    ok = all(observed == expected for _name, observed, expected in results)
    for name, observed, expected in results:
        print(f"  [{'PASS' if observed == expected else 'FAIL'}] self-test {name}: observed={observed} expected={expected}", flush=True)
    print(f"VERDICT VERDICT_HELPER_SELF_TEST = {'PASS' if ok else 'FAIL'}", flush=True)
    GROUP_RESULT["VERDICT_HELPER_SELF_TEST"] = "PASS" if ok else "FAIL"
    if not ok:
        FAILURES.append("SELFTEST::verdict helper")
    return ok


def _abort_hook(exc_type, exc, tb):
    """An uncaught exception prints its FULL traceback, then every open tag is reported ABORTED."""
    traceback.print_exception(exc_type, exc, tb)
    for tag, slot in CHECK_COUNTS.items():
        if tag not in CLOSED_TAGS:
            print(f"VERDICT {tag} = ABORTED   assertions={slot['executed']} failed={slot['failed']}", flush=True)
    print(f"ABORTED_BY {exc_type.__name__}: {exc}", flush=True)


sys.excepthook = _abort_hook
_self_test_verdict_helper()


# ===========================================================================
print("===== IDENTITY GUARDS =====", flush=True)
import os  # noqa: E402

for relative, expected in MANIFEST.items():
    path = pathlib.Path("/ragflow") / relative
    digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "MISSING"
    check("identity", f"runtime {relative}", digest, expected, ok=digest == expected)
for leaf, expected in FROZEN.items():
    path = pathlib.Path("/ragflow/rag/retrieval") / leaf
    digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "MISSING"
    check("identity", f"frozen {leaf}", digest, expected, ok=digest == expected)
frontend = pathlib.Path("/ragflow/web/dist/index.html")
check("identity", "frontend asset present", frontend.exists(), True, ok=frontend.exists())
group("IDENTITY_GUARDS")

# settings must precede rag.nlp.search: search imports query -> redis_conn -> common.settings.
from common import settings  # noqa: E402

settings.init_settings()
import requests  # noqa: E402
import yaml  # noqa: E402
from rag.nlp import doc_context, rag_tokenizer, retrieval_projection  # noqa: E402
from rag.nlp import search as rag_search  # noqa: E402
from rag.retrieval import decomposition, health, health_bridge as hb  # noqa: E402
from rag.retrieval.chunk_profile import carries_value, _body_text, numeric_occurrences  # noqa: E402

print("===== MODULE PATHS =====", flush=True)
for module in (rag_search, decomposition, doc_context, retrieval_projection):
    inside = str(pathlib.Path(module.__file__).resolve()).startswith("/ragflow/")
    check("identity", f"module path {module.__name__}", inside, True, ok=inside)
    print(f"    {module.__name__} -> {module.__file__}", flush=True)

conf = yaml.safe_load(pathlib.Path("/ragflow/conf/service_conf.yaml").read_text(encoding="utf-8"))["es"]
host, auth = str(conf["hosts"]).rstrip("/"), (conf.get("username"), conf.get("password"))
check("identity", "isolated datastore host", host, "http://repair-es:9200", ok="es01" not in host and "repair-es" in host)


# ===========================================================================
print("\n===== GROUP A: numeric semantic guard =====", flush=True)
from rag.retrieval.decomposition import question_values, question_numeric_occurrences  # noqa: E402

check("A", "question_numeric_occurrences exists", hasattr(decomposition, "question_numeric_occurrences"), True)
check("A", "question_value_occurrences exists", hasattr(decomposition, "question_value_occurrences"), True)
check("A", "audited composite probe", question_values("根据 Q/GDW 73286.2-2026，厚度是3.9还是4.1mm？"), ["3.9", "4.1"])
check("A", "locator vs asked identity", question_values("根据 2026版，另一份规范的版本是2025版吗？"), ["2025"])
check("A", "cross-clause isolation", question_values("Q/GDW 73286.2-2026规定800mm²电缆；待审文件的标准号是多少？"), ["800"])
check("A", "declarative identity not promoted", question_values("已知型号为AB123CD，厚度应取1.8还是2.0mm？"), ["1.8", "2.0"])
check("A", "coordinated locators", question_values("按照2026版和2025版核对800mm²电缆，待审文件的版本是2024版吗？"), ["800", "2024"])
check("A", "locator noun vs preposition", question_values("依据是2026版还是2025版，允许厚度为1.8mm吗？"), ["2026", "2025", "1.8"])
check("A", "same-literal multi occurrence", question_values("额定电压0.6/1 kV、型号WDZC-YJY-0.6/1kV 的电缆载流量是多少？"), ["0.6"])
four = "根据 2026版 与 AB2026CD 的 2026mm² 数据，待选型号为 EF2026GH 吗？"
check("A", "four-role same-literal kinds", sorted(i.kind for i in question_numeric_occurrences(four) if i.text == "2026"),
      sorted(["IDENTITY_USED_TO_LOCATE_DOCUMENT", "MODEL_IDENTITY", "TECHNICAL_MEASUREMENT", "IDENTITY_VALUE_EXPLICITLY_ASKED_BY_USER"]))
roundtrip = True
for probe in ("第12部分  电压  220kV", "第5章 5.3.3 绝缘标称厚度 1.2mm 是多少？"):
    for item in question_numeric_occurrences(probe):
        if probe[item.start : item.end] != item.text:
            roundtrip = False
check("A", "original-offset roundtrip", roundtrip, True)
for raw in ("电缆长度100m时的载流量", "电缆长度100 m 时的载流量", "电缆长度100\tm 时的载流量", "电缆长度100\nm 时的载流量"):
    check("A", f"whitespace unit equivalence {raw!r}", question_values(raw), ["100"])
check("A", "longest valid unit", [i.kind for i in numeric_occurrences("储能容量100kWh 的电缆要求") if i.text == "100"], ["TECHNICAL_MEASUREMENT"])
group("GROUP_A_NUMERIC")


# ===========================================================================
print("\n===== GROUP B: metadata final boundary =====", flush=True)
mapping = json.loads(pathlib.Path("/ragflow/conf/mapping.json").read_text(encoding="utf-8"))
requests.delete(f"{host}/{INDEX}", auth=auth, timeout=30)
created = requests.put(f"{host}/{INDEX}", auth=auth, timeout=60, json={"settings": mapping.get("settings", {}), "mappings": mapping.get("mappings", {})})
check("B", "isolated index created", created.status_code, 200, ok=created.status_code in (200, 201))
FIELDS = doc_context.PREFIX_FIELDS


def produce(body=BODY):
    chunk = {"content_with_weight": body, "doc_id": "d", "docnm_kwd": NAME, "content_ltks": "", "content_sm_ltks": ""}
    doc_context.apply_document_context([chunk], NAME, language="Chinese")
    return chunk


def store(doc_id, chunk):
    content = chunk["content_with_weight"]
    document = {"id": f"{doc_id}-c", "doc_id": doc_id, "kb_id": KB, "docnm_kwd": NAME, "available_int": 1,
                "content_with_weight": content, "content_ltks": rag_tokenizer.tokenize(content), "doc_type_kwd": "text"}
    for field in FIELDS:
        if field in chunk:
            document[field] = chunk[field]
    status = requests.post(f"{host}/{INDEX}/_doc/{doc_id}-c?refresh=true", auth=auth, timeout=30, json=document).status_code
    assert status in (200, 201), status
    return requests.get(f"{host}/{INDEX}/_doc/{doc_id}-c", auth=auth, timeout=30).json()["_source"]


def dealer():
    d = rag_search.Dealer(settings.docStoreConn)

    async def keep(result):
        return result

    d._prune_deleted_chunks = keep
    return d


def final_chunks(question="内衬层厚度", embd_mdl=None):
    async def go():
        ranks = await dealer().retrieval(question=question, embd_mdl=embd_mdl, tenant_ids=[TENANT], kb_ids=[KB], page=1,
                                         page_size=10, similarity_threshold=0.0, vector_similarity_weight=0.3,
                                         rerank_mdl=None, rank_feature=None)
        return ranks
    return asyncio.run(go())


provenanced = produce()
collision = {"content_with_weight": LOOK_ALIKE, "doc_id": "collision", "docnm_kwd": NAME}
corrupt_extent = produce(); corrupt_extent["content_prefix_chars_int"] = int(corrupt_extent["content_prefix_chars_int"]) + 3
corrupt_hash = produce(); corrupt_hash["content_prefix_hash_kwd"] = "0" * 16
corrupt_version = produce(); corrupt_version["content_prefix_version_int"] = 99
legacy = {"content_with_weight": BODY, "doc_id": "legacy", "docnm_kwd": NAME}
stored_by_doc = {}
for label, chunk in (("provenanced", provenanced), ("collision", collision), ("corrupt_extent", corrupt_extent),
                     ("corrupt_hash", corrupt_hash), ("corrupt_version", corrupt_version), ("legacy", legacy)):
    stored_by_doc[label] = store(label, chunk)

loaded = final_chunks()
final = {c.get("doc_id"): c for c in loaded["chunks"]}
print(f"  final boundary returned: {sorted(final)}", flush=True)


def f(doc_id):
    return final[doc_id]


chunk = f("provenanced"); stored = stored_by_doc["provenanced"]
check("B", "A four fields present", [x for x in FIELDS if x in chunk], list(FIELDS))
check("B", "A kind", chunk["content_prefix_kind_kwd"], stored["content_prefix_kind_kwd"])
check("B", "A hash", chunk["content_prefix_hash_kwd"], stored["content_prefix_hash_kwd"])
check("B", "A extent wire value", chunk["content_prefix_chars_int"], str(stored["content_prefix_chars_int"]))
check("B", "A version wire value", chunk["content_prefix_version_int"], str(stored["content_prefix_version_int"]))
check("B", "A verified extent", doc_context.verified_prefix_extent(chunk), stored["content_prefix_chars_int"])
check("B", "A body only", _body_text(chunk), BODY)
check("B", "A no header contamination", carries_value(chunk, ("220",)), False)
group("B_A_PROVENANCED")

chunk = f("collision")
check("B", "B no provenance", doc_context.verified_prefix_extent(chunk), None)
check("B", "B whole body preserved", _body_text(chunk), LOOK_ALIKE)
check("B", "B body evidence remains", carries_value(chunk, ("220",)), True)
group("B_B_COLLISION")

for label in ("corrupt_extent", "corrupt_hash", "corrupt_version"):
    chunk = f(label)
    check("B", f"C {label} transported unchanged", chunk["content_prefix_chars_int"], str(stored_by_doc[label]["content_prefix_chars_int"]))
    check("B", f"C {label} verification fails", doc_context.verified_prefix_extent(chunk), None)
    check("B", f"C {label} whole content", _body_text(chunk), chunk["content_with_weight"])
    check("B", f"C {label} no partial strip", _body_text(chunk).startswith("[标准号: "), True)
group("B_C_CORRUPTED")

chunk = f("legacy")
check("B", "D no provenance synthesised", [x for x in FIELDS if x in chunk], [])
check("B", "D whole content retained", _body_text(chunk), BODY)
check("B", "D body evidence remains", carries_value(chunk, ("1.5",)), True)
group("B_D_LEGACY")

appended = dict(provenanced)
extended = appended["content_with_weight"] + "编辑追加：外被层颜色应为黑色。"
doc_context.invalidation_after_edit(appended, extended)
appended["content_with_weight"] = extended
check("B", "E1 provenance preserved for a prefix-preserving edit", doc_context.verified_prefix_extent(appended), int(provenanced["content_prefix_chars_int"]))
store("edited_append", appended)
chunk = [c for c in final_chunks()["chunks"] if c.get("doc_id") == "edited_append"][0]
check("B", "E1 verified through the final boundary", doc_context.verified_prefix_extent(chunk), int(provenanced["content_prefix_chars_int"]))
check("B", "E1 body-only evidence", _body_text(chunk), extended[int(provenanced["content_prefix_chars_int"]) :])
check("B", "E1 no header contamination", carries_value(chunk, ("220",)), False)
group("B_E1_APPEND_EDIT")

destroyed = dict(provenanced)
prefix = destroyed["content_with_weight"][: int(destroyed["content_prefix_chars_int"])]
rewritten = "X" + destroyed["content_with_weight"][1:]
check("B", "E2 mutation destroys the prefix bytes", rewritten.startswith(prefix), False)
doc_context.invalidation_after_edit(destroyed, rewritten)
destroyed["content_with_weight"] = rewritten
check("B", "E2 invalidated by the authorised path", doc_context.verified_prefix_extent(destroyed), None)
stored_destroy = store("edited_destroy", destroyed)
check("B", "E2 datastore reflects invalidation", stored_destroy["content_prefix_kind_kwd"], doc_context.PREFIX_NONE)
check("B", "E2 datastore extent is zero", stored_destroy["content_prefix_chars_int"], 0)
chunk = [c for c in final_chunks()["chunks"] if c.get("doc_id") == "edited_destroy"][0]
check("B", "E2 fields still travel", [x for x in FIELDS if x in chunk], list(FIELDS))
check("B", "E2 stale provenance cannot strip", doc_context.verified_prefix_extent(chunk), None)
check("B", "E2 fail closed to whole content", _body_text(chunk), chunk["content_with_weight"])
check("B", "E2 header text is evidence again", carries_value(chunk, ("220",)), True)
group("B_E2_PREFIX_DESTROY_EDIT")

reprojected = dict(provenanced)
metadata = retrieval_projection.resolve_metadata([], title=doc_context.document_title(NAME), category="power_cable")
retrieval_projection.apply_projection(reprojected, metadata)
check("B", "F provenance recomputed", doc_context.verified_prefix_extent(reprojected), int(reprojected["content_prefix_chars_int"]))
check("B", "F kind is profile", reprojected["content_prefix_kind_kwd"], doc_context.PREFIX_KIND_PROFILE)
store("reprojected", reprojected)
chunk = [c for c in final_chunks()["chunks"] if c.get("doc_id") == "reprojected"][0]
check("B", "F verified through the final boundary", doc_context.verified_prefix_extent(chunk), int(reprojected["content_prefix_chars_int"]))
check("B", "F body-only restored", _body_text(chunk), BODY)
check("B", "F no header contamination", carries_value(chunk, ("220",)), False)
group("B_F_REPROJECTION")
group("GROUP_B_METADATA_FINAL_BOUNDARY")


# ===========================================================================
print("\n===== GROUP C: healthy/degraded propagation =====", flush=True)
healthy = final_chunks()
check("C", "healthy path returns chunks", len(healthy["chunks"]) > 0, True)
check("C", "healthy modes", {c.get("score_provenance", {}).get("mode") for c in healthy["chunks"]}, {"LEXICAL_ONLY"})
hc = [c for c in healthy["chunks"] if c.get("doc_id") == "provenanced"][0]
check("C", "healthy provenance survives", [x for x in FIELDS if x in hc], list(FIELDS))
check("C", "healthy verifies", doc_context.verified_prefix_extent(hc) is not None, True)
group("C_HEALTHY_PROVENANCE")

from rag.llm.embedding_model import EmbeddingError  # noqa: E402


class StubEmb:
    def encode(self, texts):
        raise EmbeddingError("provider precondition", retryable=False)

    def encode_queries(self, texts):
        raise EmbeddingError("provider precondition", retryable=False)


degraded = final_chunks(embd_mdl=StubEmb())
check("C", "degraded path returns chunks", len(degraded["chunks"]) > 0, True)
check("C", "degraded modes", {c.get("score_provenance", {}).get("mode") for c in degraded["chunks"]}, {"LEXICAL_DEGRADED"})
dc = [c for c in degraded["chunks"] if c.get("doc_id") == "provenanced"][0]
check("C", "degraded provenance survives", [x for x in FIELDS if x in dc], list(FIELDS))
check("C", "degraded verifies", doc_context.verified_prefix_extent(dc) is not None, True)
check("C", "degraded body only", _body_text(dc), BODY)
group("C_DEGRADED_PROVENANCE")
group("GROUP_C_PROPAGATION")


# ===========================================================================
print("\n===== GROUP D: FALSE_EMPTY behavioural smoke =====", flush=True)
def discover_exception(name):
    for module_name in ("rag.llm.chat_model", "rag.llm.embedding_model", "rag.llm.model_factory", "rag.llm.tenant_llm", "rag.llm"):
        try:
            module = __import__(module_name, fromlist=["x"])
        except Exception:  # noqa: BLE001
            continue
        candidate = getattr(module, name, None)
        if isinstance(candidate, type):
            return candidate, module_name
    return None, None


ModelException, discovered_from = discover_exception("ModelException")
print(f"  ModelException discovered from: {discovered_from}", flush=True)
check("D", "ModelException discovered from the candidate", discovered_from is not None, True, ok=discovered_from is not None)


def run_search(emb, wait_seconds=2):
    async def go():
        d = dealer()
        d._embedding_wait_seconds = wait_seconds
        hb.begin_retrieval_health("acceptance")
        result = await d.search({"question": "内衬层厚度", "page": 1, "size": 5, "similarity": 0.0, "vector": True}, [INDEX], [KB], emb, False)
        return result, hb.current_session()
    return asyncio.run(go())


def make_stub(exc=None, box=None):
    """A deterministic local failure/block injector: the accepted offline technique, no provider call."""

    class _Stub:
        def encode(self, texts):
            if box is not None:
                box["entered"].set()
                box["release"].wait(30)
            if exc is not None:
                raise exc
            return [[0.0] * 8 for _ in texts]

        encode_queries = encode

    return _Stub()


if ModelException is None:
    FAILURES.append("D::ModelException not discoverable from the candidate modules")
else:
    check("D", "ModelException discovered from the candidate", True, True)
    result, session = run_search(make_stub(ModelException("connector hiccup", retryable=True)))
    LAST_SESSION = session
    check("D", "retryable ModelException degrades to lexical", result.retrieval_mode, "LEXICAL_DEGRADED")
    check("D", "retryable failure still returns chunks", len(result.ids) > 0, True)
    print(f"  health.LegStatus members: {[(m.name, m.value) for m in health.LegStatus]}", flush=True)
    FAILED_STATUS = next((m for m in health.LegStatus if m.value == "failed"), None)
    SUCCESS_STATUS = next((m for m in health.LegStatus if m.name.upper().startswith("SUCC")), None)
    print(f"  contract-derived statuses: failed={FAILED_STATUS!r} success={SUCCESS_STATUS!r}", flush=True)
    check("D", "dense leg is the contract failure status", session.legs["dense"].status, FAILED_STATUS,
          ok=FAILED_STATUS is not None and session.legs["dense"].status == FAILED_STATUS)
    check("D", "lexical leg is the contract success status", session.legs["lexical"].status, SUCCESS_STATUS,
          ok=SUCCESS_STATUS is not None and session.legs["lexical"].status == SUCCESS_STATUS)
    incident, _incident_session = run_search(make_stub(EmbeddingError("provider precondition", retryable=False)))
    check("D", "EmbeddingError(retryable=False) degrades", incident.retrieval_mode, "LEXICAL_DEGRADED")
    for label, exc in (("non-retryable ModelException", ModelException("bad key", retryable=False)),
                       ("PermissionError", PermissionError("denied")),
                       ("unknown RuntimeError", RuntimeError("boom"))):
        raised = None
        try:
            run_search(make_stub(exc))
        except BaseException as caught:  # noqa: BLE001
            raised = type(caught).__name__
        check("D", f"{label} raises", raised, type(exc).__name__)

box = {"entered": threading.Event(), "release": threading.Event()}


def blocked_case():
    async def go():
        d = dealer()
        d._embedding_wait_seconds = 2
        hb.begin_retrieval_health("late-dense")
        task = asyncio.create_task(d.search({"question": "内衬层厚度", "page": 1, "size": 5, "similarity": 0.0, "vector": True}, [INDEX], [KB], make_stub(box=box), False))
        for _ in range(200):
            if box["entered"].is_set():
                break
            await asyncio.sleep(0.05)
        entered = box["entered"].is_set()
        result = await task
        mid = hb.current_session()
        box["release"].set()
        await asyncio.sleep(1.0)
        return entered, result, mid
    return asyncio.run(go())


entered, result, mid = blocked_case()
check("D", "dense worker was blocked while lexical ran", entered, True)
check("D", "blocked dense degrades to lexical", result.retrieval_mode, "LEXICAL_DEGRADED")
check("D", "lexical executed anyway", len(result.ids) > 0, True)
check("D", "late dense cannot rewrite failure", mid.legs["dense"].status, FAILED_STATUS,
      ok=FAILED_STATUS is not None and mid.legs["dense"].status == FAILED_STATUS)
threads = threading.active_count()
check("D", "no resource leak", threads, True, ok=threads < 40)
group("D_FALSE_EMPTY")
group("GROUP_D_FALSE_EMPTY")


# ===========================================================================
print("\n===== GROUP E: P0 / health smoke =====", flush=True)
try:
    check("E", "KNOWN_LEGS unchanged", list(health.KNOWN_LEGS), ["decomposition", "lexical", "dense", "rerank", "followup"])
    session = globals().get("LAST_SESSION") or hb.current_session()
    if session is None:
        hb.begin_retrieval_health("p0-smoke")
        session = hb.current_session()
    check("E", "a health session is available for the DTO assertions", session is not None, True, ok=session is not None)
    if session is None:
        raise RuntimeError("no retrieval-health session available in this context")
    check("E", "no unknown leg in the session", [n for n in sorted(session.legs) if n not in health.KNOWN_LEGS], [])
    sample = session.legs.get("dense")
    check("E", "leg DTO fields present", sorted(x for x in ("name", "status", "reason", "routes_attempted", "routes_succeeded", "detail") if hasattr(sample, x)),
          ["detail", "name", "reason", "routes_attempted", "routes_succeeded", "status"])
    check("E", "reason taxonomy carries a reason for the failed leg", sample.reason is not None, True, ok=sample.reason is not None)
    # `attach_retrieval_health` reads the session bound to the CURRENT context. The DTO assertions above
    # deliberately reuse whichever session ran earlier, but a session begun inside `asyncio.run(...)`
    # does NOT propagate back out to this context (measured: `current_session()` is None here, and the
    # same measurement reproduces on the deployed base image). Attaching without first beginning a
    # session in THIS context therefore asserted against an unset contextvar rather than against the
    # attach contract. Begin one here so the assertion exercises the contract it names; the assertion
    # itself is unchanged.
    hb.begin_retrieval_health("p0-attach")
    attached = hb.attach_retrieval_health({"chunks": [{"id": "x"}]})
    check("E", "attach_retrieval_health shape", sorted(attached), ["chunks", "retrieval_health"])
    check("E", "frontend asset present", pathlib.Path("/ragflow/web/dist/index.html").exists(), True)
except BaseException:  # noqa: BLE001
    traceback.print_exc()
    FAILURES.append("E::aborted before its assertions completed")
    print("GROUP_E_CLASSIFICATION = see traceback above; harness defect unless it names a product module",
          flush=True)
finally:
    group("E_P0_HEALTH")
    group("GROUP_E_P0")

requests.delete(f"{host}/{INDEX}", auth=auth, timeout=30)
print("\n===== SUMMARY =====", flush=True)
for name, verdict in GROUP_RESULT.items():
    print(f"  {name}: {verdict}", flush=True)
if FAILURES:
    print(f"\nFIRST FAILING ASSERTION: {FAILURES[0]}", flush=True)
    print(f"total failures: {len(FAILURES)}", flush=True)
    raise SystemExit(1)
print("\nALL GROUPS PASSED", flush=True)
