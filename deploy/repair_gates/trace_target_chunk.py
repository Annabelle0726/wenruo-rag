"""TRACING ONLY. Post-retrieval attribution for one chunk: where exactly does it die?

No retrieval or reranking logic is modified. Every fact below is produced by wrapping an existing
boundary and observing what it was given and what it returned; nothing is injected into the pipeline,
no threshold, window, top-k or reranker parameter is touched, and the trace runs with the production
assistant's own configuration.

Stages instrumented, in the order the pipeline runs them:

  S1 dataStore.search        the raw ES window per route (order = ES rank)
  S2 Dealer.search           the SearchResult: ids, retrieval_mode, query vector presence
  S3 Dealer.retrieval        the route's RETURNED page: ids + per-chunk lexical score + total
  S4 _retrieve_route         the RouteResult a route contributes (page cut already applied)
  S5 merge_route_hits        the merged, de-duplicated pool
  S6 rerank_chunks           the ordered pool handed to the cut (reranker score if any)
  S7 select_context          the final window: what was chosen, and the quota state at the time

The target and the control chunk are tracked side by side, and the FIRST stage at which the target is
absent from the pool is the answer.
"""
import asyncio
import contextvars
import dataclasses
import copy
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
from rag.retrieval import rerank as rerank_module
from rag.retrieval import multi_route as multi_route_module
from rag.retrieval import pipeline as pipeline_module
from rag.retrieval.chunk_profile import document_key, document_name, is_prose_chunk, is_table_chunk, standard_designations

TARGET = "d1d75672f2dbc333"
CONTROL = "b5aaf72bcd33d44a"
KB = "9463d93eb97511f1938f2592e9bc6fb04"  # placeholder, replaced below
KB = "9463d93eb97511f1938f2592e9bc6fe4"
TENANT = "a9e28731ab7011f19b833887d563fb04"
DIALOG_ID = "29a6da60ba1f11f1be9555eabe501d5b"
INCIDENT = "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"
OUT = pathlib.Path(os.environ.get("P12_TRACE_OUT", "/tmp/target_chunk_trace.json"))

route_context = contextvars.ContextVar("p12_trace_route", default=None)
TRACE = {"es_windows": [], "search_results": [], "route_pages": [], "route_results": [], "merges": [], "rerank": [], "selection": []}


def patch(module, name, replacement):
    """Replace `module.name` and every module that imported it by value, so a wrapper is seen
    everywhere the pipeline actually resolves it."""
    original = getattr(module, name)
    setattr(module, name, replacement)
    for other in (pipeline_module, multi_route_module, rerank_module, rag_search):
        if getattr(other, name, None) is original:
            setattr(other, name, replacement)
    return original


def ids_of(chunks):
    return [str(chunk.get("chunk_id") or chunk.get("id") or "")[:16] for chunk in chunks or []]


def rank_of(ids, chunk_id):
    return (ids.index(chunk_id) + 1) if chunk_id in ids else None


def short(text, limit=90):
    return " ".join(str(text or "").split())[:limit]


def quota_snapshot(policy, pool, chosen_keys, top_n):
    """Mirror of select_context's quota arithmetic, computed for DIAGNOSIS only.

    It reads the same public policy numbers and the same pool; it never decides anything the
    pipeline uses. Its purpose is to name which cap blocked a passage instead of leaving the
    transcript with "it was not selected".
    """
    import math

    table_cap = top_n if policy.max_table_share >= 1.0 else min(top_n, math.ceil(top_n * policy.max_table_share))
    document_cap = 0 if policy.max_auxiliary_document_share >= 1.0 else max(1, min(top_n, math.ceil(top_n * policy.max_auxiliary_document_share)))
    every_document_cap = 0 if policy.max_document_share >= 1.0 else max(1, min(top_n, math.ceil(top_n * policy.max_document_share)))
    chosen_chunks = [chunk for chunk in pool if str(chunk.get("chunk_id"))[:16] in chosen_keys]
    per_document = {}
    for chunk in chosen_chunks:
        key = document_key(chunk) or ("chunk:" + str(chunk.get("chunk_id"))[:16])
        per_document[key] = per_document.get(key, 0) + 1
    return {
        "top_n": top_n,
        "table_cap": table_cap,
        "table_cap_share": policy.max_table_share,
        "document_cap": document_cap,
        "auxiliary_share": policy.max_auxiliary_document_share,
        "every_document_cap": every_document_cap,
        "compared_share": policy.max_document_share,
        "min_prose": policy.min_prose,
        "pool_size": len(pool),
        "chosen_size": len(chosen_chunks),
        "chosen_tables": sum(1 for chunk in chosen_chunks if is_table_chunk(chunk)),
        "chosen_per_document": per_document,
        "pool_tables": sum(1 for chunk in pool if is_table_chunk(chunk)),
        "pool_per_document": {},
    }


async def main():
    dialog_row = Dialog.get_or_none(Dialog.id == DIALOG_ID)
    owner = getattr(dialog_row, "tenant_id", TENANT) or TENANT
    ok, kb = KnowledgebaseService.get_by_id(KB)
    params = {
        "similarity_threshold": dialog_row.similarity_threshold,
        "vector_similarity_weight": dialog_row.vector_similarity_weight,
        "final_top_n": dialog_row.top_n,
        "knn_top_k": dialog_row.top_k,
    }

    embd_mdl = LLMBundle(owner, resolve_model_config(owner, LLMType.EMBEDDING, kb.embd_id))
    try:
        config = get_tenant_default_model_by_type(owner, LLMType.CHAT)
        chat_mdl = LLMBundle(owner, config) if isinstance(config, dict) and config else None
    except Exception:  # noqa: BLE001
        chat_mdl = None
    dealer = rag_search.Dealer(settings.docStoreConn)

    # ---- S1: the raw ES window per route -------------------------------------------------------
    original_search = dealer.dataStore.search

    def search_wrapper(*args, **kwargs):
        expressions = args[3] if len(args) > 3 else kwargs.get("matchExprs", [])
        result = original_search(*args, **kwargs)
        window = [str(i) for i in dealer.dataStore.get_doc_ids(result)]
        TRACE["es_windows"].append(
            {
                "route_query": route_context.get(),
                "limit": args[6] if len(args) > 6 else None,
                "expression_types": [type(e).__name__ for e in (expressions or [])],
                "window_size": len(window),
                "target_rank": rank_of(window, TARGET),
                "control_rank": rank_of(window, CONTROL),
                "window_head": window[:6],
            }
        )
        return result

    dealer.dataStore.search = search_wrapper

    # ---- S2/S3: the SearchResult and the route's returned page ---------------------------------
    original_retrieval = dealer.retrieval

    async def retrieval_wrapper(question, *args, **kwargs):
        route_context.set(question)
        page_size = args[4] if len(args) > 4 else kwargs.get("page_size")
        ranks = await original_retrieval(question, *args, **kwargs)
        returned = [str(chunk.get("chunk_id"))[:16] for chunk in (ranks.get("chunks") or [])]
        scores = {}
        for chunk in ranks.get("chunks") or []:
            cid = str(chunk.get("chunk_id"))[:16]
            provenance = chunk.get("score_provenance") or {}
            scores[cid] = {
                "similarity": chunk.get("similarity"),
                "term_similarity": chunk.get("term_similarity"),
                "lexical_selection_score": provenance.get("lexical_selection_score"),
                "score_kind": provenance.get("score_kind"),
                "mode": provenance.get("mode"),
                "is_table": is_table_chunk(chunk),
                "is_prose": is_prose_chunk(chunk),
                "document": short(document_name(chunk), 60),
                "document_key": document_key(chunk),
            }
        TRACE["route_pages"].append(
            {
                "route_query": short(question),
                "page_size": page_size,
                "returned_size": len(returned),
                "returned_total_reported": ranks.get("total"),
                "target_in_page": TARGET in returned,
                "target_page_rank": rank_of(returned, TARGET),
                "control_in_page": CONTROL in returned,
                "control_page_rank": rank_of(returned, CONTROL),
                "returned_head": returned[:6],
                "all_scores": scores,
            }
        )
        return ranks

    dealer.retrieval = retrieval_wrapper

    # ---- S4: what each route contributes --------------------------------------------------------
    original_retrieve_route = multi_route_module._retrieve_route

    async def route_wrapper(*args, **kwargs):
        result = await original_retrieve_route(*args, **kwargs)
        contributed = ids_of(result.chunks)
        TRACE["route_results"].append(
            {
                "query": short(result.query),
                "chunk_count": len(contributed),
                "target_present": TARGET in contributed,
                "control_present": CONTROL in contributed,
                "retrieval_mode": getattr(result, "retrieval_mode", None),
                "failed": result.failed,
            }
        )
        return result

    patch(multi_route_module, "_retrieve_route", route_wrapper)

    # ---- S5: the merge ---------------------------------------------------------------------------
    original_merge = multi_route_module.merge_route_hits

    def merge_wrapper(hits, existing=None):
        merged = original_merge(hits, existing)
        pool = ids_of(merged.get("chunks"))
        TRACE["merges"].append(
            {
                "routes_in": [short(hit.query) for hit in hits],
                "existing_present": bool(existing),
                "pool_size": len(pool),
                "target_present": TARGET in pool,
                "target_pool_rank": rank_of(pool, TARGET),
                "control_present": CONTROL in pool,
                "retrieval_mode": merged.get("retrieval_mode"),
                "selection_trace_policy": (merged.get("selection_trace") or {}).get("policy"),
            }
        )
        return merged

    patch(multi_route_module, "merge_route_hits", merge_wrapper)

    # ---- S6: ordering / reranking ----------------------------------------------------------------
    original_rerank = rerank_module.rerank_chunks

    async def rerank_wrapper(rerank_mdl, chunks, question, top_n=None):
        pool = ids_of(chunks)
        result = await original_rerank(rerank_mdl, chunks, question, top_n)
        TRACE["rerank"].append(
            {
                "rerank_model": None if rerank_mdl is None else type(rerank_mdl).__name__,
                "top_n_argument": top_n,
                "pool_in_size": len(pool),
                "target_in_pool": TARGET in pool,
                "target_pool_rank": rank_of(pool, TARGET),
                "control_in_pool": CONTROL in pool,
                "control_pool_rank": rank_of(pool, CONTROL),
                "out_size": len(ids_of(result)),
                "target_out": TARGET in ids_of(result),
            }
        )
        return result

    patch(rerank_module, "rerank_chunks", rerank_wrapper)

    # ---- S7: the cut -----------------------------------------------------------------------------
    original_select = rerank_module.select_context
    original_by_fused = rerank_module._by_fused_score
    original_adjust = rerank_module.apply_rank_adjustments

    def adjust_wrapper(chunks, policy):
        before = ids_of(chunks)
        after = original_adjust(chunks, policy)
        TRACE.setdefault("rank_adjustments", []).append(
            {
                "in_size": len(before),
                "out_size": len(ids_of(after)),
                "target_rank_in": rank_of(before, TARGET),
                "target_rank_out": rank_of(ids_of(after), TARGET),
                "control_rank_in": rank_of(before, CONTROL),
                "control_rank_out": rank_of(ids_of(after), CONTROL),
                "top5_out": ids_of(after)[:5],
            }
        )
        return after

    patch(rerank_module, "apply_rank_adjustments", adjust_wrapper)

    def pool_profile(ordered, chosen_ids):
        """Every candidate in the order the cut walks it, with the type that decides its pass."""
        profile = []
        for position, chunk in enumerate(ordered, 1):
            cid = str(chunk.get("chunk_id"))[:16]
            profile.append(
                {
                    "position": position,
                    "chunk_id": cid,
                    "is_table": is_table_chunk(chunk),
                    "is_prose": is_prose_chunk(chunk),
                    "similarity": chunk.get("similarity"),
                    "document": short(document_name(chunk), 46),
                    "document_key": document_key(chunk),
                    "chosen": cid in chosen_ids,
                }
            )
        return profile

    def select_wrapper(ordered, top_n, policy=None):
        pool = ids_of(ordered)
        policy_obj = policy if policy is not None else rerank_module.DiversityPolicy()
        chosen = original_select(ordered, top_n, policy_obj)
        chosen_ids = ids_of(chosen)
        chosen_keys = set(chosen_ids)
        target_chunk = next((chunk for chunk in ordered if str(chunk.get("chunk_id"))[:16] == TARGET), None)
        snapshot = quota_snapshot(policy_obj, ordered, chosen_keys, top_n)
        snapshot["pool_per_document"] = {}
        for chunk in ordered:
            key = document_key(chunk) or ("chunk:" + str(chunk.get("chunk_id"))[:16])
            snapshot["pool_per_document"][key] = snapshot["pool_per_document"].get(key, 0) + 1
        profile = pool_profile(ordered, chosen_keys)
        chosen_profile = [row for row in profile if row["chosen"]]
        first_table_position = next((row["position"] for row in profile if row["is_table"]), None)
        last_chosen_position = max((row["position"] for row in chosen_profile), default=None)

        # Where the target would sit under a PURE score ordering, and what the 12th slot cost. This is
        # arithmetic over the traced pool, not a change to anything the pipeline uses.
        by_score = sorted(profile, key=lambda row: -(row["similarity"] or 0.0))
        pure_score_rank = next((index for index, row in enumerate(by_score, 1) if row["chunk_id"] == TARGET), None)
        twelfth_score = by_score[11]["similarity"] if len(by_score) >= 12 else None

        # COUNTERFACTUAL, diagnostic only and never consumed by the pipeline: the same cut with the
        # table quota lifted, which makes table_cap == top_n and therefore takes the plain top-N
        # branch instead of deferring every table behind every prose passage. Its only purpose is to
        # say whether the table deferral is what cost the target its slot.
        try:
            loose = dataclasses.replace(policy_obj, max_table_share=1.0)
            cf_chosen = ids_of(original_select(ordered, top_n, loose))
            counterfactual = {
                "policy": "max_table_share=1.0 (table deferral disabled)",
                "chosen_size": len(cf_chosen),
                "target_chosen": TARGET in cf_chosen,
                "target_rank_in_window": rank_of(cf_chosen, TARGET),
                "control_chosen": CONTROL in cf_chosen,
            }
        except Exception as exc:  # noqa: BLE001
            counterfactual = {"error": "%s: %s" % (type(exc).__name__, exc)}

        TRACE["selection"].append(
            {
                "ordered_size": len(ordered),
                "top_n": top_n,
                "chosen_size": len(chosen_ids),
                "target_in_pool": TARGET in pool,
                "target_pool_rank": rank_of(pool, TARGET),
                "target_chosen": TARGET in chosen_ids,
                "target_chosen_rank": rank_of(chosen_ids, TARGET),
                "control_in_pool": CONTROL in pool,
                "control_pool_rank": rank_of(pool, CONTROL),
                "control_chosen": CONTROL in chosen_ids,
                "window_filled_by": {
                    "chosen_tables": sum(1 for row in chosen_profile if row["is_table"]),
                    "chosen_prose": sum(1 for row in chosen_profile if row["is_prose"]),
                    "pool_tables": sum(1 for row in profile if row["is_table"]),
                    "pool_prose": sum(1 for row in profile if row["is_prose"]),
                    "last_chosen_position": last_chosen_position,
                    "first_table_position_in_pool": first_table_position,
                    "first_chosen_table_position": next((row["position"] for row in chosen_profile if row["is_table"]), None),
                },
                "score_margin": {
                    "target_similarity": None if target_chunk is None else target_chunk.get("similarity"),
                    "weakest_chosen_similarity": min((row["similarity"] for row in chosen_profile), default=None),
                    "strongest_not_chosen_similarity": max((row["similarity"] for row in profile if not row["chosen"]), default=None),
                    "weakest_chosen_position": max((row["position"] for row in chosen_profile), default=None),
                    "target_rank_under_pure_score_ordering": pure_score_rank,
                    "twelfth_score_under_pure_score_ordering": twelfth_score,
                    "target_would_be_cut_by_pure_score_too": bool(
                        pure_score_rank and twelfth_score is not None and (target_chunk is None or (target_chunk.get("similarity") or 0.0) < twelfth_score)
                    ),
                },
                "counterfactual_table_deferral_disabled": counterfactual,
                "policy": {
                    "max_table_share": policy_obj.max_table_share,
                    "max_auxiliary_document_share": policy_obj.max_auxiliary_document_share,
                    "max_document_share": policy_obj.max_document_share,
                    "min_prose": policy_obj.min_prose,
                    "compared_documents": sorted(policy_obj.compared_documents),
                    "core_documents": sorted(policy_obj.core_documents)[:6],
                },
                "quotas": snapshot,
                "ordered_profile": profile,
                "target_profile": None
                if target_chunk is None
                else {
                    "is_table": is_table_chunk(target_chunk),
                    "is_prose": is_prose_chunk(target_chunk),
                    "is_hollow_table": rerank_module.is_hollow_table(target_chunk),
                    "document": short(document_name(target_chunk), 90),
                    "document_key": document_key(target_chunk),
                    "is_core_document": policy_obj.is_core_document(target_chunk),
                    "is_compared_document": policy_obj.is_compared_document(target_chunk),
                    "designations": sorted(standard_designations(document_name(target_chunk))),
                    "similarity": target_chunk.get("similarity"),
                    "routes": rerank_module.routes_of(target_chunk),
                    "content_head": short(target_chunk.get("content_with_weight"), 160),
                },
            }
        )
        return chosen

    patch(rerank_module, "select_context", select_wrapper)

    # ---- run one live retrieval ------------------------------------------------------------------
    result = await pipeline_module.retrieve_multi_route(
        retriever=dealer,
        question=INCIDENT,
        chat_mdl=chat_mdl,
        embd_mdl=embd_mdl,
        rerank_mdl=None,
        tenant_ids=[owner],
        kb_ids=[KB],
        similarity_threshold=params["similarity_threshold"],
        vector_similarity_weight=params["vector_similarity_weight"],
        final_top_n=params["final_top_n"],
        knn_top_k=params["knn_top_k"],
        rerank_candidates_count=None,
        doc_ids=None,
        rank_feature=None,
    )

    final_ids = ids_of(result.get("chunks"))

    # ---- verdict ---------------------------------------------------------------------------------
    stages = [
        ("S1_es_window", [row for row in TRACE["es_windows"] if row["target_rank"] is not None]),
        ("S3_route_page", [row for row in TRACE["route_pages"] if row["target_in_page"]]),
        ("S4_route_result", [row for row in TRACE["route_results"] if row["target_present"]]),
        ("S5_merged_pool", [row for row in TRACE["merges"] if row["target_present"]]),
        ("S6_ordered_pool", [row for row in TRACE["rerank"] if row["target_in_pool"]]),
        ("S7_final_window", [row for row in TRACE["selection"] if row["target_chosen"]]),
    ]
    first_lost = None
    for index in range(1, len(stages)):
        if not stages[index][1]:
            first_lost = stages[index][0]
            break
    if first_lost is None and TARGET not in final_ids:
        first_lost = "S7_cut_dropped_despite_being_in_the_pool"

    report = {
        "purpose": "post-retrieval attribution for one chunk; tracing only, no logic modified",
        "parameters_used": params,
        "target": TARGET,
        "control": CONTROL,
        "trace": TRACE,
        "stage_presence": {name: len(rows) for name, rows in stages},
        "first_stage_without_target": first_lost,
        "target_in_final_window": TARGET in final_ids,
        "control_in_final_window": CONTROL in final_ids,
        "final_window_size": len(final_ids),
        "final_ids": final_ids,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("TARGET_TRACE_BEGIN")
    print(json.dumps({k: report[k] for k in ("first_stage_without_target", "stage_presence", "target_in_final_window", "control_in_final_window", "final_window_size")}, ensure_ascii=False, indent=1))
    print("TARGET_TRACE_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

