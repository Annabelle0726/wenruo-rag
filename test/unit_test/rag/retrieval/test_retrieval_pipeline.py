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
"""Pipeline wiring: which questions get decomposed, and what reaches the model.

The single-dimension case is the one that must not regress: it took one
retrieval call before the pipeline existed and must still take one.
"""

import pytest

from rag.retrieval import decomposition, pipeline

pytestmark = pytest.mark.p1


class _Store:
    def __init__(self, chunks):
        self.chunks = chunks
        self.questions = []

    async def retrieval(self, question, embd_mdl, tenant_ids, kb_ids, page, page_size, threshold, **kwargs):
        self.questions.append(question)
        return {"total": len(self.chunks), "chunks": [dict(c) for c in self.chunks], "doc_aggs": []}


def _chunk(chunk_id, similarity):
    return {"chunk_id": chunk_id, "content_with_weight": f"{chunk_id} 正文", "doc_id": "doc-1", "similarity": similarity}


@pytest.fixture
def llm(monkeypatch):
    """A scripted decomposition node that also records how often it was asked."""
    calls = []

    def _install(payload):
        async def _fake_gen_json(system_prompt, user_prompt, chat_mdl, gen_conf=None, max_retry=2):
            calls.append(user_prompt)
            return payload

        monkeypatch.setattr(decomposition, "gen_json", _fake_gen_json)
        return calls

    return _install


async def test_a_single_dimension_question_takes_one_route_and_no_llm_call(llm):
    calls = llm({"sub_queries": ["绝不该用到"]})
    store = _Store([_chunk("c1", 0.8)])

    result = await pipeline.retrieve_multi_route(
        retriever=store,
        question="标称厚度是多少",
        chat_mdl=object(),
        embd_mdl=object(),
        tenant_ids=["t-1"],
        kb_ids=["kb-1"],
    )

    assert store.questions == ["标称厚度是多少"]
    assert calls == [], "a single-dimension question must not pay for decomposition"
    assert [c["chunk_id"] for c in result["chunks"]] == ["c1"]


async def test_a_composite_question_adds_the_original_as_its_first_route(llm):
    llm({"sub_queries": ["绝缘标称厚度是多少", "交流电压试验要求是多少"]})
    store = _Store([_chunk("c1", 0.8)])
    question = "绝缘标称厚度和例行交流电压试验要求分别是什么"

    await pipeline.retrieve_multi_route(
        retriever=store,
        question=question,
        chat_mdl=object(),
        embd_mdl=object(),
        tenant_ids=["t-1"],
        kb_ids=["kb-1"],
    )

    assert store.questions == [
        question,
        "绝缘标称厚度是多少",
        "交流电压试验要求是多少",
        # The question asks how something is TESTED, so the deterministic
        # prose-tier route goes on the end (see the clause-route tests below).
        f"{question} {decomposition.CLAUSE_ROUTE_ANCHOR}",
    ]


async def test_a_failed_decomposition_still_answers_from_a_route(llm):
    """The clause route is deterministic: a dead LLM node must not lose it."""
    calls = llm(None)
    store = _Store([_chunk("c1", 0.8)])
    question = "绝缘标称厚度和例行交流电压试验要求分别是什么"

    result = await pipeline.retrieve_multi_route(
        retriever=store,
        question=question,
        chat_mdl=object(),
        embd_mdl=object(),
        tenant_ids=["t-1"],
        kb_ids=["kb-1"],
    )

    assert len(calls) == 1, "the LLM node was asked once and failed"
    assert store.questions == [question, f"{question} {decomposition.CLAUSE_ROUTE_ANCHOR}"]
    assert [c["chunk_id"] for c in result["chunks"]] == ["c1"]


async def test_the_reranker_receives_the_original_question_and_the_context_is_cut(llm):
    llm({"sub_queries": ["绝缘标称厚度是多少", "交流电压试验要求是多少"]})
    store = _Store([_chunk("a", 0.9), _chunk("b", 0.8), _chunk("c", 0.7)])

    class _Reranker:
        def __init__(self):
            self.queries = []

        def similarity(self, query, texts):
            import numpy as np

            self.queries.append(query)
            return np.asarray([0.1] * len(texts), dtype=float), 0

    reranker = _Reranker()
    question = "绝缘标称厚度和例行交流电压试验要求分别是什么"

    result = await pipeline.retrieve_multi_route(
        retriever=store,
        question=question,
        chat_mdl=object(),
        embd_mdl=object(),
        rerank_mdl=reranker,
        tenant_ids=["t-1"],
        kb_ids=["kb-1"],
        final_top_n=2,
    )

    assert reranker.queries == [question], "relevance is judged against what the user asked"
    assert len(result["chunks"]) == 2
    assert result["total"] >= 2


async def test_an_empty_question_never_touches_the_store(llm):
    llm({"sub_queries": ["x"]})
    store = _Store([_chunk("a", 0.9)])

    result = await pipeline.retrieve_multi_route(retriever=store, question="   ", chat_mdl=object(), tenant_ids=["t-1"], kb_ids=["kb-1"])

    assert result == {"total": 0, "chunks": [], "doc_aggs": []}
    assert store.questions == []


async def test_no_passages_means_an_empty_result_not_a_rerank(llm):
    llm({"sub_queries": ["绝缘标称厚度是多少"]})
    store = _Store([])

    result = await pipeline.retrieve_multi_route(
        retriever=store,
        question="绝缘标称厚度和例行交流电压试验要求分别是什么",
        chat_mdl=object(),
        embd_mdl=object(),
        tenant_ids=["t-1"],
        kb_ids=["kb-1"],
    )

    assert result == {"total": 0, "chunks": [], "doc_aggs": []}


async def test_a_comparative_question_searches_each_side_separately(llm):
    """One shared query cannot bring back the second document; a route per side can."""
    llm({"sub_queries": []})
    store = _Store([_chunk("c1", 0.8)])
    question = "400 mm²、630 mm² 与 1600 mm² 截面电缆在 20°C 时的导体最大直流电阻标准值分别是多少？单芯与三芯要求是否一致？"

    await pipeline.retrieve_multi_route(retriever=store, question=question, chat_mdl=object(), embd_mdl=object(), tenant_ids=["t-1"], kb_ids=["kb-1"])

    assert store.questions[0] == question, "the user's own question is still the first route"
    side_queries = [q for q in store.questions if q.startswith(("单芯 ", "三芯 "))]
    assert len(side_queries) == 2, f"one route per side, got {side_queries}"
    assert side_queries[0].startswith("单芯 ") and "1600" in side_queries[0]
    assert side_queries[1].startswith("三芯 ") and "1600" in side_queries[1]
    assert "三芯" not in side_queries[0] and "单芯" not in side_queries[1]


async def test_a_single_subject_question_gets_no_side_route(llm):
    llm({"sub_queries": []})
    store = _Store([_chunk("c1", 0.8)])

    await pipeline.retrieve_multi_route(retriever=store, question="三芯电缆的外径是多少", chat_mdl=object(), embd_mdl=object(), tenant_ids=["t-1"], kb_ids=["kb-1"])

    assert store.questions == ["三芯电缆的外径是多少"]
