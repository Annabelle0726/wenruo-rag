"""Offline gates for the question-value feature repair: semantics, and a frozen consumer proof.

Two things are proved here and they are deliberately separate.

**Feature semantics** - `question_values` must stop reading DOCUMENT IDENTITY as answer-bearing, and
must stop discarding answer-bearing technical values for being common; `chunk_profile._values_text`
must stop treating the ingest's identity preamble as the passage's own evidence. Groups A-F are the
operator's regression matrix.

**Frozen consumers** - the `×1.3` pairing boost, the `×0.8` value-list penalty and the selection and
warning consumers must be provably untouched. Group G proves it two ways: the consumer module's bytes
are identical to the deployed image's, and feeding a KNOWN value set through the REAL
`apply_rank_adjustments` reproduces the exact multipliers.

No network, no index, no pool required: this is deterministic text and arithmetic, which is why it can
be gated while the dense leg is degraded. Nothing here asserts anything about recall.
"""
import hashlib
import pathlib
import re
import sys

import pytest

sys.path.insert(0, "/ragflow")

from rag.retrieval import rerank as rerank_module
from rag.retrieval.chunk_profile import carries_value, identity_spans, paired_values, standard_designations
from rag.retrieval.decomposition import question_values

#: The deployed consumer module. Its hash is asserted so a repair that leaked into the ordering or the
#: cut fails here rather than being discovered in a query.
RERANK_SHA256 = "1152c59a782766bfb219474cc9a00b7df5168c08c802d280252d8965af3e25cc"
#: The consumer multipliers, frozen by this window's authorisation.
FROZEN_CONSTANTS = {
    "VALUE_PAIRING_BOOST": 1.3,
    "VALUE_LIST_PENALTY": 0.8,
    "TABLE_PENALTY": 0.85,
    "CORE_DOCUMENT_BOOST": 1.15,
    "HOLLOW_TABLE_PENALTY": 0.6,
    "MAX_TABLE_SHARE": 0.5,
    "MIN_PROSE_PASSAGES": 4,
    "MAX_AUXILIARY_DOCUMENT_SHARE": 0.4,
    "MAX_COMPARED_DOCUMENT_SHARE": 0.5,
}

QGDW_COMPOSITE = "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"
QGDW_WITH_FIGURE = "Q/GDW 73286.2-2026 表 1 中 800 mm² 单芯电缆的导体标称截面规格数量是多少？"
MODEL_NUMBER = "WDZC-YJY-0.6/1kV 3×25 电缆的载流量是多少？"
TECHNICAL_VALUE = "220kV 单芯海底电缆 800 mm² 截面的内衬层厚度要求是多少？"
MULTI_VALUE = "针对 800 mm² 与 1200 mm² 的单芯与三芯电缆，内衬层厚度要求有什么区别？"
YEAR_ONLY = "2026 年版的海底电缆标准对铠装层有什么规定？"
YEAR_AS_MEASUREMENT = "2000 mm² 的导体直流电阻是多少？"
PLAIN = "海底电缆的内衬层有什么要求？"

HEADER = "[标准号: Q/GDW 73286.3 | 文档: 220kV海底电力电缆系统采购标准+第3部分.pdf | 电压: 220kV | 芯数: 三芯 | 章节: 4 标准规范性要素]"


def chunk(content, doc_id="doc-a", name="part3.pdf"):
    return {"chunk_id": "c1", "doc_id": doc_id, "docnm_kwd": name, "content_with_weight": content}


def pool_with(value, size=20, hits=None):
    """A pool where `value` is carried by `hits` of `size` chunks (default: nearly all of them)."""
    hits = size - 1 if hits is None else hits
    out = []
    for index in range(size):
        body = f"{value} mm² 的厚度要求是 1.5 mm" if index < hits else "内衬层与外被层的一般要求"
        out.append(chunk(body, doc_id=f"doc-{index}"))
    return out


# ---------------------------------------------------------------------------
# A. standard number + year must not be answer-bearing values
# ---------------------------------------------------------------------------


def test_a_standard_designation_and_its_year_are_not_values():
    values = question_values(QGDW_COMPOSITE)
    assert values == [], values
    for identity in ("73286.2", "73286.3", "2026"):
        assert identity not in values


def test_a_designation_only_question_yields_no_values():
    assert question_values("Q/GDW 73286.2-2026 是什么标准？") == []


def test_a_year_reference_is_not_a_value():
    assert question_values(YEAR_ONLY) == []


def test_a_bare_four_digit_measurement_is_still_a_value():
    """The year rule needs its cue, so a measurement that merely looks like a year survives."""
    assert question_values(YEAR_AS_MEASUREMENT) == ["2000"]


def test_identity_spans_cover_the_designation_and_its_year():
    text = " ".join(QGDW_COMPOSITE.split())
    spans = identity_spans(text)
    assert len(spans) == 2
    covered = "".join(text[start:end] for start, end in spans)
    assert "73286.2-2026" in covered.replace(" ", "")
    assert "73286.3-2026" in covered.replace(" ", "")


def test_the_normalized_designation_api_is_unchanged():
    """`standard_designations` is what document resolution uses; the new span helper must not alter it."""
    assert standard_designations("Q/GDW 73286.2-2026 是什么标准？") == {"QGDW73286.2"}


# ---------------------------------------------------------------------------
# B. genuine technical values survive a high pool share
# ---------------------------------------------------------------------------


def test_b_technical_values_survive_a_high_pool_share():
    pool = pool_with("800", size=20, hits=19)  # share 0.95, the measured corpus case
    assert "800" in question_values("800 mm² 的厚度是多少？", pool)
    pool = pool_with("800", size=30, hits=25)  # share 0.833, the measured multi-value case
    values = question_values("针对 800 mm² 与 1200 mm² 的电缆，厚度有什么区别？", pool_with("800", size=30, hits=25))
    assert "800" in values


def test_b_multi_value_question_keeps_both_values():
    assert question_values(MULTI_VALUE) == ["800", "1200"]


def test_b_only_a_universal_value_is_dropped():
    """The degenerate case, stated as such: a token EVERY candidate carries cannot separate two of
    them. It is an equality, not a tuned ratio - 0.95 and 0.83 are preserved above."""
    universal = pool_with("800", size=20, hits=20)
    assert question_values("800 mm² 的厚度是多少？", universal) == []
    nearly = pool_with("800", size=20, hits=19)
    assert question_values("800 mm² 的厚度是多少？", nearly) == ["800"]


def test_b_technical_value_query_keeps_every_declared_kind():
    values = question_values(TECHNICAL_VALUE)
    assert "220" in values and "800" in values


# ---------------------------------------------------------------------------
# C. model numbers must not supply answer values
# ---------------------------------------------------------------------------


def test_c_a_model_code_contributes_no_value():
    values = question_values(MODEL_NUMBER)
    assert "0.6" not in values, values


def test_c_a_dimension_pair_next_to_a_model_is_still_a_measurement():
    """`3×25` is a size notation, not part of the code; its figure stays a value."""
    assert "25" in question_values(MODEL_NUMBER)


def test_c_a_model_code_no_longer_drives_the_pairing_boost():
    """The measured defect: `0.6` from `WDZC-YJY-0.6/1kV` fired the boost on a 0.0836-similarity table."""
    values = question_values(MODEL_NUMBER)
    table = chunk("<table><tr><td>载流量</td><td>0.6</td></tr></table>")
    assert paired_values(table, tuple(values)) == set()


# ---------------------------------------------------------------------------
# D. a table whose BODY carries the value must still be recognized
# ---------------------------------------------------------------------------


def test_d_table_body_value_is_carried_and_paired():
    table = chunk("<table><caption>表1</caption><tr><td>800</td><td>3.9</td></tr></table>")
    assert carries_value(table, ("800",)) is True
    assert paired_values(table, ("800",)) == {"800"}


def test_d_body_value_is_recognised_when_the_header_is_also_present():
    table = chunk(f"{HEADER} <table><tr><td>800</td><td>3.9</td></tr></table>")
    assert carries_value(table, ("800",)) is True
    assert paired_values(table, ("800",)) == {"800"}


# ---------------------------------------------------------------------------
# E. the ingest metadata preamble is not evidence
# ---------------------------------------------------------------------------


def test_e_a_header_only_designation_is_not_carried():
    table = chunk(f"{HEADER} <table><tr><td>导体</td><td>铜</td></tr></table>")
    assert carries_value(table, ("73286.3",)) is False


def test_e_a_header_only_technical_figure_is_not_carried():
    """`电压: 220kV` in the preamble is metadata about the document, not evidence in the passage."""
    table = chunk(f"{HEADER} <table><tr><td>导体</td><td>铜</td></tr></table>")
    assert carries_value(table, ("220",)) is False


def test_e_the_same_figure_in_the_body_is_still_carried():
    """The removal is scoped to the metadata block, so a genuine body figure still matches."""
    table = chunk(f"{HEADER} <table><tr><td>导体</td><td>800</td></tr></table>")
    assert carries_value(table, ("800",)) is True


def test_e_prose_without_the_preamble_is_unaffected():
    prose = chunk("内衬层的标称厚度应不小于 1.5 mm。")
    assert carries_value(prose, ("1.5",)) is True


def test_e_an_ordinary_bracketed_phrase_is_not_stripped():
    """Only a block carrying the ingest's identity markers is metadata."""
    prose = chunk("试验条件 [温度 20 ℃ 湿度 60 %] 下的载流量为 500 A。")
    assert carries_value(prose, ("20",)) is True
    assert carries_value(prose, ("500",)) is True


def test_e_metadata_value_detection_is_value_independent():
    """No figure is special-cased: ANY value that lives only in the preamble is not carried."""
    table = chunk(f"{HEADER} <table><tr><td>导体</td><td>铜</td></tr></table>")
    for value in ("73286.3", "2026", "220", "73286.2"):
        assert carries_value(table, (value,)) is False, value


# ---------------------------------------------------------------------------
# F. ordinary queries are not disturbed
# ---------------------------------------------------------------------------


def test_f_a_non_numeric_question_has_no_values():
    assert question_values(PLAIN) == []


def test_f_an_empty_or_dimension_only_question_has_no_values():
    assert question_values("") == []
    assert question_values("第 2 部分") == []
    assert question_values("表 1") == []


def test_f_a_question_naming_only_a_designation_does_not_change_theordering():
    """The measured composite case: with no values the ordering value is the plain score."""
    assert question_values(QGDW_COMPOSITE) == []


# ---------------------------------------------------------------------------
# G. FROZEN CONSUMERS
# ---------------------------------------------------------------------------


def test_g_consumer_module_is_byte_identical_to_the_deployed_image():
    text = pathlib.Path("/ragflow/rag/retrieval/rerank.py").read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert digest == RERANK_SHA256, "rerank.py changed; this window may not touch the consumers"


def test_g_consumer_multipliers_are_unchanged():
    for name, expected in FROZEN_CONSTANTS.items():
        assert getattr(rerank_module, name) == expected, name


def test_g_consumer_symbols_are_unchanged():
    """A byte-identical file cannot have lost a consumer; assert they are still callable anyway."""
    for name in ("apply_rank_adjustments", "select_context", "dedupe_chunks", "_warn_when_a_value_passage_was_cut", "by_fused_or_reranked" if hasattr(rerank_module, "by_fused_or_reranked") else "_by_fused_score"):
        assert callable(getattr(rerank_module, name)), name


def _isolation_policy(**overrides):
    """A policy whose type and document multipliers are 1.0, so a rank_score/base RATIO isolates the
    value multiplier that this window must not have changed."""
    base = {"table_penalty": 1.0, "core_document_boost": 1.0, "question_values": frozenset({"800"})}
    base.update(overrides)
    return rerank_module.DiversityPolicy(**base)


def _rank_ratio(content, **overrides):
    policy = _isolation_policy(**overrides)
    target = chunk(content)
    target["similarity"] = 0.5
    ordered = rerank_module.apply_rank_adjustments([target], policy)
    return ordered[0]["rank_score"] / 0.5


def test_g_pairing_boost_still_applies_exactly_1_3_given_a_pairing_value():
    assert _rank_ratio("<table><tr><td>800</td><td>3.9</td></tr></table>") == pytest.approx(
        rerank_module.VALUE_PAIRING_BOOST, rel=1e-9
    )


def test_g_value_list_penalty_still_applies_exactly_0_8_given_a_non_pairing_value():
    assert _rank_ratio("<table><tr><td>800</td><td>1000</td><td>1200</td></tr></table>") == pytest.approx(
        rerank_module.VALUE_LIST_PENALTY, rel=1e-9
    )


def test_g_the_table_penalty_still_composes_with_the_pairing_boost():
    assert _rank_ratio("<table><tr><td>800</td><td>3.9</td></tr></table>", table_penalty=0.85) == pytest.approx(
        0.85 * rerank_module.VALUE_PAIRING_BOOST, rel=1e-9
    )


def test_g_prose_without_a_value_keeps_its_plain_score():
    assert _rank_ratio("内衬层的一般要求。") == pytest.approx(1.0, rel=1e-9)


def test_g_no_consumer_rule_was_added_or_removed():
    """The two branches the value input feeds, and nothing else, exist in the ordering pass."""
    source = pathlib.Path("/ragflow/rag/retrieval/rerank.py").read_text(encoding="utf-8")
    assert source.count("paired_values(") == 3  # ordering, compared-document reservation, warning
    assert source.count("carries_value(") == 1
