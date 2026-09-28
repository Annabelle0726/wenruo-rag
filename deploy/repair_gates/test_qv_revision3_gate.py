"""QV Numeric Semantics Revision 3 - the gate, written BEFORE the implementation.

Codex rejected Revision 2 with numeric counterexamples that split into four families, and this module
states the required semantics for each. Its RED run against Revision 2 is the reproduction.

**A - intent binding is LOCAL.** A sentence-level connective may not promote every occurrence of a class
it happens to sit near. `还是` binds the two figures it compares, not the designation digits in front of
them (`根据 Q/GDW 73286.2-2026，厚度是3.9还是4.1mm？`), and a locator year protected by `根据` stays a
locator even while another year in the same sentence is the answer.

**B - offsets are ORIGINAL-QUESTION offsets.** Every published occurrence must satisfy
`question[start:end] == occurrence.text`. Revision 2 returned offsets into a NORMALIZED string, so
`第12部分  电压  220kV` could not round-trip.

**C - unit normalization is consistent.** `100m时`, `100 m 时`, `100\\tm`, `100\\nm` are one measurement.

**D - invariants, not examples.** The properties below are asserted as properties: locality (D1),
independence of repeated text (D2), projection legality (D3), offset round-trip (D4), pool independence (D5).
"""
import sys

import pytest

sys.path.insert(0, "/ragflow")

from rag.retrieval import chunk_profile
from rag.retrieval.chunk_profile import (
    NUMERIC_ANSWER_VALUE,
    NUMERIC_IDENTITY_ASKED,
    NUMERIC_IDENTITY_LOCATOR,
    NUMERIC_MODEL_IDENTITY,
    NUMERIC_TECHNICAL_MEASUREMENT,
    NUMERIC_VALUE_CLASSES,
    numeric_occurrences,
)
from rag.retrieval.decomposition import question_value_occurrences, question_values

try:  # the original-offset API this revision adds
    from rag.retrieval.decomposition import question_numeric_occurrences
except ImportError:  # Revision 2 has no such API; fall back so the counterexamples still RUN and fail

    def question_numeric_occurrences(question):  # type: ignore[misc]
        return numeric_occurrences(question)


def occurrence_map(question):
    """``{text: [occurrence, ...]}`` over the ORIGINAL question, so duplicates are not collapsed."""
    grouped = {}
    for occurrence in question_numeric_occurrences(question):
        grouped.setdefault(occurrence.text, []).append(occurrence)
    return grouped


def kinds(question):
    return sorted(occurrence.kind for occurrence in question_value_occurrences(question))


def test_b_the_original_offset_api_exists():
    """AUDIT B's first half: Revision 2 published no occurrence API whose offsets index the question the
    caller passed - `question_value_occurrences` offsets belonged to a normalized copy, which is why the
    round-trip assertions below could not even be expressed."""
    import rag.retrieval.decomposition as decomposition

    assert hasattr(decomposition, "question_numeric_occurrences")


# ===========================================================================
# A1 - occurrence-local intent binding
# ===========================================================================


def test_a1_a_choice_connector_does_not_promote_the_designation_in_front_of_it():
    """AUDIT A1. `还是` compares 3.9 and 4.1; the designation it does NOT compare must stay a locator."""
    question = "根据 Q/GDW 73286.2-2026，厚度是3.9还是4.1mm？"
    grouped = occurrence_map(question)
    assert grouped["73286.2"][0].kind == NUMERIC_IDENTITY_LOCATOR, grouped["73286.2"][0]
    assert grouped["2026"][0].kind == NUMERIC_IDENTITY_LOCATOR, grouped["2026"][0]
    assert question_values(question) == ["3.9", "4.1"], question_values(question)
    assert grouped["3.9"][0].kind in (NUMERIC_TECHNICAL_MEASUREMENT, NUMERIC_ANSWER_VALUE)
    assert grouped["4.1"][0].kind == NUMERIC_TECHNICAL_MEASUREMENT


def test_a1_the_locator_is_protected_wherever_the_connective_sits():
    """The same question with the comparison FIRST and the locator last: locality must hold both ways."""
    question = "厚度是3.9还是4.1mm，依据 GB/T 12706.2-2020？"
    assert question_values(question) == ["3.9", "4.1"], question_values(question)
    assert occurrence_map(question)["12706.2"][0].kind == NUMERIC_IDENTITY_LOCATOR


# ===========================================================================
# A2 - locator year vs answer year
# ===========================================================================


def test_a2_a_locator_year_stays_a_locator_while_another_year_is_the_answer():
    """AUDIT A2. `根据2026版` locates; `是2025版还是2024版` asks. One sentence, two verdicts."""
    question = "根据2026版，投产依据是2025版还是2024版？"
    grouped = occurrence_map(question)
    assert grouped["2026"][0].kind == NUMERIC_IDENTITY_LOCATOR, grouped["2026"][0]
    assert question_values(question) == ["2025", "2024"], question_values(question)
    assert grouped["2025"][0].kind == NUMERIC_IDENTITY_ASKED
    assert grouped["2024"][0].kind == NUMERIC_IDENTITY_ASKED


def test_a2_the_noun_依据_inside_a_word_is_not_a_locator_phrase():
    """`投产依据` is a noun; only a clause-initial preposition binds a locator. Otherwise the answer year
    would be demoted by the word it sits in."""
    question = "投产依据是2025版还是2024版？"
    assert question_values(question) == ["2025", "2024"], question_values(question)


# ===========================================================================
# A3 - identity itself is the answer
# ===========================================================================


def test_a3_1_a_question_about_the_standard_number_asks_for_it():
    question = "GB/T 12706.2-2020的标准号是多少？"
    assert question_values(question) == ["12706.2", "2020"], question_values(question)
    assert occurrence_map(question)["12706.2"][0].kind == NUMERIC_IDENTITY_ASKED


def test_a3_2_a_model_code_the_question_asks_about_is_a_value():
    question = "型号为AB123CD吗？"
    assert question_values(question) == ["123"], question_values(question)
    assert occurrence_map(question)["123"][0].kind == NUMERIC_IDENTITY_ASKED


def test_a3_3_a_list_followed_by_an_interrogative_asks_for_its_members():
    question = "2026年版、2025年版，哪一个是现行版本？"
    assert question_values(question) == ["2026", "2025"], question_values(question)
    assert set(kinds(question)) == {NUMERIC_IDENTITY_ASKED}


def test_a3_4_a_comparison_of_two_parts_asks_for_both():
    question = "Q/GDW 73286.2 和 73286.3 哪一部分规定了金属套厚度？"
    assert question_values(question) == ["73286.2", "73286.3"], question_values(question)


def test_a3_5_a_comparison_of_two_tables_keeps_the_technical_figure():
    question = "表1和表2哪个包含800 mm²？"
    assert question_values(question) == ["800"], question_values(question)


def test_a3_no_sentence_global_cue_promotes_a_class():
    """The rejected model upgraded every occurrence of a class when the sentence contained a cue. The two
    sentences below both contain `还是`; in the first it compares technical figures and the designation is a
    locator, in the second it compares editions. Neither may leak into the other's class."""
    technical = "根据 Q/GDW 73286.2-2026，厚度是3.9还是4.1mm？"
    editions = "根据2026版，投产依据是2025版还是2024版？"
    assert "73286.2" not in question_values(technical)
    assert "2026" not in question_values(editions)
    assert question_values(technical) == ["3.9", "4.1"]
    assert question_values(editions) == ["2025", "2024"]


# ===========================================================================
# B - the occurrence offset contract
# ===========================================================================


@pytest.mark.parametrize(
    "question",
    [
        "第12部分  电压  220kV",
        "第12部分\t电压\t220kV",
        "第12部分\n电压\n220kV",
        "  第5章  5.3.3  绝缘标称厚度 1.2mm 是多少？  ",
        "根据　Q/GDW 73286.2-2026，厚度是3.9还是4.1mm？",
        "针对 800 mm² 与 1200 mm² 的电缆，厚度有什么区别？",
        "型号 WDZC-YJY-0.6/1kV 3×25 与 AB123CD 的载流量？",
        "截面 800～1200mm²，偏差 ±0.5mm，长度 100m。",
    ],
)
def test_b_every_published_occurrence_round_trips_to_the_original_question(question):
    """AUDIT B. Revision 2 handed out offsets into a normalized copy, so they pointed at the wrong
    characters in the question the caller actually passed."""
    published = list(question_numeric_occurrences(question)) + list(question_value_occurrences(question))
    assert published, question
    for occurrence in published:
        assert question[occurrence.start : occurrence.end] == occurrence.text, (
            question,
            occurrence,
            question[occurrence.start : occurrence.end],
        )


def test_b_the_projection_keeps_the_original_offsets_too():
    question = "第12部分  电压  220kV"
    projected = question_value_occurrences(question)
    assert [item.text for item in projected] == ["220"]
    item = projected[0]
    assert question[item.start : item.end] == "220"
    assert item.end <= len(question)


def test_b_normalization_can_shorten_the_text_and_the_offsets_still_hold():
    """The section word is removed by normalization; the surviving figure's offsets must still index the
    ORIGINAL string, not the shortened copy."""
    question = "第5章 5.3.3 绝缘标称厚度 1.2mm 是多少？"
    item = [occurrence for occurrence in question_numeric_occurrences(question) if occurrence.text == "1.2"][0]
    assert question[item.start : item.end] == "1.2"
    assert item.start > 10


def test_b_repeated_whitespace_and_tabs_do_not_shift_the_offsets():
    for question in ("电压  220kV  1.5mm", "电压\t220kV\t1.5mm", "电压\n220kV\n1.5mm"):
        for occurrence in question_numeric_occurrences(question):
            assert question[occurrence.start : occurrence.end] == occurrence.text, (question, occurrence)


def test_b_a_full_width_dot_is_reported_as_written():
    """Canonical equivalence, recorded explicitly: the CLASS is decided on the canonical form
    (`1.5`), while `text` and the offsets are the original spelling (`1．5`)."""
    question = "绝缘厚度 1．5mm 的要求"
    occurrences = question_numeric_occurrences(question)
    thickness = [item for item in occurrences if item.text in ("1.5", "1．5")][0]
    assert question[thickness.start : thickness.end] == thickness.text
    assert thickness.kind == NUMERIC_TECHNICAL_MEASUREMENT


# ===========================================================================
# C - unit normalization consistency
# ===========================================================================


@pytest.mark.parametrize("raw", ["电缆长度100m时的载流量", "电缆长度100 m 时的载流量", "电缆长度100\tm 时的载流量", "电缆长度100\nm 时的载流量"])
def test_c_every_whitespace_spelling_is_one_measurement(raw):
    """AUDIT C. Tabs and newlines are whitespace to a reader and different bytes to a regex; the classifier
    must not disagree with itself about the same measurement."""
    occurrences = [item for item in question_numeric_occurrences(raw) if item.text == "100"]
    assert [item.kind for item in occurrences] == [NUMERIC_TECHNICAL_MEASUREMENT], occurrences
    assert question_values(raw) == ["100"]


def test_c_the_raw_classifier_and_the_projection_agree():
    """The projection normalizes and the raw classifier does not; both must reach the same verdict for the
    same spelling."""
    for raw in ("100m时", "100 m 时", "100\tm 时", "100\nm 时"):
        raw_kind = [item.kind for item in numeric_occurrences(raw) if item.text == "100"]
        assert raw_kind == [NUMERIC_TECHNICAL_MEASUREMENT], (raw, raw_kind)


# ===========================================================================
# D - invariants
# ===========================================================================


def test_d1_a_connective_changes_nothing_outside_its_comparison_span():
    """D1 as a property: prepend a locator to a comparison question and the locator's class is unchanged
    while the answer set is unchanged as well."""
    base = "厚度是3.9还是4.1mm？"
    for prefix in ("根据 Q/GDW 73286.2-2026，", "依据 GB/T 12706.2-2020，", "第3部分规定，"):
        question = prefix + base
        assert question_values(question) == question_values(base) == ["3.9", "4.1"], question


def test_d2_repeated_text_is_classified_per_occurrence():
    """D2 as a property: same literal, different roles, independent verdicts."""
    question = "额定电压0.6/1 kV、型号WDZC-YJY-0.6/1kV 与 0.6 的厚度？"
    records = occurrence_map(question)["0.6"]
    assert len(records) == 3, records
    assert len({item.start for item in records}) == 3
    # sorted() is alphabetical: the bare asked figure, the model code, the voltage - three verdicts.
    assert sorted(item.kind for item in records) == [
        NUMERIC_ANSWER_VALUE,
        NUMERIC_MODEL_IDENTITY,
        NUMERIC_TECHNICAL_MEASUREMENT,
    ]
    assert question_values(question) == ["0.6"]


def test_d3_the_projection_only_contains_allowed_classes_and_keeps_records_intact():
    """D3 as a property: every projected occurrence is one of the input records, carries an allowed class,
    and survives its own round-trip."""
    questions = [
        "根据 Q/GDW 73286.2-2026，厚度是3.9还是4.1mm？",
        "额定电压0.6/1 kV、型号WDZC-YJY-0.6/1kV 的电缆载流量？",
        "截面 800～1200mm² 的铠装层要求？",
        "标准发布的是2026年版还是2025年版？",
        "第12部分  电压  220kV",
    ]
    for question in questions:
        records = {(item.start, item.end): item for item in question_numeric_occurrences(question)}
        for projected in question_value_occurrences(question):
            assert projected.kind in NUMERIC_VALUE_CLASSES, (question, projected)
            same = records.get((projected.start, projected.end))
            assert same is not None and same == projected, (question, projected)
            assert question[projected.start : projected.end] == projected.text


def test_d4_offsets_index_the_question_that_was_passed():
    """D4 as a property over a table of shapes, including one where normalization removes text."""
    questions = [
        "第12部分  电压  220kV",
        "第5章 5.3.3 绝缘标称厚度 1.2mm",
        "附录A 表6.2 的 800 mm² 厚度",
        "Q/GDW 73286.2-2026 中 3.9 与 4.1 的差别",
        "型号AB123CD与WDZC-YJY-0.6/1kV 3×25",
    ]
    for question in questions:
        occurrences = question_numeric_occurrences(question)
        assert occurrences, question
        for occurrence in occurrences:
            assert question[occurrence.start : occurrence.end] == occurrence.text, (question, occurrence)


def test_d5_the_pool_cannot_change_a_class_or_the_projection():
    """D5 as a property: classes come from the text; the pool is not an input to classification."""
    question = "根据 Q/GDW 73286.2-2026，厚度是3.9还是4.1mm？"
    bare_classes = [item.kind for item in question_numeric_occurrences(question)]
    pools = [
        (),
        [{"content_with_weight": "3.9 4.1 73286.2 2026"} for _ in range(20)],
        [{"content_with_weight": "nothing here"} for _ in range(3)],
    ]
    for pool in pools:
        assert question_values(question, pool) == ["3.9", "4.1"]
    # The classification itself takes no pool at all, so this is an invariant by signature as well:
    assert bare_classes == [item.kind for item in question_numeric_occurrences(question)]
    assert "chunks" not in numeric_occurrences.__code__.co_varnames


def test_d5_a_candidate_count_cannot_change_a_class():
    """Frequency, rarity and candidate count are diagnostics - never inputs. Asserted on the function's own
    name table and signature rather than by grepping for the word `count`, which the occurrence's own
    `counts_as_value` predicate would trip."""
    import inspect

    from rag.retrieval import decomposition

    signature = inspect.signature(decomposition.question_value_occurrences)
    assert list(signature.parameters) == ["question"], signature
    assert "_pool_share" not in decomposition.question_value_occurrences.__code__.co_names
    assert "carries_value" not in decomposition.question_value_occurrences.__code__.co_names
