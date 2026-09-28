"""LIVE incident acceptance: prove the execution chain on real production retrieval.

The incident's own acceptance condition is present in production right now (the embedding provider
refuses with a location restriction), so this is the real thing rather than a simulation of it.

WHAT THIS PROVES, in the operator's required form - the execution chain, not "some chunks came back":

    Dense failure -> lexical ES request actually executed -> real lexical candidates
                  -> degraded selection -> merge/context -> final retrieval_health

EVERY fact below is OBSERVED at a real boundary:

* the dense leg is exercised by the real `LLMBundle` against the real provider;
* the lexical leg is observed by wrapping the real `dataStore.search` round trip, which records the
  expression types that were sent (so "lexical ran" means an actual `MatchTextExpr` ES request, and
  "dense did not run" means no `MatchDenseExpr`/`FusionExpr` was sent);
* candidates are the ids the store returned, not a fixture;
* `retrieval_health` is read from the real session the pipeline built;
* the P0-7 operator event is captured from the real emitter's logger.

Nothing is fabricated and nothing is monkeypatched INTO the retrieval path: the wrappers observe.
Secrets are never printed - a provider failure is reduced to its exception class plus a boolean
saying whether its text matched the known location-restriction marker.

Read-only with respect to ES, MySQL and Redis; no answer is generated; no parameter is changed.
"""
import asyncio
import contextvars
import json
import logging
import os
import pathlib
import sys

sys.path.insert(0, "/ragflow")

from common import settings

settings.init_settings()

from api.db.db_models import Dialog
from api.db.joint_services.tenant_model_service import get_tenant_default_model_by_type, resolve_model_config
from api.db.services.knowledgebase_service import KnowledgebaseService
from api.db.services.llm_service import LLMBundle
from common.constants import LLMType
from rag.nlp import search as rag_search
from rag.retrieval import health_bridge as hb
from rag.retrieval import retrieve_multi_route

OUT = pathlib.Path(os.environ.get("P12_LIVE_OUT", "/tmp/live_incident_acceptance.json"))

KB = "9463d93eb97511f1938f2592e9bc6fe4"
TENANT = "a9e28731ab7011f19b833887d563fb04"
THREE = "d1d75672f2dbc333"
SINGLE = "b5aaf72bcd33d44a"
INCIDENT = "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"
CONTROL = "根据 Q/GDW 73286.2-2026 表 1，单芯电缆的导体标称截面有哪些规格？"
STRUCTURE = "220kV 三芯海缆的主要结构有哪些？"

#: Anything matching these must never appear in a payload, a log line or a health field.
LEAK_MARKERS = ("AQ.Ab8RN6", "api_key", "Authorization", "generativelanguage", "AIza", "Traceback", "RESOURCE_EXHAUSTED", "FAILED_PRECONDITION", "content_with_weight", "三芯海缆")

OPERATOR_MARKER = "[RetrievalHealth]"
FROZEN_OPERATOR_FIELDS = {"event", "schema_version", "overall", "reason", "evidence_completeness", "legs", "contract_valid", "routes_attempted", "routes_succeeded"}

operator_lines = []


class OperatorCapture(logging.Handler):
    def emit(self, record):
        message = record.getMessage()
        if message.startswith(OPERATOR_MARKER):
            operator_lines.append(message)


def sanitized_provider_outcome(exc):
    text = f"{type(exc).__name__}: {exc}"
    return {
        "exception_class": type(exc).__name__,
        "is_location_restriction": "failed_precondition" in text.casefold() and "location" in text.casefold(),
        "is_credential_or_permission": any(marker in text.casefold() for marker in ("401", "403", "permission_denied", "unauthenticated", "api key not valid", "forbidden")),
        "classified_recoverable": bool(rag_search.Dealer._recoverable_embedding_failure(exc)),
        "length": len(text),
    }


def assistant_parameters():
    """The real assistant's retrieval parameters, so the run uses production's own numbers."""
    for row in Dialog.select().where((Dialog.tenant_id == TENANT) & (Dialog.kb_ids.is_null(False))).dicts():
        kb_ids = row.get("kb_ids") or []
        if KB in kb_ids:
            return {
                "dialog_id": row.get("id"),
                "dialog_name": row.get("name"),
                "kb_ids": kb_ids,
                "similarity_threshold": row.get("similarity_threshold"),
                "vector_similarity_weight": row.get("vector_similarity_weight"),
                "top_n": row.get("top_n"),
                "top_k": row.get("top_k"),
                "rerank_id": row.get("rerank_id"),
            }
    return None


async def run_question(dealer, chat_mdl, embd_mdl, rerank_mdl, question, params):
    """One live retrieval, with every boundary observed.

    Route attribution matters and is easy to get wrong: the routes are retrieved CONCURRENTLY, so the
    order in which `dataStore.search` calls return is completion order, not route order. A
    ContextVar set on the route's own task is the only correct way to say which query a given ES
    request belongs to - the value is copied into the worker thread by `thread_pool_exec`, exactly as
    the retrieval path's own health session is.
    """
    route_of_request = contextvars.ContextVar("p12_route_query", default=None)
    es_requests = []
    provider_calls = []
    original_search = dealer.dataStore.search
    original_retrieve = dealer.retrieval
    original_encode = embd_mdl.encode_queries if embd_mdl is not None else None

    async def capture_retrieval(query, *args, **kwargs):
        route_of_request.set(query)
        return await original_retrieve(query, *args, **kwargs)

    def capture_search(*args, **kwargs):
        expressions = args[3] if len(args) > 3 else kwargs.get("matchExprs", [])
        result = original_search(*args, **kwargs)
        es_requests.append(
            {
                "route_query": route_of_request.get(),
                "is_original_question": route_of_request.get() == question,
                "expression_types": [type(expr).__name__ for expr in (expressions or [])],
                "limit": args[6] if len(args) > 6 else None,
                "candidate_ids": [str(i) for i in dealer.dataStore.get_doc_ids(result)],
                "total_reported": dealer.dataStore.get_total(result),
            }
        )
        return result

    def capture_encode(text):
        try:
            value = original_encode(text)
            provider_calls.append({"outcome": "ok"})
            return value
        except BaseException as exc:  # noqa: BLE001 - observed, then re-raised unchanged
            provider_calls.append({"outcome": "failed", **sanitized_provider_outcome(exc)})
            raise

    dealer.dataStore.search = capture_search
    dealer.retrieval = capture_retrieval
    if original_encode is not None:
        embd_mdl.encode_queries = capture_encode

    operator_lines.clear()
    hb.begin_retrieval_health()
    error = None
    kbinfos = {}
    try:
        kbinfos = await retrieve_multi_route(
            retriever=dealer,
            question=question,
            chat_mdl=chat_mdl,
            embd_mdl=embd_mdl,
            rerank_mdl=rerank_mdl,
            tenant_ids=[TENANT],
            kb_ids=[KB],
            similarity_threshold=params["similarity_threshold"],
            vector_similarity_weight=params["vector_similarity_weight"],
            final_top_n=params["top_n"],
            knn_top_k=params["top_k"],
            rerank_candidates_count=None,
            doc_ids=None,
            rank_feature=None,
        )
    except BaseException as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    finally:
        dealer.dataStore.search = original_search
        dealer.retrieval = original_retrieve
        if original_encode is not None:
            embd_mdl.encode_queries = original_encode

    session = hb.current_session()
    legs = {name: leg.status.value for name, leg in (session.legs or {}).items()} if session else {}
    dto = hb.attach_retrieval_health({"chunks": kbinfos.get("chunks") or []})["retrieval_health"]
    chunks = kbinfos.get("chunks") or []
    events = []
    for line in operator_lines:
        try:
            events.append(json.loads(line[len(OPERATOR_MARKER):].strip()))
        except Exception:  # noqa: BLE001
            events.append({"_parse_error": True})

    first_pass = [request for request in es_requests if request["is_original_question"]]
    primary = first_pass[0] if first_pass else None
    window_ids = primary["candidate_ids"] if primary else []
    everything = [chunk_id for request in es_requests for chunk_id in request["candidate_ids"]]

    return {
        "question": question,
        "error": error,
        "provider_calls": provider_calls,
        "es_requests": es_requests,
        "route_count": len(es_requests),
        "original_question_requests": len(first_pass),
        "dense_executed_request": any(any(t in ("MatchDenseExpr", "FusionExpr") for t in request["expression_types"]) for request in es_requests),
        "lexical_executed_request": any("MatchTextExpr" in request["expression_types"] for request in es_requests),
        "window_limit": primary["limit"] if primary else None,
        "candidate_window_size": len(window_ids),
        "candidate_window_head": window_ids[:8],
        "candidates_are_real_es_ids": all(isinstance(i, str) and len(i) == 16 for i in window_ids[:5]) if window_ids else False,
        "target_in_any_route_window": {"three": THREE in everything, "single": SINGLE in everything},
        "returned_count": len(chunks),
        "returned_ids": [str(chunk.get("chunk_id")) for chunk in chunks],
        "modes": sorted({(chunk.get("score_provenance") or {}).get("mode") for chunk in chunks}),
        "dense_absent_on_every_chunk": all(chunk.get("vector_similarity") is None and chunk.get("vector") is None and (chunk.get("score_provenance") or {}).get("dense_score") is None for chunk in chunks) if chunks else None,
        "health_dto": dto,
        "legs": legs,
        "leg_reasons": {name: (leg.reason.value if getattr(leg, "reason", None) is not None else None) for name, leg in (session.legs or {}).items()} if session else {},
        "operator_events": events,
        "operator_event_count": len(events),
        "window_ranks": {
            "three": (window_ids.index(THREE) + 1) if THREE in window_ids else None,
            "single": (window_ids.index(SINGLE) + 1) if SINGLE in window_ids else None,
            "three_selected": THREE in [str(chunk.get("chunk_id")) for chunk in chunks],
            "single_selected": SINGLE in [str(chunk.get("chunk_id")) for chunk in chunks],
        },
    }


async def main():
    capture = OperatorCapture()
    logging.getLogger("rag.retrieval.health_producers").addHandler(capture)
    logging.getLogger("rag.retrieval.health_producers").setLevel(logging.INFO)

    params = assistant_parameters()
    if params is None:
        print(json.dumps({"error": "no assistant bound to the target knowledge base"}), file=sys.stderr)
        return 1

    owner = TENANT
    ok, kb = KnowledgebaseService.get_by_id(KB)
    embd_mdl = LLMBundle(owner, resolve_model_config(owner, LLMType.EMBEDDING, kb.embd_id))
    chat_mdl = None
    try:
        config = get_tenant_default_model_by_type(owner, LLMType.CHAT)
        if isinstance(config, dict) and config:
            chat_mdl = LLMBundle(owner, config)
    except Exception:  # noqa: BLE001
        chat_mdl = None
    rerank_mdl = None
    if params.get("rerank_id"):
        try:
            rerank_mdl = LLMBundle(owner, resolve_model_config(owner, LLMType.RERANK, params["rerank_id"]))
        except Exception:  # noqa: BLE001
            rerank_mdl = None

    dealer = rag_search.Dealer(settings.docStoreConn)

    report = {
        "purpose": "live incident acceptance on production retrieval",
        "image": os.environ.get("P12_IMAGE", "unknown"),
        "assistant_parameters": params,
        "chat_model_present": chat_mdl is not None,
        "rerank_model_present": rerank_mdl is not None,
        "kb": {"id": KB, "name": getattr(kb, "name", None), "embd_id": kb.embd_id},
        "questions": [],
    }
    for question in (INCIDENT, CONTROL, STRUCTURE):
        report["questions"].append(await run_question(dealer, chat_mdl, embd_mdl, rerank_mdl, question, params))

    answer = next((q for q in report["questions"] if q["question"] == INCIDENT), None)
    control = next((q for q in report["questions"] if q["question"] == CONTROL), None)
    structure = next((q for q in report["questions"] if q["question"] == STRUCTURE), None)

    def event_shape_ok(event):
        return set(event.keys()) == FROZEN_OPERATOR_FIELDS

    all_text = json.dumps(report, ensure_ascii=False)
    leaks = [marker for marker in LEAK_MARKERS if marker in all_text and marker not in ("三芯海缆",)]

    report["chain_checks"] = {
        "dense_attempted_and_failed": bool(answer["provider_calls"]) and all(call["outcome"] == "failed" for call in answer["provider_calls"]),
        "dense_failure_is_the_location_restriction": all(call.get("is_location_restriction") for call in answer["provider_calls"] if call["outcome"] == "failed"),
        "dense_failure_classified_recoverable": all(call.get("classified_recoverable") for call in answer["provider_calls"] if call["outcome"] == "failed"),
        "lexical_es_request_executed": answer["lexical_executed_request"],
        "no_dense_expression_was_sent": not answer["dense_executed_request"],
        "candidates_came_from_the_store": answer["candidates_are_real_es_ids"],
        "dense_absent_on_every_chunk": answer["dense_absent_on_every_chunk"],
        "degraded_mode_marked": answer["modes"] == ["LEXICAL_DEGRADED"],
        "health_dto_overall_degraded": answer["health_dto"]["overall"] == "degraded",
        "health_dto_reason_present": bool(answer["health_dto"]["degradation_reason"]),
        "dense_leg_failed": answer["legs"].get("dense") == "failed",
        "lexical_leg_success": answer["legs"].get("lexical") == "success",
        "operator_event_exactly_once": answer["operator_event_count"] == 1,
        "operator_event_exact_field_set": bool(answer["operator_events"]) and event_shape_ok(answer["operator_events"][0]),
        "operator_event_matches_the_dto": bool(answer["operator_events"]) and answer["operator_events"][0].get("overall") == answer["health_dto"]["overall"],
        "no_secret_or_provider_body_leak": not leaks,
        "no_unexpected_error": answer["error"] is None,
    }
    report["qgdw_live"] = {
        "candidate_window_limit": answer["window_limit"],
        "three_core_rank_in_original_question_window": answer["window_ranks"]["three"],
        "three_core_in_original_window": bool(answer["window_ranks"]["three"] and answer["window_ranks"]["three"] <= (answer["window_limit"] or 0)),
        "three_core_in_some_route_window": answer["target_in_any_route_window"]["three"],
        "three_core_survived_degraded_selection": answer["window_ranks"]["three_selected"],
        "single_core_main_rank": answer["window_ranks"]["single"],
        "single_core_main_outside_window": bool(answer["window_ranks"]["single"] and answer["window_ranks"]["single"] > (answer["window_limit"] or 0)),
        "single_core_main_in_some_route_window": answer["target_in_any_route_window"]["single"],
        "single_core_control_rank": control["window_ranks"]["single"],
        "single_core_control_window_limit": control["window_limit"],
        "single_core_control_inside_window": bool(control["window_ranks"]["single"] and control["window_ranks"]["single"] <= (control["window_limit"] or 0)),
        "single_core_control_survived": control["window_ranks"]["single_selected"],
        "structure_target_rank": structure["window_ranks"]["three"],
        "structure_target_inside_window": bool(structure["window_ranks"]["three"] and structure["window_ranks"]["three"] <= (structure["window_limit"] or 0)),
        "structure_target_survived": structure["window_ranks"]["three_selected"],
        "route_counts": {"incident": answer["route_count"], "control": control["route_count"], "structure": structure["route_count"]},
    }
    report["leak_markers_found"] = leaks
    report["passed"] = all(report["chain_checks"].values())

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("LIVE_ACCEPTANCE_BEGIN")
    print(json.dumps({k: report[k] for k in ("chain_checks", "qgdw_live", "leak_markers_found", "passed")}, ensure_ascii=False, indent=1))
    print("LIVE_ACCEPTANCE_END")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
