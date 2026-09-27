"""Task A probe: decomposition cold-cache sensitivity (isolated, read-only with respect to Redis).

Isolation method: this process patches `get_llm_cache` to always miss and `set_llm_cache` to a no-op,
so the deployed decomposition path runs UNCACHED inside this process only. Production Redis keys are
never read, written, deleted or flushed, and no deployed file is modified.

Every query is run 10 times through the real deployed pipeline with the cache disabled, so each run
produces its own fresh LLM decomposition and its own evidence window. The pair (sub-queries -> window)
is therefore captured per run, which is the retrieval replay the round asks for, without needing to
inject a synthetic route list.

No answer is generated. No retrieval parameter is changed.
"""

from __future__ import annotations

import asyncio
import functools
import json
import sys

sys.path.insert(0, "/ragflow")

KB = "9463d93eb97511f1938f2592e9bc6fe4"
RUNS = 10
CHAT_CALLS: list = []
FIRED: dict = {}
CAPTURED: list = []

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
    {"id": "C_STD", "kind": "COMPOSITE", "text": "Q/GDW 73286.2-2026 中 220kV 单芯海底电缆的内衬层厚度和铠装层要求分别是多少？"},
    {"id": "C_COMPARE", "kind": "COMPOSITE", "text": "220kV 单芯和三芯海底电缆的内衬层要求有什么区别？"},
    {"id": "C_PARTS", "kind": "COMPOSITE", "text": "导体、内衬层和铠装层分别有什么技术要求？"},
    {"id": "C_MULTI", "kind": "COMPOSITE", "text": "单芯电缆与三芯电缆在金属套厚度和铠装层结构上有什么不同，各自依据哪份规范？"},
    {"id": "N_STD", "kind": "NON_COMPOSITE_CONTROL", "text": "Q/GDW 73286.2-2026 是什么标准？"},
    {"id": "N_ARMOUR", "kind": "NON_COMPOSITE_CONTROL", "text": "220kV 三芯海底电缆的铠装层要求是什么？"},
]


def rows(chunks: list) -> list:
    out, seen = [], set()
    for chunk in chunks or []:
        cid = str(chunk.get("chunk_id") or chunk.get("id") or "")[:16]
        if not cid or cid in seen:
            continue
        seen.add(cid)
        similarity = chunk.get("similarity")
        scalar = similarity if isinstance(similarity, (int, float)) else (similarity[0] if isinstance(similarity, list) and similarity else None)
        out.append(
            {
                "id": cid,
                "part": next((m for m in ("第1部分", "第2部分", "第3部分") if m in str(chunk.get("docnm_kwd") or "")), "other"),
                "similarity": scalar,
            }
        )
    return out


def wrap(module_name: str, name: str, stage: str, bucket: list) -> None:
    try:
        module = __import__(module_name, fromlist=["__name__"])
    except Exception:  # noqa: BLE001
        return
    fn = getattr(module, name, None)
    if not callable(fn):
        return

    if inspect_is_async(fn):

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            FIRED[name] = FIRED.get(name, 0) + 1
            result = await fn(*args, **kwargs)
            bucket.append({"stage": stage, "fn": name, "result": summarize(result)})
            return result

    else:

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            FIRED[name] = FIRED.get(name, 0) + 1
            result = fn(*args, **kwargs)
            bucket.append({"stage": stage, "fn": name, "result": summarize(result)})
            return result

    setattr(module, name, wrapper)
    for other in ("rag.retrieval.pipeline", "rag.retrieval.multi_route", "rag.retrieval"):
        try:
            target = __import__(other, fromlist=["__name__"])
        except Exception:  # noqa: BLE001
            continue
        if getattr(target, name, None) is fn:
            setattr(target, name, wrapper)


def inspect_is_async(fn) -> bool:
    import inspect

    return inspect.iscoroutinefunction(fn)


def summarize(result):
    if isinstance(result, list):
        return [str(item)[:160] for item in result[:12]]
    if isinstance(result, str):
        return result[:160]
    if result is None:
        return None
    if isinstance(result, dict):
        return {str(key): str(value)[:120] for key, value in list(result.items())[:10]}
    return f"<{type(result).__name__}>"


async def main() -> int:
    from common import settings

    settings.init_settings()
    import rag.graphrag.utils as gu

    cache_state = {
        "get_llm_cache": type(gu.get_llm_cache).__name__,
        "set_llm_cache": type(gu.set_llm_cache).__name__,
    }
    gu.get_llm_cache = lambda *args, **kwargs: None
    gu.set_llm_cache = lambda *args, **kwargs: None
    patched = ["rag.graphrag.utils"]
    try:
        import rag.prompts.generator as generator

        if hasattr(generator, "get_llm_cache"):
            generator.get_llm_cache = gu.get_llm_cache
            generator.set_llm_cache = gu.set_llm_cache
            patched.append("rag.prompts.generator")
    except Exception:  # noqa: BLE001
        pass

    from api.db.joint_services.tenant_model_service import get_tenant_default_model_by_type, resolve_model_config
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from api.db.services.llm_service import LLMBundle
    from common.constants import LLMType
    from rag.nlp import search as rag_search
    from rag.retrieval.decomposition import looks_composite

    global OWNER
    ok, kb = KnowledgebaseService.get_by_id(KB)
    if not ok:
        print("COLD_JSON_BEGIN")
        print(json.dumps({"error": "KB not found"}))
        print("COLD_JSON_END")
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

    if chat_mdl is not None:
        original = chat_mdl.async_chat

        @functools.wraps(original)
        async def counting(*args, **kwargs):
            CHAT_CALLS.append(1)
            return await original(*args, **kwargs)

        chat_mdl.async_chat = counting

    calls: list = []
    for name, stage in (("decompose_question", "decomposition"), ("comparative_routes", "side_route"), ("clause_route", "side_route"), ("core_document_followup", "followup"), ("rerank_chunks", "selection")):
        wrap("rag.retrieval.decomposition" if name in ("decompose_question", "comparative_routes", "clause_route") else "rag.retrieval.pipeline", name, stage, calls)

    dealer = rag_search.Dealer(settings.docStoreConn)
    import inspect

    signature = inspect.signature(__import__("rag.retrieval", fromlist=["retrieve_multi_route"]).retrieve_multi_route)
    params = {key: value for key, value in PARAMS.items() if key in signature.parameters}

    report = {
        "purpose": "Task A: decomposition cold-cache sensitivity with paired retrieval replay",
        "isolation": "in-process cache bypass only; production Redis untouched (no read, write, delete or flush)",
        "cache_functions_before": cache_state,
        "patched_modules": patched,
        "runs_per_query": RUNS,
        "frozen_parameters": PARAMS,
        "chat_model_path": chat_model_path,
        "answer_generation": "NONE",
        "queries": [],
    }

    for query in QUERIES:
        calls.clear()
        chat_before = len(CHAT_CALLS)
        item = {**query, "looks_composite": bool(looks_composite(query["text"])), "runs": []}
        for index in range(RUNS):
            calls.clear()
            kbinfos, error = {}, None
            try:
                kbinfos = await __import__("rag.retrieval", fromlist=["retrieve_multi_route"]).retrieve_multi_route(
                    retriever=dealer, question=query["text"], tenant_ids=[OWNER], kb_ids=[KB], chat_mdl=chat_mdl, embd_mdl=embd_mdl, **params
                )
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"
            decomposition = [call for call in calls if call["stage"] == "decomposition"]
            side = [call for call in calls if call["stage"] == "side_route"]
            followup = [call for call in calls if call["stage"] == "followup"]
            chunks = kbinfos.get("chunks") or []
            item["runs"].append(
                {
                    "run": index + 1,
                    "sub_queries": (decomposition[0]["result"] if decomposition else []),
                    "side_routes": [value for call in side for value in (call["result"] if isinstance(call["result"], list) else ([call["result"]] if call["result"] else []))],
                    "decomposition_calls": len(decomposition),
                    "followup_calls": len(followup),
                    "kbinfos_keys": sorted(str(key) for key in kbinfos.keys()),
                    "window": rows(chunks),
                    "window_ids": [row["id"] for row in rows(chunks)],
                    "error": error,
                    "chat_calls_this_run": len(CHAT_CALLS) - chat_before if index == 0 else None,
                }
            )
            print(f"[cold] {query['id']} run {index + 1}/{RUNS} subs={len(item['runs'][-1]['sub_queries'])} window={len(item['runs'][-1]['window'])}", file=sys.stderr)
        report["queries"].append(item)

    report["wrappers_fired"] = FIRED
    report["chat_model_calls_total"] = len(CHAT_CALLS)
    print("COLD_JSON_BEGIN")
    print(json.dumps(report, ensure_ascii=False))
    print("COLD_JSON_END")
    return 0


OWNER = ""

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
