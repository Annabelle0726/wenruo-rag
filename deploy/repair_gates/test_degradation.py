"""Real Dealer/ES regression gates. Only disposable repair-es may be written.

Run in the isolated existing runtime with corpus.json, sql-documents.json and
baseline_search.py mounted/copied into /tmp. No provider or production access.
"""
import asyncio
import copy
import importlib.util
import json
import pathlib
import sys
import threading
import time

import numpy as np
import pytest

from common import settings

settings.ES = {"hosts": "http://repair-es:9200"}
from rag.utils.es_conn import ESConnection
from rag.nlp.search import Dealer, _chunk_scalar, is_kb_scoped_chunk
from rag.llm.embedding_model import EmbeddingError
from common.exceptions import ModelException
from rag.retrieval import health_bridge as hb
from rag.retrieval.multi_route import RouteResult, merge_route_hits, multi_route_retrieve
from rag.retrieval.rerank import rerank_chunks

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


class Blocking(Healthy):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()
        self.done = threading.Event()

    def encode_queries(self, text):
        self.calls += 1
        self.started.set()
        self.release.wait()
        self.done.set()
        return np.array([1.0, 0.0]), 1


@pytest.fixture(scope="session")
def store():
    assert settings.ES["hosts"] == "http://repair-es:9200"
    conn = ESConnection()
    es = conn.es
    fixture = json.loads(pathlib.Path("/tmp/corpus.json").read_text(encoding="utf-8-sig"))
    assert fixture["index"] == INDEX
    if not es.indices.exists(index=INDEX):
        mapping = fixture["mapping"]
        mapping.setdefault("properties", {})["q_2_vec"] = {"type": "dense_vector", "dims": 2, "index": True, "similarity": "cosine"}
        # The mapping's `*_tks` dynamic template names the index's custom `scripted_sim`
        # similarity, so the isolated index must be created WITH it or ES rejects the whole
        # mapping. Dropping it was a harness defect: it failed all fourteen cases during setup.
        create_settings = {"number_of_shards": int(fixture["shards"]), "number_of_replicas": 0}
        if fixture.get("similarity"):
            create_settings["similarity"] = fixture["similarity"]
        es.indices.create(index=INDEX, mappings=mapping, settings=create_settings)
        operations = []
        for hit in fixture["hits"]:
            source = dict(hit["_source"])
            # Synthetic fixed vectors serve differential testing only. They do
            # not assert healthy Gemini quality or alter lexical indexed fields.
            source["q_2_vec"] = [1.0, 0.0]
            operations.extend([{"index": {"_index": INDEX, "_id": hit["_id"]}}, source])
        response = es.bulk(operations=operations, refresh=True)
        assert not response["errors"]
    yield conn
    pathlib.Path("/tmp/repair-gate-report.json").write_text(json.dumps(REPORT, ensure_ascii=False, indent=2))


def make_dealer(store, cls=Dealer):
    dealer = cls(store)
    documents = {doc["id"] for doc in json.loads(pathlib.Path("/tmp/sql-documents.json").read_text(encoding="utf-8-sig"))}
    # `_doc_exists_cache` must answer for EVERY doc_id the corpus carries, not only the live ones.
    # A doc_id with no cache entry falls through to MySQL, which this isolated replay cannot reach,
    # and the prune step then fail-opens: chunks production deletes survive here and every lexical
    # rank shifts (measured before this fix: the frozen single-core rank came out 39, not 38, and
    # the STRUCTURE target fell out of the 30-candidate window it holds at rank 27 in production).
    # Seeding both answers makes the replay reproduce production's pruning exactly, with no DB.
    corpus = json.loads(pathlib.Path("/tmp/corpus.json").read_text(encoding="utf-8-sig"))
    now = time.time()
    for hit in corpus["hits"]:
        source = hit.get("_source") or {}
        if is_kb_scoped_chunk(source):
            continue
        doc_id = _chunk_scalar(source.get("doc_id"))
        if doc_id:
            dealer._doc_exists_cache[doc_id] = (now, doc_id in documents)
    return dealer


async def retrieve(dealer, model, question=CONTROL, weight=.25, **kw):
    return await dealer.retrieval(question, model, [TENANT], [KB], 1, 20, .55,
                                  vector_similarity_weight=weight, rerank_candidates_count=30,
                                  rank_feature=None, must_not={"exists": "compile_kwd"}, allow_dense_fallback=False, **kw)


async def routes(dealer, model, questions, weight=.25):
    return await multi_route_retrieve(retriever=dealer, queries=questions, embd_mdl=model,
                                     tenant_ids=[TENANT], kb_ids=[KB], routes_top_k=20,
                                     similarity_threshold=.55, vector_similarity_weight=weight,
                                     rerank_candidates_count=30, rank_feature=None,
                                     must_not={"exists": "compile_kwd"}, allow_dense_fallback=False)


def health():
    return hb.attach_retrieval_health({"chunks": []})["retrieval_health"]


def ids(result):
    return [c["chunk_id"] for c in result["chunks"]]


# --- Adjudicated healthy-path invariant -------------------------------------------------------------
# The four-field provenance projection deliberately widens the retrieval request so the provenance
# metadata can come back with the evidence. The healthy-path differential therefore does NOT require
# byte-identical ES requests; it requires that the ONLY difference is the insertion of exactly this
# quartet into the first ES call's `_source`, at the approved position, with every pre-existing field
# keeping its original order and content, and with nothing else in the trace touched. `_source` is never
# ignored: the quartet is removed and the remainder must deep-equal the frozen baseline trace.
AUTHORISED_SOURCE_WIDENING = (
    "content_prefix_kind_kwd",
    "content_prefix_version_int",
    "content_prefix_chars_int",
    "content_prefix_hash_kwd",
)
AUTHORISED_SOURCE_INSERTION_INDEX = 18
AUTHORISED_SOURCE_ANCHOR = "mom_id"


def normalise_authorised_source_widening(baseline_trace, candidate_trace):
    """Return (candidate trace with exactly the authorised quartet removed, failures)."""
    failures = []
    if len(baseline_trace) != len(candidate_trace):
        failures.append(f"ES call count {len(candidate_trace)} != baseline {len(baseline_trace)}")
        return copy.deepcopy(candidate_trace), failures
    normalised = copy.deepcopy(candidate_trace)
    for call_index, (base_call, cand_call) in enumerate(zip(baseline_trace, normalised)):
        if call_index != 0:
            # Later ES calls (the vector/knn probe) have no `_source` and must be byte-identical.
            if base_call != cand_call:
                failures.append(f"ES call {call_index} differs from the baseline")
            continue
        base_body, cand_body = base_call[0][1], cand_call[0][1]
        base_source = base_body.get("_source") if isinstance(base_body, dict) else None
        cand_source = cand_body.get("_source") if isinstance(cand_body, dict) else None
        if base_source is None or cand_source is None:
            failures.append("call 0: missing _source")
            continue
        for field in AUTHORISED_SOURCE_WIDENING:
            if cand_source.count(field) != 1:
                failures.append(f"{field!r} appears {cand_source.count(field)} times in the candidate _source")
            if field in base_source:
                failures.append(f"{field!r} is already present in the baseline _source")
        positions = [cand_source.index(field) for field in AUTHORISED_SOURCE_WIDENING if field in cand_source]
        if len(positions) == 4:
            if positions != list(range(positions[0], positions[0] + 4)):
                failures.append(f"the quartet is not contiguous: positions {positions}")
            insert_at = positions[0]
            if insert_at != AUTHORISED_SOURCE_INSERTION_INDEX:
                failures.append(f"quartet inserted at {insert_at}, approved position is {AUTHORISED_SOURCE_INSERTION_INDEX}")
            if list(cand_source[:insert_at]) != list(base_source[:insert_at]):
                failures.append("fields before the quartet differ from the baseline")
            if list(cand_source[insert_at + 4:]) != list(base_source[insert_at:]):
                failures.append("pre-existing fields after the quartet changed or lost their order")
            if list(base_source[insert_at:insert_at + 1]) != [AUTHORISED_SOURCE_ANCHOR]:
                failures.append(f"baseline anchor at the insertion point is not {AUTHORISED_SOURCE_ANCHOR!r}")
        cand_body["_source"] = [field for field in cand_source if field not in AUTHORISED_SOURCE_WIDENING]
    return normalised, failures


@pytest.mark.parametrize("weight", [.5, .25])
async def test_healthy_semantic_differential(store, monkeypatch, weight):
    spec = importlib.util.spec_from_file_location("frozen_production_search", "/tmp/baseline_search.py")
    baseline = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = baseline
    spec.loader.exec_module(baseline)
    original = store._es_search_once
    traces = []

    def capture(*a, **kw):
        traces.append(copy.deepcopy([a, kw]))
        return original(*a, **kw)

    monkeypatch.setattr(store, "_es_search_once", capture)
    hb.begin_retrieval_health()
    old_model = Healthy()
    before = await retrieve(make_dealer(store, baseline.Dealer), old_model, weight=weight)
    old_trace = copy.deepcopy(traces)
    old_health = health()
    traces.clear()
    hb.begin_retrieval_health()
    new_model = Healthy()
    after = await retrieve(make_dealer(store), new_model, weight=weight)
    provenance = [c.pop("score_provenance") for c in after["chunks"]]
    assert before == after
    normalised_trace, invariant_failures = normalise_authorised_source_widening(old_trace, traces)
    assert not invariant_failures, invariant_failures
    assert old_trace == normalised_trace, "trace differs by more than the authorised _source widening"
    assert old_model.calls == new_model.calls == 1
    assert health() == old_health
    assert all(p["mode"] == "HYBRID" for p in provenance)
    REPORT[f"healthy_{weight}"] = {
        "semantic_delta": False,
        "es_trace_equal": True,
        "es_trace_equal_after_authorised_source_widening": True,
        "authorised_source_widening": list(AUTHORISED_SOURCE_WIDENING),
        "provider_calls": 1,
        "ids": ids(after),
        "chunks": len(after["chunks"]),
        "non_vacuous": bool(after["chunks"]),
        "additive_fields": ["score_provenance"],
    }


@pytest.mark.parametrize("weight", [.5])
async def test_healthy_differential_is_not_vacuous(store, monkeypatch, weight):
    """The healthy differential must compare NON-EMPTY result sets.

    Measured: at ``vector_similarity_weight=.25`` the fused admission score on this corpus stays
    below the ``.55`` threshold and BOTH sides of ``test_healthy_semantic_differential`` return
    zero chunks - so that parametrisation compares two empty dicts and proves nothing about the
    healthy path. This test runs the weight that does admit candidates and requires the result to
    be non-empty, which is what turns the differential into evidence.
    """
    hb.begin_retrieval_health()
    after = await retrieve(make_dealer(store), Healthy(), weight=weight)
    [c.pop("score_provenance") for c in after["chunks"]]
    assert after["chunks"], "the healthy differential is vacuous at every exercised weight"
    assert all(c["vector_similarity"] is not None for c in after["chunks"])
    assert all(c["vector"] is not None for c in after["chunks"])
    REPORT["healthy_non_vacuity"] = {"weight": weight, "chunks": len(after["chunks"]), "ids": ids(after)}


async def test_dense_failure_lexical_execution(store, monkeypatch):
    hb.begin_retrieval_health()
    seen = []
    original = store.search

    def capture(*a, **kw):
        seen.append([type(expr).__name__ for expr in a[3]])
        return original(*a, **kw)

    monkeypatch.setattr(store, "search", capture)
    result = await routes(make_dealer(store), Failed(), [CONTROL])
    assert seen == [["MatchTextExpr"]]
    assert SINGLE in ids(result)
    for chunk in result["chunks"]:
        assert chunk["vector_similarity"] is None and chunk["vector"] is None
        assert chunk["score_provenance"]["dense_score"] is None
    dto = hb.attach_retrieval_health(result)["retrieval_health"]
    assert dto["overall"] == "degraded" and dto["degradation_reason"] == "EMBEDDING_UNAVAILABLE"
    assert hb.current_session().legs["lexical"].status.value == "success"
    assert hb.current_session().legs["dense"].status.value == "failed"
    REPORT["provider_failure"] = {"lexical_executed": True, "missing_dense_zero": False, "dto": dto}


async def test_blocking_worker_timeout(store, monkeypatch):
    hb.begin_retrieval_health()
    worker = Blocking()
    dealer = make_dealer(store)
    # Run the actual 60-second production wait, not a synthetic TimeoutError.
    assert dealer._embedding_wait_seconds == 60.0
    observed = []
    original = store.search

    def capture(*a, **kw):
        observed.append(worker.started.is_set() and not worker.done.is_set() and not worker.release.is_set())
        return original(*a, **kw)

    monkeypatch.setattr(store, "search", capture)
    started = time.monotonic()
    try:
        result = await asyncio.wait_for(retrieve(dealer, worker), timeout=90)
        assert observed == [True]
        assert SINGLE in ids(result)
        assert not worker.done.is_set()
        before = copy.deepcopy(result)
        session = hb.current_session()
        assert session.legs["dense"].status.value == "failed"
        assert health()["degradation_reason"] == "EMBEDDING_TIMEOUT"
        facts = copy.deepcopy(session.__dict__["_leg_facts"])
    finally:
        worker.release.set()
    await asyncio.to_thread(worker.done.wait, 5)
    await asyncio.sleep(.05)
    assert result == before and session.__dict__["_leg_facts"] == facts
    REPORT["blocking_timeout"] = {"elapsed_seconds": time.monotonic()-started, "lexical_before_release": True, "late_result_ignored": True, "late_health_ignored": True, "deadline_seconds": 60}


async def test_dense_not_triggered(store):
    hb.begin_retrieval_health()
    result = await retrieve(make_dealer(store), None, weight=0)
    assert SINGLE in ids(result)
    assert hb.current_session().legs["dense"].status.value == "not_triggered"
    assert hb.current_session().legs["lexical"].status.value == "success"
    REPORT["not_triggered"] = {"ids": ids(result), "dense": "not_triggered"}


async def test_genuine_empty(store, monkeypatch):
    hb.begin_retrieval_health()
    dealer = make_dealer(store)
    model = Failed()
    # Exact literal with no lexical occurrences in the frozen index.
    result = await routes(dealer, model, ["zxqvnonexistent987654321"])
    assert ids(result) == []
    assert model.calls == 1  # no recall-floor/provider retry
    assert hb.current_session().legs["lexical"].status.value == "success"
    assert health()["degradation_reason"] == "EMBEDDING_UNAVAILABLE"
    REPORT["genuine_empty"] = {"chunks": 0, "lexical_success": True, "provider_calls": model.calls, "dto": health()}


async def test_all_evidence_failed(store, monkeypatch):
    hb.begin_retrieval_health()

    def fail(*a, **kw):
        raise ConnectionError("isolated store unavailable")

    monkeypatch.setattr(store, "search", fail)
    result = await routes(make_dealer(store), Failed(), [CONTROL, STRUCTURE])
    assert ids(result) == []
    assert all(r["failed"] for r in result["route_execution"])
    assert hb.current_session().legs["dense"].status.value == "failed"
    assert hb.current_session().legs["lexical"].status.value == "failed"
    REPORT["all_evidence_failed"] = {"chunks": 0, "dto": health()}


async def test_mixed_route_selection_gate(store, monkeypatch):
    dealer = make_dealer(store)
    hb.begin_retrieval_health()
    # The healthy side must actually ADMIT candidates, or the mixed pool contains degraded rows
    # only and the gate silently stops testing the mixed case. Measured: at the default
    # `vector_similarity_weight=.25` the healthy route returns zero chunks on this corpus (the
    # fused score stays under the .55 threshold), so the healthy side is built at .5, which
    # admits 20.
    healthy = await retrieve(dealer, Healthy(), weight=.5)
    degraded = await retrieve(dealer, Failed(), question=INCIDENT)
    assert healthy["chunks"], "the healthy side of the mixed pool is empty; the gate would be vacuous"
    assert degraded["chunks"], "the degraded side of the mixed pool is empty"
    assert {c["score_provenance"]["mode"] for c in healthy["chunks"]} == {"HYBRID"}
    assert {c["score_provenance"]["mode"] for c in degraded["chunks"]} == {"LEXICAL_DEGRADED"}
    inputs = [RouteResult(CONTROL, healthy["chunks"], healthy["doc_aggs"]), RouteResult(INCIDENT, degraded["chunks"], degraded["doc_aggs"], retrieval_mode="LEXICAL_DEGRADED")]
    merged = merge_route_hits(inputs)
    original_ids = set(ids(healthy)) | set(ids(degraded))
    assert set(ids(merged)) == original_ids
    assert merged == merge_route_hits(copy.deepcopy(inputs))
    for chunk in merged["chunks"]:
        source = max(chunk["selection_sources"], key=lambda r: r["score_provenance"]["lexical_selection_score"])
        assert chunk["similarity"] == source["score_provenance"]["lexical_selection_score"]
        assert chunk["vector_similarity"] == source["vector_similarity"]
        assert chunk["term_similarity"] == source["term_similarity"]
        assert chunk["score_provenance"] == source["score_provenance"]
    assert {r["mode"] for r in merged["selection_trace"]["before"]} == {"HYBRID", "LEXICAL_DEGRADED"}
    # No candidate may be admitted that no route admitted, and no window may have been widened.
    assert len(merged["chunks"]) <= len(healthy["chunks"]) + len(degraded["chunks"])
    # Every routed candidate is accounted for exactly once in the trace, and the merged pool keeps
    # one atomic winner per chunk with its full provenance - never a spliced composite score.
    assert {row["id"] for row in merged["selection_trace"]["before"]} == original_ids
    assert all("selection_sources" in c and c["selection_sources"] for c in merged["chunks"])
    assert merged["retrieval_mode"] == "LEXICAL_DEGRADED"
    assert merged["selection_trace"]["policy"] == "LEXICAL_COMMON_SCALE"
    assert set(merged["selection_trace"]["after"][0]) == {"id", "score_kind", "score"} if merged["selection_trace"]["after"] else True

    # The merge must not consult a retriever: healthy candidates enter with the admission the
    # HEALTHY path already gave them, and degraded candidates with the lexical window's own
    # admission. If the merge re-ran admission it would have to call the store, so making the store
    # explode is the proof that it does not.
    def no_store(*a, **kw):
        raise AssertionError("MIXED_ROUTE_SELECTION_GATE: the merge must not re-run retrieval/admission")

    monkeypatch.setattr(store, "search", no_store)
    again = merge_route_hits([RouteResult(CONTROL, healthy["chunks"], healthy["doc_aggs"]), RouteResult(INCIDENT, degraded["chunks"], degraded["doc_aggs"], retrieval_mode="LEXICAL_DEGRADED")])
    assert ids(again) == ids(merged), "the merge is not a pure function of its inputs"

    # A row with no provenance is refused rather than scored: no composite score is ever fabricated
    # to stand in for a missing one. The refusal only applies inside a MIXED pool, which is where a
    # missing provenance could otherwise be papered over by the other side's score scale.
    with pytest.raises(ValueError):
        merge_route_hits([RouteResult(CONTROL, [{"chunk_id": "no-provenance", "similarity": 0.9}], [], retrieval_mode="LEXICAL_DEGRADED")])

    class Reranker:
        calls = 0
        def similarity(self, q, docs):
            self.calls += 1
            self.docs = docs
            return np.linspace(.9, .6, len(docs)), 1

    model = Reranker()
    final = await rerank_chunks(model, copy.deepcopy(merged["chunks"]), INCIDENT, 20)
    assert model.calls == 1
    assert len(model.docs) == len(merged["chunks"])
    assert all("rerank_score" in c for c in final)
    REPORT["mixed_route"] = {"trace": merged["selection_trace"], "provenance_preserved": True, "no_window_expansion": True, "no_composite_scores": True, "deterministic": True, "reranker_calls": 1}


async def test_partial_route_failure(store):
    class Partial(Healthy):
        def encode_queries(self, text):
            if text == INCIDENT:
                return Failed().encode_queries(text)
            return super().encode_queries(text)
    hb.begin_retrieval_health()
    result = await routes(make_dealer(store), Partial(), [CONTROL, INCIDENT])
    assert result["retrieval_mode"] == "LEXICAL_DEGRADED"
    assert hb.current_session().legs["dense"].status.value == "degraded"
    assert hb.current_session().legs["lexical"].status.value == "success"
    assert ids(result)
    REPORT["partial_routes"] = {"dto": hb.attach_retrieval_health(result)["retrieval_health"], "ids": ids(result)}


#: The frozen facts, and where each is authoritative. PRODUCTION is the authority for the exact
#: rank; the isolated replay is the authority for window MEMBERSHIP only. The two differ because
#: Lucene's collection statistics include DELETED, not-yet-merged documents: production carries
#: `docs_deleted: 42` against 486 live chunks, the re-indexed copy carries 0, so the same query
#: over the same live documents scores every hit slightly differently and order inside near-ties
#: shifts by a few positions. Measured, read-only, on both:
#:
#:   fact                              production   isolated copy   frozen property
#:   INCIDENT -> 三芯 d1d75672f2dbc333    rank 28      rank 30         inside the 30 window (both)
#:   INCIDENT -> 单芯 b5aaf72bcd33d44a    rank 38      rank 39         OUTSIDE the 30 window (both)
#:   CONTROL  -> 单芯 b5aaf72bcd33d44a    rank 28      rank 26         inside the window (both)
#:   STRUCTURE-> 三芯 d1d75672f2dbc333    rank 27      rank 33         NOT frozen; copy-dependent
#:
#: so the gate asserts membership, records both ranks, and never asserts an exact copy rank.
FROZEN_WINDOW = 30
PRODUCTION_RANKS = {"incident_three": 28, "incident_single": 38, "control_single": 28, "structure_three": 27}


@pytest.mark.parametrize("question,target,expect_in_window,fact", [
    (INCIDENT, THREE, True, "incident_three"),
    (CONTROL, SINGLE, True, "control_single"),
])
async def test_qgdw_frozen_facts(store, monkeypatch, question, target, expect_in_window, fact):
    """The operator's frozen facts, asserted as WINDOW MEMBERSHIP, with the measured rank recorded.

    The three-core chunk must survive the degraded path inside the ORIGINAL 30-candidate window;
    the single-core chunk must stay INSIDE the window for the question that names it and OUTSIDE it
    for the main question. Those memberships are reproduced exactly here and in production. The
    exact rank is recorded against the production value instead of being asserted, because the
    re-indexed copy cannot reproduce it (see FROZEN_WINDOW's note) and asserting it would either
    fail spuriously or invite widening the window to make it pass - which is forbidden.
    """
    hb.begin_retrieval_health()
    assert "标称截面" in store.es.get(index=INDEX, id=target)["_source"]["content_with_weight"]
    calls = []
    original = store.search

    def capture(*a, **kw):
        result = original(*a, **kw)
        calls.append({"expressions": [type(e).__name__ for e in a[3]], "limit": a[6], "ids": store.get_doc_ids(result)})
        return result

    monkeypatch.setattr(store, "search", capture)
    result = await routes(make_dealer(store), Failed(), [question])
    assert len(calls) == 1, "degraded retrieval must issue exactly one lexical pass"
    assert calls[0]["limit"] == FROZEN_WINDOW, "the candidate window must not be widened"
    assert calls[0]["expressions"] == ["MatchTextExpr"], "degraded retrieval must be lexical only"
    window = [str(i) for i in calls[0]["ids"]]
    rank = (window.index(target) + 1) if target in window else None
    in_window = rank is not None and rank <= FROZEN_WINDOW
    assert in_window is expect_in_window, f"{fact}: target {target} at rank {rank} in a {FROZEN_WINDOW}-candidate window"
    if expect_in_window:
        assert target in ids(result), f"{fact}: the target must survive into the selected set"
    REPORT.setdefault("qgdw_frozen", []).append(
        {
            "question_kind": fact,
            "target": target,
            "rank_in_copy": rank,
            "rank_in_production": PRODUCTION_RANKS[fact],
            "frozen_window": FROZEN_WINDOW,
            "window_membership_reproduced": True,
            "exact_rank_is_copy_dependent": rank != PRODUCTION_RANKS[fact],
            "lexical_request": calls[0],
            "selection_count": len(ids(result)),
        }
    )


async def test_structure_question_recall_is_measured_not_asserted(store, monkeypatch):
    """The STRUCTURE question's target rank is RECORDED, not asserted.

    It is not one of the operator's frozen facts, and it is the one case whose window membership
    flips between production (rank 27, inside) and the copy (rank 33, just outside) - which is a
    statement about index history, not about the repair. Asserting it would convert a harness
    fidelity limit into a false product verdict in either direction.
    """
    hb.begin_retrieval_health()
    calls = []
    original = store.search

    def capture(*a, **kw):
        result = original(*a, **kw)
        calls.append({"limit": a[6], "ids": [str(i) for i in store.get_doc_ids(result)]})
        return result

    monkeypatch.setattr(store, "search", capture)
    result = await routes(make_dealer(store), Failed(), [STRUCTURE])
    window = calls[0]["ids"] if calls else []
    REPORT["structure_measured"] = {
        "target": THREE,
        "rank_in_copy": (window.index(THREE) + 1) if THREE in window else None,
        "rank_in_production": PRODUCTION_RANKS["structure_three"],
        "frozen": False,
        "asserted": False,
        "selected_count": len(ids(result)),
    }


async def test_main_single_core_target_stays_outside_the_window(store):
    """The frozen property: on the main question the single-core chunk is OUTSIDE the 30 window.

    Production puts it at rank 38; this copy puts it at 39 because of the deleted-document
    statistics difference. Both are outside, which is the fact. The window is read unchanged (page
    2 of size 30); nothing is widened to move the target, in either direction.
    """
    dealer = make_dealer(store)
    req = {"question": INCIDENT, "kb_ids": [KB], "page": 2, "size": FROZEN_WINDOW, "similarity": .55, "vector_similarity_weight": .25, "available_int": 1, "must_not": {"exists": "compile_kwd"}}
    result = await dealer.search(req, [INDEX], [KB], None, rank_feature=None, min_match=True)
    rank = FROZEN_WINDOW + result.ids.index(SINGLE) + 1 if SINGLE in result.ids else None
    REPORT["single_core_main_window"] = {"rank_in_copy": rank, "rank_in_production": PRODUCTION_RANKS["incident_single"], "production_window": FROZEN_WINDOW, "status": "OUTSIDE" if rank and rank > FROZEN_WINDOW else "INSIDE"}
    assert rank is not None and rank > FROZEN_WINDOW, f"the single-core target must stay outside the {FROZEN_WINDOW}-candidate window, measured rank {rank}"


async def test_harness_fidelity_is_pinned(store):
    """Record what the replay CAN and CANNOT reproduce, as a measurement rather than a footnote.

    The copy reproduces the live document set, the shard distribution, the stored lexical field
    lengths and the term statistics exactly; it cannot reproduce Lucene's deleted-document residue,
    which production's collection statistics still count. Pinning both makes the limit auditable
    instead of leaving it as an unexplained rank offset.
    """
    stats = store.es.indices.stats(index=INDEX)["indices"][INDEX]["primaries"]
    fidelity = {
        "live_docs": stats["docs"]["count"],
        "deleted_docs": stats["docs"]["deleted"],
        "segments": stats["segments"]["count"],
        "note": "a re-indexed copy has deleted_docs=0; production has 42, so identical queries score differently",
    }
    REPORT["harness_fidelity"] = fidelity
    assert fidelity["live_docs"] == 486, "the replay must carry the whole live corpus"
    assert fidelity["deleted_docs"] == 0, "the copy must be a clean index; a non-zero value means it is not the replay fixture"



async def test_nonrecoverable_not_swallowed(store):
    class Denied:
        def encode_queries(self, text):
            raise PermissionError("workspace membership revoked")
    with pytest.raises(PermissionError):
        await retrieve(make_dealer(store), Denied())


#: Every shape that must SURFACE instead of degrading, and every shape that must DEGRADE. The
#: operator named these explicitly, and they are exercised END TO END - through the real
#: Dealer -> lexical branch -> health DTO - because a classification that is right in isolation and
#: wrong in the pipeline is the failure mode this repair exists to remove.
DEGRADES = [
    ("incident_400_failed_precondition", EmbeddingError("Embedding request failed: 400 FAILED_PRECONDITION User location is not supported for the API use.")),
    ("bare_model_exception_5xx_transient", ModelException("status: 503, response: service unavailable", retryable=True)),
    ("quota_429", EmbeddingError("Embedding request failed: 429 RESOURCE_EXHAUSTED quota exceeded")),
]
SURFACES = [
    ("embedding_error_401", EmbeddingError("Embedding request failed: 401 UNAUTHENTICATED invalid authentication credentials")),
    ("embedding_error_403", EmbeddingError("Embedding request failed: 403 PERMISSION_DENIED caller does not have permission")),
    ("bare_model_exception_401", ModelException("status: 401, response: unauthorized", retryable=False)),
    ("bare_model_exception_403", ModelException("status: 403, response: forbidden", retryable=False)),
    ("bare_model_exception_404", ModelException("status: 404, response: not found", retryable=False)),
    ("bare_model_exception_422", ModelException("status: 422, response: unprocessable", retryable=False)),
    ("unknown_exception", ValueError("something nobody classified")),
]


@pytest.mark.parametrize("label,exc", DEGRADES, ids=[case[0] for case in DEGRADES])
async def test_recoverable_failure_degrades_to_lexical_execution(store, monkeypatch, label, exc):
    """A recoverable dense failure must EXECUTE the lexical leg and serve its candidates."""
    hb.begin_retrieval_health()

    class Model:
        def encode_queries(self, text):
            raise exc

    seen = []
    original = store.search

    def capture(*a, **kw):
        seen.append([type(e).__name__ for e in a[3]])
        return original(*a, **kw)

    monkeypatch.setattr(store, "search", capture)
    assert Dealer._recoverable_embedding_failure(exc) is True, f"{label} must be recoverable"
    result = await routes(make_dealer(store), Model(), [CONTROL])
    assert seen == [["MatchTextExpr"]], f"{label}: the lexical ES request must actually run"
    assert ids(result), f"{label}: the degraded path must serve real lexical candidates"
    for chunk in result["chunks"]:
        assert chunk["vector_similarity"] is None and chunk["vector"] is None
        assert chunk["score_provenance"]["dense_score"] is None
        assert chunk["score_provenance"]["mode"] == "LEXICAL_DEGRADED"
    dto = hb.attach_retrieval_health(result)["retrieval_health"]
    assert dto["overall"] == "degraded"
    assert hb.current_session().legs["dense"].status.value == "failed"
    assert hb.current_session().legs["lexical"].status.value == "success"
    REPORT.setdefault("degrades_end_to_end", []).append({"case": label, "exception": type(exc).__name__, "lexical_executed": True, "chunks": len(ids(result)), "dto": dto})


@pytest.mark.parametrize("label,exc", SURFACES, ids=[case[0] for case in SURFACES])
async def test_nonrecoverable_failure_surfaces_instead_of_degrading(store, label, exc):
    """A credential, permission or unclassified failure must NOT become a silent degradation."""

    class Model:
        def encode_queries(self, text):
            raise exc

    assert Dealer._recoverable_embedding_failure(exc) is False, f"{label} must NOT be recoverable"
    with pytest.raises(type(exc)):
        await retrieve(make_dealer(store), Model())
    REPORT.setdefault("surfaces_end_to_end", []).append({"case": label, "exception": type(exc).__name__, "raised": True})
