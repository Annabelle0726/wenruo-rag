#
#  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
#  Modifications Copyright 2026 线缆工业智搜平台. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
"""Retrieval metadata: canonical facts, a domain profile, and the header they project.

The pipeline that this module is the whole of:

    candidates -> canonical metadata -> domain profile -> retrieval projection
              -> retrieval header -> retrieval text (= header + raw chunk)

Three separations are the point of it, and each one is a defect that was measured
before it existed:

1. **The raw chunk is not the representation.** ``raw_chunk`` is what the parser
   produced and what the answer model should read; ``retrieval_text`` is
   ``header + raw_chunk`` and is what the lexical and dense legs index. They are
   different objects with the same field today (``content_with_weight``), so nothing
   here mutates a chunk in place: :func:`retrieval_text` composes, and
   :func:`split_retrieval_header` takes them apart again.

2. **A cited number is not this document's number.** A corpus repeats the standards a
   document APPLIES (GB/T 12706.1 in a 规格书, GB/T 1.1 in every foreword), and the
   frequency of a designation in a body says how often it is cited, not who owns the
   document. ``document_standard_no`` and ``referenced_standard_nos`` are therefore
   separate keys, filled from separate sources with separate confidences, and a
   document whose identity cannot be established keeps ``document_standard_no = None``
   rather than the most frequent citation.

3. **The fields are the PROFILE's, not the renderer's.** ``[标准号 | 文档 | 芯数 | 电压 |
   章节]`` is what a power cable needs. An OPGW document needs 纤芯数 and 光纤类型, a
   transformer needs 额定容量 and 冷却方式, and a corpus of software procedures needs
   neither: a renderer that names those fields would be a cable renderer pretending to
   be a generic one. :func:`render_retrieval_header` walks a profile's field list and
   knows no field name at all; adding a domain is adding a :class:`DocumentProfile`
   (see ``test_retrieval_metadata.py``, which adds one and renders it without touching
   a single line of this renderer).

Everything here is deterministic and offline: no model call, no I/O, no mutation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

#: Bumped whenever the projection changes shape (a field added to a profile, a label
#: changed, the header syntax changed). A chunk whose ``retrieval_schema_version`` is
#: not this value was embedded from a different representation, which is the fact the
#: embedding-dirty design needs - see :func:`embedding_is_stale`.
RETRIEVAL_SCHEMA_VERSION = 1

#: Bumped whenever the EMBEDDING of the retrieval text changes (a new model, a new
#: dimension). Independent of the schema version on purpose: a corpus can be re-headed
#: without being re-embedded, and that is exactly the transition the platform is on.
EMBEDDING_SCHEMA_VERSION = 1

#: Where a candidate came from, strongest first. The ORDER is the conflict resolution:
#: a value read off the title page outranks the same value guessed from a family.
SOURCE_TITLE_PAGE = "title_page"
SOURCE_FILE_NAME = "file_name"
SOURCE_DOCUMENT_BODY = "document_body"
SOURCE_METADATA_STORE = "metadata_store"
SOURCE_FAMILY_INFERENCE = "family_inference"
SOURCE_ORDER = (
    SOURCE_TITLE_PAGE,
    SOURCE_FILE_NAME,
    SOURCE_METADATA_STORE,
    SOURCE_DOCUMENT_BODY,
    SOURCE_FAMILY_INFERENCE,
)

#: How sure a source is, before the evidence of the individual value is taken into
#: account. A file name is the document naming itself; a body is where citations live.
SOURCE_CONFIDENCE = {
    SOURCE_TITLE_PAGE: 0.98,
    SOURCE_FILE_NAME: 0.9,
    SOURCE_METADATA_STORE: 0.85,
    SOURCE_DOCUMENT_BODY: 0.55,
    SOURCE_FAMILY_INFERENCE: 0.45,
}

#: Below this, a candidate is not written into the canonical metadata at all.
MIN_CONFIDENCE = 0.5


@dataclass(frozen=True)
class MetadataCandidate:
    """One value for one key, with where it came from and how sure we are.

    The audit trail the earlier rounds needed and did not have: "芯数: 单芯" is not a
    fact until it says whether the file name said so or a body merely mentioned it.
    """

    key: str
    value: Any
    source: str
    confidence: float
    evidence: str = ""

    def __str__(self) -> str:  # for the dry-run report
        return f"{self.key}={self.value!r} <- {self.source} ({self.confidence:.2f}{'; ' + self.evidence if self.evidence else ''})"


@dataclass
class CanonicalMetadata:
    """What is known about ONE document, after conflict resolution."""

    document_id: str = ""
    title: str = ""
    document_type: str = ""
    category: str = "unknown"
    document_standard_no: str | None = None
    referenced_standard_nos: tuple[str, ...] = ()
    attributes: dict[str, str] = field(default_factory=dict)
    #: Every candidate that was considered, kept for review - including the rejected
    #: ones, because "why is this field wrong" is answered by the losers.
    evidence: list[MetadataCandidate] = field(default_factory=list)

    def value_of(self, key: str) -> Any:
        """The value of a profile field, wherever it lives."""
        if key == "document_standard_no":
            return self.document_standard_no
        if key == "title":
            return self.title
        if key == "document_type":
            return self.document_type
        if key == "category":
            return self.category
        return self.attributes.get(key)


def resolve_metadata(candidates: Iterable[MetadataCandidate], *, document_id: str = "", title: str = "", category: str = "") -> CanonicalMetadata:
    """Candidates -> canonical metadata, one winner per key, losers kept as evidence.

    Resolution is ``(source order, confidence)`` and NOT frequency: a designation the
    body repeats twenty times is a document citing a standard it applies, while the one
    in the file name is the document saying what it is. A key whose only candidates sit
    below :data:`MIN_CONFIDENCE` stays unset, which is the "宁可不写" rule.
    """
    resolved = CanonicalMetadata(document_id=document_id, title=title, category=category or "unknown")
    ordered = sorted(
        candidates,
        key=lambda candidate: (SOURCE_ORDER.index(candidate.source) if candidate.source in SOURCE_ORDER else len(SOURCE_ORDER), -candidate.confidence),
    )
    resolved.evidence = list(ordered)
    for candidate in ordered:
        if candidate.value in (None, "", (), [], {}):
            continue
        if candidate.key == "document_standard_no":
            if resolved.document_standard_no is None and candidate.confidence >= MIN_CONFIDENCE:
                resolved.document_standard_no = str(candidate.value)
            continue
        if candidate.key == "referenced_standard_nos":
            values = tuple(str(value) for value in candidate.value if value)
            if values:
                resolved.referenced_standard_nos = tuple(dict.fromkeys((*resolved.referenced_standard_nos, *values)))
            continue
        if candidate.key in ("title", "document_type"):
            # A name-derived title/type never overrides one that was passed in.
            continue
        if candidate.key not in resolved.attributes and candidate.confidence >= MIN_CONFIDENCE:
            resolved.attributes[candidate.key] = str(candidate.value)
    return resolved


# ---------------------------------------------------------------------------
# Profiles: which fields a domain projects, and under which label
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetrievalField:
    """One field a profile writes into the retrieval header.

    ``label`` is the Chinese label the header prints; ``key`` is where the value comes
    from in the canonical metadata. Both belong to the PROFILE, so a new domain is a new
    profile and never an ``if`` in the renderer.
    """

    key: str
    label: str


@dataclass(frozen=True)
class DocumentProfile:
    """A domain: what it calls its fields, and which of them retrieval indexes.

    ``identity_fields`` say WHAT the document is (and are the minimum a header needs);
    ``retrieval_fields`` are the domain attributes worth matching a question against.
    """

    category: str
    identity_fields: tuple[RetrievalField, ...]
    retrieval_fields: tuple[RetrievalField, ...]
    cues: tuple[str, ...] = ()

    @property
    def fields(self) -> tuple[RetrievalField, ...]:
        return (*self.identity_fields, *self.retrieval_fields)


#: The identity every profile shares: a standard number when the document has one, and
#: its title always. Written once so a new profile cannot forget it.
_COMMON_IDENTITY = (
    RetrievalField("document_standard_no", "标准号"),
    RetrievalField("title", "文档"),
)

#: The profiles that exist today. Declarative data: a YAML file would hold the same
#: tuples, and nothing but this table would have to change.
PROFILES: dict[str, DocumentProfile] = {
    "power_cable": DocumentProfile(
        category="power_cable",
        identity_fields=_COMMON_IDENTITY,
        retrieval_fields=(
            RetrievalField("voltage_level", "电压"),
            RetrievalField("core_count", "芯数"),
            RetrievalField("cable_type", "线缆类别"),
            RetrievalField("cable_environment", "敷设环境"),
        ),
        cues=("电缆", "导线", "架空绝缘", "海缆", "电力电缆", "绝缘线"),
    ),
    "optical_cable": DocumentProfile(
        category="optical_cable",
        identity_fields=_COMMON_IDENTITY,
        retrieval_fields=(
            RetrievalField("fiber_count", "纤芯数"),
            RetrievalField("fiber_type", "光纤类型"),
            RetrievalField("voltage_level", "电压"),
            RetrievalField("cable_environment", "敷设环境"),
        ),
        cues=("OPGW", "ADSS", "光缆", "光纤", "导引光缆"),
    ),
    "transformer": DocumentProfile(
        category="transformer",
        identity_fields=_COMMON_IDENTITY,
        retrieval_fields=(
            RetrievalField("rated_capacity", "额定容量"),
            RetrievalField("voltage_ratio", "电压比"),
            RetrievalField("cooling_method", "冷却方式"),
        ),
        cues=("变压器", "互感器", "电抗器"),
    ),
}

#: The safe fallback: a document whose domain is unknown still gets its IDENTITY into
#: the retrieval text (a title and a standard number are useful in any domain) and no
#: invented attribute. Nothing is ever skipped, and nothing is ever guessed.
UNKNOWN_PROFILE = DocumentProfile(category="unknown", identity_fields=_COMMON_IDENTITY, retrieval_fields=())


def profile_for(category: str) -> DocumentProfile:
    return PROFILES.get(str(category or "").strip().lower(), UNKNOWN_PROFILE)


def classify_category(*texts: str) -> str:
    """The domain a document belongs to, from its own words, or ``unknown``.

    Deliberately a cue match over the profile table and nothing cleverer: a document
    that names no domain keeps the fallback profile rather than being forced into the
    nearest one, because a wrong category would project the WRONG fields.
    """
    haystack = " ".join(str(text or "") for text in texts).upper()
    for profile in PROFILES.values():
        for cue in profile.cues:
            if cue.upper() in haystack:
                return profile.category
    return UNKNOWN_PROFILE.category


# ---------------------------------------------------------------------------
# The header: a projection of the profile's fields, and nothing else
# ---------------------------------------------------------------------------

HEADER_OPEN = "["
HEADER_CLOSE = "] "
_HEADER_RE = re.compile(r"^\[[^\[\]]*\]\s?")


def render_retrieval_header(metadata: CanonicalMetadata, profile: DocumentProfile | None = None) -> str:
    """``[label: value | label: value] `` for the profile's non-empty fields.

    The renderer knows NO field name: it walks ``profile.fields``, asks the metadata for
    each key, and skips what is missing - so a field that does not exist in a domain is
    simply absent, never rendered as an empty or dashed placeholder, and a new domain
    renders correctly without this function changing.
    """
    profile = profile or profile_for(metadata.category)
    parts: list[str] = []
    for spec in profile.fields:
        value = metadata.value_of(spec.key)
        if isinstance(value, (list, tuple)):
            value = "、".join(str(item) for item in value if item)
        text = " ".join(str(value or "").split())
        if not text:
            continue
        parts.append(f"{spec.label}: {text}")
    if not parts:
        return ""
    return HEADER_OPEN + " | ".join(parts) + HEADER_CLOSE


def split_retrieval_header(text: str) -> tuple[str, str]:
    """``(header, raw_chunk)`` for a retrieval text, header included only if present.

    The inverse of :func:`retrieval_text`, and the reason a backfill cannot double-prepend:
    a body that already carries a header yields it here, so the caller replaces rather
    than stacks. It matches ANY bracketed lead-in rather than the fields of one version,
    so a legacy header is recognised by the version that replaced it.
    """
    body = str(text or "")
    match = _HEADER_RE.match(body)
    if not match:
        return "", body
    return match.group(0).rstrip(), body[match.end() :]


def retrieval_text(raw_chunk: str, header: str) -> str:
    """``retrieval_header + raw_chunk`` - the text the retrieval legs index.

    Idempotent by construction: an existing header is dropped first, so applying the
    same projection twice cannot stack two headers, and re-projecting after a schema
    change REPLACES the old header instead of accumulating one.
    """
    _existing, body = split_retrieval_header(raw_chunk)
    if not header:
        return body
    return header + body


#: The three states a stored chunk can be in, for a migration that must not stack.
PREFIX_NONE = "no_prefix"
PREFIX_LEGACY = "legacy_prefix"
PREFIX_CURRENT = "current_prefix"


def declared_prefix_kind(text: str, *, current_fields: Sequence[str] = ()) -> str:
    """Which header a stored chunk carries: none, a LEGACY one, or the current shape.

    The distinction a backfill needs is "does this body already start with a header",
    which :func:`split_retrieval_header` answers, plus "is that header the shape this
    version writes". The IDENTITY labels cannot tell the two apart - every version
    prints 标准号 and 文档 - so a header counts as CURRENT only when it carries a label
    from a profile's RETRIEVAL fields (芯数/电压/纤芯数…), which is exactly the difference
    between the live 3-field legacy header and the projection this module renders. A
    caller may pass its own labels for a domain whose header it knows.
    """
    header, body = split_retrieval_header(text)
    if not header:
        return PREFIX_NONE
    if not body.strip():
        return PREFIX_LEGACY
    current_labels = {spec.label for profile in (*PROFILES.values(), UNKNOWN_PROFILE) for spec in profile.retrieval_fields}
    current_labels.update(str(label) for label in current_fields)
    carried = {part.split(":", 1)[0].strip() for part in header.strip("[]").split("|") if ":" in part}
    if carried & current_labels:
        return PREFIX_CURRENT
    return PREFIX_LEGACY


# ---------------------------------------------------------------------------
# Version + dirty: what the embedding represents
# ---------------------------------------------------------------------------


def embedding_is_stale(*, retrieval_schema_version: Any, embedding_schema_version: Any) -> bool:
    """Whether a stored chunk's vector was built from a different representation.

    One predicate, two reasons: the projection changed (this module's version) or the
    embedding itself did. A chunk with neither field recorded is treated as STALE rather
    than current: it was written before the fields existed, so nothing can claim its
    vector matches today's representation.
    """
    try:
        schema = int(retrieval_schema_version)
    except (TypeError, ValueError):
        return True
    try:
        embedding = int(embedding_schema_version)
    except (TypeError, ValueError):
        return True
    return schema != RETRIEVAL_SCHEMA_VERSION or embedding != EMBEDDING_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Document families (the minimum a cross-part fallback needs)
# ---------------------------------------------------------------------------

#: A part states the RULES for its whole standard; the parts beside it state what a
#: project must respond with. The distinction is what a fallback rides on.
ROLE_COMMON_SPEC = "common_spec"
ROLE_SPECIFIC_SPEC = "specific_spec"
ROLE_UNKNOWN = "unknown"

_COMMON_CUE = "通用技术规范"
_SPECIFIC_CUE = "专用技术规范"


@dataclass(frozen=True)
class DocumentFamily:
    """The smallest relation that answers "which document states the baseline?".

    No graph: a family id, the part number, the role, and the two links a fallback needs
    - the common spec to read a baseline from, and what this part applies to. An LLM
    guessing relations from titles is what this replaces.
    """

    family_id: str
    part_no: int | None
    document_role: str
    related_common_spec: str | None = None
    applies_to: tuple[str, ...] = ()

    @property
    def needs_common_spec(self) -> bool:
        """A specific part with no common spec in sight is the fallback's trigger."""
        return self.document_role == ROLE_SPECIFIC_SPEC and self.related_common_spec is None


def resolve_family(*, designation: str | None, name: str, family_id: str = "") -> DocumentFamily:
    """``DocumentFamily`` for a document, from its designation and its file name."""
    from rag.retrieval.chunk_profile import designation_parts, name_family

    role = ROLE_UNKNOWN
    if _COMMON_CUE in name:
        role = ROLE_COMMON_SPEC
    elif _SPECIFIC_CUE in name:
        role = ROLE_SPECIFIC_SPEC
    part: int | None = None
    resolved_id = family_id
    if designation:
        parsed = designation_parts(designation)
        if parsed:
            resolved_id = resolved_id or parsed[0]
            part = parsed[1]
    resolved_id = resolved_id or name_family(name)
    return DocumentFamily(family_id=resolved_id, part_no=part, document_role=role)


def link_families(families: Sequence[DocumentFamily]) -> list[DocumentFamily]:
    """Fill ``related_common_spec`` for every specific part of a family, offline.

    A family is linked only when the common part is IN the sequence: a link invented for
    a part whose Part 1 was never ingested would send a fallback into an empty scope, so
    the absence is left visible in ``related_common_spec = None``.
    """
    commons: dict[str, DocumentFamily] = {}
    for family in families:
        if family.document_role == ROLE_COMMON_SPEC and family.family_id:
            commons.setdefault(family.family_id, family)
    linked: list[DocumentFamily] = []
    for family in families:
        common = commons.get(family.family_id)
        if family.document_role == ROLE_SPECIFIC_SPEC and common is not None:
            linked.append(DocumentFamily(family.family_id, family.part_no, family.document_role, common.family_id, family.applies_to))
        else:
            linked.append(family)
    return linked


# ---------------------------------------------------------------------------
# Blank response templates (a signal, not an evidence source)
# ---------------------------------------------------------------------------

#: The words a bidder fill-in template writes where a value should be. Measured on the
#: live 220kV report: the two 专用技术规范 parts carry 58 and 54 occurrences of 项目单位填写
#: against 0 in 《第1部分：通用技术规范》, which is what makes this the signal and the
#: cell-fill ratio only the corroboration.
FILL_IN_MARKERS = ("项目单位填写", "投标人填写", "项目单位提供", "投标人提供", "投标人应提供", "由投标人", "由项目单位", "待填写", "填写")

#: A table is a template when it SAYS a value is to be filled in, and either its cells
#: are half empty or the marker repeats. A parameter table full of real values carries
#: neither, and a template caught by the marker alone still triggers the fallback - which
#: is the conservative direction: the cost of a false positive is one extra retrieval,
#: the cost of a false negative is a refusal.
BLANK_TEMPLATE_MAX_FILL = 0.8
BLANK_TEMPLATE_MIN_MARKERS = 2

CLASS_BLANK_RESPONSE_TEMPLATE = "blank_response_template"


def blank_template_evidence(chunk: dict) -> list[str]:
    """Why a passage looks like a bidder response template, or why it does not."""
    from rag.retrieval.chunk_profile import is_table_chunk, table_fill_ratio

    if not is_table_chunk(chunk):
        return []
    body = str(chunk.get("content_with_weight") or chunk.get("content") or "")
    markers = sum(body.count(marker) for marker in FILL_IN_MARKERS)
    fill = table_fill_ratio(chunk)
    if not markers:
        return []
    if fill is not None and fill > BLANK_TEMPLATE_MAX_FILL and markers < BLANK_TEMPLATE_MIN_MARKERS:
        return []
    reasons = [f"{markers} fill-in marker(s)"]
    if fill is not None:
        reasons.append(f"{fill:.2f} of its cells non-empty")
    return reasons


def is_blank_response_template(chunk: dict) -> bool:
    """Whether a passage is a template a bidder fills in.

    Such a passage may be RECALLED - it is where the question's parameter names live -
    but it is not evidence for a value, and finding one is what tells the pipeline to
    read the baseline from the common spec instead.
    """
    return bool(blank_template_evidence(chunk))
