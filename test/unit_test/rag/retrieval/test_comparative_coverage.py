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
"""Comparative questions must be answered from BOTH sides.

Measured on 《Q/GDW 73286.2 第2部分(单芯)》 / 《Q/GDW 73286.3 第3部分(三芯)》 with

    400 mm²、630 mm² 与 1600 mm² 截面电缆在 20°C 时的导体最大直流电阻标准值分别是
    多少？单芯与三芯要求是否一致？

the answer came back from Part 2 alone ("知识库未检索到三芯规范的对应数据"). Both files
are standards, so the auxiliary-document quota never applied to either, and Part 2's
table - one document, split into row-batches, so many near-identical high-scoring
passages - filled the window. The other part was not retrieved at all, and no cut
policy can rebalance a pool a document is missing from.

Three mechanisms, all deterministic (no extra LLM call):

* the question's SIDES are read ("单芯"/"三芯", "第2部分"/"第3部分", "Part 2"/"Part 3");
* one retrieval ROUTE per side, so each side's own wording is searched and
  ``select_context``'s per-route reservation represents both;
* when the pool holds the documents those sides point at, no single document may take
  more than half the window and each of them is reserved a slot - which is the one
  shape where the "the standard is exempt from the document quota" rule is wrong.

A question that compares nothing keeps the plain top-N, including the eleven-passage
single-document answer an earlier milestone measured; those cases pin that too.
"""

import pytest

from rag.retrieval import chunk_profile, decomposition, rerank

pytestmark = pytest.mark.p1

PART2 = "Q_GDW 73286.2-2026 第2部分：单芯海底电力电缆采购标准.pdf"
PART3 = "Q_GDW 73286.3-2026 第3部分：三芯海底电力电缆采购标准.pdf"
COMPARATIVE = "400 mm²、630 mm² 与 1600 mm² 截面电缆在 20°C 时的导体最大直流电阻标准值分别是多少？单芯与三芯要求是否一致？"
SINGLE = "400mm² 导体在 20°C 时的最大直流电阻是多少？"

#: Part 2's table split into row-batches: many near-identical high-scoring passages.
PART2_SCORES = [0.66, 0.655, 0.65, 0.645, 0.64, 0.635, 0.63, 0.625, 0.62, 0.615]
#: Part 3's table, scored lower on the same words.
PART3_SCORES = [0.60, 0.595]


def _chunk(chunk_id, doc, score, body="400 0.0470 630 0.0283 1600 0.0113"):
    return {
        "chunk_id": chunk_id,
        "doc_id": doc,
        "docnm_kwd": doc,
        "doc_type_kwd": "table",
        "content_with_weight": f"<table><tr><td>{body}</td></tr></table>",
        "similarity": score,
    }


def _pool():
    chunks = [_chunk(f"p2-{i}", PART2, score) for i, score in enumerate(PART2_SCORES)]
    chunks += [_chunk(f"p3-{i}", PART3, score) for i, score in enumerate(PART3_SCORES)]
    return chunks


def _documents(chunks):
    """Which document each returned passage came from, in order."""
    return [chunk_profile.document_name(chunk) for chunk in chunks]


def _ordered(pool):
    return sorted(pool, key=lambda chunk: chunk["similarity"], reverse=True)


# ---------------------------------------------------------------------------
# Reading the comparison out of the question
# ---------------------------------------------------------------------------


def test_the_sides_a_question_compares_are_read_in_order():
    assert chunk_profile.comparison_sides(COMPARATIVE) == ["单芯", "三芯"]
    assert chunk_profile.comparison_sides("第2部分和第3部分的金属套厚度差异") == ["第2部分", "第3部分"]
    assert chunk_profile.comparison_sides("Compare Part 2 and Part 3 conductor resistance") == ["Part 2", "Part 3"]


def test_a_question_that_compares_nothing_names_no_side():
    assert chunk_profile.comparison_sides(SINGLE) == []
    assert chunk_profile.is_comparative_question(SINGLE) is False


def test_a_comparison_is_recognised_by_a_cue_or_by_two_sides():
    assert chunk_profile.is_comparative_question(COMPARATIVE) is True, "是否一致"
    assert chunk_profile.is_comparative_question("单芯与三芯哪个外径更大") is True, "two sides, no cue word"
    assert chunk_profile.is_comparative_question("二者有何区别") is True, "a cue, no sides"
    assert chunk_profile.is_comparative_question("三芯电缆的外径是多少") is False, "one side is not a comparison"


def test_the_compared_documents_are_the_ones_the_sides_name():
    compared = chunk_profile.resolve_compared_documents(_pool(), COMPARATIVE)

    assert compared == {PART2, PART3}


def test_a_side_the_corpus_does_not_separate_resolves_to_one_document():
    pool = [_chunk("a", PART2, 0.6), _chunk("b", "供应商数据表.pdf", 0.5)]

    assert chunk_profile.resolve_compared_documents(pool, COMPARATIVE) == {PART2}


# ---------------------------------------------------------------------------
# One route per side
# ---------------------------------------------------------------------------


def test_each_side_gets_a_route_carrying_its_own_word_and_the_parameters():
    routes = decomposition.comparative_routes(COMPARATIVE)

    assert len(routes) == 2
    assert routes[0].startswith("单芯 ") and "1600" in routes[0]
    assert routes[1].startswith("三芯 ") and "1600" in routes[1]
    for route in routes:
        others = [side for side in ("单芯", "三芯") if not route.startswith(side)]
        for other in others:
            assert other not in route, "a side route must not match the other side's wording"


def test_a_question_that_compares_nothing_gets_no_side_route():
    assert decomposition.comparative_routes(SINGLE) == []
    assert decomposition.comparative_routes("") == []


# ---------------------------------------------------------------------------
# The cut: the failure this file exists for
# ---------------------------------------------------------------------------


def test_a_comparative_question_is_answered_from_both_documents():
    pool = _pool()
    policy = rerank.DiversityPolicy.for_question(COMPARATIVE, pool)

    selected = rerank.select_context(_ordered(pool), 8, policy)

    documents = _documents(selected)
    assert PART2 in documents, "the single-core side"
    assert PART3 in documents, "the three-core side must survive the cut"
    assert documents.count(PART3) >= 1


def test_no_single_document_owns_a_comparative_window():
    pool = _pool()
    policy = rerank.DiversityPolicy.for_question(COMPARATIVE, pool)

    selected = rerank.select_context(_ordered(pool), 8, policy)

    assert _documents(selected).count(PART2) <= 4, "half of an 8-passage window"
    assert _documents(selected).count(PART3) <= 4


def test_the_lower_scoring_side_is_reserved_a_slot():
    """Part 3's best passage is the FIRST thing the score fill would drop."""
    pool = _pool()
    policy = rerank.DiversityPolicy.for_question(COMPARATIVE, pool)

    selected = rerank.select_context(_ordered(pool), 4, policy)

    assert PART3 in _documents(selected)


def test_a_comparison_the_corpus_cannot_separate_keeps_a_plain_top_n():
    """One document named twice is not a comparison of two sources: capping it would
    truncate the only answer there is."""
    pool = [_chunk(f"p2-{i}", PART2, score) for i, score in enumerate(PART2_SCORES)]
    policy = rerank.DiversityPolicy.for_question(COMPARATIVE, pool)

    selected = rerank.select_context(_ordered(pool), 6, policy)

    assert _documents(selected) == [PART2] * 6
    assert policy.max_document_share == 1.0


def test_a_single_document_question_still_lets_one_document_own_the_window():
    """The earlier milestone's winning answer was ELEVEN passages of ONE document."""
    pool = [_chunk(f"p2-{i}", PART2, 0.62) for i in range(11)] + [_chunk("p3-0", PART3, 0.5)]
    policy = rerank.DiversityPolicy.for_question(SINGLE, pool)

    selected = rerank.select_context(_ordered(pool), 12, policy)

    assert _documents(selected).count(PART2) == 11
    assert policy.active is False or policy.max_document_share == 1.0
