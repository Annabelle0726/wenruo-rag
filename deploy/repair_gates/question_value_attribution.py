"""READ-ONLY question-value attribution. Stage three.

Nothing under rag/ is modified, no multiplier, threshold, window, top_n, merge or selection rule is
changed, and no filtering rule or new value class is introduced. The counterfactuals call the REAL
`apply_rank_adjustments` and `select_context` on deep copies of a real pool with a policy whose
`question_values` differ — that is a diagnostic re-evaluation, not a product change, and nothing it
computes is fed back into the pipeline.

Produces:
  1. the staged derivation of `question_values` for nine questions, with each candidate's real pool
     share and its class (standard-identity vs technical value);
  2. the consumer-effect census: which passages each question_value-driven predicate fires on;
  3. four counterfactual value-sets evaluated through the real ordering and the real cut.
"""
import asyncio
import contextvars
import copy
import dataclasses
import json
import os
import pathlib
import re
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
from rag.retrieval.chunk_profile import carries_value, document_key, document_name, is_table_chunk, paired_values, standard_designations
from rag.retrieval.decomposition import MAX_QUESTION_VALUES, MAX_VALUE_POOL_SHARE, _pool_share, _QUESTION_NUMBER_RE, question_values, strip_section_references

KB = "9463d93eb97511f1938f2592e9bc6fe4"
DIALOG_ID = "29a6da60ba1f11f1be9555eabe501d5b"
OUT = pathlib.Path(os.environ.get("P12_QV_OUT", "/tmp/question_value_attribution.json"))
TARGET = "d1d75672f2dbc333"
CONTROL = "b5aaf72bcd33d44a"

QUERIES = [
    {"id": "INCIDENT_COMPOSITE", "shape": "standard number + year, composite", "text": "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"},
    {"id": "TABLE_SINGLE_PART2", "shape": "standard number + year", "text": "根据 Q/GDW 73286.2-2026 表 1，单芯电缆的导体标称截面有哪些规格？"},
    {"id": "TABLE_THREE_PART3", "shape": "standard number + year", "text": "根据 Q/GDW 73286.3-2026 表 1，三芯电缆的导体标称截面有哪些规格？"},
    {"id": "TABLE_STRUCTURE", "shape": "no numbers", "text": "220kV 三芯海缆的主要结构有哪些？"},
    {"id": "TABLE_VALUE_LOOKUP", "shape": "standard number + year + one figure", "text": "Q/GDW 73286.2-2026 表 1 中 800 mm² 单芯电缆的导体标称截面规格数量是多少？"},
    {"id": "SHAPE_MODEL_NUMBER", "shape": "cable model number", "text": "WDZC-YJY-0.6/1kV 3×25 电缆的载流量是多少？"},
    {"id": "SHAPE_TECHNICAL_VALUE", "shape": "genuine technical parameter value", "text": "220kV 单芯海底电缆 800 mm² 截面的内衬层厚度要求是多少？"},
    {"id": "SHAPE_MULTI_VALUE", "shape": "multi-value comparison", "text": "针对 800 mm² 与 1200 mm² 的单芯与三芯电缆，内衬层厚度要求有什么区别？"},
    {"id": "SHAPE_YEAR_ONLY", "shape": "year only, no designation", "text": "2026 年版的海底电缆标准对铠装层有什么规定？"},
]

CURRENT = {}
route_context = contextvars.ContextVar("p12_qv_route", default=None)


def ids_of(chunks):
    return [str(chunk.get("chunk_id") or "")[:16] for chunk in chunks or []]


def rank_of(ids, chunk_id):
    return (ids.index(chunk_id) + 1) if chunk_id in ids else None


def classify(token, question):
    """Classify one extracted token. Diagnostic only: nothing in the pipeline calls this."""
    if re.fullmatch(r"(19|20)\d{2}", token):
        return "identity_year"
    # `standard_designations` is the deployed public API (this tracer must not depend on helpers that
    # exist only in the newer repository tree). It returns normalized keys such as "Q/GDW73286.2",
    # with the year already excluded, which is exactly the split this classification needs.
    for designation in standard_designations(question):
        if token and token in designation:
            return "identity_designation"
    return "technical_value"


def staged(question, pool):
    """Mirror `question_values`' own stages so the derivation can be read step by step."""
    stripped = strip_section_references(question)
    text = re.sub(r"\s+", " ", stripped).strip()
    matches = [m.group(0).replace("．", ".") for m in _QUESTION_NUMBER_RE.finditer(text)]
    rows = []
    seen = set()
    for token in matches:
        digits = token.replace(".", "")
        if len(digits) < 2 and "." not in token:
            rows.append({"token": token, "stage": "dropped_short"})
            continue
        if token in seen:
            rows.append({"token": token, "stage": "dropped_duplicate"})
            continue
        seen.add(token)
        share = _pool_share(token, pool) if pool else None
        rows.append(
            {
                "token": token,
                "stage": "candidate",
                "pool_share": share,
                "class": classify(token, question),
                "carries_in_pool": sum(1 for chunk in pool if carries_value(chunk, (token,))),
                "survives_share_filter": (share is None) or (share <= MAX_VALUE_POOL_SHARE),
            }
        )
    final = question_values(question, pool)
    return {"question": question, "text_after_strip": text, "regex_matches": matches, "stages": rows, "final_question_values": final, "final_classes": [classify(token, question) for token in final], "max_question_values": MAX_QUESTION_VALUES, "max_pool_share": MAX_VALUE_POOL_SHARE, "pool_size": len(pool)}


def consumer_census(pool, values):
    """Which passages each question_value-driven predicate fires on. Observation only."""
    values = tuple(sorted(values))
    paired, carried_tables, paired_tables = [], [], []
    for chunk in pool:
        cid = str(chunk.get("chunk_id"))[:16]
        if not values:
            continue
        is_paired = bool(paired_values(chunk, values))
        carries = carries_value(chunk, values)
        if is_paired:
            paired.append({"chunk_id": cid, "is_table": is_table_chunk(chunk), "similarity": chunk.get("similarity"), "document": " ".join(str(document_name(chunk)).split())[:40]})
            if is_table_chunk(chunk):
                paired_tables.append(cid)
        elif is_table_chunk(chunk) and carries:
            carried_tables.append({"chunk_id": cid, "similarity": chunk.get("similarity"), "document": " ".join(str(document_name(chunk)).split())[:40]})
    return {
        "values": list(values),
        "pairing_boost_fires_on": paired,
        "value_list_penalty_fires_on": carried_tables,
        "paired_but_table": paired_tables,
        "paired_count": len(paired),
        "penalised_count": len(carried_tables),
    }


def evaluate(pool, policy, values, top_n):
    """Evaluate one counterfactual value-set through the REAL ordering and the REAL cut."""
    working = copy.deepcopy(pool)
    variant_policy = dataclasses.replace(policy, question_values=frozenset(values))
    ordered = rerank_module.apply_rank_adjustments(working, variant_policy)
    chosen = rerank_module.select_context(ordered, top_n, variant_policy)
    ordered_ids = ids_of(ordered)
    chosen_ids = ids_of(chosen)
    by_id = {str(chunk.get("chunk_id"))[:16]: chunk for chunk in working}
    pure = sorted(working, key=lambda chunk: -(chunk.get("similarity") or 0.0))
    cut = rerank_module.select_context(ordered, top_n, variant_policy)
    return {
        "values": list(values),
        "target_rank": rank_of(ordered_ids, TARGET),
        "target_rank_score": (by_id.get(TARGET) or {}).get("rank_score"),
        "target_similarity": (by_id.get(TARGET) or {}).get("similarity"),
        "target_chosen": TARGET in chosen_ids,
        "control_rank": rank_of(ordered_ids, CONTROL),
        "control_chosen": CONTROL in chosen_ids,
        "ordered_top12": [
            {"chunk_id": cid, "is_table": is_table_chunk(by_id[cid]), "rank_score": by_id[cid].get("rank_score"), "similarity": by_id[cid].get("similarity")}
            for cid in ordered_ids[:top_n]
        ],
        "ordered_top12_tables": sum(1 for cid in ordered_ids[:top_n] if is_table_chunk(by_id[cid])),
        "chosen_size": len(chosen_ids),
        "chosen_tables": sum(1 for chunk in chosen if is_table_chunk(chunk)),
        "chosen_prose": sum(1 for chunk in chosen if not is_table_chunk(chunk)),
        "pure_by_similarity_top12_tables": sum(1 for chunk in pure[:top_n] if is_table_chunk(chunk)),
        "pure_by_similarity_target_rank": rank_of(ids_of(pure), TARGET),
        "chosen_ids": chosen_ids,
        "_ordered_ids": ordered_ids,
    }


async def main():
    dialog_row = Dialog.get_or_none(Dialog.id == DIALOG_ID)
    owner = getattr(dialog_row, "tenant_id", None) or "a9e28731ab7011f19b833887d563fb04"
    ok, kb = KnowledgebaseService.get_by_id(KB)
    params = {"similarity_threshold": dialog_row.similarity_threshold, "vector_similarity_weight": dialog_row.vector_similarity_weight, "final_top_n": dialog_row.top_n, "knn_top_k": dialog_row.top_k}
    embd_mdl = LLMBundle(owner, resolve_model_config(owner, LLMType.EMBEDDING, kb.embd_id))
    try:
        config = get_tenant_default_model_by_type(owner, LLMType.CHAT)
        chat_mdl = LLMBundle(owner, config) if isinstance(config, dict) and config else None
    except Exception:  # noqa: BLE001
        chat_mdl = None
    dealer = rag_search.Dealer(settings.docStoreConn)

    original_adjust = rerank_module.apply_rank_adjustments

    def adjust_capture(chunks, policy):
        CURRENT["pool"] = copy.deepcopy(chunks)
        CURRENT["policy"] = policy
        CURRENT["policy_fields"] = {
            "min_prose": policy.min_prose,
            "max_table_share": policy.max_table_share,
            "table_penalty": policy.table_penalty,
            "core_document_boost": policy.core_document_boost,
            "max_auxiliary_document_share": policy.max_auxiliary_document_share,
            "max_document_share": policy.max_document_share,
            "question_values": sorted(policy.question_values),
            "compared_documents": sorted(policy.compared_documents),
        }
        return original_adjust(chunks, policy)

    rerank_module.apply_rank_adjustments = adjust_capture

    report = {"parameters_used": params, "constants": {"VALUE_PAIRING_BOOST": rerank_module.VALUE_PAIRING_BOOST, "VALUE_LIST_PENALTY": rerank_module.VALUE_LIST_PENALTY, "TABLE_PENALTY": rerank_module.TABLE_PENALTY, "CORE_DOCUMENT_BOOST": rerank_module.CORE_DOCUMENT_BOOST, "MAX_VALUE_POOL_SHARE": MAX_VALUE_POOL_SHARE, "MAX_QUESTION_VALUES": MAX_QUESTION_VALUES}, "queries": []}

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
        pool = CURRENT.get("pool") or []
        policy = CURRENT.get("policy")
        entry = {
            "id": query["id"],
            "shape": query["shape"],
            "question": query["text"],
            "derivation": staged(query["text"], pool),
            "policy_fields": CURRENT.get("policy_fields"),
            "final_ids": ids_of(result.get("chunks")),
            "pool_size": len(pool),
            "pool_tables": sum(1 for chunk in pool if is_table_chunk(chunk)),
        }
        if policy is not None:
            entry["consumer_census"] = consumer_census(pool, policy.question_values)
        if query["id"] == "INCIDENT_COMPOSITE" and policy is not None:
            current = sorted(policy.question_values)
            without_year = [value for value in current if not re.fullmatch(r"(19|20)\d{2}", value)]
            technical_only = [value for value in current if classify(value, query["text"]) == "technical_value"]
            variants = {
                "A_current": current,
                "B_without_year": without_year,
                "C_technical_only": technical_only,
                "D_separated_classes_identity_excluded": technical_only,
                "E_no_values_at_all": [],
            }
            entry["counterfactuals"] = {}
            for label, values in variants.items():
                evaluated = evaluate(pool, policy, values, params["final_top_n"] or 12)
                order = evaluated.pop("_ordered_ids")
                if label == "A_current":
                    base_order = order
                entry["counterfactuals"][label] = evaluated
            base_order = entry["counterfactuals"]["A_current"]["_ordered_ids"] if "_ordered_ids" in entry["counterfactuals"]["A_current"] else None
        report["queries"].append(entry)
        print("captured", query["id"], "values", entry["derivation"]["final_question_values"], "classes", entry["derivation"]["final_classes"], "pool", len(pool), file=sys.stderr)

    rerank_module.apply_rank_adjustments = original_adjust
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("QV_ATTR_BEGIN")
    print(json.dumps({"queries": [{"id": entry["id"], "shape": entry["shape"], "question_values": entry["derivation"]["final_question_values"], "classes": entry["derivation"]["final_classes"], "pool": entry["pool_size"]} for entry in report["queries"]]}, ensure_ascii=False, indent=1))
    print("QV_ATTR_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
