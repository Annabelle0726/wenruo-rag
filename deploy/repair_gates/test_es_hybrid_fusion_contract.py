"""RED/GREEN gates for the ES healthy-hybrid fusion contract.

CONTRACT: for healthy ES hybrid candidate generation with configured vector weight w,
  lexical contribution weight = 1 - w,  vector contribution weight = w,
  and the emitted ES DSL must express BOTH explicitly (no reliance on the default kNN boost).

Three independent layers are gated, because fixing only one of them does not satisfy the contract:
  1. `Dealer.search` must BUILD the ES fusion expr from the request's `vector_similarity_weight`
     (the ES branch previously hardcoded "0.001,1").
  2. `ESConnection.search` must EMIT both boosts from that expr's two components
     (it previously read only component [1] and set `bool.boost = 1 - that`, leaving kNN at default).
  3. The BEHAVIOURAL consequence on an isolated ES corpus: changing w must change candidate ordering
     in the expected direction, not merely the serialized string.

Frozen paths are gated too: the second pure-KNN score-read call, and the pure-dense first search,
must not acquire a boost they do not have today.
"""
import asyncio
import json
import sys

sys.path.insert(0, "/ragflow")

import pytest

from common import settings

settings.init_settings()

from common.doc_store.doc_store_base import (  # noqa: E402
    FusionExpr,
    MatchDenseExpr,
    MatchTextExpr,
    OrderByExpr,
)
from rag.nlp.search import Dealer, build_fusion_expr  # noqa: E402
from rag.utils.es_conn import ESConnection  # noqa: E402

WEIGHTS = [0.0, 0.25, 0.5, 0.8, 1.0]
KNN_TOP_K = 30
FIELDS = ["content_ltks"]


class _CapturingStore:
    """Minimal doc-store double: records the match expressions Dealer.search builds."""

    def __init__(self):
        self.match_expressions = None
        self.condition = None
        self.limit = None

    def search(self, select_fields, highlight_fields, condition, match_expressions, order_by,
               offset, limit, index_names, kb_ids, **kwargs):
        self.match_expressions = match_expressions
        self.condition = condition
        self.limit = limit
        return {"hits": {"total": {"value": 1}, "hits": []}}

    def get_total(self, result):
        return 1

    def get_doc_ids(self, result):
        return ["chunk-1"]

    def get_fields(self, result, fields):
        return {"chunk-1": {"_score": 1.0, "content_ltks": "x", "content_with_weight": "x", "kb_id": "kb-1"}}

    def get_scores(self, result):
        return {"chunk-1": 0.5}

    def get_aggregation(self, result, *args, **kwargs):
        return []

    def get_highlight(self, result, fields):
        return {}


class _StubEmbedding:
    """Just enough of an embedding model for Dealer.search to build the dense leg."""

    def encode_queries(self, text):
        return [1.0, 0.0], 1


def _dealer_request(w):
    return {"question": "Q/GDW 73286 test question", "page": 1, "size": KNN_TOP_K,
            "similarity": 0.0, "vector": True, "knn_top_k": KNN_TOP_K,
            "vector_similarity_weight": w}


def _dealer_fusion_expr(w):
    store = _CapturingStore()
    dealer = Dealer(store)
    asyncio.run(dealer.search(_dealer_request(w), ["idx"], ["kb-1"], _StubEmbedding(), False))
    assert store.match_expressions, "no match expressions captured"
    fusions = [m for m in store.match_expressions if isinstance(m, FusionExpr)]
    assert len(fusions) == 1, (
        f"expected exactly one FusionExpr, got {len(fusions)}; expressions="
        f"{[type(m).__name__ for m in store.match_expressions]}")
    return fusions[0]


def capture_dsl(match_expressions, limit=KNN_TOP_K):
    """Run the REAL ES body builder and return the DSL it would send."""
    conn = ESConnection()
    captured = []

    def fake_once(index_names, query, track_total_hits):
        captured.append(query)
        return {"timed_out": False, "hits": {"total": {"value": 0}, "hits": []}}

    conn._es_search_once = fake_once
    conn.search(select_fields=["content_with_weight"], highlight_fields=[], condition={},
                match_expressions=match_expressions, order_by=OrderByExpr(), offset=0,
                limit=limit, index_names=["idx"], knowledgebase_ids=["kb-1"])
    assert captured, "no ES body captured"
    return captured[0]


# =============================================================================================
# 1. Dealer.search must build the ES fusion expr from the configured weight
# =============================================================================================
@pytest.mark.parametrize("w", WEIGHTS)
def test_es_branch_fusion_weights_follow_the_configured_weight(w):
    expr = _dealer_fusion_expr(w)
    expected = f"{1 - w:g},{w:g}"
    assert expr.method == "weighted_sum"
    assert expr.fusion_params["weights"] == expected, (
        f"ES healthy path built fusion weights {expr.fusion_params['weights']!r} for "
        f"vector_similarity_weight={w}; contract requires {expected!r}")


# =============================================================================================
# 2. The emitted ES DSL must express BOTH contributions explicitly
# =============================================================================================
@pytest.mark.parametrize("w", WEIGHTS)
def test_es_dsl_explicit_lexical_and_knn_boost(w):
    exprs = [MatchTextExpr(FIELDS, "Q/GDW 73286 test question", KNN_TOP_K,
                           {"minimum_should_match": 0.3}),
             MatchDenseExpr("q_2_vec", [1.0, 0.0], "float", "cosine", KNN_TOP_K, {"similarity": 0.0}),
             build_fusion_expr(KNN_TOP_K, w)]
    body = capture_dsl(exprs)
    bool_boost = body["query"]["bool"].get("boost")
    knn_boost = body.get("knn", {}).get("boost")
    assert bool_boost == pytest.approx(1 - w), (
        f"lexical boost {bool_boost!r} != 1-w = {1 - w} for w={w}")
    assert knn_boost is not None, f"kNN boost not emitted for w={w}: relying on the ES default"
    assert knn_boost == pytest.approx(w), f"kNN boost {knn_boost!r} != w = {w} for w={w}"


# =============================================================================================
# 3. Frozen paths must NOT acquire a boost
# =============================================================================================
def _lexical_clauses(body):
    """The `query_string` clauses the bool actually carries (a filter-only bool has none)."""
    must = (body.get("query") or {}).get("bool", {}).get("must") or []
    return [m for m in must if isinstance(m, dict) and "query_string" in m]


def test_second_pure_knn_score_read_carries_no_fusion_boost():
    """The second KNN-only score-read passes a single MatchDenseExpr and no FusionExpr."""
    dense = MatchDenseExpr("q_2_vec", [1.0, 0.0], "float", "cosine", 10, {"similarity": 0.0})
    body = capture_dsl([dense], limit=10)
    assert "knn" in body
    assert "boost" not in body["knn"], "pure-KNN score read must keep the default kNN boost"
    assert not _lexical_clauses(body), "pure-KNN score read must carry no lexical clause"


def test_pure_dense_first_search_carries_no_fusion_boost():
    """A dense-only first search (no matchText) also passes no FusionExpr."""
    dense = MatchDenseExpr("q_2_vec", [1.0, 0.0], "float", "cosine", KNN_TOP_K, {"similarity": 0.0})
    body = capture_dsl([dense])
    assert "boost" not in body["knn"]


def test_lexical_only_request_keeps_todays_default_boost():
    """A lexical-only request (no dense expr, therefore no FusionExpr) must keep TODAY'S behaviour.

    With no fusion expr to read a weight from, `es_conn` falls back to its local default 0.5 and sets
    `bool.boost = 1 - 0.5`. That is a uniform constant factor on a lexical-only ranking, so it does not
    reorder anything; it is frozen behaviour and this gate pins it so the contract change cannot leak
    into the lexical-only path.
    """
    text = MatchTextExpr(FIELDS, "q", KNN_TOP_K, {"minimum_should_match": 0.0})
    body = capture_dsl([text])
    assert "knn" not in body
    assert body["query"]["bool"]["boost"] == pytest.approx(0.5), (
        "lexical-only path must keep its existing default boost")


# =============================================================================================
# 4. Frozen DSL invariants
# =============================================================================================
def test_frozen_dsl_invariants_unchanged():
    exprs = [MatchTextExpr(FIELDS, "Q/GDW 73286 test question", KNN_TOP_K,
                           {"minimum_should_match": 0.3}),
             MatchDenseExpr("q_2_vec", [1.0, 0.0], "float", "cosine", KNN_TOP_K, {"similarity": 0.0}),
             build_fusion_expr(KNN_TOP_K, 0.5)]
    body = capture_dsl(exprs, limit=KNN_TOP_K)
    qs = body["query"]["bool"]["must"][0]["query_string"]
    assert qs["fields"] == FIELDS, "query fields changed"
    assert qs["type"] == "best_fields", "query_string type changed"
    assert qs["minimum_should_match"] == "30%", "minimum_should_match changed"
    assert qs["boost"] == 1, "per-clause lexical boost changed"
    filters = body["query"]["bool"]["filter"]
    assert {"terms": {"kb_id": ["kb-1"]}} in filters, "document scope filter changed"
    assert body["knn"]["field"] == "q_2_vec"
    assert body["knn"]["k"] == KNN_TOP_K, "k changed"
    assert body["knn"]["num_candidates"] == min(KNN_TOP_K * 2, 10000), "num_candidates changed"
    assert body["knn"]["similarity"] == 0.0, "similarity threshold changed"
    assert body["knn"]["filter"] == body["query"], "kNN filter must stay the same bool query"
    assert body["size"] == KNN_TOP_K, "size changed"
    assert body["_source"] == ["content_with_weight"], "source projection changed"


def test_fusion_expr_helper_keeps_its_declared_semantics():
    """`build_fusion_expr` is the reference for the contract and must stay 1-w, w."""
    for w, expected in ((0.0, "1,0"), (0.3, "0.7,0.3"), (0.5, "0.5,0.5"), (1.0, "0,1")):
        assert build_fusion_expr(10, w).fusion_params["weights"] == expected


# =============================================================================================
# 5. Behavioural corpus gate - ordering must actually change with w
# =============================================================================================
INDEX = "es_hybrid_fusion_contract"
KB = "kb-es-hybrid-fusion"
MAPPING = {"properties": {
    "content_ltks": {"type": "text"},
    "content_with_weight": {"type": "text"},
    "kb_id": {"type": "keyword"},
    "doc_id": {"type": "keyword"},
    "q_2_vec": {"type": "dense_vector", "dims": 2, "index": True, "similarity": "cosine"},
}}

# A: lexical-strong / vector-weak   B: vector-strong / lexical-weak   C: both strong
# B still matches some query terms so it survives the lexical `must` clause as a candidate.
LEX_A = "alpha beta gamma delta epsilon zeta conductor nominal section"
LEX_B = "alpha beta zeta filler unrelated words"
CORPUS = {
    "A": {"content_ltks": LEX_A, "q_2_vec": [0.0, 1.0]},     # cosine 0.5 against [1, 0]
    "B": {"content_ltks": LEX_B, "q_2_vec": [1.0, 0.0]},     # cosine 1.0
    "C": {"content_ltks": LEX_A, "q_2_vec": [1.0, 0.0]},     # both strong
}
QUERY_TEXT = "alpha beta gamma delta epsilon zeta conductor nominal section"
QUERY_VECTOR = [1.0, 0.0]


def _es():
    return ESConnection()


def _build_corpus(conn):
    from common import settings as s
    client = conn.es
    if client.indices.exists(index=INDEX):
        client.indices.delete(index=INDEX)
    client.indices.create(index=INDEX, mappings=MAPPING)
    for name, src in CORPUS.items():
        client.index(index=INDEX, id=name,
                     document={**src, "kb_id": KB, "doc_id": name,
                               "content_with_weight": src["content_ltks"]}, refresh=True)
    return client


def _build_body(w, knn=True):
    exprs = [MatchTextExpr(["content_ltks"], QUERY_TEXT, 10, {"minimum_should_match": 0.0})]
    if knn:
        exprs.append(MatchDenseExpr("q_2_vec", QUERY_VECTOR, "float", "cosine", 10, {"similarity": 0.0}))
        exprs.append(build_fusion_expr(10, w))
    conn = ESConnection()
    captured = []

    def fake_once(index_names, query, track_total_hits):
        captured.append(query)
        return {"timed_out": False, "hits": {"total": {"value": 0}, "hits": []}}

    conn._es_search_once = fake_once
    conn.search(select_fields=[], highlight_fields=[], condition={"kb_id": [KB]},
                match_expressions=exprs, order_by=OrderByExpr(), offset=0, limit=10,
                index_names=[INDEX], knowledgebase_ids=[KB])
    return captured[0]


def _run(client, body):
    res = client.search(index=INDEX, body={k: v for k, v in body.items() if k in ("query", "knn", "size")})
    hits = res["hits"]["hits"]
    return [h["_id"] for h in hits], {h["_id"]: round(float(h["_score"]), 6) for h in hits}


def _component_scores(client):
    """Raw BM25 (lexical clause at boost 1) and raw cosine (kNN at its default boost), per passage."""
    lex_body = _build_body(0.0, knn=False)
    lex_body["query"]["bool"]["boost"] = 1.0
    lex_body.pop("from", None)
    bm25 = _run(client, lex_body)[1]
    dense_body = {"knn": {"field": "q_2_vec", "k": 10, "num_candidates": 20,
                          "query_vector": QUERY_VECTOR, "similarity": 0.0}, "size": 10}
    cos = _run(client, dense_body)[1]
    return bm25, cos


def test_behavioural_corpus_scoring_implements_the_weight():
    """ES scores the hybrid as `(1-w) x BM25 + w x cosine`; the pre-fix DSL made that 0 x BM25 + 1 x cosine."""
    conn = _es()
    client = _build_corpus(conn)
    try:
        bm25, cos = _component_scores(client)
        print("raw BM25      ", bm25)
        print("raw cosine    ", cos)
        assert bm25["A"] != bm25["B"], "fixture precondition: A must be lexically stronger than B"
        assert cos["B"] > cos["A"], "fixture precondition: B must be vector-closer than A"

        for w in (0.0, 0.25, 0.5, 0.8, 1.0):
            order, scores = _run(client, _build_body(w))
            print(f"w={w:<4} order {order} scores {scores}")
            for cid in CORPUS:
                expected = (1 - w) * bm25[cid] + w * cos[cid]
                assert scores[cid] == pytest.approx(expected, rel=1e-6, abs=1e-6), (
                    f"w={w}: passage {cid} scored {scores[cid]} but "
                    f"(1-w)xBM25 + wxcosine = {expected:.6f}")

        order_lex = _run(client, _build_body(0.0))[0]
        order_dense = _run(client, _build_body(1.0))[0]
        assert order_lex.index("A") < order_lex.index("B"), (
            f"at w=0 (lexical only) the lexical-strong passage must outrank the lexical-weak one: {order_lex}")
        assert order_dense.index("B") < order_dense.index("A"), (
            f"at w=1 (vector only) the vector-strong passage must outrank the vector-weak one: {order_dense}")
        assert order_lex != order_dense, "changing w must change the ordering, not only the DSL string"
    finally:
        client.indices.delete(index=INDEX, ignore_unavailable=True)
