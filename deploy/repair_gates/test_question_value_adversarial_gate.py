"""The red-team audit's adversarial matrix, at BEHAVIOUR level, as a formal gate.

Every case here was REPRODUCED against the rejected repair (commit `42ca64339`) before it was written,
and each group is a blocker the audit named:

A. unit-aware technical detection that hardcodes no unit
B. document and model identity, complete, without making every year or part number permanent identity
C. context-sensitive figures - the same digits are an edition in one sentence and the answer in the next
D. pool independence: extraction does not consult the corpus
E. the metadata boundary, defined by the PRODUCER of the header, including its own limitation

**This module deliberately imports only the API the rejected revision also had**
(`question_values`, `carries_value`, `identity_spans`, `_pool_share`, `strip_section_references`), so it
COLLECTS against that revision and its cases fail one by one, on their own merits. A gate that dies at
import proves nothing about which semantics broke. The API the revision ADDS - the published classes -
is gated separately in `test_question_value_class_gate.py`.

Run it against both revisions. It must FAIL on the rejected one.
"""
import sys

import pytest

sys.path.insert(0, "/ragflow")

from rag.retrieval.chunk_profile import carries_value, identity_spans
from rag.retrieval.decomposition import _pool_share, question_values


def chunk(content, doc_id="doc-a", name="part3.pdf"):
    return {"chunk_id": "c1", "doc_id": doc_id, "docnm_kwd": name, "content_with_weight": content}


# ---------------------------------------------------------------------------
# A. technical measurements: unit-aware, and no unit is hardcoded
# ---------------------------------------------------------------------------

TECHNICAL_SHAPES = [
    ("2000mm² 的导体直流电阻是多少？", ["2000"]),
    ("导体长期工作温度 90°C 时载流量是多少？", ["90"]),
    ("金属套标称厚度 1.5mm 的允许偏差是多少？", ["1.5"]),
    ("截面 800～1200mm² 的铠装层要求是什么？", ["800", "1200"]),
    ("220kV 电缆的金属套平均厚度是多少？", ["220"]),
    ("800 mm² 的厚度是多少？", ["800"]),
    ("针对 800 mm² 与 1200 mm² 的电缆，内衬层厚度有什么区别？", ["800", "1200"]),
    ("1×800 mm² 单芯电缆的金属套厚度是多少？", ["800"]),
    # `0.6/1kV`: the `0.6` is the discriminative figure and survives; the `1` is a single digit, and the
    # PRE-EXISTING rule ("two digits or a decimal part") drops it as noise, exactly as it drops the `1`
    # of `1×800`. Recorded here so the rule's reach is visible instead of assumed.
    ("额定电压 0.6/1kV 的电缆绝缘厚度是多少？", ["0.6"]),
    # A unit the repair never names: `dB` is in `query_router._NUMERIC_UNIT_RE`, so this proves the
    # decision is lexicon-driven rather than an enumerated list of kV/mm/°C.
    ("衰减 3.5dB 的电缆载流量是多少？", ["3.5"]),
]


@pytest.mark.parametrize("question,expected", TECHNICAL_SHAPES)
def test_a_every_technical_shape_the_audit_reproduced_survives(question, expected):
    """All of the first nine returned `[]` under the rejected repair: its unit test could not match
    `mm²`/`°C` (an ASCII-only `[A-Za-z]+` suffix) and its passage-level test misfired on the
    surrounding words, so the values a question names were deleted."""
    assert question_values(question) == expected


# ---------------------------------------------------------------------------
# B. document and model identity, complete
# ---------------------------------------------------------------------------

IDENTITY_QUESTIONS = [
    ("Q/GDW 73286.2 规定的金属套厚度是多少？", ["73286.2"]),
    ("Q/GDW 73286.2-2026 是什么标准？", ["73286.2", "2026"]),
    ("IEC 60502-1:2021 对金属套厚度有什么规定？", ["60502", "1", "2021"]),
    ("GB/T 19666 表 6.2 的厚度要求是什么？", ["19666", "6.2"]),
    ("型号 123ABC 的电缆载流量是多少？", ["123"]),
    ("型号 AB123CD 的电缆载流量是多少？", ["123"]),
    ("WDZC-YJY-0.6/1kV 3×25 电缆的载流量是多少？", ["0.6", "1"]),
]


@pytest.mark.parametrize("question,identities", IDENTITY_QUESTIONS)
def test_b_identity_figures_are_not_values(question, identities):
    """`IEC 60502-1:2021` returned `['60502','2021']` and `123ABC` returned `['123']` as ANSWER values
    under the rejected repair - `IEC`/`ISO` were missing from the designation vocabulary it reused -
    so a question about a standard's own number was answered against the number itself."""
    values = question_values(question)
    for identity in identities:
        assert identity not in values, (question, identity, values)


def test_b_a_dimension_pair_beside_a_model_is_still_a_measurement():
    """`3×25` is a size notation, not part of the code - the contrast that keeps the model rule honest."""
    assert "25" in question_values("WDZC-YJY-0.6/1kV 3×25 电缆的载流量是多少？")


def test_b_a_designation_span_covers_the_reference_number_shape_too():
    text = "IEC 60502-1:2021"
    covered = "".join(text[start:end] for start, end in identity_spans(text))
    assert covered.replace(" ", "") == "IEC60502-1:2021"


def test_b_a_figure_led_section_notation_is_a_measurement():
    """`2000mm2` and `1x800mm2` are how this corpus writes a section with no space; the `x` is the
    multiplication sign `query_router._DIMENSION_PAIR_RE` already reads as one (`3x25`), not a name."""
    assert question_values("截面 2000mm2 的厚度是多少？") == ["2000"]
    assert question_values("1x800mm2 的厚度是多少？") == ["800"]


# ---------------------------------------------------------------------------
# C. context decides: the same digits, two classes
# ---------------------------------------------------------------------------


def test_c_a_year_the_question_asks_about_is_a_value():
    """Returned `[]` under the rejected repair, whose year cue was a bare `年`/`版`: `2026年，` matched
    it, so a question comparing two years lost both."""
    assert question_values("投产年份是否为2026年，而不是2025年？") == ["2026", "2025"]


@pytest.mark.parametrize(
    "question", ["2026 年版的海底电缆标准对铠装层有什么规定？", "2026年版的采购标准与2019年版有什么区别？"]
)
def test_c_an_edition_year_is_identity(question):
    assert question_values(question) == []


def test_c_a_bare_four_digit_measurement_is_not_a_year():
    assert question_values("2000 mm² 的导体直流电阻是多少？") == ["2000"]


def test_c_a_part_number_is_reported_not_claimed():
    """`第2部分` figures are removed by the PRE-EXISTING structural stripper
    (`strip_section_references`, shared with `parse_sub_queries`), which runs before classification -
    unchanged by this window and NOT silently claimed as fixed. Recording the actual behaviour keeps a
    future change visible here instead of surfacing as a regression."""
    from rag.retrieval.decomposition import strip_section_references

    assert "2" not in strip_section_references("适用部分到底是第2部分还是第3部分？")
    assert question_values("适用部分到底是第2部分还是第3部分？") == []


# ---------------------------------------------------------------------------
# D. the pool cannot decide what the question asked
# ---------------------------------------------------------------------------


def _pool(carries, size=20):
    body = "800 3.9 1200 220kV 1×800mm2" if carries else "内衬层与外被层的一般要求"
    return [chunk(body, doc_id=f"doc-{index}") for index in range(size)]


POOL_QUESTIONS = [
    "800 mm² 的厚度是多少？",
    "针对 800 mm² 与 1200 mm² 的电缆，厚度有什么区别？",
    "220kV 单芯海底电缆 800 mm² 截面的内衬层厚度要求是多少？",
    "Q/GDW 73286.2 与 Q/GDW 73286.3 中 800 mm² 与 1200 mm² 的电缆，金属套平均厚度分别是多少？",
    "投产年份是否为2026年，而不是2025年？",
]


@pytest.mark.parametrize("question", POOL_QUESTIONS)
def test_d_the_value_set_is_pool_independent(question):
    """The rejected repair removed figures by corpus share and its own unit test asserted that as a
    virtue. The audit's counterexample is this corpus's actual shape: a standard repeats its section
    series in every parameter table, so the question's own figures ARE the ubiquitous ones, and the
    universal-carry rule deleted exactly them."""
    bare = question_values(question)
    assert question_values(question, _pool(True)) == bare
    assert question_values(question, _pool(False)) == bare


def test_d_a_figure_the_whole_pool_carries_is_still_the_question_s_value():
    """The audit's exact counterexample: twenty candidates that all carry `800`, one of which pairs it."""
    pool = [chunk("800 mm² 的厚度要求是 1.5 mm", doc_id=f"doc-{index}") for index in range(20)]
    assert question_values("800 mm² 的厚度是多少？", pool) == ["800"]


def test_d_pool_share_survives_only_as_a_diagnostic():
    """`_pool_share` still reports discrimination and no extraction path calls it any more."""
    from rag.retrieval import decomposition

    pool = _pool(True)
    assert _pool_share("800", pool) == 1.0
    assert _pool_share("999", pool) == 0.0
    assert "_pool_share" not in decomposition.question_values.__code__.co_names


# ---------------------------------------------------------------------------
# E. the metadata boundary is the producer's, and its limitation is reported
# ---------------------------------------------------------------------------

PRODUCTION_HEADER = (
    "[标准号: Q/GDW 73286.2 | 文档: 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范.pdf"
    " | 电压: 220kV | 芯数: 单芯 | 线缆类别: 海底电力电缆 | 敷设环境: 海底 | 章节: 4 标准技术参数表] "
    "<table><caption>表1 电缆</caption><tr><td>3.9</td></tr></table>"
)
LEGACY_HEADER = (
    "[标准号: Q/GDW 73289.2-2026 | 文档: 450/750V聚氯乙烯绝缘电缆采购标准+第2部分：专用技术规范"
    " | 章节: 表1 技术参数特性表] <table><tr><td>导体</td><td>铜</td></tr></table>"
)
NESTED_HEADER = (
    "[标准号: Q/GDW 73286.3 | 文档: 规范[第3部分].pdf | 电压: 220kV | 章节: 4 表] "
    "<table><tr><td>3.9</td></tr></table>"
)
MID_BODY_QUOTE = "原文明确要求：[标准号: GB/T 10000 | 电压: 220kV]。导体截面 1×800 mm² 的厚度为 3.9 mm。"
TABLE_CELL_QUOTE = "<table><tr><td>原文要求 [标准号: GB/T 10000 | 电压: 220kV]</td><td>3.9</td></tr></table>"


def test_e_the_leading_header_is_metadata_not_evidence():
    table = chunk(PRODUCTION_HEADER, name="220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范.pdf")
    for value in ("73286.2", "220"):
        assert carries_value(table, (value,)) is False, value
    assert carries_value(table, ("3.9",)) is True


def test_e_the_deployed_ingest_s_legacy_header_is_also_stripped():
    """Two producers coexist on the live corpus: the deployed ingest writes the legacy three-field
    `[标准号: … | 文档: … | 章节: …]` (`doc_context`, the only one the image ships), while the Phase A
    backfill wrote the domain-attribute shape (`retrieval_projection`, run from the repository). Both
    verify against the same stored document name - and a header that cannot be verified is not removed."""
    table = chunk(LEGACY_HEADER, name="450/750V聚氯乙烯绝缘电缆采购标准+第2部分：专用技术规范.pdf")
    assert carries_value(table, ("73289.2",)) is False
    assert carries_value(table, ("2026",)) is False


def test_e_a_mid_body_quotation_of_the_field_list_is_evidence():
    """The audit's over-deletion: the rejected pattern matched its markers ANYWHERE in the passage, so
    this clause's figures disappeared from prose and from table cells alike."""
    prose = chunk(MID_BODY_QUOTE)
    assert carries_value(prose, ("10000",)) is True
    assert carries_value(prose, ("220",)) is True
    assert carries_value(prose, ("3.9",)) is True


def test_e_a_table_cell_quotation_of_the_field_list_is_evidence():
    assert carries_value(chunk(TABLE_CELL_QUOTE), ("10000",)) is True


def test_e_a_bracketed_title_is_a_reported_limitation_not_a_partial_strip():
    """The producer's pattern forbids brackets inside a header field and its writer does not escape
    them, so this header is unreadable to `split_retrieval_header` as well. The contract is that
    NOTHING is removed - a partial deletion is the dangerous half, which is what the rejected repair
    did, leaving the tail of the header in the passage as if it were evidence - and the residual stays
    visible."""
    from rag.retrieval.chunk_profile import _values_text

    table = chunk(NESTED_HEADER)
    assert carries_value(table, ("3.9",)) is True
    assert carries_value(table, ("73286.3",)) is True

    text = _values_text(table)
    assert text.startswith("[标准号:")
    assert "第3部分].pdf" in text  # nothing truncated mid-header
