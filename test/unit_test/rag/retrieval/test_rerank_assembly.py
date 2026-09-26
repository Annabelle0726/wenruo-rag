#
#  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
"""Module C: dedupe, rerank against the original question, cut the context.

A reranker is an ordering pass, never a gate: every path where the model is
missing, fails, or answers with the wrong number of scores must still hand the
answer model the pool the routes found. The one thing this stage must not do is
average the cross-encoder score with the fused score, because the fused score's
text leg is a recall ratio that penalizes a passage for every dimension of a
composite question it does not cover.
"""

import logging

import numpy as np
import pytest

from rag.retrieval import rerank

pytestmark = pytest.mark.p1


def _chunk(chunk_id, similarity, text="正文", doc_id="doc-1"):
    return {"chunk_id": chunk_id, "content_with_weight": text, "doc_id": doc_id, "similarity": similarity}


class _Reranker:
    """Scores by a script, or by a function of the document text."""

    def __init__(self, scores=None, scorer=None, error=None, drop_scores=0):
        self.scores = scores
        self.scorer = scorer
        self.error = error
        self.drop_scores = drop_scores
        self.queries = []
        self.documents = []

    def similarity(self, query, texts):
        self.queries.append(query)
        self.documents.append(list(texts))
        if self.error is not None:
            raise self.error
        if self.scorer is not None:
            values = [self.scorer(text) for text in texts]
        else:
            values = list(self.scores or [])
        if self.drop_scores:
            values = values[: len(values) - self.drop_scores]
        return np.asarray(values, dtype=float), 0


async def test_the_pool_is_ranked_by_the_reranker_and_cut_to_top_n():
    reranker = _Reranker(scores=[0.2, 0.9, 0.5])
    pool = [_chunk("a", 0.8), _chunk("b", 0.7), _chunk("c", 0.6)]

    kept = await rerank.rerank_chunks(reranker, pool, "绝缘标称厚度是多少", top_n=2)

    assert [c["chunk_id"] for c in kept] == ["b", "c"]
    assert [c["rerank_score"] for c in kept] == [0.9, 0.5]


async def test_the_reranker_scores_against_the_original_question():
    reranker = _Reranker(scores=[0.5])

    await rerank.rerank_chunks(reranker, [_chunk("a", 0.8)], "普通绝缘和轻型薄绝缘的厚度、绝缘电阻和电压试验有什么区别？")

    assert reranker.queries == ["普通绝缘和轻型薄绝缘的厚度、绝缘电阻和电压试验有什么区别？"]


async def test_the_natural_chunk_text_is_sent_to_the_reranker():
    """Tokenized ``content_ltks`` collapse a cross-encoder's scores."""
    reranker = _Reranker(scores=[0.5])

    await rerank.rerank_chunks(reranker, [_chunk("a", 0.8, text="5.3.3 绝缘标称厚度应不小于 1.2mm")], "标称厚度")

    assert reranker.documents == [["5.3.3 绝缘标称厚度应不小于 1.2mm"]]


async def test_the_rerank_score_replaces_the_fused_score():
    reranker = _Reranker(scores=[0.31])

    kept = await rerank.rerank_chunks(reranker, [_chunk("a", 0.78)], "q")

    assert kept[0]["similarity"] == pytest.approx(0.31)
    assert kept[0]["fused_similarity"] == pytest.approx(0.78)


async def test_duplicates_are_scored_once():
    reranker = _Reranker(scores=[0.5, 0.4])
    pool = [_chunk("a", 0.8), _chunk("a", 0.8), _chunk("b", 0.7)]

    kept = await rerank.rerank_chunks(reranker, pool, "q")

    assert reranker.documents[0] == ["正文", "正文"]
    assert len(kept) == 2


async def test_a_passage_without_an_id_is_kept():
    """De-duplication must not collapse passages it cannot identify."""
    reranker = _Reranker(scores=[0.5, 0.4])
    pool = [{"content_with_weight": "一段正文", "doc_id": "d1"}, {"content_with_weight": "另一段正文", "doc_id": "d2"}]

    kept = await rerank.rerank_chunks(reranker, pool, "q")

    assert len(kept) == 2


async def test_without_a_reranker_the_fused_order_is_kept():
    pool = [_chunk("low", 0.4), _chunk("high", 0.9)]

    kept = await rerank.rerank_chunks(None, pool, "q", top_n=1)

    assert [c["chunk_id"] for c in kept] == ["high"]
    assert "rerank_score" not in kept[0]


async def test_a_deployment_without_a_reranker_says_so_once_per_search(caplog):
    """Level 3 of the fallback must be visible in the transcript.

    `dialog_service.resolve_rerank_mdl` returns None when no reranker is
    configured anywhere; the cut stage then keeps the fused order. Without this
    line that is indistinguishable from a reranker that ran and agreed.
    """
    pool = [_chunk("low", 0.4), _chunk("high", 0.9)]

    with caplog.at_level(logging.WARNING):
        kept = await rerank.rerank_chunks(None, pool, "q", top_n=2)

    assert [c["chunk_id"] for c in kept] == ["high", "low"]
    assert "no rerank model" in caplog.text


async def test_a_failing_reranker_degrades_to_the_fused_order(caplog):
    pool = [_chunk("low", 0.4), _chunk("high", 0.9)]

    with caplog.at_level(logging.WARNING):
        kept = await rerank.rerank_chunks(_Reranker(error=RuntimeError("rerank endpoint down")), pool, "q")

    assert [c["chunk_id"] for c in kept] == ["high", "low"]
    assert "reranker failed" in caplog.text


async def test_a_score_count_mismatch_degrades_to_the_fused_order(caplog):
    pool = [_chunk("low", 0.4), _chunk("high", 0.9)]

    with caplog.at_level(logging.WARNING):
        kept = await rerank.rerank_chunks(_Reranker(scores=[0.1, 0.9], drop_scores=1), pool, "q")

    assert [c["chunk_id"] for c in kept] == ["high", "low"]
    assert "returned 1 score(s) for 2 candidate(s)" in caplog.text


async def test_textless_candidates_keep_the_fused_order():
    pool = [_chunk("a", 0.4, text=""), _chunk("b", 0.9, text="")]

    kept = await rerank.rerank_chunks(_Reranker(scores=[0.1, 0.2]), pool, "q")

    assert [c["chunk_id"] for c in kept] == ["b", "a"]


async def test_an_empty_pool_needs_no_rerank():
    reranker = _Reranker(scores=[])

    assert await rerank.rerank_chunks(reranker, [], "q") == []
    assert reranker.queries == []


def test_the_default_context_size_is_in_the_recommended_band():
    low, high = rerank.FINAL_TOP_N_RECOMMENDED
    assert low <= rerank.DEFAULT_FINAL_TOP_N <= high
    assert rerank.resolve_final_top_n(None) == rerank.DEFAULT_FINAL_TOP_N


def test_the_configured_context_size_wins():
    """The cable assistant configures 12 with a measured reason behind it."""
    assert rerank.resolve_final_top_n(12) == 12
    assert rerank.resolve_final_top_n(0) == rerank.DEFAULT_FINAL_TOP_N
    assert rerank.resolve_final_top_n("7") == 7


# ---------------------------------------------------------------------------
# The cut: every route is represented
# ---------------------------------------------------------------------------


def _routed(chunk_id, similarity, *routes):
    return dict(_chunk(chunk_id, similarity), retrieval_routes=list(routes))


def _keys(chunks):
    return [chunk["chunk_id"] for chunk in chunks]


def test_a_dominant_route_cannot_fill_every_slot():
    """Measured on the cable corpus, and the reason this pass exists.

    Twelve near-identical parameter tables of the dimension the question leads
    with scored 0.596-0.603 and filled all twelve slots; the `6.2.3 交流电压试验`
    clause the corpus does hold sat at 0.577 and was dropped.
    """
    thickness = [_routed(f"t{i}", 0.60 - i * 0.0001, "标称厚度有什么区别") for i in range(12)]
    voltage = [_routed("v1", 0.577, "交流电压试验有什么区别")]
    pool = thickness + voltage

    kept = _keys(rerank.ensure_route_coverage(pool, 12))

    assert "v1" in kept, kept
    assert len(kept) == 12
    # ... and the rest is still filled by score.
    assert kept[0] == "t0"


async def test_the_cut_keeps_the_best_passage_of_every_route_in_score_order():
    reranker = _Reranker(scores=[0.9, 0.88, 0.89, 0.2])
    pool = [
        _routed("t1", 0.5, "厚度"),
        _routed("t2", 0.5, "厚度"),
        _routed("v1", 0.5, "电压试验"),
        _routed("t3", 0.5, "厚度"),
    ]

    kept = _keys(await rerank.rerank_chunks(reranker, pool, "q", top_n=2))

    # t1 (0.90) keeps its slot and v1 (0.89) takes the one the flood would have.
    assert kept == ["t1", "v1"]


async def test_the_cut_without_a_reranker_also_reserves_a_slot_per_route():
    pool = [_routed(f"t{i}", 0.60 - i * 0.001, "厚度") for i in range(5)] + [_routed("v1", 0.577, "电压试验")]

    kept = _keys(await rerank.rerank_chunks(None, pool, "q", top_n=3))

    assert "v1" in kept
    assert kept == ["t0", "t1", "v1"]


def test_a_single_route_is_cut_the_ordinary_way():
    pool = [_routed(f"t{i}", 0.6 - i * 0.01, "厚度") for i in range(5)]

    assert _keys(rerank.ensure_route_coverage(pool, 3)) == ["t0", "t1", "t2"]


def test_a_pool_without_route_provenance_is_cut_the_ordinary_way():
    """Web-search passages and single-query callers carry no route."""
    pool = [_chunk(f"c{i}", 0.6 - i * 0.01) for i in range(5)]

    assert _keys(rerank.ensure_route_coverage(pool, 3)) == ["c0", "c1", "c2"]


def test_a_pool_that_fits_is_returned_whole():
    pool = [_routed("t1", 0.6, "厚度"), _routed("v1", 0.5, "电压")]

    assert _keys(rerank.ensure_route_coverage(pool, 5)) == ["t1", "v1"]


def test_the_routes_of_a_chunk_are_read_defensively():
    assert rerank.routes_of({"retrieval_routes": ["a", "b"]}) == ["a", "b"]
    assert rerank.routes_of({"retrieval_routes": "a"}) == []
    assert rerank.routes_of({}) == []
