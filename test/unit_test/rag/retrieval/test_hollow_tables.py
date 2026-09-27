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
"""An unfilled table grid must not out-rank the table that fills it.

Measured on 《Q/GDW 73286.2 第2部分：单芯》 (26 pages, 39 stored table chunks): the chunk
that holds the answer - ``<td>3.9 </td><td>对应1×800 mm2截面</td>``, ``4.1 → 1×1200`` -
is 0% empty, while fourteen other chunks of the same document repeat the question's own
numbers with BLANK value cells (``<td>800 </td><td></td>``), 20-64% empty. The question
names those numbers, so it matches the empty grids at least as well as the filled one,
and the answer comes back as "800 和 1200 对应的具体数值在提供的资料中并未出现" - while
holding a passage whose 800 row is blank.
"""

import pytest

from rag.retrieval import chunk_profile, rerank

pytestmark = pytest.mark.p1

_ANSWER_TABLE = (
    "<table><caption>表1 电缆结构</caption><tr><th>金属套平均厚度</th><th>截面</th></tr><tr><td>3.9 </td><td>对应1×800 mm2截面</td></tr><tr><td>4.1 </td><td>对应1×1200 mm2截面</td></tr></table>"
)
#: The shape of the fourteen competing chunks: labels present, values absent.
_EMPTY_GRID = "<table><tr><td>800 </td><td></td></tr><tr><td>1200 </td><td></td></tr></table>"


def _chunk(chunk_id, body, score, shape="table"):
    return {"chunk_id": chunk_id, "doc_id": "doc-1", "docnm_kwd": "Q_GDW 73286.2-2026 第2部分：单芯.pdf", "doc_type_kwd": shape, "content_with_weight": body, "similarity": score}


def test_the_fill_ratio_separates_a_filled_table_from_an_empty_grid():
    assert chunk_profile.table_fill_ratio(_chunk("a", _ANSWER_TABLE, 0.6)) == 1.0
    assert chunk_profile.table_fill_ratio(_chunk("b", _EMPTY_GRID, 0.6)) == 0.5


def test_a_half_blank_table_counts_as_hollow():
    assert chunk_profile.is_hollow_table(_chunk("b", _EMPTY_GRID, 0.6)) is True
    assert chunk_profile.is_hollow_table(_chunk("a", _ANSWER_TABLE, 0.6)) is False


def test_a_passage_with_no_cells_is_not_called_hollow():
    """``None`` and ``0.0`` are different answers: prose is not an empty table."""
    assert chunk_profile.table_fill_ratio(_chunk("c", "例行交流电压试验应施加 3.5kV。", 0.6, shape="text")) is None
    assert chunk_profile.is_hollow_table(_chunk("c", "例行交流电压试验应施加 3.5kV。", 0.6, shape="text")) is False


def test_a_markdown_table_is_measured_too():
    markdown = "表1 电缆结构\n| 截面 | 厚度 |\n| --- | --- |\n| 800 | 3.9 |"

    assert chunk_profile.table_fill_ratio(_chunk("d", markdown, 0.6)) == 1.0


def test_the_filled_table_wins_a_near_tie():
    """The empty grid scores HIGHER on the raw number match and must still lose."""
    answer = _chunk("answer", _ANSWER_TABLE, 0.60)
    empty = _chunk("empty", _EMPTY_GRID, 0.66)

    ordered = rerank.apply_rank_adjustments([answer, empty], rerank.DiversityPolicy())

    assert [chunk["chunk_id"] for chunk in ordered] == ["answer", "empty"]
    assert empty["rank_score"] < empty["similarity"], "the ordering value carries the penalty"
    assert empty["similarity"] == 0.66, "the model's own number is untouched"


def test_a_hollow_table_is_ordered_below_but_never_dropped():
    """A corpus whose tables are all sparse still needs them."""
    chunks = [_chunk(f"e{i}", _EMPTY_GRID, 0.66 - i / 100) for i in range(3)] + [_chunk("answer", _ANSWER_TABLE, 0.6)]

    ordered = rerank.apply_rank_adjustments(chunks, rerank.DiversityPolicy())

    assert len(ordered) == 4
    assert ordered[0]["chunk_id"] == "answer"
    assert {chunk["chunk_id"] for chunk in ordered[1:]} == {"e0", "e1", "e2"}


def test_a_very_empty_grid_loses_a_near_tie_but_not_a_real_gap():
    """The penalty is an ordering nudge, not an override: it decides a near tie, while a
    passage whose relevance is genuinely higher still wins."""
    grid = "<table><tr><td></td><td></td><td>800</td></tr><tr><td></td><td></td><td></td></tr></table>"
    near_tie = _chunk("v", grid, 0.62)
    prose = _chunk("p", "本条规定了金属套厚度。", 0.5, shape="text")

    ordered = rerank.apply_rank_adjustments([near_tie, prose], rerank.DiversityPolicy())

    assert [chunk["chunk_id"] for chunk in ordered] == ["p", "v"]

    ordered = rerank.apply_rank_adjustments([_chunk("v2", grid, 0.95), _chunk("p2", "本条规定了金属套厚度。", 0.5, shape="text")], rerank.DiversityPolicy())

    assert [chunk["chunk_id"] for chunk in ordered] == ["v2", "p2"]


# ---------------------------------------------------------------------------
# One document's row-batch table parts must not fill the window with themselves
# ---------------------------------------------------------------------------

_PART2 = "Q_GDW 73286.2-2026 第2部分：单芯.pdf"
_PART3 = "Q_GDW 73286.3-2026 第3部分：三芯.pdf"


def _table(chunk_id, doc, score, body="<table><tr><td>800 </td><td></td></tr></table>"):
    chunk = _chunk(chunk_id, body, score)
    chunk["docnm_kwd"] = doc
    chunk["doc_id"] = doc  # the quota bucket each document is charged to
    return chunk


def _prose(chunk_id, doc, score):
    chunk = _chunk(chunk_id, "本条规定了金属套的平均厚度要求。", score, shape="text")
    chunk["docnm_kwd"] = doc
    chunk["doc_id"] = doc
    return chunk


def test_one_documents_empty_grids_cannot_own_the_window():
    """The measured Part 2 shape: 39 stored tables, five of them in a 12-slot window."""
    pool = [_table(f"t{i}", _PART2, 0.70 - i / 100) for i in range(10)] + [_table(f"s{i}", _PART3, 0.60 - i / 100) for i in range(2)]

    selected = rerank.select_context(pool, 12, rerank.DiversityPolicy())

    assert len([chunk for chunk in selected if chunk["docnm_kwd"] == _PART2]) <= 3, "a quarter of 12"
    assert any(chunk["docnm_kwd"] == _PART3 for chunk in selected)


def test_the_cap_is_on_empty_grids_not_on_tables():
    """A parameter table IS the right source for a parameter question: a FILLED one is
    never withheld, however many of them one document contributes."""
    filled = "<table><tr><td>800 </td><td>3.9 </td></tr><tr><td>1200 </td><td>4.1 </td></tr></table>"
    pool = [_table(f"t{i}", _PART2, 0.70 - i / 100, filled) for i in range(6)]

    selected = rerank.select_context(pool, 4, rerank.DiversityPolicy())

    assert [chunk["chunk_id"] for chunk in selected] == ["t0", "t1", "t2", "t3"]


def test_the_freed_slots_go_to_that_documents_prose():
    pool = [_table(f"t{i}", _PART2, 0.70 - i / 100) for i in range(6)] + [_prose("p1", _PART2, 0.4)]

    selected = rerank.select_context(pool, 4, rerank.DiversityPolicy())

    ids = [chunk["chunk_id"] for chunk in selected]
    assert "p1" in ids, "the prose takes a freed slot"
    assert sum(1 for chunk in selected if chunk_profile.is_hollow_table(chunk)) <= 1


def test_a_pool_of_nothing_but_one_documents_empty_grids_comes_back_short():
    """An empty grid cannot answer, so a window of them is not better than a shorter one -
    the short window is the honest signal that the parse, not the ranking, needs work."""
    pool = [_table(f"t{i}", _PART2, 0.70 - i / 100) for i in range(6)]

    selected = rerank.select_context(pool, 4, rerank.DiversityPolicy())

    assert 0 < len(selected) <= 2, f"capped, not filled: {[c['chunk_id'] for c in selected]}"
