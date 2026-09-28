"""Materiality isolation for the question-value repair. READ-ONLY, diagnostic only.

The before/after comparison is made on the SAME retrieved pool inside one process, so planner variance
(the chat model's decomposition is not deterministic - measured in P1-0) cannot be mistaken for the
effect of the fix. The OLD extraction is mirrored here for comparison only; the NEW value set comes
from the real, repaired `question_values`, and both are evaluated through the REAL
`apply_rank_adjustments` and `select_context` on deep copies of a real pool.

Nothing this computes re-enters the pipeline. It exists to answer two questions separately:

  FEATURE_CORRECTNESS  - are the value SETS now semantically right?
  QGDW_RECOVERY        - does that change where the target chunk ends up? (materiality only, and
                         explicitly NOT a success criterion for the repair)
"""
import asyncio
import contextvars
import copy
import dataclasses
import functools
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, "/ragflow")

from common import settings

settings.init_settings()

# The LLM cache is bypassed in-process so this window writes NOTHING to the deployed Redis.
import rag.graphrag.utils as graphrag_utils

graphrag_utils.get_llm_cache = lambda *args, **kwargs: None
graphrag_utils.set_llm_cache = lambda *args, **kwargs: None

from api.db.db_models import Dialog
from api.db.joint_services.tenant_model_service import get_tenant_default_model_by_type, resolve_model_config
from api.db.services.knowledgebase_service import KnowledgebaseService
from api.db.services.llm_service import LLMBundle
from common.constants import LLMType
from rag.nlp import search as rag_search
from rag.retrieval import rerank as rerank_module
from rag.retrieval import pipeline as pipeline_module
from rag.retrieval.chunk_profile import carries_value, document_name, is_table_chunk, paired_values
from rag.retrieval.decomposition import MAX_QUESTION_VALUES, _QUESTION_NUMBER_RE, _pool_share, question_values, strip_section_references

KB = "9463d93eb97511f1938f2592e9bc6fe4"
DIALOG_ID = "29a6da60ba1f11f1be9555eabe501d5b"
OUT = pathlib.Path(os.environ.get("P12_MAT_OUT", "/tmp/question_value_materiality.json"))
TARGET = "d1d75672f2dbc333"
CONTROL = "b5aaf72bcd33d44a"
OLD_SHARE_LIMIT = 0.8

QUERIES = [
    ("QGDW_COMPOSITE", "standard number + year, composite", "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"),
    ("QGDW_SINGLE_PART2", "standard number + year", "根据 Q/GDW 73286.2-2026 表 1，单芯电缆的导体标称截面有哪些规格？"),
    ("QGDW_THREE_PART3", "standard number + year", "根据 Q/GDW 73286.3-2026 表 1，三芯电缆的导体标称截面有哪些规格？"),
    ("STRUCTURE", "voltage only", "220kV 三芯海缆的主要结构有哪些？"),
    ("VALUE_LOOKUP", "std + year + one figure", "Q/GDW 73286.2-2026 表 1 中 800 mm² 单芯电缆的导体标称截面规格数量是多少？"),
    ("MODEL_NUMBER", "cable model number", "WDZC-YJY-0.6/1kV 3×25 电缆的载流量是多少？"),
    ("TECHNICAL_VALUE", "genuine technical values", "220kV 单芯海底电缆 800 mm² 截面的内衬层厚度要求是多少？"),
    ("MULTI_VALUE", "multi-value comparison", "针对 800 mm² 与 1200 mm² 的单芯与三芯电缆，内衬层厚度要求有什么区别？"),
    ("YEAR_ONLY", "year only", "2026 年版的海底电缆标准对铠装层有什么规定？"),
    ("NO_NUMBERS", "no numbers", "海底电缆的内衬层有什么要求？"),
]

CURRENT = {}
route_context = contextvars.ContextVar("p12_mat_route", default=None)


def old_question_values(question, chunks=()):
    """The DEPLOYED extraction, mirrored for comparison only: regex -> length -> dedupe -> share<=0.8."""
    text = re.sub(r"\s+", " ", strip_section_references(str(question or ""))).strip()
    if not text:
        return []
    found = []
    for match in _QUESTION_NUMBER_RE.finditer(text):
        token = match.group(0).replace("．", ".")
        digits = token.replace(".", "")
        if len(digits) < 2 and "." not in token:
            continue
        if token not in found:
            found.append(token)
    if not found:
        return []
    pool = list(chunks or ())
    if pool:
        found = [value for value in found if _pool_share(value, pool) <= OLD_SHARE_LIMIT]
    return found[:MAX_QUESTION_VALUES]


def ids_of(chunks):
    return [str(chunk.get("chunk_id") or "")[:16] for chunk in chunks or []]


def rank_of(ids, chunk_id):
    return (ids.index(chunk_id) + 1) if chunk_id in ids else None


def evaluate(pool, policy, values, top_n):
    working = copy.deepcopy(pool)
    variant = dataclasses.replace(policy, question_values=frozenset(values))
    ordered = rerank_module.apply_rank_adjustments(working, variant)
    chosen = rerank_module.select_context(ordered, top_n, variant)
    ordered_ids = ids_of(ordered)
    chosen_ids = ids_of(chosen)
    by_id = {str(chunk.get("chunk_id"))[:16]: chunk for chunk in working}
    pure = sorted(working, key=lambda chunk: -(chunk.get("similarity") or 0.0))
    pure_ids = ids_of(pure)
    penalised = [cid for cid, chunk in by_id.items() if is_table_chunk(chunk) and carries_value(chunk, tuple(sorted(values))) and not paired_values(chunk, tuple(sorted(values)))]
    boosted = [cid for cid, chunk in by_id.items() if paired_values(chunk, tuple(sorted(values)))]
    return {
        "values": list(values),
        "target_base_similarity": (by_id.get(TARGET) or {}).get("similarity"),
        "target_adjusted_score": (by_id.get(TARGET) or {}).get("rank_score"),
        "target_adjusted_rank": rank_of(ordered_ids, TARGET),
        "target_rank_by_raw_similarity": rank_of(pure_ids, TARGET),
        "target_overtakers": (rank_of(ordered_ids, TARGET) or 0) - (rank_of(pure_ids, TARGET) or 0),
        "target_selected": TARGET in chosen_ids,
        "control_adjusted_rank": rank_of(ordered_ids, CONTROL),
        "control_selected": CONTROL in chosen_ids,
        "ordered_top12_tables": sum(1 for cid in ordered_ids[:top_n] if is_table_chunk(by_id[cid])),
        "ordered_top12_prose": sum(1 for cid in ordered_ids[:top_n] if not is_table_chunk(by_id[cid])),
        "chosen_tables": sum(1 for chunk in chosen if is_table_chunk(chunk)),
        "chosen_prose": sum(1 for chunk in chosen if not is_table_chunk(chunk)),
        "chosen_size": len(chosen_ids),
        "pure_top12_tables": sum(1 for cid in pure_ids[:top_n] if is_table_chunk(by_id[cid])),
        "value_penalty_fires_on_tables": len(penalised),
        "value_pairing_fires_on": len(boosted),
        "pool_tables": sum(1 for chunk in working if is_table_chunk(chunk)),
        "chosen_ids": chosen_ids,
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

    def capture(chunks, policy):
        CURRENT["pool"] = copy.deepcopy(chunks)
        CURRENT["policy"] = policy
        return original_adjust(chunks, policy)

    rerank_module.apply_rank_adjustments = capture

    report = {"purpose": "materiality isolation for the question-value repair; diagnostic only", "parameters_used": params, "target": TARGET, "control": CONTROL, "shape_matrix": [], "composite_materiality": None}

    # --- shape matrix: the value SETS, old mirror vs repaired function -------------------------
    for query_id, shape, text in QUERIES:
        report["shape_matrix"].append(
            {
                "id": query_id,
                "shape": shape,
                "question": text,
                "values_before": old_question_values(text),
                "values_after": question_values(text),
            }
        )

    # --- one real retrieval, and the materiality comparison on ITS pool ------------------------
    CURRENT.clear()
    await pipeline_module.retrieve_multi_route(
        retriever=dealer,
        question=QUERIES[0][2],
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
    pool = CURRENT["pool"]
    policy = CURRENT["policy"]
    before_values = old_question_values(QUERIES[0][2], pool)
    after_values = question_values(QUERIES[0][2], pool)
    report["composite_materiality"] = {
        "question": QUERIES[0][2],
        "pool_size": len(pool),
        "routes": sorted({route for chunk in pool for route in rerank_module.routes_of(chunk)})[:1],
        "before": evaluate(pool, policy, before_values, params["final_top_n"] or 12),
        "after": evaluate(pool, policy, after_values, params["final_top_n"] or 12),
    }
    report["composite_materiality"]["delta"] = {
        key: (report["composite_materiality"]["after"][key] - report["composite_materiality"]["before"][key])
        for key in ("target_adjusted_rank", "target_adjusted_score", "target_overtakers", "ordered_top12_tables", "chosen_tables", "value_penalty_fires_on_tables", "value_pairing_fires_on")
        if isinstance(report["composite_materiality"]["before"].get(key), (int, float)) and isinstance(report["composite_materiality"]["after"].get(key), (int, float))
    }

    # --- header contamination, isolated on the SAME pool and the SAME value set -----------------
    # The legacy text is the deployed `_plain(_content(chunk))`; the fixed text is the same with the
    # ingest metadata block removed. The relation is a pure subset, so every difference is the header.
    legacy_values = before_values
    legacy_text = {str(chunk.get("chunk_id"))[:16]: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(chunk.get("content_with_weight") or chunk.get("content") or ""))).strip().lower() for chunk in pool}

    def legacy_carries(chunk, values):
        """The deployed `carries_value` reading, i.e. over the text INCLUDING the ingest metadata.

        Only the CARRIES side is mirrored. Pairing is deliberately not mirrored here: `paired_values`
        decides what counts as a result figure through `result_figures`, which excludes reference
        numbers, and a crude mirror of that is not trustworthy. The penalty counts are taken from the
        real predicate instead, in the two evaluations above.
        """
        text = legacy_text.get(str(chunk.get("chunk_id"))[:16], "")
        return any(re.search(rf"(?<!\d){re.escape(str(value))}(?!\d)", text) for value in values if value)

    tables = [chunk for chunk in pool if is_table_chunk(chunk)]
    target_table = next((chunk for chunk in tables if str(chunk.get("chunk_id"))[:16] == TARGET), None)
    report["header_contamination"] = {
        "value_set": legacy_values,
        "pool_tables": len(tables),
        "legacy_text_tables_carrying": sum(1 for chunk in tables if legacy_carries(chunk, tuple(legacy_values))),
        "fixed_text_tables_carrying": sum(1 for chunk in tables if carries_value(chunk, tuple(legacy_values))),
        "real_value_list_penalties_with_fixed_text": report["composite_materiality"]["before"]["value_penalty_fires_on_tables"],
        "target_carries_legacy": None if target_table is None else legacy_carries(target_table, tuple(legacy_values)),
        "target_carries_fixed": None if target_table is None else carries_value(target_table, tuple(legacy_values)),
        "note": "same pool, same value set; the only difference is whether the ingest metadata block counts as evidence",
    }

    rerank_module.apply_rank_adjustments = original_adjust
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("MATERIALITY_BEGIN")
    print(json.dumps({"shape_matrix": report["shape_matrix"], "composite": {k: v for k, v in report["composite_materiality"].items() if k != "routes"}}, ensure_ascii=False, indent=1))
    print("MATERIALITY_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
