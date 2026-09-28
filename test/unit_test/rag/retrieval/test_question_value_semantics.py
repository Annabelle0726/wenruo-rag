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
"""The value/non-value boundary: document identity is not an answer-bearing figure.

These pin the two semantics a corpus-wide measurement found inverted on a single-standard index:

* a **document identifier** - a standard's part number, its year, a model-code fragment - was admitted
  as a "question figure" because it is RARE in the pool, and a document identifier is rare precisely
  because it names one document;
* an **answer-bearing technical value** was discarded for being COMMON, and on a single-standard corpus
  every table of that standard lists it.

The ingest's own identity preamble is the same error one layer down: it made every table in the corpus
"carry" the question's figures, which turned the rule that tells a table that merely LISTS the figures
from one that PAIRS them into a flat penalty on the whole type.
"""

from rag.retrieval.chunk_profile import carries_value, identity_spans, paired_values
from rag.retrieval.decomposition import question_values

COMPOSITE = "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"
HEADER = "[标准号: Q/GDW 73286.3 | 文档: 第3部分.pdf | 电压: 220kV | 芯数: 三芯]"


def chunk(content: str) -> dict:
    return {"chunk_id": "c1", "content_with_weight": content}


def pool_of(value: str, size: int, carrying: int) -> list[dict]:
    return [chunk(f"{value} mm² 的厚度要求是 1.5 mm" if index < carrying else "内衬层的一般要求") for index in range(size)]


class TestDocumentIdentityIsNotAValue:
    def test_a_standard_part_number_and_its_year_are_not_figures(self):
        assert question_values(COMPOSITE) == []

    def test_a_designation_only_question_has_no_figures(self):
        assert question_values("Q/GDW 73286.2-2026 是什么标准？") == []

    def test_an_edition_year_is_not_a_figure(self):
        assert question_values("2026 年版的海底电缆标准对铠装层有什么规定？") == []

    def test_a_measurement_that_looks_like_a_year_survives(self):
        """The year rule needs its cue, so a real 2000 mm² measurement is not mistaken for an edition."""
        assert question_values("2000 mm² 的导体直流电阻是多少？") == ["2000"]

    def test_a_model_code_contributes_no_figure(self):
        assert "0.6" not in question_values("WDZC-YJY-0.6/1kV 3×25 电缆的载流量是多少？")

    def test_a_dimension_pair_beside_a_model_code_is_still_a_measurement(self):
        assert "25" in question_values("WDZC-YJY-0.6/1kV 3×25 电缆的载流量是多少？")

    def test_identity_spans_cover_the_designation_and_its_year(self):
        text = " ".join(COMPOSITE.split())
        covered = "".join(text[start:end] for start, end in identity_spans(text)).replace(" ", "")
        assert "73286.2-2026" in covered and "73286.3-2026" in covered


class TestTechnicalValuesSurviveBeingCommon:
    def test_a_value_nearly_every_candidate_carries_is_kept(self):
        assert question_values("800 mm² 的厚度是多少？", pool_of("800", 20, 19)) == ["800"]

    def test_both_figures_of_a_comparison_are_kept(self):
        assert question_values("针对 800 mm² 与 1200 mm² 的电缆，内衬层厚度要求有什么区别？") == ["800", "1200"]

    def test_only_a_universal_value_is_dropped(self):
        """The degenerate case: a figure EVERY candidate carries cannot separate two of them."""
        assert question_values("800 mm² 的厚度是多少？", pool_of("800", 20, 20)) == []
        assert question_values("800 mm² 的厚度是多少？", pool_of("800", 20, 19)) == ["800"]

    def test_a_designation_plus_a_real_figure_keeps_only_the_figure(self):
        assert question_values("Q/GDW 73286.2-2026 表 1 中 800 mm² 单芯电缆的截面规格数量是多少？") == ["800"]


class TestTheIngestPreambleIsNotEvidence:
    def test_a_table_whose_only_designation_is_in_the_preamble_does_not_carry_it(self):
        assert carries_value(chunk(f"{HEADER} <table><tr><td>导体</td><td>铜</td></tr></table>"), ("73286.3",)) is False

    def test_a_preamble_figure_is_not_carried(self):
        assert carries_value(chunk(f"{HEADER} <table><tr><td>导体</td><td>铜</td></tr></table>"), ("220",)) is False

    def test_the_same_figure_in_the_body_is_still_carried(self):
        # `paired_values` asks for the figure AND a RESULT beside it, so the fixture carries both:
        # 800 is the question's figure and 3.9 is the value the answering row puts next to it.
        table = chunk(f"{HEADER} <table><tr><td>导体</td><td>800</td><td>3.9</td></tr></table>")
        assert carries_value(table, ("800",)) is True
        assert paired_values(table, ("800",)) == {"800"}

    def test_ordinary_prose_without_a_preamble_is_unaffected(self):
        assert carries_value(chunk("内衬层的标称厚度应不小于 1.5 mm。"), ("1.5",)) is True

    def test_an_ordinary_bracketed_phrase_is_not_metadata(self):
        prose = chunk("试验条件 [温度 20 ℃ 湿度 60 %] 下的载流量为 500 A。")
        assert carries_value(prose, ("20",)) is True
        assert carries_value(prose, ("500",)) is True


class TestOrdinaryQuestionsAreUndisturbed:
    def test_a_question_with_no_figures_has_none(self):
        assert question_values("海底电缆的内衬层有什么要求？") == []

    def test_empty_and_structural_only_questions_have_none(self):
        assert question_values("") == []
        assert question_values("第 2 部分") == []
        assert question_values("表 1") == []
