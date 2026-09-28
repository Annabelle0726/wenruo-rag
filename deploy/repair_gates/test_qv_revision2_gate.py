"""QV Semantic Boundary Repair Revision 2 - the behavioural half of the formal gate.

These tests import ONLY what both revisions expose (`question_values`, `carries_value`, `paired_values`,
`_values_text`, the frozen `rerank`), so they COLLECT against the current revision and each audit
counterexample fails on its own semantics - which is the RED reproduction this window had to produce
before touching product code. The occurrence-provenance layer, which needs the model this revision adds,
is gated in `test_qv_revision2_occurrence_gate.py`.

Counterexamples A-H from the audit, by letter:

A. `[800 mm²：厚度3.9 mm] 后续要求` is body text, not metadata (layer 3)
B. a title containing `]` must never be partially deleted (layer 3)
C. `储能容量100kWh` - longest valid unit, not a `kW` prefix match (layer 1)
D. `电缆长度100m时` == `电缆长度100 m 时` (layer 1)
E. `ISO 9001:2015` is identity, not a measurement (layer 1)
F. `Q_GDW_73286.2-2026` must not leak (layer 1)
G. an edition the question ASKS about is answer-bearing (layer 2)
H. one digit string, two provenance records (layer 1 behaviour; fields in the occurrence gate)
"""
import hashlib
import pathlib
import sys

import pytest

sys.path.insert(0, "/ragflow")

from rag.retrieval import rerank as rerank_module
from rag.retrieval.chunk_profile import _values_text, carries_value, paired_values
from rag.retrieval.decomposition import question_values

RERANK_SHA256 = "1152c59a782766bfb219474cc9a00b7df5168c08c802d280252d8965af3e25cc"
RERANK_CONSTANTS = {
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


def chunk(content, name="part3.pdf", doc_id="doc-a"):
    return {"chunk_id": "c1", "doc_id": doc_id, "docnm_kwd": name, "content_with_weight": content}


def producer_recorded(content, name="part3.pdf", **kwargs):
    """A fixture for a chunk the PRODUCER wrote: its leading ``[...] `` prefix is recorded as injected.

    This is fixture construction, not boundary recovery. The tests that use it assert about a header the
    ingest wrote, so the fixture records exactly what a producer records; the tests that assert the
    fail-closed direction deliberately keep using :func:`chunk` with no provenance at all.
    """
    from rag.nlp.doc_context import LEGACY_PREFIX_VERSION, PREFIX_KIND_LEGACY, record_prefix

    payload = chunk(content, name=name, **kwargs)
    text = str(content)
    prefix = text[: text.index("] ") + 2] if "] " in text else ""
    if prefix and prefix.startswith("[标准号: "):
        record_prefix(payload, prefix, PREFIX_KIND_LEGACY, LEGACY_PREFIX_VERSION)
    return payload


def producer_recorded(content, name="part3.pdf", **kwargs):
    """A fixture for a chunk the PRODUCER wrote: its leading ``[...] `` prefix is recorded as injected.

    This is fixture construction, not boundary recovery. The tests that use it assert about a header the
    ingest wrote, so the fixture records exactly what a producer records; the tests that assert the
    fail-closed direction deliberately keep using :func:`chunk` with no provenance at all.
    """
    from rag.nlp.doc_context import LEGACY_PREFIX_VERSION, PREFIX_KIND_LEGACY, record_prefix

    payload = chunk(content, name=name, **kwargs)
    text = str(content)
    prefix = text[: text.index("] ") + 2] if "] " in text else ""
    if prefix and prefix.startswith("[标准号: "):
        record_prefix(payload, prefix, PREFIX_KIND_LEGACY, LEGACY_PREFIX_VERSION)
    return payload


# ===========================================================================
# LAYER 1 (behaviour) - the unit adapter
# ===========================================================================


@pytest.mark.parametrize(
    "question,expected",
    [
        # AUDIT C: `kW` and `kWh` both start at this position; the first-listed alternative won.
        ("储能容量100kWh 的电缆要求", ["100"]),
        # AUDIT D: `m` followed by a CJK character is not a `\b` boundary, so the tight writing lost the unit.
        ("电缆长度100m时的载流量", ["100"]),
        ("电缆长度100 m 时的载流量", ["100"]),
        # The rest of the unit shapes the audit's section 4 names: Unicode, no-space, compound, tolerance.
        ("试验压力 2.5MPa 下的要求", ["2.5"]),
        ("衰减 3.5dB 的电缆", ["3.5"]),
        ("导体工作温度 90℃ 时", ["90"]),
        ("截面 2000mm² 的厚度", ["2000"]),
        ("绝缘电阻不小于 100MΩ", ["100"]),
        ("扭矩 25N·m 的要求", ["25"]),
        ("厚度允许偏差 ±0.5mm", ["0.5"]),
        ("额定电压0.6/1 kV 的电缆", ["0.6"]),
        ("截面 800～1200mm² 的铠装层", ["800", "1200"]),
    ],
)
def test_layer1_the_unit_adapter_resolves_every_shape(question, expected):
    assert question_values(question) == expected, question


def test_layer1_d_the_spaced_and_unspaced_writings_agree_exactly():
    """AUDIT D, stated as the equivalence the audit demanded rather than as two separate cases."""
    assert question_values("电缆长度100m时的载流量") == question_values("电缆长度100 m 时的载流量") == ["100"]


# ===========================================================================
# LAYER 1 (behaviour) - identity completeness
# ===========================================================================


@pytest.mark.parametrize(
    "question",
    [
        # AUDIT E: a colon between number and edition.
        "依据 ISO 9001:2015 的电缆要求",
        # AUDIT F: the underscore spelling of a designation, as archived file names and pasted text write it.
        "依据Q_GDW_73286.2-2026 的电缆要求",
        "依据 Q/GDW 73286.2-2026 的电缆要求",
        "依据 Q/GDW 73286.2 的电缆要求",
        "IEC 60502-1:2021 对金属套厚度有什么规定？",
        "GB/T 19666 表 6.2 的厚度要求是什么？",
        "型号 123ABC 的电缆载流量是多少？",
        "型号 AB123CD 的电缆载流量是多少？",
    ],
)
def test_layer1_identity_shapes_do_not_leak_into_the_answer_values(question):
    assert question_values(question) == [], question


# ===========================================================================
# LAYER 1 (behaviour) - occurrence provenance is not collapsed by digit string
# ===========================================================================


def test_layer1_h_a_voltage_and_a_model_with_the_same_digits():
    """AUDIT H. Same sentence, same literal `0.6`, two meanings. The voltage IS asked about; the model
    code is a name. Any string-keyed provenance reports one verdict for both."""
    question = "额定电压0.6/1 kV、型号WDZC-YJY-0.6/1kV 的电缆载流量是多少？"
    assert question_values(question) == ["0.6"], question_values(question)


def test_layer1_h_the_model_side_alone_is_still_excluded():
    assert question_values("WDZC-YJY-0.6/1kV 3×25 电缆的载流量是多少？") == ["25"]


# ===========================================================================
# LAYER 2 - projection: identity located vs identity asked
# ===========================================================================


def test_layer2_g_an_edition_the_user_asks_for_is_a_requested_value():
    """AUDIT G. `year -> identity` was applied context-free, so a question whose ANSWER is the edition
    returned `[]`."""
    assert question_values("标准发布的是2026年版还是2025年版？") == ["2026", "2025"]
    assert question_values("这个标准是2026版还是2025版？") == ["2026", "2025"]


@pytest.mark.parametrize(
    "question",
    [
        "2026 年版的海底电缆标准对铠装层有什么规定？",
        "2026年版的采购标准与2019年版有什么区别？",
        "根据 Q/GDW 73286.2-2026，导体截面是多少？",
        "Q/GDW 73286.2-2026 是什么标准？",
    ],
)
def test_layer2_an_edition_that_only_locates_the_document_is_not_a_value(question):
    assert question_values(question) == [], question


def test_layer2_the_projection_keeps_each_distinct_figure_once_in_question_order():
    assert question_values("针对 800 mm² 与 1200 mm² 的电缆，内衬层厚度有什么区别？") == ["800", "1200"]
    assert question_values("投产年份是否为2026年，而不是2025年？") == ["2026", "2025"]
    assert question_values("2000 mm² 的导体直流电阻是多少？") == ["2000"]
    assert question_values("海底电缆的内衬层有什么要求？") == []
    assert question_values("第 2 部分") == []
    assert question_values("表 1") == []


def test_layer2_pool_independence_is_frozen():
    """Codex proved this PASS independently; frequency may not return as a factor."""
    questions = [
        "800 mm² 的厚度是多少？",
        "针对 800 mm² 与 1200 mm² 的电缆，厚度有什么区别？",
        "220kV 单芯海底电缆 800 mm² 截面的内衬层厚度要求是多少？",
        "标准发布的是2026年版还是2025年版？",
    ]
    pools = [
        (),
        [chunk("800 3.9 1200 220kV") for _ in range(20)],
        [chunk("内衬层与外被层的一般要求") for _ in range(20)],
    ]
    for question in questions:
        bare = question_values(question)
        for pool in pools:
            assert question_values(question, pool) == bare, question


# ===========================================================================
# LAYER 3 - chunk evidence and the metadata boundary
# ===========================================================================

#: Read out of the live index during this window: the exact legacy header the deployed ingest writes.
LIVE_HEADER = "[标准号: Q/GDW 73237.1-2026 | 文档: 10kV架空绝缘电缆采购标准+第1部分：通用技术规范 | 章节: 4.5.2 完成合同设备安装后，买方和卖方应检查和确认安装工作，并签署安装工作完] "
LIVE_CHUNK_NAME = "10kV架空绝缘电缆采购标准+第1部分：通用技术规范.pdf"

#: Also read out of the live index: the Phase-A backfill's richer header.
BACKFILL_HEADER = (
    "[标准号: Q/GDW 73286.2 | 文档: 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范.pdf"
    " | 电压: 220kV | 芯数: 单芯 | 线缆类别: 海底电力电缆 | 敷设环境: 海底 | 章节: 4 标准技术参数表] "
)
BACKFILL_NAME = "220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范.pdf"


def test_layer3_the_live_ingest_header_is_not_evidence():
    table = producer_recorded(f"{LIVE_HEADER}<table><tr><td>导体</td><td>铜</td></tr></table>", name=LIVE_CHUNK_NAME)
    assert carries_value(table, ("73237.1",)) is False
    assert carries_value(table, ("2026",)) is False


def test_layer3_the_backfill_header_is_not_evidence():
    table = producer_recorded(f"{BACKFILL_HEADER}<table><tr><td>导体</td><td>铜</td></tr></table>", name=BACKFILL_NAME)
    assert carries_value(table, ("73286.2",)) is False
    assert carries_value(table, ("220",)) is False


def test_layer3_the_body_figure_beside_a_header_is_still_evidence():
    table = producer_recorded(f"{BACKFILL_HEADER}<table><tr><td>800</td><td>3.9</td></tr></table>", name=BACKFILL_NAME)
    assert carries_value(table, ("800",)) is True
    assert paired_values(table, ("800",)) == {"800"}


def test_layer3_a_the_body_bracket_is_evidence_not_metadata():
    """AUDIT A. `[800 mm²：厚度3.9 mm]` is the document's own bracket. Inferring "leading bracket ==
    injected metadata" from SHAPE deletes it - the boundary may not be inferred from shape."""
    prose = chunk("[800 mm²：厚度3.9 mm] 后续要求")
    assert carries_value(prose, ("800",)) is True
    assert carries_value(prose, ("3.9",)) is True


def test_layer3_b_a_bracket_in_the_title_never_partially_deletes():
    """AUDIT B. `render_document_context('Q/GDW 73286.3', '规范]附录.pdf', '4')` writes a header whose own
    title contains `]`. Cutting at the first `]` leaves the tail of the header behind AS IF it were
    evidence. For a header the producer cannot read back either, the only safe actions are all or nothing."""
    header = "[标准号: Q/GDW 73286.3 | 文档: 规范]附录.pdf | 章节: 4] "
    table = producer_recorded(f"{header}<table><tr><td>3.9</td></tr></table>", name="规范]附录.pdf")
    text = _values_text(table)
    assert carries_value(table, ("73286.3",)) is False, text[:200]
    assert "附录.pdf" not in text, text[:200]
    assert carries_value(table, ("3.9",)) is True


def test_layer3_malformed_metadata_fails_closed():
    wrong = "[标准号: Q/GDW 73286.3 | 文档: 完全不同的文档.pdf | 电压: 220kV] <table><tr><td>3.9</td></tr></table>"
    table = chunk(wrong, name="part3.pdf")
    assert carries_value(table, ("73286.3",)) is True
    assert carries_value(table, ("220",)) is True


def test_layer3_missing_document_name_fails_closed():
    bare = {"chunk_id": "c1", "content_with_weight": f"{LIVE_HEADER}<table><tr><td>3.9</td></tr></table>"}
    assert carries_value(bare, ("73237.1",)) is True


def test_layer3_an_unlabelled_leading_bracket_fails_closed():
    table = chunk("[此处为原文引用 800 mm² 的说明] <table><tr><td>3.9</td></tr></table>", name="part3.pdf")
    assert carries_value(table, ("800",)) is True


def test_layer3_a_verified_header_is_removed_whole_never_as_a_prefix():
    text = _values_text(producer_recorded(f"{BACKFILL_HEADER}<table><tr><td>3.9</td></tr></table>", name=BACKFILL_NAME))
    assert not text.startswith("[标准号"), text[:120]
    assert "标准号" not in text and "芯数" not in text
    assert "3.9" in text


# ===========================================================================
# LAYER 4 - frozen consumer integration
# ===========================================================================


def test_layer4_the_consumer_module_is_byte_identical_to_the_deployed_image():
    text = pathlib.Path("/ragflow/rag/retrieval/rerank.py").read_text(encoding="utf-8")
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == RERANK_SHA256, "rerank.py must not change"


def test_layer4_the_consumer_multipliers_are_unchanged():
    for name, expected in RERANK_CONSTANTS.items():
        assert getattr(rerank_module, name) == expected, name


def _rank_ratio(content, **overrides):
    base = {"table_penalty": 1.0, "core_document_boost": 1.0, "question_values": frozenset({"800"})}
    base.update(overrides)
    target = chunk(content)
    target["similarity"] = 0.5
    return rerank_module.apply_rank_adjustments([target], rerank_module.DiversityPolicy(**base))[0]["rank_score"] / 0.5


def test_layer4_a_pairing_value_still_gets_the_boost():
    assert _rank_ratio("<table><tr><td>800</td><td>3.9</td></tr></table>") == pytest.approx(
        rerank_module.VALUE_PAIRING_BOOST, rel=1e-9
    )


def test_layer4_a_non_pairing_value_still_gets_the_penalty():
    assert _rank_ratio("<table><tr><td>800</td><td>1000</td><td>1200</td></tr></table>") == pytest.approx(
        rerank_module.VALUE_LIST_PENALTY, rel=1e-9
    )


def test_layer4_a_correct_value_set_drives_the_frozen_rules_end_to_end():
    values = question_values("800 mm² 的厚度是多少？")
    table = chunk("<table><tr><td>800</td><td>3.9</td></tr></table>")
    assert paired_values(table, tuple(values)) == {"800"}
    table["similarity"] = 0.5
    policy = rerank_module.DiversityPolicy(table_penalty=1.0, core_document_boost=1.0, question_values=frozenset(values))
    assert rerank_module.apply_rank_adjustments([table], policy)[0]["rank_score"] / 0.5 == pytest.approx(
        rerank_module.VALUE_PAIRING_BOOST, rel=1e-9
    )
