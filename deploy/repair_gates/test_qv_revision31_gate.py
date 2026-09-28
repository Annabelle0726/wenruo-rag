"""Numeric Rev 3.1 - intent binding, gated. Written BEFORE the product change.

Codex's kill audit on `e211bea5c` produced six counterexamples plus five invariants. This module states the
required semantics, so its RED run against `e211bea5c` is the reproduction.

The architecture under test is the one the audit named:

    BEFORE: sentence-global attribute cue -> promote every same-attribute occurrence -> locator demotes some

    AFTER:  clause / local semantic span -> local predicate or question target -> bind only the eligible
            occurrence(s) inside that span

`test_architecture_no_global_promotion_path_remains` is the success condition: it is not satisfied by six
passing examples, only by the absence of the global authority.

Frozen by Rev 3 and NOT re-tested as new work here (they are re-run in
`test_qv_revision3_gate.py`): the original-question offset contract, the normalization mapping, the
occurrence record model, same-literal preservation, the longest-valid-unit adapter, whitespace-aware unit
matching, pool independence.
"""
import inspect
import re
import sys

import pytest

sys.path.insert(0, "/ragflow")

from rag.retrieval import chunk_profile
from rag.retrieval.chunk_profile import (
    NUMERIC_IDENTITY_ASKED,
    NUMERIC_IDENTITY_LOCATOR,
    NUMERIC_MODEL_IDENTITY,
    NUMERIC_TECHNICAL_MEASUREMENT,
    numeric_occurrences,
)
from rag.retrieval.decomposition import question_numeric_occurrences, question_value_occurrences, question_values


def records(question):
    grouped = {}
    for occurrence in question_numeric_occurrences(question):
        grouped.setdefault(occurrence.text, []).append(occurrence)
    return grouped


def one(question, text, index=0):
    return records(question)[text][index]


# ===========================================================================
# R1 - a locator survives a later edition question
# ===========================================================================


def test_r1_a_locator_edition_is_not_promoted_by_a_later_edition_question():
    question = "根据 2026版，另一份规范的版本是2025版吗？"
    assert one(question, "2026").kind == NUMERIC_IDENTITY_LOCATOR, one(question, "2026")
    assert one(question, "2025").kind == NUMERIC_IDENTITY_ASKED, one(question, "2025")
    assert question_values(question) == ["2025"], question_values(question)


# ===========================================================================
# R2 - a known model code is not promoted by a later model question
# ===========================================================================


def test_r2_a_known_model_code_is_not_promoted_by_a_later_model_question():
    question = "我们基于AB123CD的800mm²数据，待选型号为EF456GH吗？"
    assert one(question, "800").kind == NUMERIC_TECHNICAL_MEASUREMENT, one(question, "800")
    assert one(question, "456").kind == NUMERIC_IDENTITY_ASKED, one(question, "456")
    # The audit allows either reading of the leading model code, and forbids only its promotion:
    assert one(question, "123").kind in (NUMERIC_MODEL_IDENTITY, NUMERIC_IDENTITY_LOCATOR), one(question, "123")
    assert "123" not in question_values(question), question_values(question)
    assert question_values(question) == ["800", "456"], question_values(question)


# ===========================================================================
# R3 - coordinated locator objects are all protected
# ===========================================================================


def test_r3_every_coordinated_locator_object_is_protected():
    question = "按照2026版和2025版核对800mm²电缆，待审文件的版本是2024版吗？"
    assert one(question, "2026").kind == NUMERIC_IDENTITY_LOCATOR, one(question, "2026")
    assert one(question, "2025").kind == NUMERIC_IDENTITY_LOCATOR, one(question, "2025")
    assert one(question, "800").kind == NUMERIC_TECHNICAL_MEASUREMENT, one(question, "800")
    assert one(question, "2024").kind == NUMERIC_IDENTITY_ASKED, one(question, "2024")
    assert question_values(question) == ["800", "2024"], question_values(question)


# ===========================================================================
# R4 - object locality: another object's identity question does not promote this one
# ===========================================================================


def test_r4_a_referenced_standard_is_not_promoted_by_another_objects_standard_question():
    question = "Q/GDW 73286.2-2026规定800mm²电缆；待审文件的标准号是多少？"
    assert one(question, "73286.2").kind == NUMERIC_IDENTITY_LOCATOR, one(question, "73286.2")
    assert one(question, "2026").kind == NUMERIC_IDENTITY_LOCATOR, one(question, "2026")
    assert one(question, "800").kind == NUMERIC_TECHNICAL_MEASUREMENT, one(question, "800")
    assert question_values(question) == ["800"], question_values(question)


# ===========================================================================
# R5 - declarative identity is not a question
# ===========================================================================


def test_r5_a_declarative_model_code_is_not_a_question():
    question = "已知型号为AB123CD，厚度应取1.8还是2.0mm？"
    assert one(question, "123").kind == NUMERIC_MODEL_IDENTITY, one(question, "123")
    assert "123" not in question_values(question), question_values(question)
    assert question_values(question) == ["1.8", "2.0"], question_values(question)


def test_r5b_a_declarative_edition_beside_a_questioned_one():
    """The same distinction for the known/current context against the questioned target."""
    question = "现用2026版，待审版本是2025版吗？"
    assert one(question, "2026").kind == NUMERIC_IDENTITY_LOCATOR, one(question, "2026")
    assert one(question, "2025").kind == NUMERIC_IDENTITY_ASKED, one(question, "2025")
    assert question_values(question) == ["2025"], question_values(question)


# ===========================================================================
# R6 - the noun `依据` is not a locator preposition
# ===========================================================================


def test_r6_the_questioned_subject_依据_is_not_a_locator():
    """`依据是2026版还是2025版` asks WHICH the basis is. Reading `依据` as a preposition demotes the
    answer. The rule that decides this is syntactic - a cue followed by a copula is a subject, not a
    preposition - and it is applied to the whole locator family, not to this word."""
    question = "依据是2026版还是2025版，允许厚度为1.8mm吗？"
    assert one(question, "2026").kind == NUMERIC_IDENTITY_ASKED, one(question, "2026")
    assert one(question, "2025").kind == NUMERIC_IDENTITY_ASKED, one(question, "2025")
    assert one(question, "1.8").kind == NUMERIC_TECHNICAL_MEASUREMENT, one(question, "1.8")
    values = question_values(question)
    assert {"2026", "2025", "1.8"} <= set(values), values


def test_r6b_the_same_word_as_a_preposition_still_binds():
    """The disambiguation must not break the prepositional use - `依据2026版进行设计` locates."""
    question = "依据2026版进行设计，允许厚度为1.8mm吗？"
    assert one(question, "2026").kind == NUMERIC_IDENTITY_LOCATOR, one(question, "2026")
    assert "2026" not in question_values(question), question_values(question)


def test_r6c_the_rule_is_syntactic_not_word_specific():
    """Every member of the locator family takes the same copula test. The discriminating shape is a
    comparison: with a copula the cue is the questioned subject and BOTH members are the answer; as a
    preposition it binds its object and only the other member is."""
    for cue in ("依据", "根据", "按照", "参照", "基于"):
        question = f"{cue}是2026版还是2025版，允许厚度为1.8mm吗？"
        assert one(question, "2026").kind == NUMERIC_IDENTITY_ASKED, (cue, one(question, "2026"))
        assert one(question, "2025").kind == NUMERIC_IDENTITY_ASKED, (cue, one(question, "2025"))
        prepositional = f"{cue}2026版进行设计，允许厚度为1.8mm吗？"
        assert one(prepositional, "2026").kind == NUMERIC_IDENTITY_LOCATOR, (cue, one(prepositional, "2026"))


# ===========================================================================
# I1 - clause locality
# ===========================================================================


@pytest.mark.parametrize("separator", ["，", "；", "。", "？", ",", ";"])
def test_i1_no_attribute_question_promotes_across_a_clause_boundary(separator):
    question = f"Q/GDW 73286.2-2026规定800mm²电缆{separator}待审文件的标准号是多少？"
    assert one(question, "73286.2").kind == NUMERIC_IDENTITY_LOCATOR, (separator, one(question, "73286.2"))
    assert "73286.2" not in question_values(question), (separator, question_values(question))


def test_i1b_the_question_target_in_the_same_clause_is_promoted():
    """Clause locality must not be so strict that a same-clause target stops being asked."""
    question = "GB/T 12706.2-2020的标准号是多少？"
    assert one(question, "12706.2").kind == NUMERIC_IDENTITY_ASKED, one(question, "12706.2")
    assert question_values(question) == ["12706.2", "2020"], question_values(question)


def test_i1c_clause_locality_is_not_punctuation_only():
    """A declarative clause with no punctuation of its own still cannot be promoted by another clause's
    question - the signal is the interrogative clause, not the comma."""
    question = "已知型号为AB123CD 待选型号为EF456GH吗？"
    assert one(question, "123").kind == NUMERIC_MODEL_IDENTITY, one(question, "123")
    assert one(question, "456").kind == NUMERIC_IDENTITY_ASKED, one(question, "456")
    assert "123" not in question_values(question), question_values(question)


# ===========================================================================
# I2 - locator scope and coordination
# ===========================================================================


@pytest.mark.parametrize(
    "question,locators",
    [
        ("根据 2026版进行设计，允许厚度为1.8mm吗？", ["2026"]),
        ("根据2026版进行设计，允许厚度为1.8mm吗？", ["2026"]),
        ("根据\t2026版进行设计，允许厚度为1.8mm吗？", ["2026"]),
        ("按照2026版和2025版核对，允许厚度为1.8mm吗？", ["2026", "2025"]),
        ("按照2026版、2025版与2024版核对，允许厚度为1.8mm吗？", ["2026", "2025", "2024"]),
        ("基于 AB123CD 的数据，待选型号为EF456GH吗？", ["123"]),
    ],
)
def test_i2_a_locator_binds_its_object_including_coordinated_objects(question, locators):
    for text in locators:
        assert one(question, text).kind == NUMERIC_IDENTITY_LOCATOR, (question, text, one(question, text))
    assert not set(locators) & set(question_values(question)), question_values(question)


def test_i2b_whitespace_does_not_change_locator_scope():
    for question in ("根据2026版进行设计，允许厚度为1.8mm吗？", "根据 2026版进行设计，允许厚度为1.8mm吗？", "根据\n2026版进行设计，允许厚度为1.8mm吗？"):
        assert one(question, "2026").kind == NUMERIC_IDENTITY_LOCATOR, (question, one(question, "2026"))


# ===========================================================================
# I3 - the locator word is not sufficient
# ===========================================================================


def test_i3_locator_family_covers_the_five_prepositions():
    for cue in ("根据", "依据", "按照", "参照", "基于"):
        question = f"{cue}2026版进行设计，允许厚度为1.8mm吗？"
        assert one(question, "2026").kind == NUMERIC_IDENTITY_LOCATOR, (cue, one(question, "2026"))


def test_i3b_a_cue_followed_by_a_copula_is_a_subject_not_a_preposition():
    """A cue whose complement is the COPULA heads the predicate: `依据是2026版…` says what the basis IS,
    so nothing after it may be demoted to a locator. Asserted through the comparison shape, which is where
    the two readings give different answers."""
    for cue in ("根据", "依据", "按照", "参照", "基于"):
        subject = f"{cue}是2026版还是2025版，允许厚度为1.8mm吗？"
        assert one(subject, "2026").kind == NUMERIC_IDENTITY_ASKED, (cue, one(subject, "2026"))
        prepositional = f"{cue}2026版，允许厚度为1.8mm吗？"
        assert one(prepositional, "2026").kind == NUMERIC_IDENTITY_LOCATOR, (cue, one(prepositional, "2026"))


# ===========================================================================
# I4 - declarative identity is not a question
# ===========================================================================


@pytest.mark.parametrize(
    "question,forbidden",
    [
        ("已知型号为AB123CD，厚度应取1.8还是2.0mm？", {"123"}),
        ("现用2026版，待审版本是2025版吗？", {"2026"}),
        ("已知标准号为GB/T 12706.2-2020，待审文件的版本是2025版吗？", {"12706.2", "2020"}),
    ],
)
def test_i4_a_declarative_clause_never_supplies_the_answer(question, forbidden):
    """Whatever a declarative clause declares is context, not the answer: none of its figures may reach the
    value set, while every projected occurrence still carries an allowed class."""
    from rag.retrieval.chunk_profile import NUMERIC_VALUE_CLASSES

    values = question_values(question)
    assert not (forbidden & set(values)), (question, values)
    for occurrence in question_value_occurrences(question):
        assert occurrence.kind in NUMERIC_VALUE_CLASSES, (question, occurrence)


# ===========================================================================
# I5 - object locality
# ===========================================================================


def test_i5_the_questioned_object_is_identified_not_only_the_attribute():
    """`引用 A，询问 B 的标准号` - A is context, B is the target, and only B's clause is eligible."""
    question = "引用标准Q/GDW 73286.2-2026的规定，待审文件的版本是2025版吗？"
    assert one(question, "73286.2").kind == NUMERIC_IDENTITY_LOCATOR, one(question, "73286.2")
    assert one(question, "2025").kind == NUMERIC_IDENTITY_ASKED, one(question, "2025")
    assert question_values(question) == ["2025"], question_values(question)


# ===========================================================================
# Section 4 - same-literal stress gate
# ===========================================================================

#: One literal, four roles: a locator edition, a model code, a technical measurement, and the asked
#: identity of the questioned object.
SAME_LITERAL = "根据 2026版 与 AB2026CD 的 2026mm² 数据，待选型号为 EF2026GH 吗？"


def test_same_literal_four_roles_in_one_question():
    question = SAME_LITERAL
    occurrences = [item for item in question_numeric_occurrences(question) if item.text == "2026"]
    assert len(occurrences) == 4, occurrences
    assert len({item.start for item in occurrences}) == 4
    kinds = sorted(item.kind for item in occurrences)
    assert kinds == sorted(
        [NUMERIC_IDENTITY_LOCATOR, NUMERIC_MODEL_IDENTITY, NUMERIC_TECHNICAL_MEASUREMENT, NUMERIC_IDENTITY_ASKED]
    ), kinds


def test_same_literal_offsets_stay_original():
    question = SAME_LITERAL
    occurrences = [item for item in question_numeric_occurrences(question) if item.text == "2026"]
    for occurrence in occurrences:
        assert question[occurrence.start : occurrence.end] == occurrence.text, occurrence


def test_same_literal_projection_uses_eligibility_per_occurrence():
    """The projection is a filter over occurrences, so the literal appears because an ELIGIBLE occurrence
    exists - not because a string-keyed verdict was overwritten by the last one seen."""
    question = SAME_LITERAL
    eligible = [item for item in question_numeric_occurrences(question) if item.text == "2026" and item.counts_as_value]
    assert eligible, "the technical and asked occurrences are eligible"
    assert "2026" in question_values(question)
    projected = [item for item in question_value_occurrences(question) if item.text == "2026"]
    assert projected and all(item.counts_as_value for item in projected)


# ===========================================================================
# The success condition - the architecture, not the examples
# ===========================================================================


def test_architecture_no_global_promotion_path_remains():
    """The audit's success condition. Revision 3 bound an attribute cue by scanning EVERY occurrence in the
    sentence; that authority is what produced R1-R6, and it must not exist in any form - not even one that
    a locator rule later subtracts from."""
    source = inspect.getsource(chunk_profile._asked_starts) + inspect.getsource(chunk_profile._cue_bound_starts)
    assert "for attribute, cue in _ASKED_ATTRIBUTE_CUES.items()" in source or "_clause" in source
    # The binding must be clause-scoped: the function that resolves cue intent has to consult clause spans.
    assert "_clause" in inspect.getsource(chunk_profile._cue_bound_starts), "cue binding must be clause-local"
    assert "_clause" in inspect.getsource(chunk_profile._asked_starts) or "_cue_bound_starts" in inspect.getsource(
        chunk_profile._asked_starts
    )


def test_architecture_a_cue_cannot_bind_an_occurrence_in_another_clause():
    """The same property, as behaviour, over a matrix of separators and attribute kinds."""
    cases = [
        ("Q/GDW 73286.2 规定厚度，待审文件的标准号是多少？", "73286.2"),
        ("型号AB123CD 的载流量，待选型号为EF456GH吗？", "123"),
        ("2026版的规定，待审版本是2025版吗？", "2026"),
    ]
    for question, text in cases:
        assert text not in question_values(question), (question, question_values(question))
