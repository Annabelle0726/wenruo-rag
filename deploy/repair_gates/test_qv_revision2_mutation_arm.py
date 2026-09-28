"""Mutation arm: proof that the Rev-2 gate CATCHES the four defect classes the audit named.

A gate that passes on a correct implementation proves nothing unless it also fails on a wrong one. Each
test below takes one defect the audit identified, applies it as a MUTANT of the real implementation, and
asserts that the gate's own expectation for that case is violated by the mutant and satisfied by the real
code. The mutants reach into the real module's helpers, so they fail for the same reason the audit's
findings were real rather than because a fixture was contrived.

The four, named as in the audit's section 7:

1. **metadata regex guessing** - inferring "leading bracket == injected" from the bracket's shape.
2. **shortest-unit-prefix** - taking the first matching unit instead of the longest valid one.
3. **string-key provenance collapse** - keying classes by the digit string.
4. **unconditional year removal** - dropping an identity figure without asking what the question wants.
"""
import re
import sys

sys.path.insert(0, "/ragflow")

from rag.retrieval import chunk_profile
from rag.retrieval.chunk_profile import carries_value, numeric_occurrences
from rag.retrieval.decomposition import question_value_occurrences, question_values


def chunk(content, name="part3.pdf"):
    return {"chunk_id": "c1", "doc_id": "doc-a", "docnm_kwd": name, "content_with_weight": content}


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


# ---------------------------------------------------------------------------
# MUTANT 1 - metadata regex guessing (the previous revision's boundary)
# ---------------------------------------------------------------------------

#: The rejected boundary: any leading bracketed lead-in is metadata. It is exactly what the producer's
#: own inverse does, and exactly what the audit's counterexample A defeats.
_MUTANT_METADATA_RE = re.compile(r"^\[[^\[\]]*\]\s?")


def mutant_metadata_regex_guessing(text):
    match = _MUTANT_METADATA_RE.match(text)
    return text[match.end() :] if match else text


def test_mutant_1_the_gate_catches_metadata_regex_guessing():
    body = "[800 mm²：厚度3.9 mm] 后续要求"
    assert carries_value(chunk(body, name="part3.pdf"), ("800",)) is True, "the real boundary keeps body brackets"
    assert mutant_metadata_regex_guessing(body) == "后续要求", "the mutant deletes the document's own bracket"
    # ... and the gate's layer-3 assertion is violated by the mutant:
    assert "800" not in mutant_metadata_regex_guessing(body)


def test_mutant_1b_the_gate_catches_partial_deletion_too():
    """The audit's counterexample B: cutting at the FIRST `]` leaves the header's tail behind as evidence."""
    header = "[标准号: Q/GDW 73286.3 | 文档: 规范]附录.pdf | 章节: 4] <table><tr><td>3.9</td></tr></table>"
    first_close = header.index("]") + 1
    partial = header[first_close:].lstrip(" ")
    assert partial.startswith("附录.pdf"), partial
    assert carries_value(producer_recorded(header, name="规范]附录.pdf"), ("73286.3",)) is False, "the real boundary removes it whole"


# ---------------------------------------------------------------------------
# MUTANT 2 - shortest-unit-prefix
# ---------------------------------------------------------------------------


def shortest_unit_match(text, digits_end):
    """The previous adapter's behaviour: the lexicon's alternation returns whichever unit is listed first."""
    position = digits_end
    while position < len(text) and text[position] == " ":
        position += 1
    best = None
    for pattern in chunk_profile._unit_patterns():
        match = pattern.match(text, position)
        if match and (best is None or match.end() < best[1]):
            best = (match.group(0), match.end())
    return best


def test_mutant_2_the_gate_catches_shortest_unit_prefix():
    text = "储能容量100kWh 的电缆要求"
    real = chunk_profile._match_unit(text, text.index("kWh"))
    mutant = shortest_unit_match(text, text.index("kWh"))
    assert real is not None and real[0] == "kWh", real
    assert mutant is not None and mutant[0] == "kW", mutant
    # The gate's layer-1 expectation is exactly this: the real adapter must resolve the longest unit.
    kinds = [item.kind for item in numeric_occurrences(text) if item.text == "100"]
    assert kinds == [chunk_profile.NUMERIC_TECHNICAL_MEASUREMENT], kinds
    assert question_values(text) == ["100"]


def test_mutant_2b_the_shortest_prefix_makes_the_figure_look_like_a_code():
    """Why the mutant matters: `kW` matched, `h` left over, so the digits were read as a model code."""
    text = "储能容量100kWh 的电缆要求"
    start = text.index("100")
    unit_end = start + 3 + 2  # the mutant's `kW` match is not a valid boundary
    assert chunk_profile._unit_boundary_ok(text, unit_end) is False


# ---------------------------------------------------------------------------
# MUTANT 3 - string-key provenance collapse
# ---------------------------------------------------------------------------


def mutant_string_key_classes(text):
    """The previous projection's shape: one class per digit string, last occurrence wins."""
    return {occurrence.text: occurrence.kind for occurrence in numeric_occurrences(text)}


def test_mutant_3_the_gate_catches_string_key_collapse():
    text = "额定电压0.6/1 kV、型号WDZC-YJY-0.6/1kV 的电缆载流量是多少？"
    collapsed = mutant_string_key_classes(text)
    assert collapsed["0.6"] == chunk_profile.NUMERIC_MODEL_IDENTITY, collapsed
    # The real projection resolves each occurrence on its own evidence and keeps the voltage as a value.
    assert question_values(text) == ["0.6"]
    kinds = sorted(item.kind for item in numeric_occurrences(text) if item.text == "0.6")
    assert kinds == [chunk_profile.NUMERIC_MODEL_IDENTITY, chunk_profile.NUMERIC_TECHNICAL_MEASUREMENT], kinds


def test_mutant_3b_the_occurrence_records_are_distinguishable_by_more_than_class():
    text = "额定电压0.6/1 kV、型号WDZC-YJY-0.6/1kV 的电缆载流量是多少？"
    records = [item for item in numeric_occurrences(text) if item.text == "0.6"]
    assert len({item.start for item in records}) == 2
    assert {item.model_span is not None for item in records} == {False, True}


# ---------------------------------------------------------------------------
# MUTANT 4 - unconditional year removal
# ---------------------------------------------------------------------------


def mutant_unconditional_year_removal(question):
    """The previous rule: a four-digit year that looks like an edition never reaches the value set."""
    dropped = {"2026", "2025", "2019"}
    return [occurrence.text for occurrence in question_value_occurrences(question) if occurrence.text not in dropped]


def test_mutant_4_the_gate_catches_unconditional_year_removal():
    asked = "标准发布的是2026年版还是2025年版？"
    assert question_values(asked) == ["2026", "2025"]
    assert mutant_unconditional_year_removal(asked) == [], "the mutant returns nothing for a question about the edition"

    locator = "2026 年版的海底电缆标准对铠装层有什么规定？"
    assert question_values(locator) == []
    assert mutant_unconditional_year_removal(locator) == []


def test_mutant_4b_the_distinction_is_the_question_not_the_calendar():
    """Both sentences contain `2026年版`; only one of them asks for it. A rule that cannot separate them
    is wrong in one of the two no matter which way it is set - the audit's exact point."""
    assert chunk_profile.numeric_occurrences("标准发布的是2026年版还是2025年版？")[0].kind == chunk_profile.NUMERIC_IDENTITY_ASKED
    assert chunk_profile.numeric_occurrences("2026 年版的海底电缆标准对铠装层有什么规定？")[0].kind == chunk_profile.NUMERIC_IDENTITY_LOCATOR
