"""P0-7 gate: exactly one structured operator event per retrieval, with an exact field set.

Runs the real candidate chain (pipeline -> multi_route -> Dealer.search) with the embedding provider and
doc store doubled, captures the `rag.retrieval.health_producers` logger, and asserts:

  1. exactly ONE operator line is emitted per retrieval, including when build() is called again;
  2. the payload contains EXACTLY the approved fields and nothing else;
  3. no prompt, chunk content, credential, provider body or stack trace can appear.

Exit 0 = PASS, 1 = FAIL.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, "/ragflow")

EXPECTED_FIELDS = {
    "event",
    "schema_version",
    "overall",
    "reason",
    "evidence_completeness",
    "legs",
    "contract_valid",
    "routes_attempted",
    "routes_succeeded",
}

MARKER = "[RetrievalHealth]"
LEAK_MARKERS = ["AQ.Ab8RN6", "api_key", "Authorization", "generativelanguage", "Traceback",
                "RESOURCE_EXHAUSTED", "FAILED_PRECONDITION", "content_with_weight", "三芯海缆"]


class FakeEmbedding:
    def __init__(self, dim: int = 3072) -> None:
        self.dim = dim
        self.calls = 0

    def encode_queries(self, text):
        import numpy as np

        self.calls += 1
        v = np.zeros(self.dim, dtype=float)
        v[0] = 1.0
        return v, 1


class FakeDataStore:
    def search(self, *a, **k):
        return {"hits": {"hits": [{"_id": "c1", "_score": 1.0, "_source": {
            "content_with_weight": "clause", "docnm_kwd": "d.pdf", "doc_id": "d1",
            "chunk_order_int": 0, "page_num_int": 1, "top_int": 0,
            "create_timestamp_flt": 1.0, "vector_similarity": 0.9,
            "term_similarity": 0.5, "row_id": "r1"}}], "total": {"value": 1}}}

    def get_total(self, r): return len(r["hits"]["hits"])
    def get_doc_ids(self, r): return [h["_id"] for h in r["hits"]["hits"]]
    def get_highlight(self, *a, **k): return {}
    def get_aggregation(self, *a, **k): return []
    def get_fields(self, r, f): return [dict(h["_source"], id=h["_id"]) for h in r["hits"]["hits"]]
    def get_scores(self, r): return [h["_score"] for h in r["hits"]["hits"]]
    def index_exist(self, *a, **k): return True


class StoreBackedRetriever:
    def __init__(self, dealer) -> None:
        self.dealer = dealer

    async def retrieval(self, question, embd_mdl, tenant_ids, kb_ids, page=1, page_size=8, similarity_threshold=0.2, **kwargs):
        req = dict(kwargs)
        req["question"] = question
        req["similarity"] = 0.1
        sres = await self.dealer.search(req, [f"ragflow_{t}" for t in tenant_ids], kb_ids, embd_mdl, None, rank_feature=None, min_match=False)
        chunks = []
        for i, cid in enumerate(sres.ids):
            fields = (sres.field or [{}])[i] if sres.field and i < len(sres.field) else {}
            chunks.append(dict(fields, id=cid, chunk_id=cid))
        return {"total": sres.total, "chunks": chunks, "doc_aggs": list(sres.aggregation or [])}


class Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(record.getMessage())
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    from common import settings

    settings.init_settings()
    import importlib

    rag_search = importlib.import_module("rag.nlp.search")
    health_bridge = importlib.import_module("rag.retrieval.health_bridge")
    producers = importlib.import_module("rag.retrieval.health_producers")
    pipeline = importlib.import_module("rag.retrieval.pipeline")

    capture = Capture()
    logger = logging.getLogger("rag.retrieval.health_producers")
    logger.addHandler(capture)
    logger.setLevel(logging.INFO)

    store = FakeDataStore()
    retriever = StoreBackedRetriever(rag_search.Dealer(store))
    embd = FakeEmbedding()

    async def run():
        health_bridge.begin_retrieval_health()
        result = await pipeline.retrieve_multi_route(
            retriever=retriever,
            question="220kV 三芯海缆的主要结构有哪些？",
            tenant_ids=["t"], kb_ids=["k"], chat_mdl=None, embd_mdl=embd,
            routes_top_k=12, final_top_n=8, knn_top_k=1024,
        )
        session = health_bridge.current_session()
        # A second aggregation on the same session must NOT produce a second operator line.
        session.build()
        session.build()
        return result, session

    result, session = asyncio.run(run())

    operator_lines = [ln for ln in capture.lines if ln.startswith(MARKER)]
    payload = {}
    if operator_lines:
        try:
            payload = json.loads(operator_lines[0][len(MARKER):].strip())
        except Exception as exc:  # noqa: BLE001
            payload = {"_parse_error": f"{type(exc).__name__}: {exc}"}

    all_text = json.dumps(capture.lines, ensure_ascii=False)
    leaks = [m for m in LEAK_MARKERS if m in all_text]
    other_lines = [ln for ln in capture.lines if not ln.startswith(MARKER)]

    checks = {
        "exactly_one_operator_event": len(operator_lines) == 1,
        "payload_is_json": "_parse_error" not in payload and bool(payload),
        "exact_field_set": set(payload.keys()) == EXPECTED_FIELDS,
        "no_extra_fields": set(payload.keys()) <= EXPECTED_FIELDS,
        "event_name_correct": payload.get("event") == "retrieval_health",
        "overall_present": payload.get("overall") in ("full", "degraded", "failed"),
        "legs_is_enum_map": isinstance(payload.get("legs"), dict)
        and all(v in ("success", "degraded", "failed", "skipped", "not_triggered", "unknown") for v in (payload.get("legs") or {}).values()),
        "contract_valid_is_bool": isinstance(payload.get("contract_valid"), bool),
        "routes_are_ints": isinstance(payload.get("routes_attempted"), int) and isinstance(payload.get("routes_succeeded"), int),
        "no_sensitive_markers": leaks == [],
        "no_unstructured_lines_from_logger": other_lines == [],
    }
    out = {
        "gate": "P0_7_OPERATOR_EVENT_GATE",
        "operator_lines": len(operator_lines),
        "payload": payload,
        "extra_logger_lines": other_lines,
        "leak_markers_found": leaks,
        "retrieval_overall": (result.get("retrieval_health") or {}).get("overall"),
        "checks": checks,
        "passed": all(checks.values()),
        "verdict": "PASS" if all(checks.values()) else "FAIL",
    }
    print("P07_GATE_BEGIN")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("P07_GATE_END")
    return 0 if out["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
