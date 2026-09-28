"""Metadata provenance contract - G1-G9, written BEFORE the implementation.

The contract under test: the producer records the EXACT injected prefix so a consumer can slice
`content_with_weight[extent:]` without parsing anything. The invariant is

    kind != none
      -> extent was recorded by the producer
      -> hash(content[:extent]) == content_prefix_hash_kwd
      -> and only then is content[extent:] the body

Everything else fails closed to the WHOLE content. The central gate is G2: the same visible bytes must be
readable two ways, because provenance - not text - decides.

Guarded import: on a revision without the contract the gate still RUNS (a collection error proves nothing),
with fallbacks that describe the pre-contract state (no provenance exists), so each gate fails on its own
semantics.
"""
import hashlib
import pathlib
import sys

import pytest

sys.path.insert(0, "/ragflow")

from rag.nlp import doc_context
from rag.retrieval.chunk_profile import carries_value

try:
    from rag.nlp.doc_context import (
        LEGACY_PREFIX_VERSION,
        PREFIX_CHARS_FIELD,
        PREFIX_FIELDS,
        PREFIX_HASH_FIELD,
        PREFIX_KIND_FIELD,
        PREFIX_KIND_LEGACY,
        PREFIX_NONE,
        PREFIX_VERSION_FIELD,
        clear_prefix,
        invalidation_after_edit,
        prefix_hash,
        split_prefix,
        verified_prefix_extent,
    )

    CONTRACT_AVAILABLE = True
except ImportError:  # pre-contract revision: describe "no provenance anywhere"
    CONTRACT_AVAILABLE = False
    PREFIX_KIND_FIELD = "content_prefix_kind_kwd"
    PREFIX_VERSION_FIELD = "content_prefix_version_int"
    PREFIX_CHARS_FIELD = "content_prefix_chars_int"
    PREFIX_HASH_FIELD = "content_prefix_hash_kwd"
    PREFIX_FIELDS = (PREFIX_KIND_FIELD, PREFIX_VERSION_FIELD, PREFIX_CHARS_FIELD, PREFIX_HASH_FIELD)
    PREFIX_NONE = "none"
    PREFIX_KIND_LEGACY = "identity_legacy"
    LEGACY_PREFIX_VERSION = 1

    def prefix_hash(prefix):  # type: ignore[misc]
        return ""

    def verified_prefix_extent(chunk):  # type: ignore[misc]
        return None

    def split_prefix(chunk):  # type: ignore[misc]
        return "", str(chunk.get("content_with_weight") or "")

    def clear_prefix(chunk):  # type: ignore[misc]
        return None

    def invalidation_after_edit(chunk, new_content):  # type: ignore[misc]
        return None


NAME = "Q/GDW 73286.2-2026 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范.pdf"
STANDARD = "Q/GDW 73286.2-2026"
BODY = "5.3.4 内衬层厚度应不小于1.5mm。800 mm² 与 1200 mm² 的规格见表1。"


def fresh_chunk(body=BODY, name=NAME, language="Chinese", tokens=True):
    chunk = {"content_with_weight": body, "doc_id": "doc-1", "docnm_kwd": name}
    if tokens:
        chunk["content_ltks"] = "body tks"
        chunk["content_sm_ltks"] = "body sm tks"
    return chunk


def prefixed_chunk(body=BODY, name=NAME, section=""):
    """Run the real producer and return the chunk it wrote, prefix included."""
    chunk = fresh_chunk(body, name)
    doc_context.apply_document_context([chunk], name, language="Chinese")
    return chunk


def header_of(name=NAME, section=""):
    return doc_context.render_document_context(doc_context.detect_standard_id(name, [BODY]) or STANDARD, doc_context.document_title(name), section)


def with_provenance(content, extent, kind=PREFIX_KIND_LEGACY, version=LEGACY_PREFIX_VERSION, digest=None):
    return {
        "content_with_weight": content,
        "docnm_kwd": NAME,
        PREFIX_KIND_FIELD: kind,
        PREFIX_VERSION_FIELD: version,
        PREFIX_CHARS_FIELD: extent,
        PREFIX_HASH_FIELD: prefix_hash(content[:extent]) if digest is None else digest,
    }


# ===========================================================================
# G1 - exact producer boundary
# ===========================================================================


def test_g1_the_producer_records_the_exact_injected_extent_and_hash():
    chunk = prefixed_chunk()
    content = chunk["content_with_weight"]
    header = content[: len(content) - len(BODY)]
    assert header.endswith("] "), header
    assert chunk[PREFIX_KIND_FIELD] == PREFIX_KIND_LEGACY, chunk.get(PREFIX_KIND_FIELD)
    assert chunk[PREFIX_VERSION_FIELD] == LEGACY_PREFIX_VERSION, chunk.get(PREFIX_VERSION_FIELD)
    assert chunk[PREFIX_CHARS_FIELD] == len(header), (chunk.get(PREFIX_CHARS_FIELD), len(header))
    assert chunk[PREFIX_HASH_FIELD] == prefix_hash(header), chunk.get(PREFIX_HASH_FIELD)
    assert verified_prefix_extent(chunk) == len(header)
    prefix, body = split_prefix(chunk)
    assert prefix == header and body == BODY


def test_g1_the_extent_is_code_points_not_bytes():
    """A Unicode title must not shift the boundary between the two definitions."""
    chunk = prefixed_chunk(name=f"{STANDARD} 规范±℃Ωμ—测试.pdf")
    content = chunk["content_with_weight"]
    extent = verified_prefix_extent(chunk)
    assert extent is not None
    assert len(content[:extent].encode("utf-8")) != extent
    assert split_prefix(chunk)[1] == BODY


def expected_header():
    """The header the producer writes, built the same way it builds it."""
    return doc_context.render_document_context(
        doc_context.detect_standard_id(NAME, [BODY]),
        doc_context.document_title(NAME),
        doc_context.document_sections([BODY])[0],
    )


# ===========================================================================
# G2 - collision impossibility (the central gate)
# ===========================================================================


def test_g2_identical_visible_content_two_provenances_two_bodies():
    """Same bytes, two readings: one chunk's prefix was recorded by the producer, the other's text merely
    looks like a header (a legacy or edited chunk carries no provenance)."""
    header = header_of()
    content = header + BODY
    produced = with_provenance(content, len(header))
    natural = {"content_with_weight": content, "docnm_kwd": NAME}

    assert produced["content_with_weight"] == natural["content_with_weight"], "the visible bytes are identical"

    produced_prefix, produced_body = split_prefix(produced)
    natural_prefix, natural_body = split_prefix(natural)
    assert produced_prefix == header and produced_body == BODY
    assert natural_prefix == "" and natural_body == content
    assert produced_body != natural_body


def test_g2_the_consumer_distinguishes_them_too():
    """The difference must be observable where it matters: a figure that lives only in the injected header
    is evidence for the unprovenanced chunk and metadata for the produced one."""
    header = header_of()
    table = "<table><tr><td>导体</td><td>铜</td></tr></table>"
    produced = with_provenance(header + table, len(header))
    natural = {"content_with_weight": header + table, "docnm_kwd": NAME}
    assert "73286.2" in header, header
    assert carries_value(produced, ("73286.2",)) is False
    assert carries_value(natural, ("73286.2",)) is True


def test_g2b_a_natural_body_that_looks_like_a_header_is_still_prefixed():
    """The producer's own authority: a FRESH body whose first bytes are `[标准号: …` is a body, not a
    prefix, so it must be prefixed - and the recorded extent must cover only the injected part."""
    natural_look_alike = "[标准号: GB/T 10666-1997 | 文档: 某产品标准] 这是原文引用的一行内容。"
    chunk = prefixed_chunk(body=natural_look_alike)
    content = chunk["content_with_weight"]
    extent = verified_prefix_extent(chunk)
    assert extent is not None, "the producer must not skip injection for this body"
    assert content[:extent].endswith("] ")
    assert not content[:extent].startswith("[标准号: GB/T 10666")
    assert split_prefix(chunk)[1] == natural_look_alike, split_prefix(chunk)[1]


def test_g2c_the_old_string_heuristic_would_have_skipped_it():
    """Documents the defect this replaces: the old decision was the text itself."""
    natural_look_alike = "[标准号: GB/T 10666-1997 | 文档: 某产品标准] 这是原文引用的一行内容。"
    assert natural_look_alike.lstrip().startswith(doc_context.CONTEXT_PREFIX_OPEN), "the old check fires on body text"
    chunk = prefixed_chunk(body=natural_look_alike)
    assert chunk["content_with_weight"] != natural_look_alike, "the new producer still injects"


# ===========================================================================
# G3 - hostile header values
# ===========================================================================


@pytest.mark.parametrize(
    "hostile",
    [
        "规范]附录.pdf",
        "规范[第3部分].pdf",
        "标准|文档.pdf",
        "标准：文档：附录.pdf",
        "标题　带　全角空格.pdf",
        "标题  双空格.pdf",
        "标题\t制表符\n换行.pdf",
        "标 题 ± ℃ Ω μ — – “引号”.pdf",
        "a]b[c|d:e.pdf",
    ],
)
def test_g3_hostile_names_cannot_shift_the_boundary(hostile):
    """No parser is involved in recovery, so no character in the header can move the boundary."""
    name = f"{STANDARD} {hostile}"
    chunk = prefixed_chunk(name=name)
    extent = verified_prefix_extent(chunk)
    assert extent is not None
    assert split_prefix(chunk)[1] == BODY, name
    prefix, _body = split_prefix(chunk)
    assert prefix == chunk["content_with_weight"][:extent]
    assert prefix_hash(prefix) == chunk[PREFIX_HASH_FIELD]


def test_g3_no_heuristic_boundary_recovery_remains_in_the_consumer():
    """`_verified_header_end` and its helpers must not exist as a second authority."""
    from rag.retrieval import chunk_profile

    for banned in ("_verified_header_end", "_header_labels", "_document_names", "_strip_ingest_preamble"):
        assert not hasattr(chunk_profile, banned), banned


# ===========================================================================
# G4 - tamper / stale provenance
# ===========================================================================


def test_g4_a_tampered_prefix_byte_fails_closed():
    header = header_of()
    chunk = with_provenance(header + BODY, len(header))
    chunk["content_with_weight"] = "X" + chunk["content_with_weight"][1:]
    assert verified_prefix_extent(chunk) is None
    assert split_prefix(chunk) == ("", chunk["content_with_weight"])


@pytest.mark.parametrize("delta", [-1, 1, 3])
def test_g4_a_wrong_extent_fails_closed(delta):
    """The extent is only believable together with the hash the producer wrote FOR IT.

    Changing the extent alone - the hash still describing the real prefix - must fail closed. (A rewritten
    extent AND a rewritten hash is a different matter: `with_provenance` recomputes the digest, and that
    case is covered by the check that the producer is the only writer, plus G6's invalidation.)
    """
    header = header_of()
    chunk = with_provenance(header + BODY, len(header) + delta, digest=prefix_hash(header))
    assert verified_prefix_extent(chunk) is None
    assert split_prefix(chunk) == ("", chunk["content_with_weight"])


def test_g4_a_wrong_hash_fails_closed():
    header = header_of()
    chunk = with_provenance(header + BODY, len(header), digest="0" * 16)
    assert verified_prefix_extent(chunk) is None
    assert split_prefix(chunk) == ("", chunk["content_with_weight"])


def test_g4_a_tampered_prefix_fails_closed_and_never_partially_strips():
    """A body edit is legitimate and keeps the prefix; a change INSIDE the prefix region does not."""
    header = header_of()
    chunk = with_provenance(header + BODY, len(header))
    chunk["content_with_weight"] = header + "追加的正文"
    assert verified_prefix_extent(chunk) == len(header), "appending to the body is not tampering"
    assert split_prefix(chunk)[1] == "追加的正文"

    rewritten = with_provenance(header + BODY, len(header))
    rewritten["content_with_weight"] = "重写" + rewritten["content_with_weight"]
    assert verified_prefix_extent(rewritten) is None
    assert split_prefix(rewritten) == ("", rewritten["content_with_weight"])

    truncated = with_provenance(header + BODY, len(header))
    truncated["content_with_weight"] = truncated["content_with_weight"][5:]
    assert verified_prefix_extent(truncated) is None
    assert split_prefix(truncated) == ("", truncated["content_with_weight"])


def test_g4_missing_and_malformed_provenance_fail_closed():
    header = header_of()
    content = header + BODY
    cases = [
        {"content_with_weight": content},
        {"content_with_weight": content, PREFIX_KIND_FIELD: PREFIX_NONE},
        {"content_with_weight": content, PREFIX_KIND_FIELD: PREFIX_KIND_LEGACY, PREFIX_CHARS_FIELD: None},
        {"content_with_weight": content, PREFIX_KIND_FIELD: PREFIX_KIND_LEGACY, PREFIX_CHARS_FIELD: "12"},
        {"content_with_weight": content, PREFIX_KIND_FIELD: PREFIX_KIND_LEGACY, PREFIX_CHARS_FIELD: -3},
        {"content_with_weight": content, PREFIX_KIND_FIELD: PREFIX_KIND_LEGACY, PREFIX_CHARS_FIELD: 10**9},
        {"content_with_weight": content, PREFIX_KIND_FIELD: "unknown_kind", PREFIX_CHARS_FIELD: len(header)},
    ]
    for chunk in cases:
        assert verified_prefix_extent(chunk) is None, chunk
        assert split_prefix(chunk) == ("", content), chunk


# ===========================================================================
# G5 - idempotency
# ===========================================================================


def test_g5_a_second_producer_pass_changes_nothing():
    chunk = prefixed_chunk()
    before = dict(chunk)
    chunk_id = hashlib.sha256(before["content_with_weight"].encode("utf-8")).hexdigest()
    assert doc_context.apply_document_context([chunk], NAME, language="Chinese") == 0
    assert chunk == before
    assert hashlib.sha256(chunk["content_with_weight"].encode("utf-8")).hexdigest() == chunk_id
    content = chunk["content_with_weight"]
    assert content.count(doc_context.CONTEXT_PREFIX_OPEN) == 1
    assert verified_prefix_extent(chunk) == len(content) - len(BODY)


def test_g5_a_provenanced_chunk_is_not_prefixed_twice_even_if_the_body_looks_prefixed():
    natural = "[标准号: GB/T 1-2020 | 文档: 引用] 原文。"
    chunk = prefixed_chunk(body=natural)
    once = chunk["content_with_weight"]
    extent = chunk[PREFIX_CHARS_FIELD]
    digest = chunk[PREFIX_HASH_FIELD]
    assert doc_context.apply_document_context([chunk], NAME, language="Chinese") == 0
    assert chunk["content_with_weight"] == once
    assert chunk[PREFIX_CHARS_FIELD] == extent and chunk[PREFIX_HASH_FIELD] == digest
    assert split_prefix(chunk)[1] == natural


# ===========================================================================
# G6 - mutation invalidation
# ===========================================================================


def test_g6_an_edit_that_changes_content_invalidates_provenance():
    chunk = prefixed_chunk()
    invalidation_after_edit(chunk, "完全不同的新正文")
    chunk["content_with_weight"] = "完全不同的新正文"
    assert verified_prefix_extent(chunk) is None
    assert split_prefix(chunk)[1] == "完全不同的新正文"


def test_g6_an_edit_that_preserves_the_prefix_bytes_may_keep_it():
    chunk = prefixed_chunk()
    extent = chunk[PREFIX_CHARS_FIELD]
    prefix = chunk["content_with_weight"][:extent]
    edited = prefix + "编辑后的正文"
    invalidation_after_edit(chunk, edited)
    chunk["content_with_weight"] = edited
    assert verified_prefix_extent(chunk) == extent
    assert split_prefix(chunk)[1] == "编辑后的正文"


def test_g6_the_manual_edit_api_uses_the_invalidation_helper():
    path = pathlib.Path("/ragflow/api/apps/restful_apis/chunk_api.py")
    source = path.read_text(encoding="utf-8")
    assert "invalidation_after_edit" in source, "a manual content edit must not leave stale provenance"
    assert "PREFIX_FIELDS" in source, "and must carry the recorded fields onto the replacement document"


# ===========================================================================
# G7 - mixed-version pool
# ===========================================================================


def test_g7_legacy_new_and_malformed_chunks_coexist_deterministically():
    header = header_of()
    body_text = "厚度 1.5mm 的内衬层。"
    new = with_provenance(header + body_text, len(header))
    legacy = {"content_with_weight": header + body_text, "docnm_kwd": NAME}
    malformed = dict(new)
    malformed[PREFIX_CHARS_FIELD] = len(header) + 4
    pool = [new, legacy, malformed, {"content_with_weight": body_text, "docnm_kwd": NAME}]

    first = [split_prefix(chunk)[1] for chunk in pool]
    second = [split_prefix(chunk)[1] for chunk in pool]
    assert first == second, "verdicts are deterministic"
    assert first[0] == body_text
    assert first[1] == header + body_text
    assert first[2] == header + body_text
    assert first[3] == body_text
    # Each verdict depends only on its own chunk:
    assert split_prefix(pool[0])[1] == body_text


# ===========================================================================
# G8 - corpus semantic freeze (producer side)
# ===========================================================================


def test_g8_the_producer_changes_nothing_but_the_provenance_fields():
    chunk = prefixed_chunk()
    assert chunk["content_with_weight"] == expected_header() + BODY, "content bytes are the pre-contract bytes"
    assert chunk["content_ltks"].endswith("body tks"), chunk["content_ltks"]
    assert "q_3072_vec" not in chunk and not any(key.startswith("q_") for key in chunk)
    added = {key for key in chunk if key not in ("content_with_weight", "doc_id", "docnm_kwd", "content_ltks", "content_sm_ltks")}
    assert added == set(PREFIX_FIELDS), added


# ===========================================================================
# G9 - rollback compatibility
# ===========================================================================


def test_g9_new_consumer_shapes():
    header = header_of()
    body_text = "厚度 1.5mm。"
    new_chunk = with_provenance(header + body_text, len(header))
    legacy_chunk = {"content_with_weight": header + body_text, "docnm_kwd": NAME}
    corrupted = dict(new_chunk)
    corrupted[PREFIX_HASH_FIELD] = "deadbeefdeadbeef"

    assert split_prefix(new_chunk)[1] == body_text
    assert split_prefix(legacy_chunk)[1] == header + body_text
    assert split_prefix(corrupted)[1] == header + body_text
    # An OLD consumer (no provenance awareness) sees the recorded header as text it may still remove by
    # its own heuristic; the contract makes that unnecessary, not wrong:
    assert new_chunk["content_with_weight"].startswith("[标准号: ")


def test_g9_an_old_consumer_can_still_read_a_new_chunk():
    """The fields are additive: an image that knows nothing about them reads today's bytes unchanged."""
    chunk = prefixed_chunk()
    for field in PREFIX_FIELDS:
        assert field in chunk
    legacy_view = {key: value for key, value in chunk.items() if key not in PREFIX_FIELDS}
    assert legacy_view["content_with_weight"] == expected_header() + BODY
