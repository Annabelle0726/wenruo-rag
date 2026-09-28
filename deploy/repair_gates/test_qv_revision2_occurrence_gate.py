"""Occurrence-level provenance: the model the audit's section 3 requires, gated on its own.

Importing this against a revision without the occurrence model fails at COLLECTION, which is the honest
form of that finding: the audit's complaint is not that a class was wrong but that there was no per-
occurrence record to be wrong. The behavioural consequences are gated in `test_qv_revision2_gate.py`,
which collects and fails case by case against such a revision.
"""
import sys

import pytest

sys.path.insert(0, "/ragflow")

from rag.retrieval.chunk_profile import (
    NUMERIC_ANSWER_VALUE,
    NUMERIC_IDENTITY_ASKED,
    NUMERIC_IDENTITY_LOCATOR,
    NUMERIC_MODEL_IDENTITY,
    NUMERIC_TECHNICAL_MEASUREMENT,
    NUMERIC_UNKNOWN,
    NUMERIC_VALUE_CLASSES,
    NumericOccurrence,
    numeric_occurrences,
)
from rag.retrieval.decomposition import question_value_occurrences


def grouped(text):
    out = {}
    for occurrence in numeric_occurrences(text):
        out.setdefault(occurrence.text, []).append(occurrence)
    return out


def test_the_classes_are_published_with_the_identity_intent_split():
    assert {
        NUMERIC_IDENTITY_LOCATOR,
        NUMERIC_IDENTITY_ASKED,
        NUMERIC_MODEL_IDENTITY,
        NUMERIC_TECHNICAL_MEASUREMENT,
        NUMERIC_ANSWER_VALUE,
        NUMERIC_UNKNOWN,
    } == {
        "IDENTITY_USED_TO_LOCATE_DOCUMENT",
        "IDENTITY_VALUE_EXPLICITLY_ASKED_BY_USER",
        "MODEL_IDENTITY",
        "TECHNICAL_MEASUREMENT",
        "ANSWER_REQUESTED_NUMERIC_VALUE",
        "UNKNOWN_NUMERIC",
    }
    assert NUMERIC_IDENTITY_LOCATOR not in NUMERIC_VALUE_CLASSES
    assert {NUMERIC_TECHNICAL_MEASUREMENT, NUMERIC_ANSWER_VALUE, NUMERIC_UNKNOWN, NUMERIC_IDENTITY_ASKED} <= NUMERIC_VALUE_CLASSES


def test_every_occurrence_carries_its_local_provenance():
    occurrence = grouped("依据 Q/GDW 73286.2-2026 的 800 mm² 导体")["800"][0]
    assert isinstance(occurrence, NumericOccurrence)
    assert occurrence.start >= 0 and occurrence.end > occurrence.start
    assert occurrence.unit == "mm²"
    assert occurrence.unit_end is not None and occurrence.unit_end > occurrence.end
    assert occurrence.designation_span is None
    assert occurrence.model_span is None
    assert occurrence.relation == "bare"

    designation = grouped("依据 Q/GDW 73286.2-2026 的 800 mm² 导体")["73286.2"][0]
    assert designation.designation_span is not None
    assert designation.designation_span[0] <= designation.start < designation.end <= designation.designation_span[1]
    assert designation.kind == NUMERIC_IDENTITY_LOCATOR


def test_offsets_are_into_the_text_as_given():
    text = "800 mm² 的厚度"
    occurrence = numeric_occurrences(text)[0]
    assert text[occurrence.start : occurrence.end] == occurrence.text == "800"


def test_the_same_string_keeps_two_records_in_one_sentence():
    """AUDIT H at the provenance level: the voltage occurrence and the model occurrence both read `0.6`,
    and the two records must survive side by side."""
    text = "额定电压0.6/1 kV、型号WDZC-YJY-0.6/1kV 的电缆载流量是多少？"
    records = grouped(text)["0.6"]
    assert len(records) == 2, records
    assert sorted(item.kind for item in records) == [NUMERIC_MODEL_IDENTITY, NUMERIC_TECHNICAL_MEASUREMENT]
    assert records[0].start < records[1].start
    assert records[0].model_span is None and records[1].model_span is not None


def test_the_projection_is_derived_from_occurrences_and_not_from_a_string_map():
    question = "额定电压0.6/1 kV、型号WDZC-YJY-0.6/1kV 的电缆载流量是多少？"
    projected = question_value_occurrences(question)
    assert [item.text for item in projected] == ["0.6"]
    assert projected[0].kind == NUMERIC_TECHNICAL_MEASUREMENT
    assert all(item.kind in NUMERIC_VALUE_CLASSES for item in projected)


def test_an_asked_identity_occurrence_is_marked_as_asked():
    asked = question_value_occurrences("标准发布的是2026年版还是2025年版？")
    assert [item.text for item in asked] == ["2026", "2025"]
    assert {item.kind for item in asked} == {NUMERIC_IDENTITY_ASKED}
    assert all(item.kind in NUMERIC_VALUE_CLASSES for item in asked)


def test_a_locator_identity_occurrence_is_not_projected():
    assert question_value_occurrences("根据 Q/GDW 73286.2-2026，导体截面是多少？") == []
    assert [item.kind for item in numeric_occurrences("根据 Q/GDW 73286.2-2026，导体截面是多少？")] == [
        NUMERIC_IDENTITY_LOCATOR,
        NUMERIC_IDENTITY_LOCATOR,
    ]


@pytest.mark.parametrize(
    "text,value,unit,relation",
    [
        ("储能容量100kWh 的电缆要求", "100", "kWh", "bare"),
        ("电缆长度100m时的载流量", "100", "m", "bare"),
        ("额定电压0.6/1 kV 的电缆", "0.6", None, "ratio"),
        ("截面 800～1200mm² 的铠装层", "800", None, "range"),
        ("厚度允许偏差 ±0.5mm", "0.5", "mm", "tolerance"),
        ("扭矩 25N·m 的要求", "25", "N·m", "compound"),
    ],
)
def test_the_relation_of_a_figure_to_its_neighbours_is_recorded(text, value, unit, relation):
    occurrence = grouped(text)[value][0]
    assert occurrence.unit == unit, occurrence
    assert occurrence.relation == relation, occurrence
    assert occurrence.kind == NUMERIC_TECHNICAL_MEASUREMENT, occurrence


def test_a_standalone_digit_is_not_a_projected_value():
    """The pre-existing extraction rule (two digits or a decimal part) still governs the PROJECTION; the
    occurrence record still exists, so a diagnosis can see what was dropped and why."""
    assert [item.text for item in numeric_occurrences("WDZC-YJY-0.6/1kV 电缆")] != []
    assert question_value_occurrences("WDZC-YJY-0.6/1kV 电缆") == []


def test_a_dimension_pair_beside_a_model_is_still_a_measurement():
    """`3×25` is a count times a section, not part of the code - the contrast that keeps the model rule
    honest, and the reason the section figure stays in the value set."""
    assert [item.text for item in question_value_occurrences("WDZC-YJY-0.6/1kV 3×25 电缆")] == ["25"]
