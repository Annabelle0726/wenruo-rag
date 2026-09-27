"""Does a dense-leg failure still leave the lexical leg running? Quota-free experiment.

Drives the REAL candidate chain (pipeline -> multi_route -> Dealer.search) with the
embedding provider doubled as a FAILING client and the doc store doubled, then reports
which legs the producers actually observed. This settles whether the wording
"fell back to text search" is entailed by a dense failure.
"""

from __future__ import annotations

import asyncio
import json
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, "/ragflow")


class QuotaExhausted(Exception):
    pass


class FailingEmbedding:
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc
        self.calls = 0

    def encode_queries(self, text):
        self.calls += 1
        raise self.exc


class CountingDataStore:
    """Doc store double that records whether the store round trip was ever reached."""

    def __init__(self) -> None:
        self.search_calls = 0

    def search(self, *args, **kwargs):
        self.search_calls += 1
        return {
            "hits": {
                "hits": [
                    {
                        "_id": "c1",
                        "_score": 1.0,
                        "_source": {
                            "content_with_weight": "clause",
                            "docnm_kwd": "d.pdf",
                            "doc_id": "d1",
                            "chunk_order_int": 0,
                            "page_num_int": 1,
                            "top_int": 0,
                            "create_timestamp_flt": 1.0,
                            "vector_similarity": 0.9,
                            "term_similarity": 0.5,
                            "row_id": "r1",
                        },
                    }
                ],
                "total": {"value": 1},
            }
        }

    def get_total(self, result):
        return len(result["hits"]["hits"])

    def get_doc_ids(self, result):
        return [h["_id"] for h in result["hits"]["hits"]]

    def get_highlight(self, *args, **kwargs):
        return {}

    def get_aggregation(self, *args, **kwargs):
        return []

    def get_fields(self, result, fields):
        return [dict(h["_source"], id=h["_id"]) for h in result["hits"]["hits"]]

    def get_scores(self, result):
        return [h["_score"] for h in result["hits"]["hits"]]

    def index_exist(self, *args, **kwargs):
        return True


class StoreBackedRetriever:
    def __init__(self, dealer) -> None:
        self.dealer = dealer

    async def retrieval(self, question, embd_mdl, tenant_ids, kb_ids, page=1, page_size=8, similarity_threshold=0.2, **kwargs):
        req = dict(kwargs)
        req["question"] = question
        req["similarity"] = 0.1
        idx_names = [f"ragflow_{t}" for t in tenant_ids]
        sres = await self.dealer.search(
            req, idx_names, kb_ids, embd_mdl, None, rank_feature=None, min_match=False
        )
        chunks = []
        for i, cid in enumerate(sres.ids):
            fields = (sres.field or [{}])[i] if sres.field and i < len(sres.field) else {}
            chunks.append(dict(fields, id=cid, chunk_id=cid))
        return {"total": sres.total, "chunks": chunks, "doc_aggs": list(sres.aggregation or [])}


def experiment(exc: BaseException, label: str) -> dict:
    from common import settings

    settings.init_settings()
    import importlib

    rag_search = importlib.import_module("rag.nlp.search")
    health_bridge = importlib.import_module("rag.retrieval.health_bridge")
    pipeline = importlib.import_module("rag.retrieval.pipeline")

    store = CountingDataStore()
    dealer = rag_search.Dealer(store)
    retriever = StoreBackedRetriever(dealer)
    embd = FailingEmbedding(exc)

    async def run():
        health_bridge.begin_retrieval_health()
        result = await pipeline.retrieve_multi_route(
            retriever=retriever,
            question="220kV 三芯海缆的主要结构有哪些？",
            tenant_ids=["t"],
            kb_ids=["k"],
            chat_mdl=None,
            embd_mdl=embd,
            routes_top_k=12,
            final_top_n=8,
            knn_top_k=1024,
        )
        return result, health_bridge.current_session()

    result, session = asyncio.run(run())
    legs = {n: leg.status.value for n, leg in session.legs.items()}
    report = session.build()
    return {
        "scenario": label,
        "embedding_attempts": embd.calls,
        "store_round_trips": store.search_calls,
        "leg_status": legs,
        "lexical_leg_reported": "lexical" in legs,
        "evidence_returned": len(result.get("chunks") or []),
        "dto": result.get("retrieval_health"),
        "degradation_reason": report.degradation_reason(),
        "contract_violations": report.validate(),
    }


def main() -> int:
    out = [
        experiment(QuotaExhausted("429 RESOURCE_EXHAUSTED: quota exceeded"), "dense_quota_failure"),
        experiment(
            RuntimeError("Embedding request failed for GeminiEmbed. Error: 400 FAILED_PRECONDITION. User location is not supported for the API use."),
            "dense_geopolicy_failure",
        ),
    ]
    print("LEG_FALLBACK_BEGIN")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("LEG_FALLBACK_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
