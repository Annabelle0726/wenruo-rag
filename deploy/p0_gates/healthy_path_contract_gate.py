"""HEALTHY_PATH_CONTRACT_GATE — the healthy producer path must produce an honest health DTO.

Why this gate exists: the P0-C fault-injection suite hand-fills every leg in its fixtures, so it passed
5/5 twice against a candidate whose real producer path could not produce a `full` verdict at all. This
gate never hand-fills a leg. It drives the REAL candidate wiring (pipeline -> multi_route -> the store
layer's own producers) with only the two innermost boundaries doubled:

    * the embedding provider  (test double -> zero external Gemini quota)
    * the document store      (test double -> no cluster, deterministic lexical hits)

Everything else runs the deployed candidate code, and the DTO under test is the one the real pipeline
attached. Legs are read from the pipeline's own session, never synthesised here.

Required negative regression: when the dense producer does not report a leg it should have reported, the
verdict must be FAIL — the gate must not quietly promote the missing leg to success.

Runs inside the candidate runtime. Exit 0 = PASS, 1 = FAIL.
"""

from __future__ import annotations

import asyncio
import json
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, "/ragflow")

EXPECTED_LEGS = ("decomposition", "lexical", "dense", "rerank", "followup")
EVIDENCE_LEGS = ("lexical", "dense")
NOT_TRIGGERED_OK = {"rerank", "followup"}


class FakeEmbedding:
    """Test double for the embedding provider. Never touches the network."""

    def __init__(self, dim: int = 3072, fail: BaseException | None = None) -> None:
        self.dim = dim
        self.fail = fail
        self.calls = 0

    def encode_queries(self, text):
        import numpy as np

        self.calls += 1
        if self.fail is not None:
            raise self.fail
        vector = np.zeros(self.dim, dtype=float)
        vector[0] = 1.0
        return vector, 1


class FakeDataStore:
    """Test double for the document store: one deterministic lexical hit per round trip."""

    def __init__(self, chunks_per_call: int = 2) -> None:
        self.chunks_per_call = chunks_per_call
        self.search_calls = 0

    def _hits(self):
        hits = []
        for index in range(self.chunks_per_call):
            hits.append(
                {
                    "_id": f"chunk-{index}",
                    "_score": 1.0 - index * 0.1,
                    "_source": {
                        "content_with_weight": f"cable technical clause {index}",
                        "docnm_kwd": "Cable_Tech_Docs.pdf",
                        "doc_id": "doc-1",
                        "chunk_order_int": index,
                        "page_num_int": 1,
                        "top_int": index,
                        "create_timestamp_flt": 1.0 + index,
                        "vector_similarity": 0.9,
                        "term_similarity": 0.5,
                        "row_id": f"row-{index}",
                    },
                }
            )
        return {"hits": {"hits": hits, "total": {"value": len(hits)}}}

    def search(self, *args, **kwargs):
        self.search_calls += 1
        return self._hits()

    def get_total(self, result):
        return len(result["hits"]["hits"])

    def get_doc_ids(self, result):
        return [hit["_id"] for hit in result["hits"]["hits"]]

    def get_highlight(self, result, keywords, field):
        return {}

    def get_aggregation(self, result, field):
        return [{"doc_name": "Cable_Tech_Docs.pdf", "count": len(result["hits"]["hits"])}]

    def get_fields(self, result, fields):
        return [dict(hit["_source"], id=hit["_id"]) for hit in result["hits"]["hits"]]

    def get_scores(self, result):
        return [hit["_score"] for hit in result["hits"]["hits"]]

    def index_exist(self, *args, **kwargs):
        return True


class StoreBackedRetriever:
    """Substitutes only for `Dealer.retrieval`'s outer wrapper.

    The measured statements inside it - `Dealer.search` and `Dealer.get_vector` - are the REAL candidate
    code, so the dense and lexical facts are produced by the deployed producers, not by this double.
    """

    def __init__(self, dealer) -> None:
        self.dealer = dealer

    async def retrieval(self, question, embd_mdl, tenant_ids, kb_ids, page=1, page_size=8, similarity_threshold=0.2, **kwargs):
        req = dict(kwargs)
        req["question"] = question
        req["similarity"] = 0.1
        idx_names = [f"ragflow_{tid}" for tid in tenant_ids]
        sres = await self.dealer.search(
            req,
            idx_names,
            kb_ids,
            embd_mdl,
            None,
            rank_feature=req.get("rank_feature"),
            min_match=float(req.get("vector_similarity_weight", 0.6)) < 0.8,
        )
        chunks = []
        for index, chunk_id in enumerate(sres.ids):
            fields = (sres.field or [{}])[index] if sres.field and index < len(sres.field) else {}
            chunks.append(dict(fields, id=chunk_id, chunk_id=chunk_id, similarity=1.0 - index * 0.1))
        return {"total": sres.total, "chunks": chunks, "doc_aggs": list(sres.aggregation or [])}


def build_chain():
    from common import settings

    # Real initialization: the lexical-expression builder (`query.FulltextQueryer`) loads its synonyms
    # from Redis, so the gate needs the deployed config and a reachable stack. Only the embedding
    # provider and the document store are doubled, so no external embedding quota is reachable - and the
    # runner additionally blocks the provider host, so a real provider call would fail rather than pass.
    settings.init_settings()

    from rag.nlp import search as rag_search
    from rag.retrieval import health, health_bridge, pipeline

    store = FakeDataStore()
    dealer = rag_search.Dealer(store)
    retriever = StoreBackedRetriever(dealer)
    return store, retriever, health, health_bridge, pipeline, rag_search


async def _run_chain(pipeline, health_bridge, retriever, embd):
    """Run the real chain and read the session INSIDE the task context.

    `asyncio.run` gives the coroutine a copy of the context, so the pipeline's `begin_retrieval_health()`
    is only visible from inside; reading `current_session()` afterwards would return an unrelated, empty
    session and mis-report every leg as unresolved.
    """
    health_bridge.begin_retrieval_health()
    result = await pipeline.retrieve_multi_route(
        retriever=retriever,
        question="220kV 三芯海缆的主要结构有哪些？",
        tenant_ids=["tenant-probe"],
        kb_ids=["kb-probe"],
        chat_mdl=None,
        embd_mdl=embd,
        routes_top_k=12,
        final_top_n=8,
        knn_top_k=1024,
    )
    return result, health_bridge.current_session()


def evaluate(mute_dense_producer: bool = False) -> dict:
    store, retriever, health, health_bridge, pipeline, rag_search = build_chain()

    real_report_dense_executed = health_bridge.report_dense_executed
    if mute_dense_producer:
        # Regression: simulate a producer that should report the dense leg but does not.
        health_bridge.report_dense_executed = lambda: None

    try:
        embd = FakeEmbedding()
        result, session = asyncio.run(_run_chain(pipeline, health_bridge, retriever, embd))
    finally:
        health_bridge.report_dense_executed = real_report_dense_executed

    legs = {name: leg.status.value for name, leg in (session.legs.items() if session else [])}
    reasons = {
        name: (leg.reason.value if hasattr(leg.reason, "value") else leg.reason)
        for name, leg in (session.legs.items() if session else [])
        if leg.reason is not None
    }
    report = session.build() if session else None
    violations = report.validate() if report is not None else ["NO_SESSION"]
    dto = result.get("retrieval_health") if isinstance(result, dict) else None
    keys = sorted(str(k) for k in result.keys()) if isinstance(result, dict) else []

    checks = {
        "all_known_legs_explicitly_resolved": all(name in legs for name in EXPECTED_LEGS),
        "no_required_leg_unknown_or_absent": all(legs.get(name) not in (None, "unknown") for name in EXPECTED_LEGS),
        "dense_execution_explicitly_observed": "dense" in legs,
        "dense_is_success": legs.get("dense") == "success",
        "lexical_is_success": legs.get("lexical") == "success",
        "legitimately_unused_legs_not_triggered": all(legs.get(name) == "not_triggered" for name in NOT_TRIGGERED_OK),
        "overall_is_full": bool(isinstance(dto, dict) and dto.get("overall") == "full"),
        "degradation_reason_is_null": bool(isinstance(dto, dict) and dto.get("degradation_reason") is None),
        "zero_contract_violations": violations == [],
        "legacy_payload_unchanged": keys == ["chunks", "doc_aggs", "retrieval_health", "total"] and bool(result.get("chunks")),
        "answer_policy_enforcement_disabled": health_bridge.answer_policy_enforced() is False,
        "producer_bridge_resolved": rag_search.health_producer_error() is None,
        "embedding_was_called_through_the_real_store_path": embd.calls > 0,
    }
    return {
        "mute_dense_producer": mute_dense_producer,
        "leg_status": legs,
        "leg_reasons": reasons,
        "retrieval_health_dto": dto,
        "contract_violations": violations,
        "result_keys": keys,
        "embedding_calls": embd.calls,
        "store_search_calls": store.search_calls,
        "checks": checks,
        "passed": all(checks.values()),
    }


def main() -> int:
    # `rag.nlp.search` is imported inside build_chain() AFTER settings.init_settings(), which is the
    # deployed order; importing it first trips the pre-existing settings <-> redis_conn cycle.
    healthy = evaluate(mute_dense_producer=False)
    muted = evaluate(mute_dense_producer=True)

    out = {
        "gate": "HEALTHY_PATH_CONTRACT_GATE",
        "provenance": "real candidate pipeline -> multi_route -> store-layer producers; embedding + doc store doubled",
        "healthy_path": healthy,
        "negative_regression": muted,
        "checks": {
            "healthy_path_passes": healthy["passed"],
            "negative_regression_fails_when_dense_unreported": muted["passed"] is False,
            "negative_regression_sees_dense_missing": "dense" not in muted["leg_status"],
            "negative_regression_flags_silent_degradation": any("SILENT_DEGRADATION" in v for v in muted["contract_violations"]),
            "gate_does_not_self_heal": healthy["leg_status"].get("dense") == "success" and muted["leg_status"].get("dense") != "success",
        },
    }
    out["passed"] = all(out["checks"].values())
    out["verdict"] = "PASS" if out["passed"] else "FAIL"

    print("HEALTHY_PATH_GATE_JSON_BEGIN")
    print(json.dumps(out, ensure_ascii=False))
    print("HEALTHY_PATH_GATE_JSON_END")
    return 0 if out["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
