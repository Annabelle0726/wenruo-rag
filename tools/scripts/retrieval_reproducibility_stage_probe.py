"""Corrected stage-capture probe (v2) — read-only, series A only.

The first probe (retrieval_reproducibility_probe.py) established the reproducibility baseline for all
12 queries in both series but failed to capture three things: the per-route candidates (the deployed
pipeline does not route through `Dealer.retrieval`, so that wrapper never fired), the pre-cut fused
pool (the pool is passed as an ARGUMENT to the selection step, and only return values were recorded),
and the query embedding (the deployed bundle takes a plain string, not a list).

This probe fixes only the INSTRUMENTATION, on the same frozen configuration and the same queries.
Nothing in the deployment is modified; no answer is generated.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import inspect
import json
import sys

sys.path.insert(0, "/ragflow")

KB = "9463d93eb97511f1938f2592e9bc6fe4"
RUNS = 10
CAPTURED: list = []
INSTALLED: list = []
FIRED: dict = {}
CHAT_CALLS: list = []

PARAMS = {
    "similarity_threshold": 0.2,
    "vector_similarity_weight": 0.6,
    "routes_top_k": 12,
    "final_top_n": 8,
    "knn_top_k": 1024,
    "max_sub_queries": 4,
    "allow_dense_fallback": True,
}

QUERIES = [
    {"id": "S_A1", "class": "CANDIDATE_STABLE", "text": "Q/GDW 73286.2-2026 是什么标准？"},
    {"id": "S_A3", "class": "CANDIDATE_STABLE", "text": "那 220kV 单芯海底电缆的主要结构有哪些？"},
    {"id": "S_B1", "class": "CANDIDATE_STABLE", "text": "220kV 三芯海底电缆一般有哪些主要结构？"},
    {"id": "S_C3", "class": "CANDIDATE_STABLE", "text": "哪些要求是它们共同的？"},
    {"id": "U_A2", "class": "CANDIDATE_UNSTABLE", "text": "这个标准适用于什么类型的电缆？"},
    {"id": "U_A4", "class": "CANDIDATE_UNSTABLE", "text": "导体、内衬层和铠装层分别有什么技术要求？"},
    {"id": "U_A5", "class": "CANDIDATE_UNSTABLE", "text": "这些要求都是这个专用技术规范自己规定的吗？"},
    {"id": "U_B6", "class": "CANDIDATE_UNSTABLE", "text": "那你把专用规范和通用规范的要求区分开告诉我。"},
    {"id": "U_C1", "class": "CANDIDATE_UNSTABLE", "text": "220kV 单芯和三芯海底电缆的技术要求有什么区别？"},
    {"id": "K_STD", "class": "CRITICAL_BUSINESS", "text": "Q/GDW 73286.2-2026 中 220kV 单芯海底电缆内衬层厚度要求是多少？"},
    {"id": "K_3CORE", "class": "CRITICAL_BUSINESS", "text": "请说明 220kV 三芯海底电缆的主要结构以及铠装层的一般要求。"},
    {"id": "K_LAYER", "class": "CRITICAL_BUSINESS", "text": "220kV 单芯海底电缆的内衬层和铠装层分别有什么技术要求？"},
]

ROUTE_NAMES = ("lexical", "dense", "hybrid", "vector", "fulltext", "comparative", "clause", "numeric", "sub_query", "main")


def trunc(value, limit: int = 160):
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, dict):
        return {str(k): trunc(v, limit) for k, v in list(value.items())[:20]}
    if isinstance(value, (list, tuple)):
        return [trunc(v, limit) for v in list(value)[:24]]
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return f"<{type(value).__name__}>"


def find_chunks(node, out: list, depth: int = 0) -> None:
    """Collect every list-of-chunk-dicts found anywhere in an argument tree."""
    if depth > 4:
        return
    if isinstance(node, dict):
        cid = node.get("chunk_id") or node.get("id")
        if cid is not None and isinstance(cid, str):
            out.append(node)
            return
        for value in node.values():
            find_chunks(value, out, depth + 1)
    elif isinstance(node, (list, tuple)):
        for item in node:
            find_chunks(item, out, depth + 1)


def rows(chunks: list) -> list:
    seen, result = set(), []
    for chunk in chunks:
        cid = str(chunk.get("chunk_id") or chunk.get("id"))[:16]
        if cid in seen:
            continue
        seen.add(cid)
        similarity = chunk.get("similarity")
        vector = chunk.get("vector_similarity")
        term = chunk.get("term_similarity")

        def scalar(value):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, (int, float)) and not isinstance(item, bool):
                        return float(item)
            return None

        result.append(
            {
                "id": cid,
                "part": next((marker for marker in ("第1部分", "第2部分", "第3部分") if marker in str(chunk.get("docnm_kwd") or chunk.get("doc_name") or "")), "other"),
                "similarity": scalar(similarity),
                "vector_similarity": scalar(vector),
                "term_similarity": scalar(term),
            }
        )
    return result


def find_strings(node, out: list, depth: int = 0) -> None:
    if depth > 3:
        return
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, dict):
        for value in node.values():
            find_strings(value, out, depth + 1)
    elif isinstance(node, (list, tuple, set)):
        for item in node:
            find_strings(item, out, depth + 1)


def install() -> None:
    targets = ("rag.retrieval.decomposition", "rag.retrieval.multi_route", "rag.retrieval.pipeline", "rag.retrieval.rerank")
    propagate = ["rag.retrieval.multi_route", "rag.retrieval.pipeline", "rag.retrieval", "rag.retrieval.rerank"]
    for module_name in targets:
        try:
            module = __import__(module_name, fromlist=["__name__"])
        except Exception as exc:  # noqa: BLE001
            INSTALLED.append({"module": module_name, "name": "-", "status": f"IMPORT_FAILED {type(exc).__name__}"})
            continue
        for name in list(dir(module)):
            if name.startswith("__"):
                continue
            fn = getattr(module, name, None)
            if not callable(fn) or not str(getattr(fn, "__module__", "")).startswith("rag"):
                continue
            stage = "decomposition" if "decompos" in module_name or name in ("decompose_question", "parse_sub_queries", "clause_route", "comparative_routes", "route_question", "resolve_routes_top_k") else module_name.split(".")[-1]

            def make(function, label, stage_name):
                @functools.wraps(function)
                def wrapper(*args, **kwargs):
                    FIRED[label] = FIRED.get(label, 0) + 1
                    chunks: list = []
                    find_chunks(list(args), chunks)
                    find_chunks(kwargs, chunks)
                    strings: list = []
                    find_strings(list(args)[:6], strings)
                    record = {
                        "stage": stage_name,
                        "fn": label,
                        "caller_chunks": rows(chunks)[:40],
                        "arg_strings": [value[:200] for value in strings if isinstance(value, str) and value.strip()][:12],
                        "kwargs_keys": sorted(str(key) for key in kwargs.keys()),
                        "kwargs_small": {str(key): trunc(value, 80) for key, value in kwargs.items() if isinstance(value, (int, float, bool, str, type(None)))},
                    }
                    try:
                        result = function(*args, **kwargs)
                    except Exception as exc:  # noqa: BLE001
                        record["error"] = f"{type(exc).__name__}: {exc}"
                        CAPTURED.append(record)
                        raise
                    returned: list = []
                    find_chunks(result, returned)
                    record["returned_chunks"] = rows(returned)[:40]
                    strings_out: list = []
                    find_strings(result if isinstance(result, (list, str)) else None, strings_out)
                    record["returned_strings"] = [value[:200] for value in strings_out if value.strip()][:12]
                    CAPTURED.append(record)
                    return result

                return wrapper

            setattr(module, name, make(fn, name, stage))
            for target_name in propagate:
                try:
                    target = __import__(target_name, fromlist=["__name__"])
                except Exception:  # noqa: BLE001
                    continue
                if getattr(target, name, None) is fn:
                    setattr(target, name, make(fn, name, stage))
            INSTALLED.append({"module": module_name, "name": name, "stage": stage, "status": "WRAPPED"})


def embed_probe(embd_mdl, query: str) -> dict:
    import numpy as np

    attempts = ["encode_queries:str", "encode_queries:list", "encode:str", "encode:list"]
    for attempt in attempts:
        digests, shapes, norms, vectors, errors = [], [], [], [], []
        for _ in range(RUNS):
            try:
                if attempt == "encode_queries:str":
                    out = embd_mdl.encode_queries(query)
                elif attempt == "encode_queries:list":
                    out = embd_mdl.encode_queries([query])
                elif attempt == "encode:str":
                    out = embd_mdl.encode(query)
                else:
                    out = embd_mdl.encode([query])
                if isinstance(out, tuple):
                    out = out[0]
                array = np.ascontiguousarray(np.asarray(out).reshape(-1))
                digests.append(hashlib.sha256(array.tobytes()).hexdigest())
                shapes.append(list(np.asarray(out).shape))
                norms.append(float(np.linalg.norm(array)))
                vectors.append(array)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(exc).__name__}: {exc}")
                break
        if errors:
            continue
        cosines = []
        for i in range(len(vectors)):
            for j in range(i + 1, len(vectors)):
                a, b = vectors[i], vectors[j]
                denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
                cosines.append(float(a.dot(b) / denominator) if denominator else 0.0)
        return {
            "convention": attempt,
            "status": "OBSERVED",
            "runs": len(digests),
            "dim": shapes[0][-1] if shapes else None,
            "shape_first": shapes[0],
            "sha256_unique_count": len(set(digests)),
            "sha256_first": digests[0],
            "vectors_bit_identical": len(set(digests)) == 1,
            "norm_min": min(norms),
            "norm_max": max(norms),
            "pairwise_cosine_min": min(cosines) if cosines else None,
            "pairwise_cosine_max": max(cosines) if cosines else None,
            "verdict": "QUERY_EMBEDDING_DETERMINISTIC" if len(set(digests)) == 1 else "QUERY_EMBEDDING_NONDETERMINISM_OBSERVED",
        }
    return {"status": "NOT_OBSERVABLE", "errors": errors[:3], "attempts_tried": attempts}


def extract(run_records: list, stage_names: tuple) -> dict:
    """Pull per-stage candidates, sub-queries and effective questions out of the raw call records."""
    out = {"routes": [], "pools": [], "sub_queries": [], "route_top_k": [], "effective_questions": []}
    for record in run_records:
        name = record["fn"]
        if name in ("rerank_chunks", "select_context", "_select", "apply_rank_adjustments"):
            if record.get("caller_chunks"):
                out["pools"].append({"fn": name, "candidates": record["caller_chunks"]})
        if "route" in name and record.get("caller_chunks"):
            label = "unlabeled"
            for value in record.get("arg_strings") or []:
                for candidate in ROUTE_NAMES:
                    if value.strip().lower() == candidate:
                        label = candidate
            out["routes"].append({"fn": name, "route": label, "candidates": record["caller_chunks"], "arg_strings": (record.get("arg_strings") or [])[:3], "kwargs_small": record.get("kwargs_small")})
            for value in record.get("arg_strings") or []:
                if 3 < len(value) < 200 and not value.startswith("{") and " " not in value[:20]:
                    out["effective_questions"].append(value)
        if name in ("decompose_question", "parse_sub_queries", "clause_route", "comparative_routes") and record.get("returned_strings"):
            out["sub_queries"].extend(record["returned_strings"])
        if name == "resolve_routes_top_k":
            out["route_top_k"].append({"kwargs_small": record.get("kwargs_small"), "arg_strings": (record.get("arg_strings") or [])[:4]})
    return out


async def run_once(question: str, chat_mdl, embd_mdl, dealer, params: dict) -> dict:
    CAPTURED.clear()
    chat_before = len(CHAT_CALLS)
    record: dict = {"error": None}
    try:
        kbinfos = await __import__("rag.retrieval", fromlist=["retrieve_multi_route"]).retrieve_multi_route(
            retriever=dealer, question=question, tenant_ids=[OWNER], kb_ids=[KB], chat_mdl=chat_mdl, embd_mdl=embd_mdl, **params
        )
    except Exception as exc:  # noqa: BLE001
        kbinfos = {}
        record["error"] = f"{type(exc).__name__}: {exc}"
    record["final"] = rows(kbinfos.get("chunks") or [])
    record["final_ids"] = [row["id"] for row in record["final"]]
    records = list(CAPTURED)
    record["stages"] = extract(records, ("decompose_question", "select_context"))
    record["chat_model_calls"] = len(CHAT_CALLS) - chat_before
    record["call_names"] = sorted({item["fn"] for item in records})
    return record


async def main() -> int:
    from common import settings

    settings.init_settings()
    from rag.nlp import search as rag_search
    from api.db.joint_services.tenant_model_service import get_tenant_default_model_by_type, resolve_model_config
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from api.db.services.llm_service import LLMBundle
    from common.constants import LLMType

    global OWNER
    ok, kb = KnowledgebaseService.get_by_id(KB)
    if not ok:
        print("STAGE_JSON_BEGIN")
        print(json.dumps({"error": "KB not found"}))
        print("STAGE_JSON_END")
        return 1
    OWNER = str(getattr(kb, "tenant_id", "") or "")
    embd_mdl = LLMBundle(OWNER, resolve_model_config(OWNER, LLMType.EMBEDDING, kb.embd_id))
    chat_mdl, chat_model_path = None, "NOT_AVAILABLE"
    try:
        config = get_tenant_default_model_by_type(OWNER, LLMType.CHAT)
        if isinstance(config, dict) and config:
            chat_mdl = LLMBundle(OWNER, config)
            chat_model_path = "TENANT_CONFIGURED_CHAT_MODEL"
    except Exception as exc:  # noqa: BLE001
        chat_model_path = f"NOT_AVAILABLE ({type(exc).__name__}: {exc})"

    try:
        original_chat = chat_mdl.async_chat

        @functools.wraps(original_chat)
        async def counting_chat(*args, **kwargs):
            CHAT_CALLS.append({"kwargs_keys": sorted(str(key) for key in kwargs.keys())})
            return await original_chat(*args, **kwargs)

        chat_mdl.async_chat = counting_chat
        chat_instrumentation = "INSTRUMENTED (counted only; this probe never generates an answer)"
    except Exception as exc:  # noqa: BLE001
        chat_instrumentation = f"NOT_INSTRUMENTED ({type(exc).__name__}: {exc})"

    install()
    dealer = rag_search.Dealer(settings.docStoreConn)
    signature = inspect.signature(__import__("rag.retrieval", fromlist=["retrieve_multi_route"]).retrieve_multi_route)
    params = {key: value for key, value in PARAMS.items() if key in signature.parameters}

    report = {
        "purpose": "P0 FIRST_DIVERGENCE_STAGE stage capture (instrumentation v2); read-only",
        "answer_generation": "NONE - no answer is generated by this probe",
        "series": "A only (chat model present), identical frozen parameters",
        "runs_per_query": RUNS,
        "frozen_parameters": PARAMS,
        "chat_model_path": chat_model_path,
        "chat_model_instrumentation": chat_instrumentation,
        "wrappers_installed": INSTALLED,
        "dealer_has_retrieval": hasattr(dealer, "retrieval"),
        "queries": [],
    }
    for query in QUERIES:
        item = {**query, "embedding_probe": embed_probe(embd_mdl, query["text"]), "runs": []}
        for index in range(RUNS):
            item["runs"].append(await run_once(query["text"], chat_mdl, embd_mdl, dealer, params))
            print(f"[stage] {query['id']} run {index + 1}/{RUNS}", file=sys.stderr)
        report["queries"].append(item)
    report["wrappers_fired"] = FIRED
    report["chat_model_calls_total"] = len(CHAT_CALLS)
    print("STAGE_JSON_BEGIN")
    print(json.dumps(report, ensure_ascii=False))
    print("STAGE_JSON_END")
    return 0


OWNER = ""

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
