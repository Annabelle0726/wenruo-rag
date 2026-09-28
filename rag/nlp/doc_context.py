#
#  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
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
"""Bind the document-level identity to every chunk of a standards document.

A standards document filed under a human file name ("450/750V聚氯乙烯绝缘电缆采购
标准+第2部分：专用技术规范_2.pdf") loses its identity the moment its cover page is
sliced away from its parameter tables. The surviving chunk keeps only the file
name, which reads like a procurement standard, so the answering model concludes
the knowledge base holds "only a procurement standard" instead of the Q/GDW body
it was asked about — even though the retrieved chunk came from that very standard.

:func:`apply_document_context` prefixes each chunk with the document-level context,
so the identity travels with every slice:

    [标准号: Q/GDW 73289.2-2026 | 文档: 450/750V聚氯乙烯绝缘电缆采购标准+第2部分：专用技术规范 | 章节: 表1 技术参数特性表] 内容...

The prefix lives in the chunk body rather than in a separate metadata field, so it
reaches the index through the normal path: the prefix's tokens are prepended to
``content_ltks`` / ``content_sm_ltks``, the embedding and the chunk id are derived
from the prefixed body, and the retrieval stage hands that same body to the model. A
question naming the standard number therefore matches the chunk lexically,
semantically and visibly.

**The prefix boundary is recorded, not re-derived.** Alongside the text this module
writes four provenance fields (:data:`PREFIX_FIELDS`): the kind, the grammar version,
the exact code-point extent of the injected prefix, and a hash of exactly those
characters. A consumer that wants the passage's OWN text slices
``content_with_weight[extent:]`` after verifying the hash, and otherwise treats the
whole content as evidence. The text is never parsed to recover the boundary, because a
document's own prose can begin with bytes identical to a prefix - which is also why the
injection check below asks provenance, not the text, whether a prefix is already there.

Injection is conditional by design: a document that declares no standard number
keeps byte-identical chunks, so ordinary documents are untouched.

The Go ingestion backend implements the same policy in
``internal/ingestion/component/chunker/doccontext.go``; the two must stay aligned.
"""

import re
from typing import Any, Dict, Iterable, List, Sequence

import xxhash

#: Starts every injected prefix. It is the format's opening marker, NOT an idempotency
#: authority: whether a chunk already carries a prefix is decided by
#: :func:`verified_prefix_extent`, because a document's own body can start with these
#: exact bytes.
CONTEXT_PREFIX_OPEN = "[标准号: "

# --- Injected-prefix provenance contract ------------------------------------
#
#: The four fields a producer writes when it injects a prefix. All four names are typed
#: and stored by the chunk index's existing dynamic templates (`*_kwd` -> keyword,
#: `*_int` -> integer, both stored), so no mapping change is needed.
PREFIX_KIND_FIELD = "content_prefix_kind_kwd"
PREFIX_VERSION_FIELD = "content_prefix_version_int"
PREFIX_CHARS_FIELD = "content_prefix_chars_int"
PREFIX_HASH_FIELD = "content_prefix_hash_kwd"
PREFIX_FIELDS = (PREFIX_KIND_FIELD, PREFIX_VERSION_FIELD, PREFIX_CHARS_FIELD, PREFIX_HASH_FIELD)

#: `kind` values. `none` (and an absent field) mean "no prefix was recorded here", which
#: is the truthful answer for legacy chunks and for content a human edited.
PREFIX_NONE = "none"
PREFIX_KIND_LEGACY = "identity_legacy"
PREFIX_KIND_PROFILE = "identity_profile"

#: Grammar versions: 1 = this module's `标准号|文档|章节` line, 2 = the projection
#: module's profile header.
LEGACY_PREFIX_VERSION = 1
PROFILE_PREFIX_VERSION = 2


def prefix_hash(prefix: str) -> str:
    """The hash a consumer verifies: xxhash64 (hex) of the exact injected characters."""
    return xxhash.xxh64(str(prefix or "").encode("utf-8")).hexdigest()


def record_prefix(chunk: Dict[str, Any], prefix: str, kind: str = PREFIX_KIND_LEGACY, version: int = LEGACY_PREFIX_VERSION) -> None:
    """Record that ``prefix`` was injected at position 0 of this chunk's content.

    Called by the producer immediately after it prepends, never by a reader: the extent is
    what the producer WROTE, which is the only way to know where a prefix ends.
    """
    extent = len(str(prefix or ""))
    chunk[PREFIX_KIND_FIELD] = kind
    chunk[PREFIX_VERSION_FIELD] = int(version)
    chunk[PREFIX_CHARS_FIELD] = extent
    chunk[PREFIX_HASH_FIELD] = prefix_hash(prefix) if extent else ""


def clear_prefix(chunk: Dict[str, Any]) -> None:
    """State that this chunk has no recorded prefix (legacy, or content a human changed)."""
    chunk[PREFIX_KIND_FIELD] = PREFIX_NONE
    chunk[PREFIX_VERSION_FIELD] = 0
    chunk[PREFIX_CHARS_FIELD] = 0
    chunk[PREFIX_HASH_FIELD] = ""


#: Grammar versions this contract supports. A version the consumer does not know is not a prefix it may
#: act on, so an unsupported (or unparsable) version fails closed like any other malformed provenance.
_SUPPORTED_PREFIX_VERSIONS = (LEGACY_PREFIX_VERSION, PROFILE_PREFIX_VERSION)

#: The canonical spelling of an unsigned decimal: ASCII digits only, no sign, no whitespace, no decimal
#: point, no exponent, no full-width digit, and no leading zero beyond the single ``"0"``. `[0-9]` is
#: deliberately used instead of ``\\d``/``str.isdigit``, both of which accept Unicode digits.
_CANONICAL_UNSIGNED_DECIMAL_RE = re.compile(r"[0-9]+")


def _canonical_unsigned_decimal(value: Any) -> int | None:
    """The two wire forms an integer provenance field may arrive in, or ``None``.

    The producer writes a Python ``int``, but the datastore does not hand one back: `es_conn.get_fields`
    stringifies every non-list value it reads except ``available_int``, so a consumer sees ``"105"`` for a
    stored ``105``. Accepting exactly the canonical unsigned decimal STRING alongside a real ``int`` keeps
    the contract's invariant intact while adapting to the transport's declared representation - and only
    those two forms. ``bool`` is rejected explicitly because ``isinstance(True, int)`` is true in Python,
    and validation happens BEFORE any conversion: this is not ``int(value)`` with a try/except, which would
    accept ``" 1"``, ``"+1"``, ``"01"``, ``"1.0"`` and full-width digits.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    if not _CANONICAL_UNSIGNED_DECIMAL_RE.fullmatch(value):
        return None
    if len(value) > 1 and value[0] == "0":
        return None
    return int(value)


def verified_prefix_extent(chunk: Dict[str, Any]) -> int | None:
    """The extent of the injected prefix, or ``None`` when it cannot be PROVEN.

    The invariant: a kind other than ``none``, a version this contract supports, an integer extent in range
    (given in either wire form), and a hash of ``content[:extent]`` that matches what the producer recorded.
    Anything else - missing fields, a non-canonical representation, a negative or out-of-range extent, an
    unknown kind, an unsupported version, one byte changed anywhere in the prefix - returns ``None``, and the
    caller must then treat the whole content as the passage's text.
    """
    kind = chunk.get(PREFIX_KIND_FIELD)
    if not isinstance(kind, str) or not kind or kind == PREFIX_NONE:
        return None
    if _canonical_unsigned_decimal(chunk.get(PREFIX_VERSION_FIELD)) not in _SUPPORTED_PREFIX_VERSIONS:
        return None
    extent = _canonical_unsigned_decimal(chunk.get(PREFIX_CHARS_FIELD))
    if extent is None or extent <= 0:
        return None
    content = chunk.get("content_with_weight")
    if not isinstance(content, str) or extent > len(content):
        return None
    digest = chunk.get(PREFIX_HASH_FIELD)
    if not isinstance(digest, str) or not digest:
        return None
    return extent if prefix_hash(content[:extent]) == digest else None


def split_prefix(chunk: Dict[str, Any]) -> tuple[str, str]:
    """``(prefix, body)`` - the body being the whole content unless provenance proves a prefix."""
    content = str(chunk.get("content_with_weight") or "")
    extent = verified_prefix_extent(chunk)
    if extent is None:
        return "", content
    return content[:extent], content[extent:]


def invalidation_after_edit(chunk: Dict[str, Any], new_content: str, previous_content: str | None = None) -> None:
    """Clear recorded provenance for a manual edit, unless the prefix bytes are unchanged.

    Call it BEFORE assigning ``new_content`` to the chunk, or pass the content that is still
    stored as ``previous_content`` (an update path that builds the replacement field set
    first has to do the latter). Editing only the body keeps the prefix, and with it the
    provenance; any other edit - including a rewrite of the prefix itself - clears it, so a
    stale extent can never be inherited by content it does not describe. A caller that
    assigns first and calls afterwards simply gets the fail-closed answer, which is also
    correct.
    """
    content = str(new_content or "")
    before = str(chunk.get("content_with_weight") or "") if previous_content is None else str(previous_content or "")
    extent = verified_prefix_extent({**chunk, "content_with_weight": before})
    if extent is not None and content.startswith(before[:extent]):
        return
    clear_prefix(chunk)

#: Scan bounds. A standard number identifying the document is declared on the
#: cover page (and often repeated in the running header), so the leading chunks
#: are enough; the character cap keeps the scan cheap for pathological chunks.
SCAN_CHUNK_LIMIT = 8
SCAN_CHAR_LIMIT = 4000

#: Display fields inside a retrieval chunk; capped so a pathological file name
#: cannot dominate the chunk's token budget.
TITLE_CHAR_LIMIT = 60
SECTION_CHAR_LIMIT = 40

#: How long the TEXT after a section number may be before it stops being a heading.
#: A clause heading is a few words ("5.1 电缆结构", "6.2.3 例行交流电压试验"); anything
#: longer is the clause's own prose, and the section is then the number alone.
SECTION_TAIL_CHAR_LIMIT = 16

#: What ends a heading's text: sentence punctuation. A Chinese comma is NOT a terminator,
#: because a real heading uses one ("5.1 导体，屏蔽").
_HEADING_TAIL_BREAK_RE = re.compile(r"[。！？；;!?]|\s-\s")

#: Allowlist of standard-designation prefixes: Chinese
#: national/industry/enterprise standards plus the common international bodies. An
#: allowlist rather than a permissive pattern keeps ordinary technical prose —
#: motor ratings such as "450/750V" or cable models — from being read as a
#: standard number.
#:
#: MT (煤炭行业标准) is here because its absence was worse than a missing feature: a
#: coal standard's own number was invisible to the scan, so the detection fell
#: through to the first *cited* standard in the front matter and stamped every
#: chunk of 《MT/T 818.11-2009》 with a "标准号" the document does not own — which the
#: answering prompt is told to treat as authoritative.
_STANDARD_PREFIXES = r"Q/[A-Z]{2,6}|GB|DL|NB|MT|JB|YD|JJG|JJF|HG|SH|SY|TB|CJ|JG|JGJ|CECS|IEC|ISO|IEEE|EN|BS|DIN|JIS|ASTM|ANSI|UL|API"

#: "<prefix><optional /T> <number>[.<number>...] - <year>". Whitespace is allowed
#: around the separator because cover pages routinely wrap "Q/GDW 73289.2" away
#: from its year, and the dash may be an ASCII hyphen or a Unicode dash variant.
_STANDARD_ID_RE = re.compile(r"(?i)(" + _STANDARD_PREFIXES + r")(/[A-Z]{1,3})?\s*([0-9]{1,6}(?:\.[0-9]{1,3})*)\s*[-\u2010\u2011\u2012\u2013\u2014]\s*([0-9]{4})")

#: Year-less form. Only enterprise standards (Q/...) are accepted without a year:
#: their designation is unambiguous, whereas a bare "GB 1234" is more likely a
#: table value.
_ENTERPRISE_STANDARD_ID_RE = re.compile(r"(?i)(Q/[A-Z]{2,6})(/[A-Z]{1,3})?\s*([0-9]{1,6}(?:\.[0-9]{1,3})*)")

#: Heading lines that introduce a clause, appendix, table or figure inside a
#: standard. Group 1 is the marker; group 2 is the heading text, which must be
#: separated from the marker, so a body sentence that merely starts with
#: "图1所示" is not read as a heading.
_SECTION_HEADING_RE = re.compile(
    r"^(?:#{1,6}[ \t]*)?(表\s*[0-9]+(?:\.[0-9]+)*|图\s*[0-9]+(?:\.[0-9]+)*|附录\s*[A-Za-z0-9\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341]{1,4}|第\s*[0-9\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e]{1,4}\s*(?:章|节|部分|篇|条)|[0-9]+(?:\.[0-9]+)*)(?:[ \t\u3001.\uff0e:\uff1a]+(.*))?$"
)

_NUMERIC_MARKER_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*$")

_CJK_LEAD_RE = re.compile(r"^[\u4e00-\u9fff]")


def apply_document_context(chunks: Sequence[Dict[str, Any]], doc_name: str, language: str = "English") -> int:
    """Prefix every chunk body with the document-level context.

    Args:
        chunks: chunk dictionaries as produced by a ``rag/app`` chunker; each one
            carries its indexable body in ``content_with_weight``.
        doc_name: the source document name (``task["name"]``).
        language: the document language, forwarded to the tokenizer.

    Returns:
        The number of chunks that received a prefix; 0 when the document declares
        no standard number, in which case ``chunks`` is left untouched.
    """
    if not chunks:
        return 0

    bodies = [_chunk_body(ck) for ck in chunks]
    standard_id = detect_standard_id(doc_name, bodies)
    if not standard_id:
        return 0

    # Imported lazily: rag.nlp pulls in the C++ rag_tokenizer binding, which the
    # chunker stage has already loaded — importing at module scope would make this
    # module unusable from tooling that only wants the pure helpers.
    from rag.nlp import rag_tokenizer

    title = document_title(doc_name)
    sections = document_sections(bodies)

    # The prefix is identical for every chunk, so its tokens are computed once and
    # prepended to the chunk's own tokens. The body is NOT re-tokenized: a chunker
    # that deliberately indexes less than the body (the QA chunker indexes the
    # question only) keeps that decision, and the standard number is still matched
    # by the full-text leg.
    rag_tokenizer.tokenizer.set_language(language)
    prefix_tks = rag_tokenizer.tokenize(render_document_context(standard_id, title, ""))
    prefix_sm_tks = rag_tokenizer.fine_grained_tokenize(prefix_tks)

    prefixed = 0
    for index, ck in enumerate(chunks):
        body = bodies[index]
        if not body or not body.strip():
            # Media-only chunks keep their retrievable content in the media
            # context fields, which this prefix does not cover.
            continue
        if verified_prefix_extent(ck) is not None:
            # Provenance says a prefix is already here. The TEXT cannot say it: a body
            # that happens to start with `[标准号: ` is a body, and skipping it would
            # leave the chunk without the standard number it belongs to.
            continue
        header = render_document_context(standard_id, title, sections[index])
        ck["content_with_weight"] = header + body
        ck["content_ltks"] = _prepend_tokens(prefix_tks, ck.get("content_ltks"))
        ck["content_sm_ltks"] = _prepend_tokens(prefix_sm_tks, ck.get("content_sm_ltks"))
        record_prefix(ck, header, PREFIX_KIND_LEGACY, LEGACY_PREFIX_VERSION)
        prefixed += 1
    return prefixed


def _prepend_tokens(prefix_tokens: str, body_tokens: Any) -> str:
    """Prepend the prefix's tokens to a chunk's tokenized field."""
    if not isinstance(body_tokens, str) or not body_tokens:
        return prefix_tokens
    return prefix_tokens + " " + body_tokens


def detect_standard_id(doc_name: str, texts: Iterable[str]) -> str:
    """Return the normalized standard number the document declares, or "".

    The document name is scanned first so a standard number embedded in the file
    name wins over a chance match deeper in the body, and the name is scanned in
    both spellings of its qualifier separator: "/" is illegal in a file name, so the
    corpus files 《Q/GDW 73289.2-2026》 as "Q_GDW 73289.2-2026" and a slash-only scan
    would miss the very designation the document is filed under. Both spellings
    return the same normalized value, so the metadata field and the chunk prefix
    cannot disagree.
    """
    name = " ".join((doc_name or "").split())
    parts = [name]
    slash_spelling = name.replace("_", "/")
    if slash_spelling != name:
        parts.append(slash_spelling)
    budget = SCAN_CHAR_LIMIT
    for index, text in enumerate(texts):
        if index >= SCAN_CHUNK_LIMIT or budget <= 0:
            break
        window = (text or "")[:budget]
        parts.append(window)
        budget -= len(window)
    scan = "\n".join(parts)

    found = _first_standard_id(_STANDARD_ID_RE, scan, require_year=True)
    if found:
        return found
    return _first_standard_id(_ENTERPRISE_STANDARD_ID_RE, scan, require_year=False)


def document_title(doc_name: str) -> str:
    """Reduce the document name to a readable title by dropping the extension.

    The name is NOT split on "/" or "\\": cable-standards documents carry the
    voltage rating in their name ("450/750V聚氯乙烯绝缘电缆采购标准…"), so treating
    that slash as a path separator would truncate the title to "750V…".
    """
    title = (doc_name or "").strip()
    if not title:
        return ""
    title = re.sub(r"\.[A-Za-z]{1,6}$", "", title).strip()
    return _truncate(" ".join(title.split()), TITLE_CHAR_LIMIT)


def document_sections(texts: Sequence[str]) -> List[str]:
    """Return the section in effect for each chunk, in reading order.

    A chunk that opens with a heading names its own section; the following chunks
    inherit it until the next heading appears. The walk is over chunk order rather
    than an extracted outline: it works for every chunker, and a table chunk keeps
    its own caption ("表1 技术参数特性表") as its section.
    """
    sections: List[str] = []
    current = ""
    for text in texts:
        heading = _first_heading_line(text)
        if heading:
            current = heading
        sections.append(current)
    return sections


def render_document_context(standard_id: str, title: str, section: str) -> str:
    """Build the prefix line, omitting fields that carry no value."""
    parts = ["标准号: " + standard_id]
    if title:
        parts.append("文档: " + title)
    if section:
        parts.append("章节: " + section)
    return "[" + " | ".join(parts) + "] "


def _chunk_body(chunk: Dict[str, Any]) -> str:
    body = chunk.get("content_with_weight")
    if isinstance(body, str):
        return body
    fallback = chunk.get("text")
    return fallback if isinstance(fallback, str) else ""


def _first_standard_id(pattern: re.Pattern, text: str, require_year: bool) -> str:
    for match in pattern.finditer(text):
        if not _standard_boundary_before(text, match.start()):
            continue
        prefix, qualifier, number = match.group(1), match.group(2) or "", match.group(3)
        # The year-less pattern stops after the number, so group 4 only exists on
        # the year-bearing pattern.
        year = (match.group(4) or "") if pattern.groups >= 4 else ""
        if require_year and not year:
            continue
        if not require_year and sum(character.isdigit() for character in number) < 3:
            continue
        standard_id = prefix.upper() + qualifier.upper() + " " + number
        if year:
            standard_id += "-" + year
        return standard_id
    return ""


def _standard_boundary_before(text: str, start: int) -> bool:
    """Reject a designation glued to a preceding ASCII word.

    Only ASCII word characters count as glue: "GENERAL 100-2020" must not match
    through its inner "EN", while Chinese prose does not separate words with
    spaces, so the far more common "依据GB/T 12706.1-2020的规定" must still match.
    """
    if start == 0:
        return True
    previous = text[start - 1]
    return not (previous.isascii() and (previous.isalnum() or previous == "_"))


def _first_heading_line(text: str) -> str:
    """Return the heading formed by the chunk's first non-empty line, or "".

    Only the first line is considered: a heading introduces the text that follows
    it, so a heading-shaped line further down the chunk is body content (a table
    cell, a parameter row), not the chunk's section.
    """
    for line in (text or "").split("\n"):
        line = line.strip()
        if not line:
            continue
        return _heading_of(line)
    return ""


def _heading_of(line: str) -> str:
    match = _SECTION_HEADING_RE.match(line)
    if not match:
        return ""
    marker = "".join(match.group(1).split())
    tail = " ".join((match.group(2) or "").split())

    # A numbered heading is only trusted when its heading text STARTS with Chinese:
    # that is the shape of a real clause heading ("5.1 电缆结构"), while parameter
    # rows lead with a unit ("1.5 mm2 铜芯线", "0.6/1 kV 电缆"). A missing section is
    # far better than a section that names a measurement.
    numeric = bool(_NUMERIC_MARKER_RE.match(marker))
    if numeric and not _CJK_LEAD_RE.match(tail):
        # A line that is NOTHING but a clause number is a heading too ("4.5.2" alone),
        # which the CJK rule rejected. Two dotted levels are required for that, because
        # a bare one-dot number on its own line is a table value ("1.5", "0.6") far more
        # often than it is a clause.
        if not tail and marker.count(".") >= 2:
            return _truncate(marker, SECTION_CHAR_LIMIT)
        return ""

    # A clause's FIRST sentence is not its title. Measured live: 20 of the 57 stored
    # section values ran to the 40-character cap because the line was "4.5.2 完成合同设备
    # 安装后，买方和卖方应检查和确认安装工作…" - the extractor swallowed the paragraph,
    # which then rode into every header of that document. The tail is cut at the first
    # sentence terminator and dropped entirely when what remains is longer than a
    # heading; `4.5.2` alone is the honest answer for a clause whose line is prose.
    if tail:
        tail = _HEADING_TAIL_BREAK_RE.split(tail, maxsplit=1)[0].strip(" 　、,，:：-—_")
        if len(tail) > SECTION_TAIL_CHAR_LIMIT:
            tail = ""
    return _truncate(marker + (" " + tail if tail else ""), SECTION_CHAR_LIMIT)


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit]


__all__ = [
    "CONTEXT_PREFIX_OPEN",
    "apply_document_context",
    "detect_standard_id",
    "document_sections",
    "document_title",
    "render_document_context",
]
