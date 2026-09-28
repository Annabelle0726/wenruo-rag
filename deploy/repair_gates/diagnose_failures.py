"""Isolated diagnostic for the three failing repair-gate cases. Read-only w.r.t. production.

Answers, with measurements rather than inference:
  A. why the mixed-route gate sees only LEXICAL_DEGRADED rows (is the "healthy" route empty?)
  B. is the STRUCTURE question's target even inside the 30-candidate lexical window?
  C. what rank does the single-core chunk actually hold on the main question?
"""
import asyncio
import json
import pathlib
import sys
import time

sys.path.insert(0, "/ragflow")

import numpy as np
import pytest  # noqa: F401  (harmless; keeps the environment identical to the gate)
from common import settings

settings.ES = {"hosts": "http://repair-es:9200"}
from rag.utils.es_conn import ESConnection
from rag.nlp.search import Dealer
from rag.llm.embedding_model import EmbeddingError
from rag.retrieval.multi_route import multi_route_retrieve

KB = "9463d93eb97511f1938f2592e9bc6fe4"
TENANT = "a9e28731ab7011f19b833887d563fb04"
INDEX = "ragflow_" + TENANT
THREE = "d1d75672f2dbc333"
SINGLE = "b5aaf72bcd33d44a"
INCIDENT = "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"
CONTROL = "根据 Q/GDW 73286.2-2026 表 1，单芯电缆的导体标称截面有哪些规格？"
STRUCTURE = "220kV 三芯海缆的主要结构有哪些？"

REPORT = {}


class Healthy:
    def __init__(self):
        self.calls = 0

    def encode_queries(self, text):
        self.calls += 1
        return np.array([1.0, 0.0]), 1


class Failed(Healthy):
    def encode_queries(self, text):
        self.calls += 1
        raise EmbeddingError("Embedding request failed: 400 FAILED_PRECONDITION User location is not supported for the API use.")


def make_dealer(store):
    dealer = Dealer(store)
    documents = json.loads(pathlib.Path("/tmp/sql-documents.json").read_text(encoding="utf-8-sig"))
    dealer._doc_exists_cache.update({doc["id"]: (time.time(), True) for doc in documents})
    return dealer


async def retrieve(dealer, model, question=CONTROL, weight=0.25, **kw):
    return await dealer.retrieval(
        question, model, [TENANT], [KB], 1, 20, 0.55, vector_similarity_weight=weight, rerank_candidates_count=30, rank_feature=None, must_not={"exists": "compile_kwd"}, allow_dense_fallback=False, **kw
    )


async def routes(dealer, model, questions, weight=0.25):
    return await multi_route_retrieve(
        retriever=dealer,
        queries=questions,
        embd_mdl=model,
        tenant_ids=[TENANT],
        kb_ids=[KB],
        routes_top_k=20,
        similarity_threshold=0.55,
        vector_similarity_weight=weight,
        rerank_candidates_count=30,
        rank_feature=None,
        must_not={"exists": "compile_kwd"},
        allow_dense_fallback=False,
    )


def ids(result):
    return [c["chunk_id"] for c in result["chunks"]]


async def main():
    store = ESConnection()
    ms = {}

    # ---- A: is the "healthy" side of the mixed gate actually non-empty? ----
    healthy = await retrieve(make_dealer(store), Healthy())
    ms["A_healthy_control"] = {
        "chunks": len(healthy["chunks"]),
        "ids": ids(healthy),
        "modes": sorted({c.get("score_provenance", {}).get("mode") for c in healthy["chunks"]}),
        "similarities": [round(float(c.get("similarity") or 0), 4) for c in healthy["chunks"][:8]],
        "retrieval_mode_key": healthy.get("retrieval_mode"),
    }
    healthy_w50 = await retrieve(make_dealer(store), Healthy(), weight=0.5)
    ms["A_healthy_control_w0.5"] = {"chunks": len(healthy_w50["chunks"]), "ids": ids(healthy_w50)}
    healthy_structure = await retrieve(make_dealer(store), Healthy(), question=STRUCTURE)
    ms["A_healthy_structure"] = {"chunks": len(healthy_structure["chunks"]), "ids": ids(healthy_structure)}
    degraded = await retrieve(make_dealer(store), Failed(), question=INCIDENT)
    ms["A_degraded_incident"] = {"chunks": len(degraded["chunks"]), "ids": ids(degraded), "modes": sorted({c.get("score_provenance", {}).get("mode") for c in degraded["chunks"]})}

    # ---- B: STRUCTURE, pure lexical, what does the 30-candidate window hold? ----
    for label, model, question in (("B_structure_failed", Failed(), STRUCTURE), ("B_structure_none", None, STRUCTURE)):
        captured = {}
        original = store.search

        def capture(*a, **kw):
            result = original(*a, **kw)
            captured["limit"] = a[6]
            captured["expressions"] = [type(e).__name__ for e in a[3]]
            captured["ids"] = list(store.get_doc_ids(result))
            captured["scores"] = list(store.get_scores(result))
            return result

        store.search = capture
        try:
            result = await routes(make_dealer(store), model, [question])
        finally:
            store.search = original
        window = captured.get("ids", [])
        ms[label] = {
            "expressions": captured.get("expressions"),
            "limit": captured.get("limit"),
            "window_size": len(window),
            "target_in_window": THREE in window,
            "target_rank": (window.index(THREE) + 1) if THREE in window else None,
            "selected_in_result": THREE in ids(result),
            "result_count": len(ids(result)),
        }
        REPORT[label] = ms[label]

    # ---- C: single-core rank on the main question, pure lexical ----
    dealer = make_dealer(store)
    req = {"question": INCIDENT, "kb_ids": [KB], "page": 1, "size": 30, "similarity": 0.55, "vector_similarity_weight": 0.25, "available_int": 1, "must_not": {"exists": "compile_kwd"}}
    page1 = await dealer.search(req, [INDEX], [KB], None, rank_feature=None, min_match=True)
    req2 = dict(req, page=2)
    page2 = await dealer.search(req2, [INDEX], [KB], None, rank_feature=None, min_match=True)
    rank = None
    if SINGLE in page1.ids:
        rank = page1.ids.index(SINGLE) + 1
    elif SINGLE in page2.ids:
        rank = 30 + page2.ids.index(SINGLE) + 1
    ms["C_single_core"] = {
        "rank": rank,
        "page1_size": len(page1.ids),
        "page2_size": len(page2.ids),
        "total": page1.total,
        "in_production_window_of_30": bool(rank and rank <= 30),
        "page1_head": page1.ids[:12],
        "page1_tail": page1.ids[-6:],
    }
    REPORT["C_single_core"] = ms["C_single_core"]

    # INCIDENT window: is THREE inside the 30-candidate lexical window (frozen fact)?
    captured = {}
    original = store.search

    def capture2(*a, **kw):
        result = original(*a, **kw)
        captured["ids"] = list(store.get_doc_ids(result))
        captured["limit"] = a[6]
        return result

    store.search = capture2
    try:
        inc = await routes(make_dealer(store), Failed(), [INCIDENT])
    finally:
        store.search = original
    window = captured.get("ids", [])
    ms["D_incident_window"] = {
        "limit": captured.get("limit"),
        "window_size": len(window),
        "three_in_window": THREE in window,
        "three_rank": (window.index(THREE) + 1) if THREE in window else None,
        "single_in_window": SINGLE in window,
        "three_selected": THREE in ids(inc),
        "selection_count": len(ids(inc)),
    }
    REPORT["D_incident_window"] = ms["D_incident_window"]

    print("DIAG_BEGIN")
    print(json.dumps(ms, ensure_ascii=False, indent=2, default=str))
    print("DIAG_END")
    pathlib.Path("/tmp/diagnostic-report.json").write_text(json.dumps(REPORT, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
