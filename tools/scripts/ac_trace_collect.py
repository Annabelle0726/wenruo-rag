"""Domain-blind deployed retrieval tracer: emits FACTS as JSON, judges nothing.

Runs inside the deployed container. It imports only modules the deployed image actually has
(`common.settings`, `rag.nlp.search`, `rag.nlp.rag_tokenizer`, the api model resolver) and
deliberately contains no notion of blank templates, document families, standard identity,
metadata projection or relevance: it does not know what a "blank template" is. Any module it
cannot import makes that stage `NOT_SEPARATELY_OBSERVABLE` rather than simulated.

Output (stdout, JSON): for each query, the deployed tokenizer's tokens, then per stage the
chunks with id / document id / document name / rank / score / stored text and any score the
API actually exposes. A field the API does not expose is `NOT_OBSERVABLE`; nothing is derived.

Frozen configuration, identical for every query: threshold 0.2, vector weight 0.6,
routes_top_k 12 (used as page_size, captured from multi_route.py:235-244), final_top_n 8,
knn_top_k 1024, allow_dense_fallback True, keyword augmentation OFF.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import sys

sys.path.insert(0, "/ragflow")

KB = "9463d93eb97511f1938f2592e9bc6fe4"
QUERIES = {
    "A": "根据 Q/GDW 73286.2-2026 查找单芯 220kV 海缆参数",
    "C": "220kV 三芯海底电缆结构参数",
}
STANDARD_NO = "Q/GDW 73286.2-2026"
OVERLAP_TERMS = ("220kV", "三芯", "海底电力电缆")
THRESHOLD, WEIGHT, PAGE, PAGE_SIZE = 0.2, 0.6, 1, 50
TEXT_LIMIT = 12  # full text for the top N of each leg, ids/scores only beyond that
NOT_OBSERVABLE = "NOT_OBSERVABLE"


def chunk_fact(rank, chunk, include_text) -> dict:
    body = str(chunk.get("content_with_weight") or "")
    fact = {
        "rank": rank,
        "chunk_id": str(chunk.get("chunk_id") or chunk.get("id") or ""),
        "document_id": str(chunk.get("doc_id") or ""),
        "document_name": str(chunk.get("docnm_kwd") or ""),
        "score": float(chunk.get("similarity") or 0.0),
        "term_score": float(chunk["term_similarity"]) if isinstance(chunk.get("term_similarity"), (int, float)) else NOT_OBSERVABLE,
        "vector_score": float(chunk["vector_similarity"]) if isinstance(chunk.get("vector_similarity"), (int, float)) else NOT_OBSERVABLE,
        "fusion_score": float(chunk["similarity"]) if isinstance(chunk.get("similarity"), (int, float)) else NOT_OBSERVABLE,
        "rerank_score": float(chunk["rerank_score"]) if isinstance(chunk.get("rerank_score"), (int, float)) else NOT_OBSERVABLE,
        "page_num_int": chunk.get("page_num_int", NOT_OBSERVABLE),
        "doc_type_kwd": chunk.get("doc_type_kwd", NOT_OBSERVABLE),
    }
    if include_text:
        fact["content_with_weight"] = body
    return fact


async def collect(dealer, embd_mdl, owner, kwargs) -> dict:
    payload: dict = {"kb_id": KB, "owner_tenant": owner, "config": {"similarity_threshold": THRESHOLD, "vector_similarity_weight": WEIGHT, "page": PAGE, "page_size": PAGE_SIZE, "knn_top_k": 1024, "allow_dense_fallback": True, "final_top_n": 8, "keyword_augmentation": "OFF"}, "queries": {}}
    from rag.nlp import rag_tokenizer

    rag_tokenizer.tokenizer.set_language("Chinese")
    payload["standard_no_probe"] = {"raw": STANDARD_NO, "tokens": rag_tokenizer.tokenize(STANDARD_NO).split()}

    for tag, question in QUERIES.items():
        entry: dict = {"query": question, "query_tokens": rag_tokenizer.tokenize(question).split(), "stages": {}}
        for label, weight in (("stage1_lexical_only", 0.0), ("stage2_dense_only", 1.0), ("stage3_hybrid", WEIGHT)):
            try:
                result = await dealer.retrieval(question, embd_mdl, [owner], [KB], PAGE, PAGE_SIZE, THRESHOLD, weight, **kwargs)
                chunks = result.get("chunks") or []
                entry["stages"][label] = {"weight": weight, "total": result.get("total"), "returned": len(chunks), "chunks": [chunk_fact(index, chunk, index <= TEXT_LIMIT) for index, chunk in enumerate(chunks, 1)]}
            except Exception as exc:  # noqa: BLE001 - the tracer reports, it does not fix
                entry["stages"][label] = {"error": f"{type(exc).__name__}: {exc}"}

        # stage 4: the deployed pipeline passes no rerank model by default.
        entry["stages"]["stage4_reranker"] = {"status": "NOT ACTIVE", "reason": "the deployed call passes rerank_mdl=None (its own default)"}
        # stages 5/6: only if the deployed image actually ships the helpers.
        try:
            from rag.retrieval import rerank as deployed_rerank

            pool = [dict(chunk) for chunk in (await dealer.retrieval(question, embd_mdl, [owner], [KB], PAGE, PAGE_SIZE, THRESHOLD, WEIGHT, **kwargs)).get("chunks", [])]
            policy = deployed_rerank.DiversityPolicy.for_question(question, pool)
            ordered = deployed_rerank.apply_rank_adjustments(pool, policy)
            selected = deployed_rerank.select_context(ordered, 8, policy)
            entry["stages"]["stage5_rank_adjustments"] = {"order": [str(chunk.get("chunk_id") or "") for chunk in ordered], "rank_moves": _moves(pool, ordered)}
            entry["stages"]["stage6_final_context"] = {"window": 8, "chunks": [chunk_fact(index, chunk, index <= TEXT_LIMIT) for index, chunk in enumerate(selected, 1)]}
        except Exception as exc:  # noqa: BLE001
            entry["stages"]["stage5_rank_adjustments"] = {"status": "NOT_SEPARATELY_OBSERVABLE", "reason": f"{type(exc).__name__}: {exc}"}
            entry["stages"]["stage6_final_context"] = {"status": "NOT_SEPARATELY_OBSERVABLE"}

        # factual token overlap for the terms the query names
        overlaps = {}
        for term in OVERLAP_TERMS:
            term_tokens = set(rag_tokenizer.tokenize(term).split())
            hits = []
            for stage in ("stage1_lexical_only", "stage3_hybrid"):
                for fact in (entry["stages"].get(stage, {}).get("chunks") or []):
                    text = fact.get("content_with_weight")
                    if not text:
                        continue
                    tokens = set(rag_tokenizer.tokenize(text).split())
                    hits.append({"chunk_id": fact["chunk_id"], "stage": stage, "rank": fact["rank"], "overlap": sorted(term_tokens & tokens), "coverage": round(len(term_tokens & tokens) / max(1, len(term_tokens)), 3)})
            overlaps[term] = {"term_tokens": sorted(term_tokens), "samples": hits[:6]}
        entry["token_overlap"] = overlaps
        payload["queries"][tag] = entry
    return payload


def _moves(pool, ordered) -> list:
    before = {str(chunk.get("chunk_id") or ""): index for index, chunk in enumerate(pool, 1)}
    moves = []
    for index, chunk in enumerate(ordered, 1):
        key = str(chunk.get("chunk_id") or "")
        if key in before and before[key] != index:
            moves.append({"chunk_id": key, "from": before[key], "to": index})
    return moves


async def main() -> int:
    from common import settings

    settings.init_settings()
    from rag.nlp import search as rag_search
    from api.db.joint_services.tenant_model_service import resolve_model_config
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from api.db.services.llm_service import LLMBundle
    from common.constants import LLMType

    ok, kb = KnowledgebaseService.get_by_id(KB)
    if not ok:
        print(json.dumps({"error": f"KB {KB} not found"}))
        return 1
    owner = str(getattr(kb, "tenant_id", "") or "")
    embd_mdl = LLMBundle(owner, resolve_model_config(owner, LLMType.EMBEDDING, kb.embd_id))
    dealer = rag_search.Dealer(settings.docStoreConn)
    accepted = set(inspect.signature(dealer.retrieval).parameters)
    kwargs = {key: value for key, value in (("knn_top_k", 1024), ("allow_dense_fallback", True)) if key in accepted}

    payload = await collect(dealer, embd_mdl, owner, kwargs)
    payload["deployed_retrieval_signature"] = sorted(accepted)
    payload["embedding_model_id"] = getattr(kb, "embd_id", None)
    print("TRACE_JSON_BEGIN")
    print(json.dumps(payload, ensure_ascii=False))
    print("TRACE_JSON_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
