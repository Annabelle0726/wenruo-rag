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
"""The cut for a comparison whose answer lives in ONE table (rerank + chunk_profile).

Measured on the live 220kV index for "针对 800 mm² 与 1200 mm² 的单芯与三芯电缆，金属套平均
厚度分别是多少？": the 12-slot window came back `Part 2 (单芯): 5 chunk(s)`, `Part 3 (三芯):
7 chunk(s)`, the answer model read 3.8 mm for a 1×400 row, reported it for 800 mm², and
said 1200 mm² was not found. The index was not the problem - Part 2 holds the table that
answers it (`1×800 → 3.9`, `1×1200 → 4.1`, cells 100% filled) - and neither was recall:
Part 2's 40 table passages include EIGHTEEN that carry 800 and 1200, because a cable
standard repeats the section series in a dozen parameter tables (接头规格, 导体出线杆,
导体连接管…). Those listings out-score the table that answers, because the fused score's
text leg is a query-recall ratio and a list of the question's own numbers is a perfect
match for it.

The passages below are the LIVE TEXT of the failing corpus, so these tests fail for the
reason the live run failed:

* three of Part 2's forty passages pair the question's figures with a result, and
  `paired_values` must find exactly those;
* the twelve that only list the series must not be mistaken for them;
* the ordering must put the pairing passage first inside its own document;
* the cut must keep each side's pairing passage, whatever the score fill prefers.

Trimming note: the two answering tables are complete; the four listings keep the rows
that carry the series (their classification is ASSERTED, so a bad trim fails here rather
than silently weakening the test).
"""

import pytest

from rag.retrieval import rerank
from rag.retrieval.chunk_profile import carries_value, paired_values, result_figures
from rag.retrieval.decomposition import question_values

QUESTION = "针对 800 mm² 与 1200 mm² 的单芯与三芯电缆，金属套平均厚度分别是多少？"
PART2 = "220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范.pdf"
PART3 = "220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用技术规范.pdf"

#: The table that holds the metal-sheath thickness, page 6 of the Part 2 report.
ANSWER_2 = """[标准号: Q/GDW 73286.2-2026 | 文档: 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范] <tr><td  >3.8 </td><td  >对应1×500 mm2截面</td></tr>
<tr><td  >3.9 </td><td  >对应1×630 mm2截面</td></tr>
<tr><td  >3.9 </td><td  >对应1×800 mm2截面</td></tr>
<tr><td  >4.0 </td><td  >对应1×1000 mm2截面</td></tr>
<tr><td  >4.1 </td><td  >对应1×1200 mm2截面</td></tr>
<tr><td  >最薄点厚度不小于</td><td  >mm </td><td  >0.95tn </td></tr>
<tr><td  rowspan=8 >平均厚度不小于标称厚度 tn </td><td  rowspan=8 >mm </td><td  rowspan=4 >3.5 </td><td  >对应1×800 mm2截面</td></tr>
<tr><td  rowspan=4 >4.0 </td><td  >对应1×1200 mm2截面</td></tr>"""

#: The 接头规格 grid: the series, and nothing beside it.
LISTING_2A = """<tr><td  >800 </td><td></td></tr>
<tr><td  >1000 </td><td></td></tr>
<tr><td  >1200 </td><td></td></tr>"""

LISTING_2B = """<tr><td  rowspan=10 >8 </td><td colspan=2 rowspan=9 >接头规格</td><td  rowspan=10 >mm2 </td><td  >400 </td><td></td></tr>
<tr><td  >500 </td><td></td></tr>
<tr><td  >630 </td><td></td></tr>
<tr><td  >800 </td><td></td></tr>
<tr><td  >1000 </td><td></td></tr>
<tr><td  >1200 </td><td></td></tr>
<tr><td  >1400 </td><td></td></tr>
<tr><td  >额定电压</td><td></td><td  >kV </td><td  >127/220 </td><td></td></tr>
<tr><td  >最高运行电压</td><td></td><td  >kV </td><td  >252 </td><td></td></tr>"""

LISTING_2C = """<tr><td  rowspan=9 >6 </td><td></td><td></td><td  rowspan=9 >mm2 </td><td  >400 </td><td></td></tr>
<tr><td colspan=2 rowspan=6 >接头规格</td><td  >500 </td><td></td></tr>
<tr><td  >630 </td><td></td></tr>
<tr><td  >800 </td><td></td></tr>
<tr><td  >1200 </td><td></td></tr>
<tr><td  >额定电压</td><td></td><td  >kV </td><td  >127/220 </td><td></td></tr>
<tr><td  >雷电冲击耐受电压峰值 （正负极性各10次）</td><td  >kV </td><td  >1050 </td><td></td></tr>"""

#: The same answer on the three-core side, which the model DID read correctly.
ANSWER_3 = """<table><caption>表1（续）</caption>
<tr><td  rowspan=11 >5  6 </td><td  >纵向阻 水层</td><td  >半导电阻水膨胀 带弹性材料层×厚</td><td  >层×mm </td><td  >项目单位提供</td><td></td></tr>
<tr><td  rowspan=10 >金属套</td><td  >材料</td><td  >—</td><td  >铅合金套 分相</td><td  >—</td></tr>
<tr><td  rowspan=8 >平均厚度不小于 标称厚度t </td><td  rowspan=8 >mm </td><td  >3.5 </td><td  >对应3×400 mm2截面</td></tr>
<tr><td  >3.6 </td><td  >对应3×800 mm2截面</td></tr>
<tr><td  >3.8 </td><td  >对应3×1200 mm2截面</td></tr>
<tr><td  >最薄点厚度不小于</td><td  >mm </td><td  >铅合金套 0.95tn </td><td></td></tr>"""

#: The GIS terminal grid on the three-core side: a listing again.
LISTING_3A = """<table><caption>表6 GIS终端参数表</caption>
<tr><td  rowspan=9 >导体出线杆</td><td  >规格</td><td  >400 </td><td></td></tr>
<tr><td  >500 </td><td></td></tr>
<tr><td  >630 </td><td></td></tr>
<tr><td  >800 </td><td></td></tr>
<tr><td  >1000 </td><td></td></tr>
<tr><td  >1200 </td><td></td></tr>
<tr><td  >环氧套管</td><td  >材料</td><td  >— </td><td  >环氧树脂</td></tr>"""


#: The rest of the real pool: the general part of the standard and two unrelated
#: cable datasets, none of which names 800 or 1200. The live pool held 82 passages for
#: this question and only 18 named the sections, which is what lets the figures
#: discriminate at all - see ``MAX_VALUE_POOL_SHARE``.
PART1 = "220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf"
OTHER = "10kV架空绝缘电缆采购标准+第2部分：专用技术规范.pdf"

CLAUSE_1 = "6.2.4 金属套的标称厚度应不小于本规范表6的规定。金属套表面应光滑，不应有裂纹、夹杂物和其他影响使用的缺陷。"
TABLE_OTHER_A = "<table><caption>表3 架空绝缘电缆结构参数表</caption><tr><th>序号</th><th>项目</th><th>单位</th><th>标准参数值</th></tr><tr><td>1</td><td>导体</td><td>—</td><td>铜芯</td></tr></table>"
TABLE_OTHER_B = "<table><caption>表4 架空绝缘电缆电气参数表</caption><tr><th>序号</th><th>项目</th><th>单位</th><th>标准参数值</th></tr><tr><td>1</td><td>额定电压</td><td>kV</td><td>10</td></tr></table>"


def _chunk(chunk_id, document, content, score, doc_type="table"):
    return {
        "id": chunk_id,
        "chunk_id": chunk_id,
        "doc_id": f"doc-{document[:3]}",
        "docnm_kwd": document,
        "doc_type_kwd": doc_type,
        "content_with_weight": content,
        "similarity": score,
    }


def _pool():
    """The measured shape: the listings score ABOVE the table that answers, on both sides."""
    return [
        _chunk("p1-clause", PART1, CLAUSE_1, 0.62, doc_type="text"),
        _chunk("p2-list-a", PART2, LISTING_2A, 0.68),
        _chunk("p2-list-b", PART2, LISTING_2B, 0.66),
        _chunk("p2-list-c", PART2, LISTING_2C, 0.65),
        _chunk("p2-answer", PART2, ANSWER_2, 0.58),
        _chunk("p3-list-a", PART3, LISTING_3A, 0.64),
        _chunk("p3-answer", PART3, ANSWER_3, 0.60),
        _chunk("other-a", OTHER, TABLE_OTHER_A, 0.61),
        _chunk("other-b", OTHER, TABLE_OTHER_B, 0.59, doc_type="text"),
    ]


def _selected(pool, top_n):
    policy = rerank.DiversityPolicy.for_question(QUESTION, pool)
    ordered = rerank.apply_rank_adjustments(list(pool), policy)
    return rerank.select_context(ordered, top_n, policy)


def _ranks(pool):
    return [chunk["chunk_id"] for chunk in rerank.apply_rank_adjustments(list(pool), rerank.DiversityPolicy.for_question(QUESTION, pool))]


@pytest.mark.p1
def test_the_question_names_the_two_sections_it_asks_about():
    values = question_values(QUESTION, _pool())

    assert values == ["800", "1200"]


@pytest.mark.p1
def test_a_standard_designation_is_not_a_measurement():
    answer = _chunk("p2-answer", PART2, ANSWER_2, 0.58)

    figures = result_figures(answer)

    # 73286.2 is part of `Q/GDW 73286.2-2026`; the thicknesses are the measurements.
    assert "73286.2" not in figures
    assert {"3.9", "4.1", "3.5", "0.95"} <= figures


@pytest.mark.p1
def test_the_answering_table_pairs_both_sections_with_results():
    answer = _chunk("p2-answer", PART2, ANSWER_2, 0.58)

    assert paired_values(answer, ("800", "1200")) == {"800", "1200"}


@pytest.mark.p1
def test_a_parameter_table_that_lists_the_sections_pairs_nothing():
    listings = [chunk for chunk in _pool() if "-list-" in chunk["chunk_id"]]

    assert len(listings) == 4
    for chunk in listings:
        assert carries_value(chunk, ("800", "1200")), chunk["chunk_id"]
        assert paired_values(chunk, ("800", "1200")) == set(), chunk["chunk_id"]


@pytest.mark.p1
def test_the_pairing_table_leads_the_document_that_holds_it():
    ranks = _ranks(_pool())

    # Both answering tables first inside their own side, ahead of the listings that
    # scored higher - the ordering the fused score alone could not produce.
    assert ranks.index("p2-answer") < ranks.index("p2-list-a")
    assert ranks.index("p3-answer") < ranks.index("p3-list-a")


@pytest.mark.p1
def test_the_cut_keeps_the_answering_table_of_each_side():
    selected = {chunk["chunk_id"] for chunk in _selected(_pool(), 6)}

    assert "p2-answer" in selected
    assert "p3-answer" in selected


@pytest.mark.p1
def test_the_cut_still_fills_the_window_from_both_sides():
    selected = _selected(_pool(), 6)

    documents = {chunk["docnm_kwd"] for chunk in selected}

    assert len(selected) == 6
    # Both sides of the comparison survive the reservations, which is the point of
    # them: the answering table of each is not bought with the other side's absence.
    assert {PART2, PART3} <= documents


@pytest.mark.p1
def test_a_question_with_no_figures_keeps_the_score_order():
    question = "海底电力电缆的金属套材料是什么？"
    pool = _pool()

    policy = rerank.DiversityPolicy.for_question(question, pool)
    ordered = rerank.apply_rank_adjustments(list(pool), policy)
    ranks = [chunk["chunk_id"] for chunk in ordered]

    assert policy.question_values == frozenset()
    # The listing that scored 0.66 still leads the answering table that scored 0.58:
    # with no figures in the question there is no value axis to reorder them, and the
    # same pool under the value question puts them the other way round (above).
    assert ranks.index("p2-list-b") < ranks.index("p2-answer")


@pytest.mark.p1
def test_a_figure_the_whole_pool_carries_is_not_a_signal():
    question = "220kV 电缆的金属套平均厚度是多少？"
    pool = [_chunk("a", PART2, LISTING_2B, 0.6), _chunk("b", PART2, LISTING_2C, 0.5)]

    assert question_values(question, pool) == []
