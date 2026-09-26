#
#  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
#  Modifications Copyright 2026 线缆工业智搜平台. All Rights Reserved.
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
"""The dynamic query router: which shape a question has, and what it overrides.

Two things are checked here. The classification itself (a model/number/table
question is not a concept question), and the isolation the feature promises: the
overrides reach the retrieval legs of THIS request and nothing else - no stored
configuration is read or written, and a question that matches no rule is handed the
caller's own settings untouched.
"""

import pytest

from rag.retrieval import pipeline, query_router

pytestmark = pytest.mark.p1


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        # numeric / model / table: a literal token decides the answer
        ("WDZC-YJY-0.6/1kV 电缆的绝缘厚度是多少", query_router.NUMERIC),
        ("3×25mm² 铜芯的载流量是多少", query_router.NUMERIC),
        ("3x25 的导体直流电阻是多少", query_router.NUMERIC),
        ("表3 中偏心度的允许偏差是多少", query_router.NUMERIC),
        ("附录表A.2 列了哪些参数值", query_router.NUMERIC),
        ("绝缘标称厚度是多少", query_router.NUMERIC),
        ("电缆外径 12.5mm 是允许的吗", query_router.NUMERIC),
        ("2.5mm2 绝缘电阻是多少", query_router.NUMERIC),
        # revision / edition / clause comparison: balanced
        ("第2部分与第1部分的差异对比", query_router.REVISION),
        ("2026年版与2016年版有什么区别", query_router.REVISION),
        ("该标准的历次修订有哪些", query_router.REVISION),
        ("新版本替代了哪些条款", query_router.REVISION),
        # conceptual / macro
        ("交联聚乙烯和聚氯乙烯绝缘的异同", query_router.CONCEPTUAL),
        ("为什么电缆要采用交联聚乙烯绝缘", query_router.CONCEPTUAL),
        ("两种绝缘材料的优缺点是什么", query_router.CONCEPTUAL),
        ("电缆选型原则有哪些", query_router.CONCEPTUAL),
        # no rule: the assistant's own configuration applies
        ("抽检的基本流程是什么", query_router.PASS_THROUGH),
        ("现场抽样要注意什么", query_router.PASS_THROUGH),
        ("", query_router.PASS_THROUGH),
        ("   ", query_router.PASS_THROUGH),
    ],
)
def test_question_shape_selects_the_route(question, expected):
    assert query_router.route_question(question).name == expected


def test_route_parameters_match_the_published_table():
    """The four shapes' weights and windows, as specified."""
    numeric = query_router.route_question("3×25mm² 的载流量")
    assert (numeric.vector_similarity_weight, numeric.routes_top_k) == (0.25, 20)

    revision = query_router.route_question("第2部分和第1部分的条款对比")
    assert (revision.vector_similarity_weight, revision.routes_top_k) == (0.5, 12)

    conceptual = query_router.route_question("两种绝缘材料的区别")
    assert (conceptual.vector_similarity_weight, conceptual.routes_top_k) == (0.75, 10)

    fallback = query_router.route_question("抽检的基本流程是什么")
    assert (fallback.vector_similarity_weight, fallback.routes_top_k) == (None, None)
    assert fallback.overrides is False


def test_the_numeric_rule_wins_over_a_comparison_phrasing():
    """A question naming a table is a numeric question first.

    Its answer lives in that table, so the comparison wording must not pull it onto
    the vector-heavy path; the rules are tried numeric -> revision -> conceptual.
    """
    decision = query_router.route_question("表3 中 3×25 的载流量与另一版本的异同")

    assert decision.name == query_router.NUMERIC
    assert decision.vector_similarity_weight == query_router.NUMERIC_VECTOR_WEIGHT


def test_a_revision_question_that_also_asks_for_a_difference_stays_revision():
    decision = query_router.route_question("2026年版与2016年版在试验项目上的区别")

    assert decision.name == query_router.REVISION


def test_the_decision_records_what_matched():
    """The transcript needs the literal, not just the label."""
    decision = query_router.route_question("表3 中偏心度的允许偏差是多少")

    assert decision.signal


def test_route_question_accepts_non_string_input():
    """Callers pass whatever the transport gave them; a router is not a validator."""
    assert query_router.route_question(None).name == query_router.PASS_THROUGH
    assert query_router.route_question(12345).name == query_router.PASS_THROUGH


# ---------------------------------------------------------------------------
# Applying the decision: this request only
# ---------------------------------------------------------------------------


class _Store:
    """Records the retrieval settings each route was actually called with."""

    def __init__(self):
        self.calls = []

    async def retrieval(self, question, embd_mdl, tenant_ids, kb_ids, page, page_size, threshold, **kwargs):
        self.calls.append(
            {
                "question": question,
                "page_size": page_size,
                "vector_similarity_weight": kwargs.get("vector_similarity_weight"),
            }
        )
        return {
            "total": 1,
            "chunks": [{"chunk_id": "c1", "content_with_weight": "正文", "doc_id": "doc-1", "similarity": 0.9}],
            "doc_aggs": [],
        }


async def _run(store, question, **kwargs):
    return await pipeline.retrieve_multi_route(
        retriever=store,
        question=question,
        chat_mdl=object(),
        embd_mdl=object(),
        tenant_ids=["t-1"],
        kb_ids=["kb-1"],
        **kwargs,
    )


@pytest.mark.parametrize(
    ("question", "weight", "top_k"),
    [
        ("3×25mm² 的载流量是多少", query_router.NUMERIC_VECTOR_WEIGHT, query_router.NUMERIC_TOP_K),
        ("第2部分和第1部分的条款对比", query_router.REVISION_VECTOR_WEIGHT, query_router.REVISION_TOP_K),
        ("两种绝缘材料的异同", query_router.CONCEPTUAL_VECTOR_WEIGHT, query_router.CONCEPTUAL_TOP_K),
    ],
)
async def test_the_routed_parameters_reach_the_retrieval_call(question, weight, top_k):
    store = _Store()

    await _run(store, question, similarity_threshold=0.55, vector_similarity_weight=0.5, routes_top_k=12, final_top_n=12)

    assert store.calls, "the retriever was never called"
    assert all(call["vector_similarity_weight"] == weight for call in store.calls)
    # The routed window is a floor as well as a target: the caller returns 12
    # passages, so a narrower routed window could not fill the page.
    assert all(call["page_size"] == max(top_k, 12) for call in store.calls)


async def test_a_question_that_matches_no_rule_keeps_the_configured_settings():
    """The fallback is the point of the feature: the assistant's own sliders."""
    store = _Store()

    await _run(store, "抽检的基本流程是什么", similarity_threshold=0.55, vector_similarity_weight=0.5, routes_top_k=12, final_top_n=12)

    assert store.calls
    assert all(call["vector_similarity_weight"] == 0.5 for call in store.calls)
    assert all(call["page_size"] == 12 for call in store.calls)


async def test_a_wider_routed_window_is_used_as_configured():
    """A numeric question widens the recall window past the caller's own."""
    store = _Store()

    await _run(store, "偏心度的允许偏差是多少", vector_similarity_weight=0.5, routes_top_k=12, final_top_n=6)

    assert all(call["page_size"] == query_router.NUMERIC_TOP_K for call in store.calls)


async def test_the_router_does_not_mutate_the_callers_arguments():
    """Isolation: the override lives in the call, not in the configuration slot.

    ``retrieve_multi_route`` receives the assistant's values as plain floats and
    ints; a router that rebound them in a module-level place (or wrote them back)
    would change every later turn.
    """
    store = _Store()
    configured = {"similarity_threshold": 0.55, "vector_similarity_weight": 0.5, "routes_top_k": 12}

    await _run(store, "3×25mm² 的载流量是多少", final_top_n=12, **configured)

    assert configured == {"similarity_threshold": 0.55, "vector_similarity_weight": 0.5, "routes_top_k": 12}
