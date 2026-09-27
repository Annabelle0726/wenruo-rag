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
"""The harness search tool must run the multi-route pipeline, not one query.

This is the seam the Web UI actually reaches: a chat turn with reasoning on runs
the agentic graph, and its low/naive path is ``formalize -> direct_search ->
answer``, where ``direct_search`` calls ``hybrid_search`` with the user's
question. Whatever this function does IS what the product does.

Before the change it was one ``Dealer.retrieval`` call with one query string, so
a question asking for several parameters at once was scored as a query-recall
ratio and came back empty (the reported 未查到相关信息) even though the corpus held
both chapters. These tests pin the new behaviour at that seam: the composite
question is decomposed before it is searched, chapter 5 AND chapter 6 reach the
pool, an already-atomic query still costs exactly one retrieval and no LLM call,
and ``top_n`` keeps meaning "passages this search returns".
"""

import numpy as np
import pytest

from rag.advanced_rag.harness.tools import search as search_tools
from rag.retrieval import decomposition

pytestmark = pytest.mark.p1

#: Every passage covers exactly one of these, which is what makes the
#: query-recall ratio decisive on a composite question.
_TERMS = ("标称厚度", "绝缘电阻", "交流电压试验", "外护套", "铠装", "燃烧性能")

_QUESTION = "同时对比绝缘标称厚度、绝缘电阻、交流电压试验、外护套材料、铠装类型和燃烧性能的区别？"

_SUB_QUERIES = [
    "第5章 5.3.3 绝缘标称厚度是多少",
    "绝缘电阻的要求是多少",
    "第6章 6.2 例行交流电压试验要求是什么",
]

_CORPUS = [
    {"chunk_id": "ch5-1", "doc_id": "doc-standard", "docnm_kwd": "standard.pdf", "content_with_weight": "5.3.3 普通绝缘和轻型薄绝缘的绝缘标称厚度应不小于 1.2mm。"},
    {"chunk_id": "ch5-2", "doc_id": "doc-standard", "docnm_kwd": "standard.pdf", "content_with_weight": "5.4.2 例行试验中绝缘电阻应不小于 100MΩ·km。"},
    {"chunk_id": "ch6-1", "doc_id": "doc-standard", "docnm_kwd": "standard.pdf", "content_with_weight": "6.2 例行交流电压试验：施加 3.5kV 电压 5min 不击穿。"},
    {"chunk_id": "ch5-9", "doc_id": "doc-other", "docnm_kwd": "other.pdf", "content_with_weight": "5.1 外护套应采用阻燃聚氯乙烯材料。"},
]


class _DilutingStore:
    """Doc store whose fused score is a query-recall ratio (as ``Qryr`` computes)."""

    def __init__(self, extra=None):
        self.corpus = _CORPUS + list(extra or [])
        self.questions = []
        self.page_sizes = []
        self.kwargs_seen = []

    async def retrieval(self, question, embd_mdl, tenant_ids, kb_ids, page, page_size, threshold, **kwargs):
        self.questions.append(question)
        self.page_sizes.append(page_size)
        self.kwargs_seen.append(kwargs)
        query_terms = [term for term in _TERMS if term in question]
        scored = []
        for chunk in self.corpus:
            matched = [term for term in query_terms if term in chunk["content_with_weight"]]
            if not query_terms:
                continue
            score = len(matched) / len(query_terms)
            if score < threshold:
                continue
            scored.append(dict(chunk, similarity=score))
        scored.sort(key=lambda chunk: chunk["similarity"], reverse=True)
        return {"total": len(scored), "chunks": scored[:page_size], "doc_aggs": [{"doc_id": "doc-standard", "doc_name": "standard.pdf", "count": len(scored)}]}

    @staticmethod
    def retrieval_by_children(chunks, _tenant_ids):
        return chunks


class _Tools:
    """Stand-in for RAGTools: only what the search tools read."""

    def __init__(self, **settings):
        self.kb_ids = ["kb-1"]
        self.sql_kbs = []
        self.tenant_ids = ["t-1"]
        self.embed_mdl = object()
        self.chat_mdl = object()
        self.search_cache = None
        for name, value in settings.items():
            setattr(self, name, value)


class _Reranker:
    _SCORES = {"标称厚度": 0.93, "绝缘电阻": 0.88, "交流电压试验": 0.91}

    def __init__(self):
        self.queries = []

    def similarity(self, query, texts):
        self.queries.append(query)
        return np.asarray([next((score for term, score in self._SCORES.items() if term in text), 0.2) for text in texts], dtype=float), 0


@pytest.fixture
def store(monkeypatch):
    rec = _DilutingStore()
    monkeypatch.setattr(search_tools.settings, "retriever", rec)
    return rec


@pytest.fixture
def decomposition_node(monkeypatch):
    """Script the LLM node and count how often the search asked for it."""
    calls = []

    async def _fake_gen_json(system_prompt, user_prompt, chat_mdl, gen_conf=None, max_retry=2):
        calls.append(user_prompt)
        return {"sub_queries": list(_SUB_QUERIES)}

    monkeypatch.setattr(decomposition, "gen_json", _fake_gen_json)
    return calls


async def test_the_composite_question_is_searched_once_per_sub_query(store, decomposition_node):
    await search_tools.hybrid_search(_Tools(similarity_threshold=0.55, top_n=12), query=_QUESTION)

    # Route 0 is the original question, searched at the configured threshold and
    # then once more at the recall floor because it matched nothing; the three
    # sub-queries follow, with their chapter references already stripped.
    assert store.questions == [
        _QUESTION,
        _QUESTION,
        "绝缘标称厚度是多少",
        "绝缘电阻的要求是多少",
        "例行交流电压试验要求是什么",
    ]
    assert len(decomposition_node) == 1, "one decomposition call, not one per route"


async def test_chapter_5_and_chapter_6_both_reach_the_search_result(store, decomposition_node):
    res = await search_tools.hybrid_search(_Tools(similarity_threshold=0.55, top_n=12), query=_QUESTION)

    ids = {c["chunk_id"] for c in res["chunks"]}
    assert {"ch5-1", "ch5-2", "ch6-1"} <= ids, ids


async def test_one_query_used_to_return_nothing(store, decomposition_node):
    """The reported symptom, reproduced against the same doc store."""
    legacy = await store.retrieval(_QUESTION, object(), ["t-1"], ["kb-1"], 1, 12, 0.55, vector_similarity_weight=0.5)

    assert legacy["chunks"] == []


async def test_an_atomic_query_still_costs_one_retrieval_and_no_llm_call(store, decomposition_node):
    """Agentic modes already decomposed the question; their sub-queries are atomic."""
    await search_tools.hybrid_search(_Tools(similarity_threshold=0.55), query="绝缘标称厚度是多少")

    assert store.questions == ["绝缘标称厚度是多少"]
    assert decomposition_node == []


async def test_top_n_still_caps_what_the_search_returns(store, decomposition_node):
    res = await search_tools.hybrid_search(_Tools(similarity_threshold=0.55), query=_QUESTION, top_n=2)

    assert len(res["chunks"]) == 2
    # `top_n` is the TOOL's answer size, not the recall window: the query router owns the
    # window (it widens it for a question shape that leans on exact tokens - this one does,
    # to 20), and every route is given the same one. A widened window only means the cut
    # had more to choose from; it may never change what the caller asked to receive.
    assert len(set(store.page_sizes)) == 1, "every route gets the same window"
    assert min(store.page_sizes) >= 2, "the window can never be narrower than the answer"


async def test_the_caller_threshold_and_compile_filter_reach_every_route(store, decomposition_node):
    await search_tools.hybrid_search(_Tools(similarity_threshold=0.55, vector_similarity_weight=0.5), query=_QUESTION)

    assert set(store.kwargs_seen[0]) >= {"vector_similarity_weight", "knn_top_k", "doc_ids", "rerank_candidates_count"}
    for kwargs in store.kwargs_seen:
        assert kwargs["must_not"] == {"exists": "compile_kwd"}
        assert kwargs["allow_dense_fallback"] is False


async def test_a_callers_rerank_model_is_used_when_the_tools_carry_one(store, decomposition_node):
    """Module C is plumbed through: the agentic path has no reranker, an agent
    component that has one gets it without touching the search tool."""
    reranker = _Reranker()

    res = await search_tools.hybrid_search(_Tools(similarity_threshold=0.55, top_n=3, rerank_mdl=reranker), query=_QUESTION)

    assert reranker.queries == [_QUESTION], "the union is scored against the user's question"
    assert [c["chunk_id"] for c in res["chunks"]] == ["ch5-1", "ch6-1", "ch5-2"]


# ---------------------------------------------------------------------------
# Table dominance, through the same seam the Web UI reaches
# ---------------------------------------------------------------------------

_CLAUSE_QUESTION = "Q/GDW 73237 例行交流电压试验的维持时间是多少"

#: A 专用技术规范's bidder fill-in table: every parameter name and unit the
#: question uses, no rule.
_TABLE = {
    "chunk_id": "part2-table",
    "doc_id": "doc-part2",
    "docnm_kwd": "73237.2-2026 专用技术规范.pdf",
    "doc_type_kwd": "table",
    "content_with_weight": "技术参数特性表：标称厚度 mm / 绝缘电阻 MΩ / 交流电压试验 kV / 维持时间 min",
}

#: The clause that answers it, in the 通用技术规范.
_CLAUSE = {
    "chunk_id": "part1-clause",
    "doc_id": "doc-part1",
    "docnm_kwd": "73237.1-2026 通用技术规范.pdf",
    "doc_type_kwd": "text",
    "content_with_weight": "6.2.3 例行交流电压试验应施加 3.5kV 电压并维持 5min。",
}


class _TableHeavyStore:
    """The measured corpus shape: the fill-in table out-scores the clause."""

    def __init__(self):
        self.questions = []

    async def retrieval(self, question, embd_mdl, tenant_ids, kb_ids, page, page_size, threshold, **kwargs):
        self.questions.append(question)
        chunks = [
            dict(_TABLE, similarity=0.60),
            dict(_CLAUSE, similarity=0.58),
        ]
        return {"total": len(chunks), "chunks": chunks, "doc_aggs": []}

    @staticmethod
    def retrieval_by_children(chunks, _tenant_ids):
        return chunks


async def test_a_clause_question_searches_the_prose_tier(monkeypatch, decomposition_node):
    store = _TableHeavyStore()
    monkeypatch.setattr(search_tools.settings, "retriever", store)

    res = await search_tools.hybrid_search(_Tools(similarity_threshold=0.55), query=_CLAUSE_QUESTION, top_n=1)

    assert _CLAUSE_QUESTION in store.questions
    assert f"{_CLAUSE_QUESTION} {decomposition.CLAUSE_ROUTE_ANCHOR}" in store.questions, "the prose tier is searched deterministically"
    assert [c["chunk_id"] for c in res["chunks"]] == ["part1-clause"], "the clause beats the table it lost to"


async def test_a_value_question_takes_no_prose_tier_route(monkeypatch, decomposition_node):
    store = _TableHeavyStore()
    monkeypatch.setattr(search_tools.settings, "retriever", store)

    await search_tools.hybrid_search(_Tools(similarity_threshold=0.55), query="绝缘标称厚度是多少")

    assert store.questions == ["绝缘标称厚度是多少"]
