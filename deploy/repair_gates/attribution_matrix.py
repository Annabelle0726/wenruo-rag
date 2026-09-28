"""READ-ONLY attribution matrix. Stage two: rule-level causes, not final ranks.

Nothing under rag/ is modified and no parameter is changed: every number comes from wrapping the
existing boundaries and from reading the policy's own constants. The probe dumps the full evidence
for N queries in one run so all the arithmetic (adjustment deltas, overtakers, pure-score
counterfactuals, table-vs-prose inversions) is done offline over recorded data rather than by
re-running retrieval with different settings.

Captured per query:

  routes        the route queries, each one's ES window size and its returned page
  es_ranks      every pool member's rank inside each route's raw ES window
  page_ranks    every pool member's rank inside the route page that admitted it
  pool          the merged pool BEFORE the ordering pass: id, similarity, type, hollow-ness,
                core/auxiliary document, value pairing, document, routes, content head
  ordered       the pool AFTER apply_rank_adjustments, with the rank_score it wrote
  policy        every policy field the ordering and the cut read
  chosen        what select_context kept
"""
import asyncio
import contextvars
import json
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
from rag.retrieval.chunk_profile import carries_value, document_key, document_name, is_prose_chunk, is_table_chunk, paired_values

KB = "9463d93eb97511f1938f2592e9bc6fe4"
DIALOG_ID = "29a6da60ba1f11f1be9555eabe501d5b"
OUT = pathlib.Path(os.environ.get("P12_ATTR_OUT", "/tmp/attribution_matrix.json"))

#: The incident question plus four queries whose answer fact lives mainly in a TABLE chunk. The
#: controls are deliberately Q/GDW table lookups, so "table evidence is not represented" can be
#: separated from "this particular composite question".
QUERIES = [
    {"id": "INCIDENT_COMPOSITE", "kind": "composite", "text": "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"},
    {"id": "TABLE_SINGLE_PART2", "kind": "table_fact", "text": "根据 Q/GDW 73286.2-2026 表 1，单芯电缆的导体标称截面有哪些规格？"},
    {"id": "TABLE_THREE_PART3", "kind": "table_fact", "text": "根据 Q/GDW 73286.3-2026 表 1，三芯电缆的导体标称截面有哪些规格？"},
    {"id": "TABLE_STRUCTURE", "kind": "table_fact", "text": "220kV 三芯海缆的主要结构有哪些？"},
    {"id": "TABLE_VALUE_LOOKUP", "kind": "table_fact", "text": "Q/GDW 73286.2-2026 表 1 中 800 mm² 单芯电缆的导体标称截面规格数量是多少？"},
]

route_context = contextvars.ContextVar("p12_attr_route", default=None)
CURRENT = {}


def patch(module, name, replacement):
    original = getattr(module, name)
    setattr(module, name, replacement)
    for other in (pipeline_module, multi_route_module, rerank_module, rag_search):
        if getattr(other, name, None) is original:
            setattr(other, name, replacement)
    return original


def ids_of(chunks):
    return [str(chunk.get("chunk_id") or "")[:16] for chunk in chunks or []]


def rank_of(ids, chunk_id):
    return (ids.index(chunk_id) + 1) if chunk_id in ids else None


def short(text, limit=70):
    return " ".join(str(text or "").split())[:limit]


def describe(chunk, policy):
    values = tuple(sorted(policy.question_values))
    pairs = bool(values) and paired_values(chunk, values)
    carries = bool(values) and carries_value(chunk, values)
    is_table = is_table_chunk(chunk)
    is_hollow = is_table and rerank_module.is_hollow_table(chunk)
    penalty = policy.table_penalty if is_table else 1.0
    if is_hollow:
        penalty *= rerank_module.HOLLOW_TABLE_PENALTY
    boost = policy.core_document_boost if policy.is_core_document(chunk) else 1.0
    if values:
        if pairs:
            boost *= rerank_module.VALUE_PAIRING_BOOST
        elif is_table and carries:
            penalty *= rerank_module.VALUE_LIST_PENALTY
    return {
        "chunk_id": str(chunk.get("chunk_id"))[:16],
        "similarity": chunk.get("similarity"),
        "is_table": is_table,
        "is_prose": is_prose_chunk(chunk),
        "is_hollow_table": is_hollow,
        "document_key": document_key(chunk),
        "document": short(document_name(chunk), 50),
        "is_core_document": policy.is_core_document(chunk),
        "is_compared_document": policy.is_compared_document(chunk),
        "paired_value_with_result": pairs,
        "carries_question_value": carries,
        "table_penalty_applied": penalty,
        "boost_applied": boost,
        "predicted_rank_score": (chunk.get("similarity") or 0.0) * penalty * boost,
        "routes": rerank_module.routes_of(chunk),
        "content_head": short(chunk.get("content_with_weight"), 120),
    }


async def main():
    dialog_row = Dialog.get_or_none(Dialog.id == DIALOG_ID)
    owner = getattr(dialog_row, "tenant_id", None) or "a9e28731ab7011f19b833887d563fb04"
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

    # S1 raw ES windows
    original_search = dealer.dataStore.search

    def search_wrapper(*args, **kwargs):
        expressions = args[3] if len(args) > 3 else kwargs.get("matchExprs", [])
        result = original_search(*args, **kwargs)
        window = [str(i) for i in dealer.dataStore.get_doc_ids(result)]
        CURRENT.setdefault("es_windows", []).append(
            {"route": short(route_context.get()), "limit": args[6] if len(args) > 6 else None, "size": len(window), "ids": window, "expressions": [type(e).__name__ for e in (expressions or [])]}
        )
        return result

    dealer.dataStore.search = search_wrapper

    # S3 route pages
    original_retrieval = dealer.retrieval

    async def retrieval_wrapper(question, *args, **kwargs):
        route_context.set(question)
        ranks = await original_retrieval(question, *args, **kwargs)
        page = [str(chunk.get("chunk_id"))[:16] for chunk in (ranks.get("chunks") or [])]
        scores = {str(chunk.get("chunk_id"))[:16]: chunk.get("similarity") for chunk in (ranks.get("chunks") or [])}
        CURRENT.setdefault("pages", []).append({"route": short(question), "page_size": args[4] if len(args) > 4 else None, "ids": page, "scores": scores})
        return ranks

    dealer.retrieval = retrieval_wrapper

    # S6 ordering: snapshot BEFORE the original mutates rank_score
    original_adjust = rerank_module.apply_rank_adjustments

    def adjust_wrapper(chunks, policy):
        CURRENT["policy"] = {
            "min_prose": policy.min_prose,
            "max_table_share": policy.max_table_share,
            "table_penalty": policy.table_penalty,
            "max_auxiliary_document_share": policy.max_auxiliary_document_share,
            "core_document_boost": policy.core_document_boost,
            "core_documents": sorted(policy.core_documents),
            "max_document_share": policy.max_document_share,
            "compared_documents": sorted(policy.compared_documents),
            "question_values": sorted(policy.question_values),
        }
        before = [describe(chunk, policy) for chunk in chunks]
        before_order = [row["chunk_id"] for row in before]
        out = original_adjust(chunks, policy)
        after = []
        for position, chunk in enumerate(out, 1):
            cid = str(chunk.get("chunk_id"))[:16]
            row = next((item for item in before if item["chunk_id"] == cid), {})
            after.append({"position": position, "chunk_id": cid, "similarity": chunk.get("similarity"), "rank_score": chunk.get("rank_score"), "is_table": row.get("is_table"), "document": row.get("document")})
        CURRENT["pool_before"] = before
        CURRENT["before_order"] = before_order
        CURRENT["pool_after"] = after
        return out

    patch(rerank_module, "apply_rank_adjustments", adjust_wrapper)

    # S7 the cut
    original_select = rerank_module.select_context

    def select_wrapper(ordered, top_n, policy=None):
        policy_obj = policy if policy is not None else rerank_module.DiversityPolicy()
        chosen = original_select(ordered, top_n, policy_obj)
        CURRENT["cut"] = {
            "top_n": top_n,
            "ordered_size": len(ordered),
            "ordered_ids": ids_of(ordered),
            "chosen_ids": ids_of(chosen),
            "chosen_profile": [
                {
                    "chunk_id": str(chunk.get("chunk_id"))[:16],
                    "is_table": is_table_chunk(chunk),
                    "similarity": chunk.get("similarity"),
                    "rank_score": chunk.get("rank_score"),
                    "ordered_position": rank_of(ids_of(ordered), str(chunk.get("chunk_id"))[:16]),
                    "routes": rerank_module.routes_of(chunk),
                    "document": short(document_name(chunk), 46),
                }
                for chunk in chosen
            ],
        }
        return chosen

    patch(rerank_module, "select_context", select_wrapper)

    report = {"parameters_used": params, "helper_constants": {"MIN_PROSE_PASSAGES": rerank_module.MIN_PROSE_PASSAGES, "MAX_TABLE_SHARE": rerank_module.MAX_TABLE_SHARE, "TABLE_PENALTY": rerank_module.TABLE_PENALTY, "HOLLOW_TABLE_PENALTY": rerank_module.HOLLOW_TABLE_PENALTY, "MAX_AUXILIARY_DOCUMENT_SHARE": rerank_module.MAX_AUXILIARY_DOCUMENT_SHARE, "CORE_DOCUMENT_BOOST": rerank_module.CORE_DOCUMENT_BOOST, "VALUE_PAIRING_BOOST": rerank_module.VALUE_PAIRING_BOOST, "VALUE_LIST_PENALTY": rerank_module.VALUE_LIST_PENALTY, "MAX_COMPARED_DOCUMENT_SHARE": rerank_module.MAX_COMPARED_DOCUMENT_SHARE, "MAX_HOLLOW_TABLE_PER_DOCUMENT_SHARE": rerank_module.MAX_HOLLOW_TABLE_PER_DOCUMENT_SHARE}, "queries": []}

    for query in QUERIES:
        CURRENT.clear()
        result = await pipeline_module.retrieve_multi_route(
            retriever=dealer,
            question=query["text"],
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
        entry = {"id": query["id"], "kind": query["kind"], "question": query["text"], "final_ids": ids_of(result.get("chunks")), "routes": [row["route"] for row in CURRENT.get("es_windows", [])], "es_windows": CURRENT.get("es_windows", []), "pages": CURRENT.get("pages", []), "policy": CURRENT.get("policy"), "pool_before": CURRENT.get("pool_before", []), "before_order": CURRENT.get("before_order", []), "pool_after": CURRENT.get("pool_after", []), "cut": CURRENT.get("cut")}
        report["queries"].append(entry)
        print("captured", query["id"], "pool", len(entry["pool_before"]), "chosen", len((entry["cut"] or {}).get("chosen_ids", [])), "tables_in_pool", sum(1 for row in entry["pool_before"] if row["is_table"]), file=sys.stderr)

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("ATTR_MATRIX_BEGIN")
    print(json.dumps({"queries": [{"id": entry["id"], "routes": len(entry["routes"]), "pool": len(entry["pool_before"]), "tables_in_pool": sum(1 for row in entry["pool_before"] if row["is_table"]), "chosen": len((entry["cut"] or {}).get("chosen_ids", [])), "tables_chosen": sum(1 for row in (entry["cut"] or {}).get("chosen_profile", []) if row["is_table"])} for entry in report["queries"]]}, ensure_ascii=False, indent=1))
    print("ATTR_MATRIX_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
