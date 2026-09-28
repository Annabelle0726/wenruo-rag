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
"""The value/non-value boundary: what a figure in a question IS, and where metadata ends.

Three semantics are pinned here, and each was a defect the red-team audit reproduced:

* a **document identifier** - a standard's part number, its edition year, a model code - is a NAME, not
  an answer-bearing figure, and the boundary has to be complete: `IEC 60502-1:2021` and the model code
  `123ABC` are names too, not only `Q/GDW` designations;
* a **technical measurement** is a figure the question asks about WHATEVER the corpus does with it
  (`2000mm²`, `90°C`, `1.5mm`, `800～1200mm²`, `0.6/1kV`, `3.5dB`), and the decision is made from the
  question alone - the pool-share rule that used to remove common figures is gone, because on a
  single-standard corpus the figures a question asks about are exactly the common ones;
* the ingest's own identity preamble is **metadata, not evidence**, and the boundary that separates them
  is its PRODUCER's (`rag/nlp/retrieval_projection._HEADER_RE`: a leading, bracket-balanced header), so a
  clause that QUOTES the same field list mid-body keeps its figures.

`test_question_value_class_gate.py` and `test_question_value_adversarial_gate.py` under
`deploy/repair_gates/` gate the same semantics against the deployed image, arm by arm; these are the
repository's own unit tests for them.
"""

from rag.retrieval.chunk_profile import (
    NUMERIC_MODEL_IDENTITY,
    NUMERIC_TECHNICAL_MEASUREMENT,
    NUMERIC_VALUE_CLASSES,
    carries_value,
    classify_numeric_token,
    identity_spans,
    numeric_occurrences,
    paired_values,
)
from rag.retrieval.decomposition import question_values

COMPOSITE = "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"
#: The legacy producer writes `文档: <document name without its extension>`, so a fixture that expects its
#: header to be recognised as injected must carry the matching `docnm_kwd` - that equality IS the
#: provenance check (`chunk_profile._verified_header_end`), and without it the boundary fails closed.
HEADER_NAME = "第3部分.pdf"
HEADER = "[标准号: Q/GDW 73286.3 | 文档: 第3部分.pdf | 电压: 220kV | 芯数: 三芯]"
MODEL = "WDZC-YJY-0.6/1kV 3×25 电缆的载流量是多少？"


def chunk(content: str, name: str = HEADER_NAME) -> dict:
    payload = {"chunk_id": "c1", "docnm_kwd": name, "content_with_weight": content}
    # A fixture that expects a LEADING INGEST HEADER to be metadata must record it the way the
    # producer does: the boundary comes from provenance now, not from the bracket's shape.
    if content.startswith(HEADER):
        from rag.nlp.doc_context import LEGACY_PREFIX_VERSION, PREFIX_KIND_LEGACY, record_prefix

        record_prefix(payload, HEADER + " ", PREFIX_KIND_LEGACY, LEGACY_PREFIX_VERSION)
    return payload


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
        """The edition rule needs its cue (`年版`/`版`), so a real 2000 mm² measurement is not a year."""
        assert question_values("2000 mm² 的导体直流电阻是多少？") == ["2000"]

    def test_a_year_the_question_asks_about_is_a_figure(self):
        """A bare `年` is not an edition cue: this question names two years to COMPARE, and both are
        the figures it asks about. The rejected repair dropped both."""
        assert question_values("投产年份是否为2026年，而不是2025年？") == ["2026", "2025"]

    def test_a_model_code_contributes_no_figure(self):
        assert "0.6" not in question_values(MODEL)
        model_occurrences = [item for item in numeric_occurrences(MODEL) if item.text == "0.6"]
        assert [item.kind for item in model_occurrences] == [NUMERIC_MODEL_IDENTITY]

    def test_a_reference_number_shape_is_identity_too(self):
        """`IEC`/`ISO` and the `表`/`图`/`第` labels are identity as much as `Q/GDW` is."""
        for question, figures in (
            ("IEC 60502-1:2021 对金属套厚度有什么规定？", ("60502", "1", "2021")),
            ("GB/T 19666 表 6.2 的厚度要求是什么？", ("19666", "6.2")),
        ):
            values = question_values(question)
            assert all(figure not in values for figure in figures), question

    def test_a_type_code_written_without_a_leading_letter_is_identity(self):
        for question in ("型号 123ABC 的电缆载流量是多少？", "型号 AB123CD 的电缆载流量是多少？"):
            assert question_values(question) == [], question

    def test_a_dimension_pair_beside_a_model_code_is_still_a_measurement(self):
        assert "25" in question_values(MODEL)

    def test_identity_spans_cover_the_designation_and_its_year(self):
        text = " ".join(COMPOSITE.split())
        covered = "".join(text[start:end] for start, end in identity_spans(text)).replace(" ", "")
        assert "73286.2-2026" in covered and "73286.3-2026" in covered

    def test_identity_spans_cover_a_reference_number_and_its_edition_year(self):
        text = "IEC 60502-1:2021"
        covered = "".join(text[start:end] for start, end in identity_spans(text)).replace(" ", "")
        assert covered == "IEC60502-1:2021"


class TestTechnicalValuesAreFiguresTheQuestionAsksAbout:
    def test_a_value_nearly_every_candidate_carries_is_kept(self):
        assert question_values("800 mm² 的厚度是多少？", pool_of("800", 20, 19)) == ["800"]

    def test_both_figures_of_a_comparison_are_kept(self):
        assert question_values("针对 800 mm² 与 1200 mm² 的电缆，内衬层厚度要求有什么区别？") == ["800", "1200"]

    def test_the_pool_does_not_decide_what_the_question_asked(self):
        """The replacement for the pool-share rule. A figure EVERY candidate carries is still the figure
        the question names: ubiquity is evidence about discrimination, and it is now reported
        (`decomposition._pool_share`) rather than acted on."""
        universal = pool_of("800", 20, 20)
        bare = question_values("800 mm² 的厚度是多少？")
        assert bare == ["800"]
        assert question_values("800 mm² 的厚度是多少？", universal) == bare
        assert question_values("800 mm² 的厚度是多少？", ()) == bare

    def test_a_measurement_with_its_unit_is_a_figure_whatever_the_unit_spelling(self):
        """`mm²`, `mm2`, `°C`, `mm`, `dB`, `%` - the unit lexicon is the retrieval router's own
        (`query_router._NUMERIC_UNIT_RE`), not a list this repair enumerates."""
        for question, expected in (
            ("2000mm² 的导体直流电阻是多少？", ["2000"]),
            ("截面 2000mm2 的厚度是多少？", ["2000"]),
            ("导体长期工作温度 90°C 时载流量是多少？", ["90"]),
            ("金属套标称厚度 1.5mm 的允许偏差是多少？", ["1.5"]),
            ("截面 800～1200mm² 的铠装层要求是什么？", ["800", "1200"]),
            ("衰减 3.5dB 的电缆载流量是多少？", ["3.5"]),
        ):
            assert question_values(question) == expected, question

    def test_a_designation_plus_a_real_figure_keeps_only_the_figure(self):
        assert question_values("Q/GDW 73286.2-2026 表 1 中 800 mm² 单芯电缆的截面规格数量是多少？") == ["800"]

    def test_the_classifier_exposes_the_five_published_classes(self):
        text = "Q/GDW 73286.2-2026 中 800 mm²"
        spans = identity_spans(text)
        start = text.index("800")
        assert classify_numeric_token(text, start, start + 3, spans) in NUMERIC_VALUE_CLASSES
        assert classify_numeric_token(text, start, start + 3, spans) == NUMERIC_TECHNICAL_MEASUREMENT
        designation = text.index("73286.2")
        assert classify_numeric_token(text, designation, designation + 7, spans) not in NUMERIC_VALUE_CLASSES


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

    def test_the_boundary_is_LEADING_only_so_a_quotation_in_the_body_is_evidence(self):
        """The producer anchors its header at position 0. A clause that quotes the same field list is
        the document's own text, and its figures are evidence - the rejected version deleted them."""
        prose = chunk("原文明确要求：[标准号: GB/T 10000 | 电压: 220kV]。导体截面 1×800 mm² 的厚度为 3.9 mm。")
        assert carries_value(prose, ("10000",)) is True
        assert carries_value(prose, ("220",)) is True
        assert carries_value(prose, ("3.9",)) is True

    def test_a_quotation_inside_a_table_cell_is_evidence_too(self):
        table = chunk("<table><tr><td>原文要求 [标准号: GB/T 10000 | 电压: 220kV]</td><td>3.9</td></tr></table>")
        assert carries_value(table, ("10000",)) is True

    def test_a_bracketed_title_leaves_the_header_in_place_rather_than_half_deleted(self):
        """The producer's pattern forbids brackets inside a field and its writer does not escape them,
        so such a header is unreadable to the producer as well. The documented contract is that NOTHING
        is removed - a partial deletion is what the rejected version did - and the residual is visible."""
        nested = "[标准号: Q/GDW 73286.3 | 文档: 规范[第3部分].pdf | 电压: 220kV] <table><tr><td>3.9</td></tr></table>"
        table = chunk(nested)
        assert carries_value(table, ("3.9",)) is True
        assert carries_value(table, ("73286.3",)) is True


class TestOrdinaryQuestionsAreUndisturbed:
    def test_a_question_with_no_figures_has_none(self):
        assert question_values("海底电缆的内衬层有什么要求？") == []

    def test_empty_and_structural_only_questions_have_none(self):
        assert question_values("") == []
        assert question_values("第 2 部分") == []
        assert question_values("表 1") == []
