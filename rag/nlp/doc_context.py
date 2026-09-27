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

Injection is conditional by design: a document that declares no standard number
keeps byte-identical chunks, so ordinary documents are untouched.

The Go ingestion backend implements the same policy in
``internal/ingestion/component/chunker/doccontext.go``; the two must stay aligned.
"""

import re
from typing import Any, Dict, Iterable, List, Sequence

#: Starts every injected prefix and doubles as the idempotency marker — a re-run
#: must not stack a second prefix on a chunk that already carries one.
CONTEXT_PREFIX_OPEN = "[标准号: "

#: Scan bounds. A standard number identifying the document is declared on the
#: cover page (and often repeated in the running header), so the leading chunks
#: are enough; the character cap keeps the scan cheap for pathological chunks.
SCAN_CHUNK_LIMIT = 8
SCAN_CHAR_LIMIT = 4000

#: Display fields inside a retrieval chunk; capped so a pathological file name
#: cannot dominate the chunk's token budget.
TITLE_CHAR_LIMIT = 60
SECTION_CHAR_LIMIT = 40

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
        if body.lstrip().startswith(CONTEXT_PREFIX_OPEN):
            continue
        ck["content_with_weight"] = render_document_context(standard_id, title, sections[index]) + body
        ck["content_ltks"] = _prepend_tokens(prefix_tks, ck.get("content_ltks"))
        ck["content_sm_ltks"] = _prepend_tokens(prefix_sm_tks, ck.get("content_sm_ltks"))
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
    if _NUMERIC_MARKER_RE.match(marker) and not _CJK_LEAD_RE.match(tail):
        return ""
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
