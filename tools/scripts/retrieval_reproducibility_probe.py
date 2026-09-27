"""Read-only retrieval reproducibility probe (P0: FIRST_DIVERGENCE_STAGE).

No fix, no parameter change, no code change on the deployed side. This script only IMPORTS the
deployed modules and wraps their functions IN PROCESS to record what each stage returned; the
container filesystem is never written and no LLM answer is generated anywhere in this file.

Two series are measured per query so that a harness-configuration difference can be separated from
real randomness:

  series A - chat_mdl = tenant default chat model (the deployed-realistic configuration; the
             decomposition path may call it)
  series B - chat_mdl = None (this is what the previous behavioural round effectively used when its
             chat-model resolution failed, so B is the control for that history)

Measured per run:
  * decomposition output (sub-queries / routes) if this deployed revision exposes it
  * the effective retrieval question actually handed to the document store, per route
  * per-route candidate ids and scores (lexical / dense / hybrid, identified by
    vector_similarity_weight and rank_feature)
  * the fused pool handed to the (inactive) reranker, i.e. the candidates BEFORE the final cut
  * the final window returned to the caller, with all score fields
  * query embedding determinism: dim, sha256 of the raw bytes, and pairwise cosine over 10 encodes

Everything is printed as JSON between markers; nothing is written inside the container.
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
CHAT_CALLS: list = []
CAPTURED: list = []
INSTALLED: list = []
FIRED: dict = {}

PARAMS = {
    "similarity_threshold": 0.2,
    "vector_similarity_weight": 0.6,
    "routes_top_k": 12,
    "final_top_n": 8,
    "knn_top_k": 1024,
    "max_sub_queries": 4,
    "allow_dense_fallback": True,
}

# Reproducibility Set: candidate-stable and candidate-unstable entries come from the previous
# round's turn indices; "critical" are business-critical queries. Wording is kept exactly as tested.
QUERIES = [
    # 1 - candidate STABLE (previous round turn index 1, 7, 3, 15)
    {"id": "S_A1", "class": "CANDIDATE_STABLE", "origin": "previous turn 1 (Session A round 1)", "text": "Q/GDW 73286.2-2026 是什么标准？"},
    {"id": "S_A3", "class": "CANDIDATE_STABLE", "origin": "previous turn 3 (Session A round 3)", "text": "那 220kV 单芯海底电缆的主要结构有哪些？"},
    {"id": "S_B1", "class": "CANDIDATE_STABLE", "origin": "previous turn 7 (Session B round 1)", "text": "220kV 三芯海底电缆一般有哪些主要结构？"},
    {"id": "S_C3", "class": "CANDIDATE_STABLE", "origin": "previous turn 15 (Session C round 3)", "text": "哪些要求是它们共同的？"},
    # 2 - candidate UNSTABLE, five of the ten divergent indices (2, 4, 5, 12, 13)
    {"id": "U_A2", "class": "CANDIDATE_UNSTABLE", "origin": "previous turn index 2 (divergent)", "text": "这个标准适用于什么类型的电缆？"},
    {"id": "U_A4", "class": "CANDIDATE_UNSTABLE", "origin": "previous turn index 4 (divergent)", "text": "导体、内衬层和铠装层分别有什么技术要求？"},
    {"id": "U_A5", "class": "CANDIDATE_UNSTABLE", "origin": "previous turn index 5 (divergent)", "text": "这些要求都是这个专用技术规范自己规定的吗？"},
    {"id": "U_B6", "class": "CANDIDATE_UNSTABLE", "origin": "previous turn index 12 (divergent)", "text": "那你把专用规范和通用规范的要求区分开告诉我。"},
    {"id": "U_C1", "class": "CANDIDATE_UNSTABLE", "origin": "previous turn index 13 (divergent)", "text": "220kV 单芯和三芯海底电缆的技术要求有什么区别？"},
    # 3 - critical business queries: standard number, natural-language three-core, sheath/armour
    {"id": "K_STD", "class": "CRITICAL_BUSINESS", "origin": "new (standard number + numeric demand)", "text": "Q/GDW 73286.2-2026 中 220kV 单芯海底电缆内衬层厚度要求是多少？"},
    {"id": "K_3CORE", "class": "CRITICAL_BUSINESS", "origin": "new (natural-language three-core)", "text": "请说明 220kV 三芯海底电缆的主要结构以及铠装层的一般要求。"},
    {"id": "K_LAYER", "class": "CRITICAL_BUSINESS", "origin": "new (内衬层/铠装层 requirement lookup)", "text": "220kV 单芯海底电缆的内衬层和铠装层分别有什么技术要求？"},
]


def s(obj, depth: int = 0):
    """JSON-safe, size-bounded summary of an arbitrary object."""
    if depth > 3:
        return f"<{type(obj).__name__}>"
    if obj is None or isinstance(obj, (int, float, bool)):
        return obj
    if isinstance(obj, str):
        return obj[:600]
    if isinstance(obj, dict):
        return {str(k): s(v, depth + 1) for k, v in list(obj.items())[:24]}
    if isinstance(obj, (list, tuple, set)):
        return [s(v, depth + 1) for v in list(obj)[:40]]
    return f"<{type(obj).__name__}>"


def chunks_of(value):
    """Extract id/doc/score triples from a list of chunk dicts."""
    if not isinstance(value, list) or not value or not isinstance(value[0], dict):
        return None
    rows = []
    for item in value:
        if not isinstance(item, dict):
            return None
        cid = item.get("chunk_id") or item.get("id") or item.get("_id")
        if cid is None:
            return None
        rows.append(
            {
                "id": str(cid)[:16],
                "doc": str(item.get("docnm_kwd") or item.get("doc_name") or "")[:34],
                "similarity": s(item.get("similarity")),
                "vector_similarity": s(item.get("vector_similarity")),
                "term_similarity": s(item.get("term_similarity")),
                "score": s(item.get("score")),
                "rank_fea": s(item.get("rank_fea")),
            }
        )
    return rows


def summarize_result(result):
    if isinstance(result, dict):
        out = {"type": "dict", "keys": sorted(str(k) for k in result.keys())}
        chunk_groups = {}
        others = {}
        for key, value in result.items():
            rows = chunks_of(value)
            if rows is not None:
                chunk_groups[str(key)] = rows[:24]
            elif not isinstance(value, (list, dict)):
                others[str(key)] = s(value)
            else:
                others[str(key)] = s(value)
        if chunk_groups:
            out["chunk_groups"] = chunk_groups
        out["other"] = others
        return out
    if isinstance(result, (list, tuple)):
        return {"type": type(result).__name__, "value": s(result)}
    if isinstance(result, str):
        return {"type": "str", "value": s(result)}
    return {"type": type(result).__name__}


def install(tag: str, module_name: str, name: str, propagate: list) -> bool:
    try:
        module = __import__(module_name, fromlist=["__name__"])
    except Exception as exc:  # noqa: BLE001
        INSTALLED.append({"module": module_name, "name": name, "status": f"IMPORT_FAILED {type(exc).__name__}"})
        return False
    fn = getattr(module, name, None)
    if fn is None or not callable(fn):
        return False
    if not str(getattr(fn, "__module__", "")).startswith("rag"):
        return False

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            FIRED[name] = FIRED.get(name, 0) + 1
            record = {"stage": tag, "fn": name, "args": s([a for a in args]), "kwargs": s(kwargs)}
            try:
                result = await fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                record["error"] = f"{type(exc).__name__}: {exc}"
                CAPTURED.append(record)
                raise
            record["result"] = summarize_result(result)
            CAPTURED.append(record)
            return result

    else:

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            FIRED[name] = FIRED.get(name, 0) + 1
            record = {"stage": tag, "fn": name, "args": s([a for a in args]), "kwargs": s(kwargs)}
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                record["error"] = f"{type(exc).__name__}: {exc}"
                CAPTURED.append(record)
                raise
            record["result"] = summarize_result(result)
            CAPTURED.append(record)
            return result

    wanted = ("decompos", "sub_quer", "route", "rewrite", "expand", "plan", "fuse", "fusion", "select", "rank", "merge", "order", "cut", "candidate")
    if not any(token in name.lower() for token in wanted):
        return False
    setattr(module, name, wrapper)
    for target_name in propagate:
        try:
            target = __import__(target_name, fromlist=["__name__"])
        except Exception:  # noqa: BLE001
            continue
        if getattr(target, name, None) is fn:
            setattr(target, name, wrapper)
    INSTALLED.append({"module": module_name, "name": name, "status": "WRAPPED", "tag": tag})
    return True


def install_all() -> None:
    propagate = ["rag.retrieval.multi_route", "rag.retrieval.pipeline", "rag.retrieval"]
    for module_name in ("rag.retrieval.decomposition", "rag.retrieval.multi_route", "rag.retrieval.pipeline", "rag.retrieval.rerank"):
        try:
            module = __import__(module_name, fromlist=["__name__"])
        except Exception as exc:  # noqa: BLE001
            INSTALLED.append({"module": module_name, "name": "-", "status": f"IMPORT_FAILED {type(exc).__name__}"})
            continue
        for name in list(dir(module)):
            if name.startswith("__"):
                continue
            install("decomposition" if "decompos" in module_name else module_name.split(".")[-1], module_name, name, propagate)

    from rag.nlp import search as rag_search

    def make_retriever_wrapper(function, label):
        @functools.wraps(function)
        def wrapper(self, *args, **kwargs):
            FIRED[label] = FIRED.get(label, 0) + 1
            record = {"stage": "retriever", "fn": label, "args": s([a for a in args]), "kwargs": s(kwargs)}
            try:
                result = function(self, *args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                record["error"] = f"{type(exc).__name__}: {exc}"
                CAPTURED.append(record)
                raise
            record["result"] = summarize_result(result)
            CAPTURED.append(record)
            return result

        return wrapper

    for name in ("retrieval", "search", "rerank", "dense", "lexical"):
        fn = getattr(rag_search.Dealer, name, None)
        if fn is None or not callable(fn) or inspect.iscoroutinefunction(fn):
            continue
        setattr(rag_search.Dealer, name, make_retriever_wrapper(fn, f"Dealer.{name}"))
        INSTALLED.append({"module": "rag.nlp.search.Dealer", "name": name, "status": "WRAPPED", "tag": "retriever"})


def instrument_chat(model) -> str:
    if model is None:
        return "NOT_INSTRUMENTED (no chat model)"
    try:
        original = model.async_chat

        @functools.wraps(original)
        async def wrapper(*args, **kwargs):
            CHAT_CALLS.append({"args": s([a for a in args])[:2], "kwargs_keys": sorted(str(k) for k in kwargs.keys())})
            return await original(*args, **kwargs)

        model.async_chat = wrapper
        return "INSTRUMENTED (async_chat counted; no answer is generated by this script)"
    except Exception as exc:  # noqa: BLE001
        return f"NOT_INSTRUMENTED ({type(exc).__name__}: {exc})"


def route_of(record: dict) -> str:
    weight = None
    rank_feature = None
    for value in (record.get("args") or []) + [record.get("kwargs")]:
        pass
    text = json.dumps(record, ensure_ascii=False)
    for token, label in (("\"vector_similarity_weight\": 0.0", "vsw=0"), ("\"vector_similarity_weight\": 0", "vsw=0"), ("\"vector_similarity_weight\": 1", "vsw=1")):
        if token in text:
            weight = label
    if isinstance(record.get("kwargs"), dict):
        rank_feature = record["kwargs"].get("rank_feature")
    if weight == "vsw=0":
        return "lexical"
    if weight == "vsw=1":
        return "dense"
    if rank_feature:
        return f"rank_feature={rank_feature}"
    return "hybrid_or_unlabeled"


def embed_probe(embd_mdl, query: str) -> dict:
    import numpy as np

    digests, shapes, norms, vectors = [], [], [], []
    method = None
    for _ in range(RUNS):
        try:
            if hasattr(embd_mdl, "encode_queries"):
                out = embd_mdl.encode_queries([query])
                method = "encode_queries"
            else:
                out = embd_mdl.encode([query])
                method = "encode"
            if isinstance(out, tuple):
                out = out[0]
            array = np.asarray(out)
            array = np.ascontiguousarray(array.reshape(-1))
            digests.append(hashlib.sha256(array.tobytes()).hexdigest())
            shapes.append(list(np.asarray(out).shape))
            norms.append(float(np.linalg.norm(array)))
            vectors.append(array)
        except Exception as exc:  # noqa: BLE001
            return {"method": method, "status": f"NOT_OBSERVABLE ({type(exc).__name__}: {exc})"}
    cosines = []
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            a, b = vectors[i], vectors[j]
            denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
            cosines.append(float(a.dot(b) / denominator) if denominator else 0.0)
    return {
        "method": method,
        "status": "OBSERVED",
        "runs": len(digests),
        "shape_first": shapes[0],
        "shape_identical": len({json.dumps(shape) for shape in shapes}) == 1,
        "sha256_unique_count": len(set(digests)),
        "sha256_first": digests[0],
        "vectors_bit_identical": len(set(digests)) == 1,
        "norm_min": min(norms),
        "norm_max": max(norms),
        "pairwise_cosine_min": min(cosines) if cosines else None,
        "pairwise_cosine_max": max(cosines) if cosines else None,
        "verdict": "QUERY_EMBEDDING_DETERMINISTIC" if len(set(digests)) == 1 else "QUERY_EMBEDDING_NONDETERMINISM_OBSERVED",
    }


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

    record["kbinfos_keys"] = sorted(str(k) for k in kbinfos.keys())
    record["kbinfos_other"] = {str(k): s(v) for k, v in kbinfos.items() if k != "chunks"}
    record["final"] = chunks_of(kbinfos.get("chunks")) or []
    record["final_ids"] = [row["id"] for row in record["final"]]

    route_calls, decomposition, fusion = [], [], []
    for item in CAPTURED:
        if item["stage"] == "retriever":
            groups = (item.get("result") or {}).get("chunk_groups") or {}
            flat = []
            for rows in groups.values():
                flat.extend(rows)
            route_calls.append(
                {
                    "fn": item["fn"],
                    "route": route_of(item),
                    "args": item["args"][:8] if isinstance(item["args"], list) else item["args"],
                    "kwargs": item["kwargs"],
                    "candidates": flat[:24],
                    "candidate_ids": [row["id"] for row in flat][:24],
                    "error": item.get("error"),
                }
            )
        elif item["stage"] == "decomposition":
            decomposition.append({"fn": item["fn"], "args": item["args"], "kwargs": item["kwargs"], "result": item.get("result"), "error": item.get("error")})
        else:
            groups = (item.get("result") or {}).get("chunk_groups") or {}
            flat = []
            for rows in groups.values():
                flat.extend(rows)
            fusion.append({"stage": item["stage"], "fn": item["fn"], "input_ids": [row["id"] for row in flat][:24], "result": item.get("result"), "error": item.get("error")})

    record["route_calls"] = route_calls
    record["decomposition_calls"] = decomposition
    record["fusion_calls"] = fusion
    record["chat_model_calls"] = len(CHAT_CALLS) - chat_before
    derived_questions = []
    for call in route_calls:
        args = call.get("args") or []
        if args and isinstance(args[0], str):
            derived_questions.append(args[0])
    record["effective_retrieval_questions"] = derived_questions
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
        print("PROBE_JSON_BEGIN")
        print(json.dumps({"error": "KB not found"}))
        print("PROBE_JSON_END")
        return 1
    OWNER = str(getattr(kb, "tenant_id", "") or "")
    embd_mdl = LLMBundle(OWNER, resolve_model_config(OWNER, LLMType.EMBEDDING, kb.embd_id))

    chat_model_path = "NOT_AVAILABLE"
    chat_mdl = None
    try:
        config = get_tenant_default_model_by_type(OWNER, LLMType.CHAT)
        if isinstance(config, dict) and config:
            chat_mdl = LLMBundle(OWNER, config)
            chat_model_path = "TENANT_CONFIGURED_CHAT_MODEL (get_tenant_default_model_by_type(tenant, LLMType.CHAT) -> LLMBundle)"
    except Exception as exc:  # noqa: BLE001
        chat_model_path = f"NOT_AVAILABLE ({type(exc).__name__}: {exc})"

    chat_instrumentation = instrument_chat(chat_mdl)
    install_all()
    dealer = rag_search.Dealer(settings.docStoreConn)
    params = {key: value for key, value in PARAMS.items() if key in inspect.signature(__import__("rag.retrieval", fromlist=["retrieve_multi_route"]).retrieve_multi_route).parameters}

    report = {
        "purpose": "P0 FIRST_DIVERGENCE_STAGE for retrieval instability; read-only instrumentation",
        "answer_generation": "NONE - this script never calls the chat model to produce an answer",
        "runs_per_query": RUNS,
        "frozen_parameters": PARAMS,
        "parameters_accepted_by_deployed_signature": sorted(params.keys()),
        "chat_model_path": chat_model_path,
        "chat_model_instrumentation": chat_instrumentation,
        "wrappers_installed": INSTALLED,
        "kb_id": KB,
        "owner_tenant": OWNER,
        "queries": [],
    }

    for query in QUERIES:
        item = {**query, "series": {}, "embedding_probe": embed_probe(embd_mdl, query["text"])}
        for tag, model in (("A_chat_model_present", chat_mdl), ("B_chat_model_absent", None)):
            runs = []
            for index in range(RUNS):
                runs.append(await run_once(query["text"], model, embd_mdl, dealer, params))
                print(f"[probe] {query['id']} {tag} run {index + 1}/{RUNS}", file=sys.stderr)
            item["series"][tag] = runs
        report["queries"].append(item)

    report["wrappers_fired"] = FIRED
    report["chat_model_calls_total"] = len(CHAT_CALLS)
    report["chat_model_call_shapes"] = CHAT_CALLS[:8]
    print("PROBE_JSON_BEGIN")
    print(json.dumps(report, ensure_ascii=False))
    print("PROBE_JSON_END")
    return 0


OWNER = ""

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
