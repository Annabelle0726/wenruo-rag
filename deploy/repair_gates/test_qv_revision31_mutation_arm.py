"""Mutation arm for Rev 3.1: proof the gate catches the five defect classes the kill audit named.

Each mutant is built from the REAL module's helpers and differs from it in exactly one decision, so it
fails for the reason the audit's finding was real. Each test asserts the mutant violates the gate's
expectation for its counterexample AND that the real implementation satisfies it.

1. restore global same-attribute promotion
2. locator binding stops at ordinary whitespace
3. only the first coordinated locator object is protected
4. the locator noun always wins over choice intent
5. a declarative `型号为` is treated as interrogative
"""
import re
import sys

sys.path.insert(0, "/ragflow")

from rag.retrieval import chunk_profile
from rag.retrieval.chunk_profile import (
    NUMERIC_IDENTITY_ASKED,
    NUMERIC_IDENTITY_LOCATOR,
    NUMERIC_MODEL_IDENTITY,
    numeric_occurrences,
)
from rag.retrieval.decomposition import question_numeric_occurrences, question_values

R1 = "根据 2026版，另一份规范的版本是2025版吗？"
R3 = "按照2026版和2025版核对800mm²电缆，待审文件的版本是2024版吗？"
R4 = "Q/GDW 73286.2-2026规定800mm²电缆；待审文件的标准号是多少？"
R5 = "已知型号为AB123CD，厚度应取1.8还是2.0mm？"
R6 = "依据是2026版还是2025版，允许厚度为1.8mm吗？"


def kinds(question):
    return {item.text: item.kind for item in question_numeric_occurrences(question)}


# ---------------------------------------------------------------------------
# MUTANT 1 - global same-attribute promotion
# ---------------------------------------------------------------------------


def mutant_global_asked_starts(text):
    """The rejected authority: a cue anywhere in the sentence promotes every occurrence of its attribute.
    Clause locality and target scope are removed; everything else (locator binding, comparisons) stays."""
    occurrences = numeric_occurrences(text)
    asked = chunk_profile._compared_starts(text, occurrences)
    for attribute, cue in chunk_profile._ASKED_ATTRIBUTE_CUES.items():
        if cue.search(text):
            asked.update(item.start for item in occurrences if chunk_profile._occurrence_attribute(text, item) == attribute)
    return asked


def test_mutant_1_the_gate_catches_global_promotion():
    occurrence = [item for item in numeric_occurrences(R4) if item.text == "73286.2"][0]
    mutant = mutant_global_asked_starts(R4)
    real = chunk_profile._asked_starts(R4, numeric_occurrences(R4))
    assert occurrence.start in mutant, "the mutant promotes a standard named in another clause"
    assert occurrence.start not in real, "the real binder is clause-local"
    assert kinds(R4)["73286.2"] == NUMERIC_IDENTITY_LOCATOR
    assert "73286.2" not in question_values(R4)


def test_mutant_1b_the_mutant_also_leaks_across_every_separator():
    for separator in ("，", "；", "。", "？"):
        question = f"Q/GDW 73286.2-2026规定800mm²电缆{separator}待审文件的标准号是多少？"
        mutant = mutant_global_asked_starts(question)
        occurrence = [item for item in numeric_occurrences(question) if item.text == "73286.2"][0]
        assert occurrence.start in mutant, separator
        assert "73286.2" not in question_values(question), separator


# ---------------------------------------------------------------------------
# MUTANT 2 - the locator stops at ordinary whitespace
# ---------------------------------------------------------------------------


def mutant_locator_rejects_whitespace(text):
    """The scope test the audit's I2 forbids: a gap containing a space ends the object phrase."""
    occurrences = numeric_occurrences(text)
    bound = set()
    for cue in chunk_profile._LOCATOR_CUES:
        position = text.find(cue)
        while position != -1:
            if chunk_profile._locator_is_preposition(text, position, cue):
                after = position + len(cue)
                for occurrence in occurrences:
                    if occurrence.start < after or chunk_profile._occurrence_attribute(text, occurrence) is None:
                        continue
                    gap = text[after : occurrence.start]
                    if any(char.isspace() for char in gap):
                        break
                    if any(char in chunk_profile._OBJECT_PUNCTUATION for char in gap):
                        break
                    bound.add(occurrence.start)
                    break
            position = text.find(cue, position + 1)
    return bound


def test_mutant_2_the_gate_catches_a_whitespace_sensitive_locator():
    spaced = "根据 2026版进行设计，允许厚度为1.8mm吗？"
    occurrence = [item for item in numeric_occurrences(spaced) if item.text == "2026"][0]
    mutant = mutant_locator_rejects_whitespace(spaced)
    real = chunk_profile._locator_bound_starts(spaced, numeric_occurrences(spaced))
    assert occurrence.start not in mutant, "the mutant loses the object across a space"
    assert occurrence.start in real, "the real scope ignores whitespace"
    assert kinds(spaced)["2026"] == NUMERIC_IDENTITY_LOCATOR
    assert kinds("根据2026版进行设计，允许厚度为1.8mm吗？")["2026"] == NUMERIC_IDENTITY_LOCATOR


# ---------------------------------------------------------------------------
# MUTANT 3 - only the first coordinated object is protected
# ---------------------------------------------------------------------------


def mutant_first_object_only(text):
    """The locator binds its first object and stops, which is what the audit's R3 defeats."""
    occurrences = numeric_occurrences(text)
    bound = set()
    for cue in chunk_profile._LOCATOR_CUES:
        position = text.find(cue)
        while position != -1:
            if chunk_profile._locator_is_preposition(text, position, cue):
                after = position + len(cue)
                for occurrence in occurrences:
                    if occurrence.start < after or chunk_profile._occurrence_attribute(text, occurrence) is None:
                        continue
                    gap = text[after : occurrence.start]
                    if len(gap) > chunk_profile._LOCATOR_GAP_LIMIT or any(char in chunk_profile._OBJECT_PUNCTUATION for char in gap):
                        break
                    bound.add(occurrence.start)
                    break
            position = text.find(cue, position + 1)
    return bound


def test_mutant_3_the_gate_catches_a_single_object_locator():
    occurrences = numeric_occurrences(R3)
    second = [item for item in occurrences if item.text == "2025"][0]
    mutant = mutant_first_object_only(R3)
    real = chunk_profile._locator_bound_starts(R3, occurrences)
    assert second.start not in mutant, "the mutant protects only the first coordinated object"
    assert second.start in real, "the real binder protects every coordinated object"
    assert kinds(R3)["2025"] == NUMERIC_IDENTITY_LOCATOR
    assert "2025" not in question_values(R3)


# ---------------------------------------------------------------------------
# MUTANT 4 - the locator noun always wins over choice intent
# ---------------------------------------------------------------------------


def mutant_locator_ignores_copula(text):
    """The `依据` in `依据是…` read as a preposition, which is what the audit's R6 defeats."""
    occurrences = numeric_occurrences(text)
    bound = set()
    for cue in chunk_profile._LOCATOR_CUES:
        position = text.find(cue)
        while position != -1:
            at_clause_edge = position == 0 or text[position - 1] in chunk_profile._CLAUSE_EDGE_CHARS
            if at_clause_edge:  # the copula test removed
                after = position + len(cue)
                for occurrence in occurrences:
                    if occurrence.start < after or chunk_profile._occurrence_attribute(text, occurrence) is None:
                        continue
                    gap = text[after : occurrence.start]
                    if len(gap) > chunk_profile._LOCATOR_GAP_LIMIT or any(char in chunk_profile._OBJECT_PUNCTUATION for char in gap):
                        break
                    bound.add(occurrence.start)
                    break
            position = text.find(cue, position + 1)
    return bound


def test_mutant_4_the_gate_catches_the_locator_noun_winning():
    occurrences = numeric_occurrences(R6)
    first = [item for item in occurrences if item.text == "2026"][0]
    mutant = mutant_locator_ignores_copula(R6)
    real = chunk_profile._locator_bound_starts(R6, occurrences)
    assert first.start in mutant, "the mutant reads the questioned subject as a preposition"
    assert first.start not in real, "the real test rejects a cue whose complement is a copula"
    assert kinds(R6)["2026"] == NUMERIC_IDENTITY_ASKED
    assert "2026" in question_values(R6)


# ---------------------------------------------------------------------------
# MUTANT 5 - a declarative `型号为` treated as interrogative
# ---------------------------------------------------------------------------


def mutant_every_clause_interrogative(text):
    """The interrogative test removed, so a declarative clause's cue binds - the audit's I4/R5."""
    occurrences = numeric_occurrences(text)
    spans = chunk_profile._clause_spans(text)
    bound = set()
    for span in spans:
        scope_start = chunk_profile._target_scope_start(text, span)
        clause_text = text[scope_start : span[1]]
        for attribute, cue in chunk_profile._ASKED_ATTRIBUTE_CUES.items():
            if not cue.search(clause_text):
                continue
            bound.update(
                item.start
                for item in occurrences
                if scope_start <= item.start and item.end <= span[1] and chunk_profile._occurrence_attribute(text, item) == attribute
            )
    return bound


def test_mutant_5_the_gate_catches_a_declarative_clause_binding():
    occurrences = numeric_occurrences(R5)
    declared = [item for item in occurrences if item.text == "123"][0]
    mutant = mutant_every_clause_interrogative(R5)
    real = chunk_profile._asked_starts(R5, occurrences)
    assert declared.start in mutant, "the mutant promotes a DECLARED model code"
    assert declared.start not in real, "the real binder requires an interrogative clause"
    assert kinds(R5)["123"] == NUMERIC_MODEL_IDENTITY
    assert "123" not in question_values(R5)


def test_mutant_5b_the_interrogative_test_is_what_separates_the_two_clauses():
    spans = chunk_profile._clause_spans(R5)
    assert len(spans) == 2, spans
    assert [chunk_profile._is_interrogative(R5, span) for span in spans] == [False, True]
    # A clause with no subject-shift word scopes from its own start; one with a target starts after it.
    assert chunk_profile._target_scope_start(R1, chunk_profile._clause_spans(R1)[0]) == 0
    target = "待选型号为EF456GH吗？"
    assert chunk_profile._target_scope_start(target, (0, len(target))) == len("待选")
