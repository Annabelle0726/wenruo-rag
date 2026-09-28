"""Metadata provenance contract - G10 negative arm.

Five mutants of the real implementation, each one decision away from it. Each must be KILLED: the gate's own
expectation for that case has to fail when the mutant is in force, and pass for the real code.

1. extent derived by parsing header text (a regex boundary)
2. provenance derived from the filename
3. trusting the extent without the hash
4. stale provenance surviving a manual edit
5. the producer skipping injection because the body starts with `[标准号: `
"""
import re
import sys

sys.path.insert(0, "/ragflow")

from rag.nlp import doc_context
from rag.retrieval.chunk_profile import carries_value

try:
    from rag.nlp.doc_context import (
        LEGACY_PREFIX_VERSION,
        PREFIX_CHARS_FIELD,
        PREFIX_HASH_FIELD,
        PREFIX_KIND_FIELD,
        PREFIX_KIND_LEGACY,
        prefix_hash,
        split_prefix,
        verified_prefix_extent,
    )

    CONTRACT_AVAILABLE = True
except ImportError:  # pragma: no cover - pre-contract revision
    CONTRACT_AVAILABLE = False
    PREFIX_KIND_FIELD = "content_prefix_kind_kwd"
    PREFIX_CHARS_FIELD = "content_prefix_chars_int"
    PREFIX_HASH_FIELD = "content_prefix_hash_kwd"
    PREFIX_KIND_LEGACY = "identity_legacy"
    LEGACY_PREFIX_VERSION = 1

    def prefix_hash(prefix):
        return ""

    def verified_prefix_extent(chunk):
        return None

    def split_prefix(chunk):
        return "", str(chunk.get("content_with_weight") or "")


NAME = "Q/GDW 73286.2-2026 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范.pdf"
BODY = "5.3.4 内衬层厚度应不小于1.5mm。"
LOOK_ALIKE = "[标准号: GB/T 10666-1997 | 文档: 某产品标准] 原文引用。"
HOSTILE_NAME = "Q/GDW 73286.2-2026 规范]附录.pdf"


def prefixed(body=BODY, name=NAME):
    chunk = {"content_with_weight": body, "doc_id": "doc-1", "docnm_kwd": name}
    doc_context.apply_document_context([chunk], name, language="Chinese")
    return chunk


# ---------------------------------------------------------------------------
# MUTANT 1 - regex-derived extent
# ---------------------------------------------------------------------------

_HEADER_RE = re.compile(r"^\[[^\[\]]*\]\s?")


def mutant_regex_extent(chunk):
    """Recover the boundary by matching the header's shape, which is what the audit rejected."""
    content = str(chunk.get("content_with_weight") or "")
    match = _HEADER_RE.match(content)
    return match.end() if match else 0


def test_mutant_1_regex_extent_is_killed():
    hostile = prefixed(name=HOSTILE_NAME)
    content = hostile["content_with_weight"]
    assert verified_prefix_extent(hostile) is not None, "the real contract verifies"
    assert split_prefix(hostile)[1] == BODY
    mutant = mutant_regex_extent(hostile)
    assert mutant != content.index("] ") + 2, "the mutant stops at the first bracket inside the title"
    assert content[mutant:] != BODY, "and therefore hands the consumer the wrong body"


def test_mutant_1b_regex_extent_also_fails_on_a_body_that_looks_like_a_header():
    chunk = prefixed(body=LOOK_ALIKE)
    assert split_prefix(chunk)[1] == LOOK_ALIKE
    mutant = mutant_regex_extent(chunk)
    # The mutant matches the INJECTED header, so on this chunk it agrees by accident - which is exactly why
    # it is not an authority: it cannot tell the injected header from the quoted one that follows it.
    assert mutant == len(chunk["content_with_weight"]) - len(LOOK_ALIKE)
    unprovenanced = {"content_with_weight": LOOK_ALIKE}
    mutant_unprovenanced = mutant_regex_extent(unprovenanced)
    assert mutant_unprovenanced > 0, "the mutant strips a body that merely looks like a header"
    assert unprovenanced["content_with_weight"][mutant_unprovenanced:] != LOOK_ALIKE
    assert split_prefix(unprovenanced)[1] == LOOK_ALIKE, "the contract keeps it whole"


# ---------------------------------------------------------------------------
# MUTANT 2 - filename-derived provenance
# ---------------------------------------------------------------------------


def mutant_filename_provenance(chunk, expected_name=NAME):
    """Treat the document-name cross-check as proof and mint an extent from it."""
    content = str(chunk.get("content_with_weight") or "")
    if chunk.get("docnm_kwd") == expected_name and content.startswith("[标准号: "):
        return len(content) - len(BODY)
    return None


def test_mutant_2_filename_provenance_is_killed():
    header = doc_context.render_document_context("Q/GDW 73286.2", doc_context.document_title(NAME), "")
    content = header + BODY
    natural = {"content_with_weight": content, "docnm_kwd": NAME}
    assert verified_prefix_extent(natural) is None, "the contract refuses to infer"
    assert split_prefix(natural)[1] == content
    assert mutant_filename_provenance(natural) == len(header), "the mutant mints provenance from the name"


def test_mutant_2b_filename_provenance_also_leaks_the_standard_number():
    header = doc_context.render_document_context("Q/GDW 73286.2", doc_context.document_title(NAME), "")
    natural = {"content_with_weight": header + "<table><tr><td>导体</td><td>铜</td></tr></table>", "docnm_kwd": NAME}
    assert carries_value(natural, ("73286.2",)) is True
    # A consumer that trusted the mutant would strip and report False - deleting the document's own text:
    extent = mutant_filename_provenance(natural)
    stripped = {"content_with_weight": natural["content_with_weight"][extent:], "docnm_kwd": NAME}
    assert carries_value(stripped, ("73286.2",)) is False


# ---------------------------------------------------------------------------
# MUTANT 3 - extent trusted without the hash
# ---------------------------------------------------------------------------


def mutant_extent_without_hash(chunk):
    if chunk.get(PREFIX_KIND_FIELD) == PREFIX_KIND_LEGACY and isinstance(chunk.get(PREFIX_CHARS_FIELD), int):
        return chunk[PREFIX_CHARS_FIELD]
    return None


def test_mutant_3_extent_without_hash_is_killed():
    chunk = prefixed()
    extent = chunk[PREFIX_CHARS_FIELD]
    tampered = dict(chunk)
    tampered["content_with_weight"] = "X" + chunk["content_with_weight"][1:]
    assert verified_prefix_extent(tampered) is None, "the contract verifies the bytes"
    assert mutant_extent_without_hash(tampered) == extent, "the mutant trusts the number"
    extent_used = mutant_extent_without_hash(tampered)
    assert extent_used == extent, "the mutant accepts an extent it cannot verify"
    assert prefix_hash(tampered["content_with_weight"][:extent_used]) != tampered[PREFIX_HASH_FIELD], (
        "and calls a prefix something the recorded hash denies"
    )


def test_mutant_3b_a_stale_extent_after_a_body_edit():
    chunk = prefixed()
    extent = chunk[PREFIX_CHARS_FIELD]
    edited = dict(chunk)
    edited["content_with_weight"] = chunk["content_with_weight"] + "追加的正文"
    assert verified_prefix_extent(edited) == extent, "an appended body keeps the prefix valid"
    wrong = dict(edited)
    wrong["content_with_weight"] = "重写" + chunk["content_with_weight"]
    assert verified_prefix_extent(wrong) is None
    assert mutant_extent_without_hash(wrong) == extent, "the mutant strips a prefix that is not there"


# ---------------------------------------------------------------------------
# MUTANT 4 - stale provenance after a manual edit
# ---------------------------------------------------------------------------


def mutant_edit_keeps_provenance(chunk, new_content):
    """The edit path that forgets to invalidate."""
    chunk["content_with_weight"] = new_content
    return chunk


def test_mutant_4_stale_provenance_is_killed():
    try:
        from rag.nlp.doc_context import invalidation_after_edit

        real = invalidation_after_edit
    except ImportError:  # pragma: no cover
        real = None

    edited = mutant_edit_keeps_provenance(prefixed(), "完全重写的正文")
    assert verified_prefix_extent(edited) is None, "the contract invalidates, so a stale extent cannot verify"

    fresh = prefixed()
    if real is not None:
        real(fresh, "完全重写的正文")
        fresh["content_with_weight"] = "完全重写的正文"
    assert verified_prefix_extent(fresh) is None


# ---------------------------------------------------------------------------
# MUTANT 5 - the producer skipping on the string check
# ---------------------------------------------------------------------------


def mutant_producer_skips_on_string(body, name=NAME):
    """The pre-contract producer: the text itself decides whether a prefix exists."""
    chunk = {"content_with_weight": body, "docnm_kwd": name}
    if body.lstrip().startswith(doc_context.CONTEXT_PREFIX_OPEN):
        return chunk
    doc_context.apply_document_context([chunk], name, language="Chinese")
    return chunk


def test_mutant_5_the_string_skip_is_killed():
    skipped = mutant_producer_skips_on_string(LOOK_ALIKE)
    assert skipped["content_with_weight"] == LOOK_ALIKE, "the mutant injects nothing"
    assert PREFIX_CHARS_FIELD not in skipped, "and records no provenance at all"

    real = prefixed(body=LOOK_ALIKE)
    assert real["content_with_weight"] != LOOK_ALIKE, "the real producer prefixes it"
    assert verified_prefix_extent(real) is not None
    assert split_prefix(real)[1] == LOOK_ALIKE, "and still hands the body back intact"


def test_mutant_5b_the_string_skip_loses_the_standard_number_from_the_corpus():
    """Why it matters: the skipped chunk never gets the header, so the standard number is absent from the
    chunk that the document's own text quotes."""
    skipped = mutant_producer_skips_on_string(LOOK_ALIKE)
    real = prefixed(body=LOOK_ALIKE)
    assert doc_context.detect_standard_id(NAME, [LOOK_ALIKE]) not in skipped["content_with_weight"]
    assert doc_context.detect_standard_id(NAME, [LOOK_ALIKE]) in real["content_with_weight"]
