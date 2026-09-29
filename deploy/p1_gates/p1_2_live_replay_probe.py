"""P1-2 live replay probe: the six frozen P1-0 queries through the REAL pipeline, cold.

The same script runs on both sides of P1-2, which is what makes the comparison like-for-like:

* on the DEPLOYED image (no P1-2 files mounted) it measures what the model-authoritative planner
  actually executed, because it captures the ``queries`` argument the pipeline hands to
  ``multi_route_retrieve`` - i.e. the executable topology, not the model's proposal;
* with the repository's ``rag/retrieval`` mounted it measures the same thing, plus the compiled
  plan's hash, slots, sources and fallback triggers.

What it records per run: the ordered route list actually executed (first pass and any
content-conditional scoped pass, kept separate), the returned window, the number of chat-model
calls and each call's latency, and - under P1-2 - the plan hash and provenance.

Isolation, all of it in-process:
* the LLM cache is patched to always miss / never write, so every run is a genuine cold call and
  the deployed Redis is neither read nor written by the cache;
* ``WENRUO_PLAN_CACHE=off`` is exported by the runner, so the plan cache is disabled and no
  ``p1plan:`` key is created anywhere;
* no answer is generated, no retrieval parameter is changed, nothing is deployed.

Output: the JSON report is WRITTEN to ``P12_REPLAY_OUT`` as UTF-8 (never through a shell
redirect, which on Windows writes UTF-16).
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, "/ragflow")
sys.dont_write_bytecode = True

KB = "9463d93eb97511f1938f2592e9bc6fe4"
RUNS = int(os.environ.get("P12_REPLAY_RUNS", "10"))
OUT = pathlib.Path(os.environ.get("P12_REPLAY_OUT", "/tmp/p12_replay.json"))
LABEL = os.environ.get("P12_REPLAY_LABEL", "unlabelled")

CHAT_CALLS: list = []
ROUTE_CALLS: list = []

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
                "part": next((marker for marker in ("第1部分", "第2部分", "第3部分") if marker in str(chunk.get("docnm_kwd") or "")), "other"),
                "similarity": scalar,
            }
        )
    return out


def patch(module, name: str, replacement) -> bool:
    """Replace ``module.name``, and every module that imported it by value."""
    if not hasattr(module, name):
        return False
    original = getattr(module, name)
    setattr(module, name, replacement)
    for other in ("rag.retrieval", "rag.retrieval.pipeline", "rag.retrieval.multi_route", "rag.retrieval.decomposition"):
        try:
            target = __import__(other, fromlist=["__name__"])
        except Exception:  # noqa: BLE001
            continue
        if getattr(target, name, None) is original:
            setattr(target, name, replacement)
    return True


async def main() -> int:
    from common import settings

    settings.init_settings()
    import rag.graphrag.utils as gu

    cache_state = {"get_llm_cache": type(gu.get_llm_cache).__name__, "set_llm_cache": type(gu.set_llm_cache).__name__}
    gu.get_llm_cache = lambda *args, **kwargs: None
    gu.set_llm_cache = lambda *args, **kwargs: None

    from api.db.joint_services.tenant_model_service import get_tenant_default_model_by_type, resolve_model_config
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from api.db.services.llm_service import LLMBundle
    from common.constants import LLMType
    from rag.nlp import search as rag_search

    ok, kb = KnowledgebaseService.get_by_id(KB)
    if not ok:
        print(json.dumps({"error": "KB not found"}), file=sys.stderr)
        return 1
    owner = str(getattr(kb, "tenant_id", "") or "")
    embd_mdl = LLMBundle(owner, resolve_model_config(owner, LLMType.EMBEDDING, kb.embd_id))
    chat_mdl, chat_path = None, "NOT_AVAILABLE"
    try:
        config = get_tenant_default_model_by_type(owner, LLMType.CHAT)
        if isinstance(config, dict) and config:
            chat_mdl = LLMBundle(owner, config)
            chat_path = "TENANT_CONFIGURED_CHAT_MODEL"
    except Exception as exc:  # noqa: BLE001
        chat_path = f"NOT_AVAILABLE ({type(exc).__name__}: {exc})"

    if chat_mdl is not None:
        original_chat = chat_mdl.async_chat

        @functools.wraps(original_chat)
        async def counting(*args, **kwargs):
            started = time.perf_counter()
            error = None
            try:
                return await original_chat(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}"
                raise
            finally:
                CHAT_CALLS.append({"latency_ms": round((time.perf_counter() - started) * 1000, 3), "error": error})

        chat_mdl.async_chat = counting

    # Capture the EXECUTED route list: the first positional/keyword argument of every
    # multi_route_retrieve call, which is the route list the pipeline decided on.
    import rag.retrieval.multi_route as multi_route_module

    original_retrieve = multi_route_module.multi_route_retrieve

    @functools.wraps(original_retrieve)
    async def capturing(*args, **kwargs):
        queries = kwargs.get("queries")
        if queries is None and args:
            queries = args[1] if len(args) > 1 else None
        started = time.perf_counter()
        failed = None
        try:
            return await original_retrieve(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            failed = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            ROUTE_CALLS.append(
                {
                    "queries": [str(query) for query in (queries or [])],
                    "scoped": kwargs.get("doc_ids") is not None,
                    "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                    "failed": failed,
                }
            )

    patch(multi_route_module, "multi_route_retrieve", capturing)

    # Under P1-2 the compiled plan is captured too. The probe must also run on the deployed image,
    # where `rag.retrieval.planner` does not exist, so this is conditional.
    PLAN_CALLS: list = []
    planner_present = False
    planner_module = None
    try:
        import rag.retrieval.planner as planner_module

        planner_present = True
        original_compile = planner_module.compile_retrieval_plan

        @functools.wraps(original_compile)
        async def compiling(*args, **kwargs):
            plan = await original_compile(*args, **kwargs)
            PLAN_CALLS.append(
                {
                    "plan_hash": plan.plan_hash,
                    "topology_size": plan.topology_size,
                    "ordered_routes": list(plan.texts),
                    "slot_ids": [route.slot_id for route in plan.routes],
                    "slot_sources": list(plan.slot_sources),
                    "triggers": list(plan.provenance.fallback_reasons),
                    "cache_state": plan.provenance.cache_state,
                    "consulted": plan.provenance.consulted,
                    "model_latency_ms": plan.provenance.model_latency_ms,
                    "proposals": len(plan.provenance.proposals),
                }
            )
            return plan

        patch(planner_module, "compile_retrieval_plan", compiling)
    except Exception as exc:  # noqa: BLE001
        planner_present = False
        print(f"[replay] planner not present ({type(exc).__name__}: {exc}); measuring the deployed path", file=sys.stderr)

    dealer = rag_search.Dealer(settings.docStoreConn)
    import rag.retrieval as retrieval_package

    signature = inspect.signature(retrieval_package.retrieve_multi_route)
    params = {key: value for key, value in PARAMS.items() if key in signature.parameters}

    report = {
        "purpose": "P1-2 live replay of the six frozen P1-0 queries through the real pipeline",
        "label": LABEL,
        "plan_version": getattr(planner_module, "PLAN_VERSION", None),
        "planner_present": planner_present,
        "image": os.environ.get("P12_REPLAY_IMAGE", "unknown"),
        "isolation": {
            "llm_cache": "in-process bypass (always miss, never write); deployed Redis cache untouched",
            "plan_cache": "WENRUO_PLAN_CACHE=" + str(os.environ.get("WENRUO_PLAN_CACHE")),
            "answer_generation": "NONE",
            "retrieval_parameters_changed": False,
        },
        "cache_functions_before": cache_state,
        "runs_per_query": RUNS,
        "frozen_parameters": PARAMS,
        "chat_model_path": chat_path,
        "queries": [],
    }

    for query in QUERIES:
        item = {**query, "runs": []}
        for index in range(RUNS):
            ROUTE_CALLS.clear()
            PLAN_CALLS.clear()
            chat_before = len(CHAT_CALLS)
            kbinfos, error = {}, None
            started = time.perf_counter()
            try:
                kbinfos = await retrieval_package.retrieve_multi_route(
                    retriever=dealer, question=query["text"], tenant_ids=[owner], kb_ids=[KB], chat_mdl=chat_mdl, embd_mdl=embd_mdl, **params
                )
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"
            elapsed = round((time.perf_counter() - started) * 1000, 3)
            calls = list(CHAT_CALLS[chat_before:])
            chunks = kbinfos.get("chunks") or []
            first_pass = [call for call in ROUTE_CALLS if not call["scoped"]]
            scoped = [call for call in ROUTE_CALLS if call["scoped"]]
            item["runs"].append(
                {
                    "run": index + 1,
                    "executed_routes": first_pass[0]["queries"] if first_pass else [],
                    "scoped_passes": [call["queries"] for call in scoped],
                    "route_count": len(first_pass[0]["queries"]) if first_pass else 0,
                    "plan": PLAN_CALLS[0] if PLAN_CALLS else None,
                    "chat_calls": len(calls),
                    "chat_latency_ms": [call["latency_ms"] for call in calls],
                    "chat_errors": [call["error"] for call in calls if call["error"]],
                    "retrieval_latency_ms": elapsed,
                    "window": rows(chunks),
                    "window_ids": [row["id"] for row in rows(chunks)],
                    "kbinfos_keys": sorted(str(key) for key in kbinfos.keys()),
                    "error": error,
                }
            )
            print(
                f"[replay:{LABEL}] {query['id']} run {index + 1}/{RUNS} routes={item['runs'][-1]['route_count']} "
                f"window={len(item['runs'][-1]['window'])} chat={item['runs'][-1]['chat_calls']} error={error}",
                file=sys.stderr,
            )
        report["queries"].append(item)

    report["chat_calls_total"] = len(CHAT_CALLS)
    report["chat_latency_ms_total"] = round(sum(call["latency_ms"] for call in CHAT_CALLS), 3)
    report["chat_errors_total"] = sum(1 for call in CHAT_CALLS if call["error"])
    report["chat_latency_ms_median"] = (
        round(sorted(call["latency_ms"] for call in CHAT_CALLS)[len(CHAT_CALLS) // 2], 3) if CHAT_CALLS else None
    )
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[replay:{LABEL}] wrote {OUT} ({len(CHAT_CALLS)} chat call(s) total)", file=sys.stderr)
    print("P12_REPLAY_BEGIN")
    print(json.dumps({key: report[key] for key in ("label", "planner_present", "runs_per_query", "chat_calls_total", "chat_latency_ms_total", "chat_latency_ms_median", "chat_errors_total")}, ensure_ascii=False))
    print("P12_REPLAY_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
