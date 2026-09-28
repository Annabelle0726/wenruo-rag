"""Mutation arm for Numeric Rev 3: proof that the gate CATCHES the five defect classes Codex named.

A gate that passes on a correct implementation proves nothing until it fails on a wrong one. Each mutant
here is built from the REAL module's helpers, so it fails for the reason the audit's finding was real, and
each test asserts two things: the mutant violates an expectation the gate holds, and the real
implementation satisfies it.

1. sentence-global `还是` - a connective promoting every occurrence of a class
2. merging occurrences by their numeric string
3. normalized offsets masquerading as original offsets
4. unconditional year identity removal
5. shortest-unit-prefix matching
"""
import re
import sys

sys.path.insert(0, "/ragflow")

from rag.retrieval import chunk_profile
from rag.retrieval.chunk_profile import (
    NUMERIC_IDENTITY_LOCATOR,
    numeric_occurrences,
)
from rag.retrieval.decomposition import (
    _normalize_with_map,
    question_numeric_occurrences,
    question_value_occurrences,
    question_values,
)

A1 = "根据 Q/GDW 73286.2-2026，厚度是3.9还是4.1mm？"
A2 = "根据2026版，投产依据是2025版还是2024版？"
B = "第12部分  电压  220kV"
C = "储能容量100kWh 的电缆要求"


def _attribute(text, occurrence):
    return chunk_profile._attribute_of(text, occurrence.text, occurrence.end, occurrence.designation_span, occurrence.model_span)


# ---------------------------------------------------------------------------
# MUTANT 1 - sentence-global connective
# ---------------------------------------------------------------------------


def mutant_sentence_global_asked_starts(text):
    """Revision 2's model: the sentence contains a cue, so every occurrence of the class is promoted."""
    occurrences = numeric_occurrences(text)
    if not re.search(r"还是|或者", text):
        return set()
    return {item.start for item in occurrences if _attribute(text, item) is not None}


def test_mutant_1_the_gate_catches_a_sentence_global_connective():
    mutant = mutant_sentence_global_asked_starts(A1)
    designation = [item for item in numeric_occurrences(A1) if item.text == "73286.2"][0]
    assert designation.start in mutant, "the mutant promotes the designation in front of the comparison"
    # ... which the gate forbids: A1 requires the designation to stay a locator and the values to be the
    # two technical figures only.
    assert question_values(A1) == ["3.9", "4.1"]
    assert [item.kind for item in numeric_occurrences(A1) if item.text == "73286.2"] == [NUMERIC_IDENTITY_LOCATOR]
    # And the mutant would also promote the locator year of the second question:
    assert any(item.text == "2026" for item in numeric_occurrences(A2) if item.start in mutant_sentence_global_asked_starts(A2))
    assert question_values(A2) == ["2025", "2024"]


# ---------------------------------------------------------------------------
# MUTANT 2 - merging occurrences by numeric string
# ---------------------------------------------------------------------------


def mutant_string_keyed_kinds(text):
    """One class per literal, last write wins - the shape the audit's H and D2 forbid."""
    return {item.text: item.kind for item in question_numeric_occurrences(text)}


def test_mutant_2_the_gate_catches_string_key_merging():
    text = "额定电压0.6/1 kV、型号WDZC-YJY-0.6/1kV 与 0.6 的厚度？"
    merged = mutant_string_keyed_kinds(text)
    records = [item for item in question_numeric_occurrences(text) if item.text == "0.6"]
    assert len(records) == 3, records
    assert len({item.start for item in records}) == 3, "the real records are distinct"
    assert len(merged) < len(question_numeric_occurrences(text)), "the mutant collapses the repeats"
    assert merged["0.6"] in (chunk_profile.NUMERIC_MODEL_IDENTITY, chunk_profile.NUMERIC_ANSWER_VALUE)


# ---------------------------------------------------------------------------
# MUTANT 3 - normalized offsets masquerading as original offsets
# ---------------------------------------------------------------------------


def mutant_normalized_offsets(question):
    """Offsets into the NORMALIZED copy, published as if they indexed the question - Revision 2's contract."""
    normalized, _mapping = _normalize_with_map(question)
    return numeric_occurrences(normalized)


def test_mutant_3_the_gate_catches_normalized_offsets():
    question = B
    mutated = mutant_normalized_offsets(question)
    real = question_numeric_occurrences(question)
    assert real and all(question[item.start : item.end] == item.text for item in real), "the real contract holds"
    assert any(question[item.start : item.end] != item.text for item in mutated), "the mutant's offsets point elsewhere"


def test_mutant_3b_the_mutant_cannot_even_be_asserted_against_the_original():
    """The reason the contract matters: with the mutant's offsets, the caller cannot express the invariant
    its own API implies."""
    question = B
    mutated = mutant_normalized_offsets(question)
    mismatches = [item for item in mutated if question[item.start : item.end] != item.text]
    assert mismatches, mutated
    assert question_value_occurrences(question)[0].start != mutated[0].start


# ---------------------------------------------------------------------------
# MUTANT 4 - unconditional year identity removal
# ---------------------------------------------------------------------------


def mutant_unconditional_year_removal(question):
    """Any four-digit year that looks like an edition never reaches the value set, whatever is asked."""
    return [item.text for item in question_value_occurrences(question) if not re.fullmatch(r"(?:19|20)\d{2}", item.text)]


def test_mutant_4_the_gate_catches_unconditional_year_removal():
    asked = "标准发布的是2026年版还是2025年版？"
    assert question_values(asked) == ["2026", "2025"], "the answer IS the edition"
    assert mutant_unconditional_year_removal(asked) == [], "the mutant empties the answer set"
    locator = "2026 年版的海底电缆标准对铠装层有什么规定？"
    assert question_values(locator) == []
    assert mutant_unconditional_year_removal(locator) == []


def test_mutant_4b_a_locator_year_of_the_same_kind_is_still_a_locator():
    """The mutant cannot express the distinction the gate requires, in either direction."""
    assert question_values(A2) == ["2025", "2024"]
    assert mutant_unconditional_year_removal(A2) == [], "the mutant also deletes the ASKED years"


# ---------------------------------------------------------------------------
# MUTANT 5 - shortest-unit-prefix matching
# ---------------------------------------------------------------------------


def shortest_unit_match(text, digits_end):
    """The lexicon's alternation taken as written: whichever unit is listed first wins."""
    position = digits_end
    while position < len(text) and text[position].isspace():
        position += 1
    best = None
    for pattern in chunk_profile._unit_patterns():
        match = pattern.match(text, position)
        if match and (best is None or match.end() < best[1]):
            best = (match.group(0), match.end())
    return best


def test_mutant_5_the_gate_catches_shortest_unit_prefix():
    real = chunk_profile._match_unit(C, C.index("kWh"))
    mutant = shortest_unit_match(C, C.index("kWh"))
    assert real is not None and real[0] == "kWh", real
    assert mutant is not None and mutant[0] == "kW", mutant
    assert question_values(C) == ["100"]
    # The mutant's shorter match is not a valid boundary, so the digit run would read as a code:
    assert chunk_profile._unit_boundary_ok(C, C.index("kWh") + 2) is False
