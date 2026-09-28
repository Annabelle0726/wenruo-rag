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
"""What a retrieved passage IS - prose, a table, an image - and where it came from.

A standards corpus puts two very different things in the same index: normative
prose (``5.3.3 绝缘标称厚度应不小于 1.2mm``) and the bidder fill-in tables of a
专用技术规范 (technique-parameter tables whose cells repeat every parameter name
and unit the question asks about). The tables win the fused score - they are
dense in exactly the query's terms - and a plain top-N then hands the answer
model a window of nothing but tables, which is how a question whose clause IS in
the corpus comes back as "只有表格，没有正文规定".

The doc store already tells the two apart: ``doc_type_kwd`` is the field the
parsers write (``rag/flow/parser/parser.py`` sets ``"table"`` for a PDF table,
``"image"`` for a figure), and ``Dealer.retrieval`` copies it onto every returned
passage. This module reads that field, plus the HTML markup of tables emitted as
text, and derives the two groupings the context cut needs: the passage TYPE and
the DOCUMENT it belongs to.

Deliberately NOT used as a table signal: ``row_id``. It is the doc store's row
identity - Infinity answers ``row_id()`` for every row of every passage - so
treating it as "this is a table row" would relabel the whole corpus.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from typing import Sequence

#: ``doc_type_kwd`` values the parsers write.
DOC_TYPE_TABLE = "table"
DOC_TYPE_IMAGE = "image"
DOC_TYPE_VIDEO = "video"
_IMAGE_TYPES = frozenset({DOC_TYPE_IMAGE, DOC_TYPE_VIDEO})

#: A table emitted as text (deepdoc renders a PDF table as HTML and some
#: pipelines keep the markup). Used only when ``doc_type_kwd`` says nothing.
_TABLE_MARKUP_RE = re.compile(r"<table[\s>]|<t[dh][\s>]|<tr[\s>]", re.IGNORECASE)


#: Share of a table's cells that may be EMPTY before the passage stops being evidence.
#:
#: Measured on 《Q/GDW 73286.2 第2部分：单芯》 (26 pages, 39 table chunks): the two
#: chunks that hold the 金属套厚度 values are 0% and 17% empty, while the fourteen
#: chunks that merely repeat the question's numbers - ``<td>800 </td><td></td>``, a
#: section label with a blank value cell - run 20% to 64% empty. Those are not answers,
#: they are the structure recogniser's unfilled grid, and a question that names 800 and
#: 1200 matches them harder than it matches the table that answers it.
HOLLOW_TABLE_EMPTY_RATIO = 0.5

_CELL_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.DOTALL)
_HTML_CAPTION_RE = re.compile(r"<caption\b[^>]*>(.*?)</caption>", re.IGNORECASE | re.DOTALL)
_HTML_ROW_RE = re.compile(r"<tr\b.*?</tr>", re.IGNORECASE | re.DOTALL)


def table_fill_ratio(chunk: dict) -> float | None:
    """Share of a table passage's cells that carry text, or ``None`` when it has none.

    Works for both shapes the parsers emit (HTML from the structure recogniser, Markdown
    from the geometry extractor). ``None`` - not 0.0 - for a passage with no cells at
    all, because "no cells" and "empty cells" are different answers.
    """
    body = _content(chunk)
    if "<t" in body:
        cells = [re.sub(r"<[^>]+>", "", cell).strip() for cell in _CELL_RE.findall(body)]
    else:
        cells = []
        for line in body.splitlines():
            if not line.lstrip().startswith("|"):
                continue
            row = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if row and all(set(cell) <= set("-: ") for cell in row):
                continue  # the Markdown separator row
            cells.extend(row)
    if not cells:
        return None
    filled = sum(1 for cell in cells if cell and cell not in {"&nbsp;", "无", "-"})
    return filled / len(cells)


def is_hollow_table(chunk: dict, threshold: float = HOLLOW_TABLE_EMPTY_RATIO) -> bool:
    """Whether a table passage is mostly unfilled cells (see the constant).

    ``threshold`` is the share of cells that may be EMPTY, so the boundary itself counts
    as hollow: a table that is half blank is not evidence either.
    """
    ratio = table_fill_ratio(chunk)
    return ratio is not None and ratio <= 1.0 - threshold


def doc_type(chunk: dict) -> str:
    return str(chunk.get("doc_type_kwd") or "").strip().lower()


def _content(chunk: dict) -> str:
    return str(chunk.get("content_with_weight") or chunk.get("content") or "")


def is_table_chunk(chunk: dict) -> bool:
    """A tabular passage: the parser's own label, or HTML table markup."""
    if doc_type(chunk) == DOC_TYPE_TABLE:
        return True
    return bool(_TABLE_MARKUP_RE.search(_content(chunk)))


def is_image_chunk(chunk: dict) -> bool:
    """A figure: labelled as one, or carrying an image with no text to read."""
    if doc_type(chunk) in _IMAGE_TYPES:
        return True
    if not _content(chunk).strip():
        return bool(chunk.get("image_id") or chunk.get("img_id") or chunk.get("image"))
    return False


def is_prose_chunk(chunk: dict) -> bool:
    """A passage a normative clause can be read out of."""
    return not is_table_chunk(chunk) and not is_image_chunk(chunk)


#: A figure as a passage writes it: ``800``, ``3.9``, ``0.95``.
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

#: A dotted figure that is a COORDINATE, not a measurement: ``Q/GDW 73286.2``,
#: ``GB/T 19666``, ``表6.2``, ``第5.3.3条``. Only the token in front of it can tell the
#: two apart - ``73286.2`` and ``3.9`` are the same shape.
_REFERENCE_NUMBER_RE = re.compile(
    r"(?:Q\s*/?\s*GDW|GB\s*/?\s*T|GB|DL\s*/?\s*T|JB\s*/?\s*T|NB\s*/?\s*T|YD\s*/?\s*T|IEC|ISO|第|表|图|附录)\s*\d+(?:[.\-/]\d+)+",
    re.IGNORECASE,
)

#: How close a result figure has to sit to a section designation to count as its VALUE.
#:
#: Measured on the Part 2 document of the 220kV report: the table that answers the
#: metal-sheath thickness question writes `3.9` five characters from `1x800mm2`,
#: while the parameter tables that merely LIST the section series put their only decimal
#: (`99.9` - the conductor's purity) more than forty characters from any of them. 20
#: keeps the pairing this corpus actually writes and rejects that coincidence.
VALUE_RESULT_WINDOW = 20


def _values_text(chunk: dict) -> str:
    """The passage's OWN evidence as flat text, for matching figures written either way.

    The ingest's identity preamble is removed first, by the boundary its own producer uses
    (:func:`_strip_ingest_preamble`). It is not evidence: it names the document, its voltage class and
    its section, and it is written by the pipeline rather than by the document. Left in place it made
    every table in a standards corpus "carry" the question's figures - the standard number is in every
    one of their headers - which turned the rule that exists to tell a table that merely LISTS the
    question's figures from one that PAIRS them into a flat penalty on the whole type.

    Only a VERIFIED preamble goes (see :func:`_strip_ingest_preamble`): the removal is evidence-checked
    against the passage's own stored document name, so a figure that also occurs in the document's body -
    the answering table beside the header, or a bracketed clause the document itself wrote - still matches.
    """
    return _plain(_strip_ingest_preamble(_content(chunk), chunk))


def number_tokens(chunk: dict) -> set[str]:
    """Every figure the passage carries, as written (``800``, ``3.9``, ``0.95``)."""
    return set(_NUMBER_RE.findall(_values_text(chunk)))


def result_figures(chunk: dict) -> set[str]:
    """The figures that read as a MEASUREMENT rather than as a coordinate.

    Only a decimal can be a measurement in a cable standard, and a decimal that is part
    of a standard designation, a table number or a clause number is a coordinate. This is
    what tells a table that PAIRS a section with a thickness from a parameter table that
    only lists the section series - the distinction the cut needs, since both carry the
    question's own numbers.
    """
    text = _values_text(chunk)
    coordinates: set[str] = set()
    for match in _REFERENCE_NUMBER_RE.finditer(text):
        coordinates.update(_NUMBER_RE.findall(match.group(0)))
    return {token for token in _NUMBER_RE.findall(text) if "." in token and token not in coordinates}


def paired_values(chunk: dict, values: Sequence[str]) -> set[str]:
    """The question's own figures this passage pairs with a RESULT beside them.

    The question names sections (``800 mm虏``, ``1200 mm虏``); the passage it needs is
    the one that puts a thickness next to each of them. A passage that merely repeats
    the numbers - a connector table listing ``400 500 630 800 1000 1200 ...`` - carries
    the question's figures and answers nothing, and the fused score cannot tell the two
    apart because the text leg rewards the repetition.
    """
    text = _values_text(chunk)
    if not text:
        return set()
    results = result_figures(chunk)
    if not results:
        return set()
    paired: set[str] = set()
    for value in values or ():
        wanted = str(value)
        if not wanted:
            continue
        for match in re.finditer(rf"(?<!\d){re.escape(wanted)}(?!\d)", text):
            window = text[max(0, match.start() - VALUE_RESULT_WINDOW) : match.end() + VALUE_RESULT_WINDOW]
            if any(token in results for token in _NUMBER_RE.findall(window)):
                paired.add(wanted)
                break
    return paired


def carries_value(chunk: dict, values: Sequence[str]) -> bool:
    """Whether the passage names any of the question's own figures at all."""
    if not values:
        return False
    text = _values_text(chunk)
    return any(re.search(rf"(?<!\d){re.escape(str(value))}(?!\d)", text) for value in values if value)


def table_family_key(chunk: dict) -> str | None:
    """Identify the TABLE a passage is a part of, or ``None`` when it is not a part.

    A long table is stored as several chunks, and every part repeats the caption and the
    header row (``table_to_markdown`` / ``split_html_table`` guarantee it), so the caption
    plus that header identifies the table across its parts. Selection uses it to keep a
    table's parts TOGETHER: the part holding ``3.8 → 1×400`` and the part holding
    ``3.9 → 1×800`` are one answer, and a window that keeps one and drops the other
    answers the question halfway - measured, on the 220kV Part 2 report, as "金属套平均
    厚度一栏只截取到了 1×400 mm² 截面这一行".
    """
    if not is_table_chunk(chunk):
        return None
    body = _content(chunk)
    if "<t" in body:
        caption = _HTML_CAPTION_RE.search(body)
        rows = _HTML_ROW_RE.findall(body)
        head = next((row for row in rows if re.search(r"<th\b", row, re.IGNORECASE)), rows[0] if rows else "")
        marker = _plain(caption.group(1) if caption else "") + "|" + _plain(head)
    else:
        lines = [line for line in body.splitlines() if line.strip()]
        caption = "" if lines and lines[0].lstrip().startswith("|") else (lines[0] if lines else "")
        header = next((line for line in lines if line.lstrip().startswith("|")), "")
        marker = _plain(caption) + "|" + _plain(header)
    if not marker.strip("|"):
        return None
    return f"{document_key(chunk)}::{hashlib.sha1(marker.encode('utf-8', 'surrogatepass')).hexdigest()[:12]}"


def _plain(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", str(text or ""))
    return re.sub(r"\s+", " ", text).strip().lower()


#: The producer's own opening marker, ``rag/nlp/doc_context.CONTEXT_PREFIX_OPEN``. Both producers of the
#: header start with it (the legacy one by construction, the Phase-A projection because a profile's first
#: identity field is 标准号), so it is the one thing a leading candidate must have before anything else is
#: considered. It is a producer constant, not a pattern this module invented.
_CONTEXT_PREFIX_OPEN = "[标准号: "

#: The header's field labels, taken from the producers' own declarations: the legacy three from
#: `doc_context.render_document_context`, the rest from `retrieval_projection.PROFILES`. Used only to
#: check that a candidate block really IS a field list; a label outside this set makes verification fail,
#: and failing verification means STRIP NOTHING.
_HEADER_FALLBACK_LABELS = frozenset({"标准号", "文档", "章节", "电压", "芯数", "线缆类别", "敷设环境", "纤芯数"})


def _header_labels() -> frozenset[str]:
    """The producers' field labels, from `retrieval_projection` when the build ships it."""
    try:
        from rag.nlp.retrieval_projection import PROFILES, SECTION_FIELD, profile_fields
    except Exception:
        return _HEADER_FALLBACK_LABELS
    labels = {field.label for profile in PROFILES.values() for field in profile_fields(profile)}
    labels.add(SECTION_FIELD.label)
    return frozenset(labels) | _HEADER_FALLBACK_LABELS


def _document_names(chunk: dict) -> set[str]:
    """The names the header's title field could legitimately carry, from the STORED document name."""
    name = document_name(chunk)
    if not name:
        return set()
    names = {name}
    try:
        from rag.nlp.doc_context import document_title
    except Exception:
        names.add(re.sub(r"\.[A-Za-z]{1,6}$", "", name).strip())
        return names
    title = document_title(name)
    if title:
        names.add(title)
    return names


def _verified_header_end(text: str, chunk: dict) -> int | None:
    """Where a VERIFIED ingest header ends, or ``None`` when it cannot be proven.

    The audit's ``METADATA_BOUNDARY_VERDICT = BLOCKING_AMBIGUITY`` was about shape: a leading bracketed
    block cannot be classified as injected or authored by looking at the bracket. This does not look at the
    bracket. It looks for the one thing that a leading field list has and an authored bracket does not - a
    ``文档``/``title`` field that EQUALS the document name the doc store returned with the passage
    (``docnm_kwd``, or that name without its extension, which is what the legacy producer writes).

    Consequences, all of them requirements of the audit's section 2:

    * every field of the candidate block must parse as ``label: value`` with a label the PRODUCERS declare,
      so an authored bracket such as ``[800 mm²：厚度3.9 mm]`` is never a candidate at all;
    * candidates are tried at EVERY closing bracket in the leading block, so a title that itself contains
      ``]`` is matched at its true end and the whole header goes - a header the producer's own regex cannot
      read back is deleted WHOLE or not at all, never partially;
    * a mismatch anywhere, or a passage with no stored document name, returns ``None`` and nothing is
      removed. Failing closed costs evidence cleanliness; failing open costs the document's own text.
    """
    if not text.startswith(_CONTEXT_PREFIX_OPEN):
        return None
    names = _document_names(chunk)
    if not names:
        return None
    labels = _header_labels()
    limit = text.find("\n")
    window = text if limit == -1 else text[:limit]
    for close in range(1, len(window)):
        if window[close] != "]":
            continue
        fields = window[1:close].split(" | ")
        parsed: list[tuple[str, str]] = []
        for field in fields:
            label, separator, value = field.partition(": ")
            if not separator or label not in labels:
                parsed = []
                break
            parsed.append((label, value.strip()))
        if not parsed:
            continue
        title = next((value for label, value in parsed if label in ("文档", "标题", "title")), "")
        if title and title in names:
            return close + 1
    return None


def _strip_ingest_preamble(text: str, chunk: dict) -> str:
    """Drop a VERIFIED ingest header from the head of a passage, and nothing else.

    The boundary is provenance-backed rather than inferred: :func:`_verified_header_end` accepts a leading
    field list only when its title field equals the stored document name. When it cannot be verified the
    text is returned untouched - the whole string is then treated as the passage's own evidence, which is
    the conservative direction the audit demanded ("无法证明来源时宁可不 strip").

    LIMITATION, reported rather than papered over: the deployed index stores NO provenance for the injected
    header - it exists only inside ``content_with_weight`` (verified by reading the live mapping: the only
    fields are ``content_with_weight``/``content_ltks``/``content_sm_ltks``/``docnm_kwd``/``title_tks``/
    ``doc_id``/``kb_id``/… and none of them records an injected extent). The stored document name is the
    one structured field a consumer can check against, and it makes the boundary verifiable for every
    header either producer writes today, but it is not a byte-level record of what was injected: a body
    that opens with a field list whose title field reproduces the document name exactly would still be
    read as metadata. The deterministic fix is a producer-side representation change (see the window
    report's METADATA_REPRESENTATION_DECISION), which this window reports as a contract boundary instead
    of guessing around it.
    """
    body = str(text or "")
    if not body.startswith(_CONTEXT_PREFIX_OPEN):
        return body
    end = _verified_header_end(body, chunk)
    if end is None:
        return body
    remainder = body[end:]
    return remainder[1:] if remainder.startswith(" ") else remainder


def document_key(chunk: dict) -> str:
    """The document a passage came from (``doc_id``, else its file name)."""
    for name in ("doc_id", "docnm_kwd", "docnm", "document_name"):
        value = chunk.get(name)
        if value:
            return str(value)
    return ""


def document_id(chunk: dict) -> str:
    """The doc-store id only - what a ``doc_ids`` scope can be built from.

    Distinct from :func:`document_key`, which falls back to the file name for
    grouping: a file name is fine for counting passages per document, but handing
    one to the doc store as a ``doc_id`` filter would match nothing.
    """
    return str(chunk.get("doc_id") or "")


def document_name(chunk: dict) -> str:
    """The document's file name/title as the transcript shows it."""
    for name in ("docnm_kwd", "docnm", "document_name"):
        value = chunk.get(name)
        if value:
            return str(value)
    return ""


#: A standard designation in a file name or a question: ``Q/GDW 73237.1-2026``,
#: ``GB/T 19666``, ``DL/T 5221``. ``_`` and spaces are interchangeable with the
#: slash, because an archived file is routinely named ``Q_GDW_73237.2-2026_…``.
_STANDARD_DESIGNATION_RE = re.compile(
    r"\b(?:Q\s*/?\s*GDW|GB\s*/?\s*T|GB|DL\s*/?\s*T|JB\s*/?\s*T|NB\s*/?\s*T|YD\s*/?\s*T|T\s*/?\s*CEC|JJG|JG)\s*\d{2,}(?:\.\d+)?",
    re.IGNORECASE,
)

#: Names that say "this file IS the standard the corpus is about", without a
#: designation of their own. Deliberately NOT a list of auxiliary names (抽检/
#: 检验/试验/方案…): a corpus is free to name a standard 《…验收规范》, and a
#: blacklist would then hide the standard itself. The rule is positive - a file
#: either carries a standard designation (or one of these tier names) or it does
#: not - so it generalises past the corpus that produced it.
CORE_DOCUMENT_NAME_CUES = ("采购标准", "通用技术规范", "专用技术规范")


def _normalized_name(text: str) -> str:
    return re.sub(r"[\s_]+", " ", str(text or "")).strip()


def standard_designations(text: str) -> set[str]:
    """Every standard designation a file name or question carries, normalized.

    Normalization drops the separators so ``Q/GDW73237.1`` in a question matches
    ``Q_GDW_73237.1-2026`` in a file name.
    """
    found = set()
    for match in _STANDARD_DESIGNATION_RE.finditer(_normalized_name(text)):
        found.add(re.sub(r"[\s/]+", "", match.group(0)).upper())
    return found


#: A document identity WITH its optional year or edition suffix (``Q/GDW 73286.2-2026``,
#: ``IEC 60502-1:2021``, ``Q_GDW_73286.2-2026``). Built from the module's own vocabularies - the two
#: patterns above are NOT edited, so `standard_designations` and document resolution see exactly what
#: they saw before - with the three gaps the audit found closed:

#: * ``_`` is accepted wherever ``/`` or a space is (``Q_GDW_73286.2-2026``), because an archived file
#:   name and a pasted reference spell a designation that way.
#: * ``:`` is accepted between a reference number and its edition (``ISO 9001:2015``), which the
#:   ``_REFERENCE_NUMBER_RE`` separator class did not include, so both figures fell through as
#:   measurements.
#: * the suffix accepts ``:`` as well as the dashes.
_DESIGNATION_SPAN_RE = re.compile(
    r"\b(?:Q[\s_]*/?[\s_]*GDW|GB[\s_]*/?[\s_]*T|GB|DL[\s_]*/?[\s_]*T|JB[\s_]*/?[\s_]*T|NB[\s_]*/?[\s_]*T"
    r"|YD[\s_]*/?[\s_]*T|T[\s_]*/?[\s_]*CEC|JJG|JG)[\s_]*\d{2,}(?:\.\d+)?",
    re.IGNORECASE,
)
_REFERENCE_SPAN_RE = re.compile(
    r"(?:Q[\s_]*/?[\s_]*GDW|GB[\s_]*/?[\s_]*T|GB|DL[\s_]*/?[\s_]*T|JB[\s_]*/?[\s_]*T|NB[\s_]*/?[\s_]*T"
    r"|YD[\s_]*/?[\s_]*T|IEC|ISO|第|表|图|附录)[\s_]*\d+(?:[.\-/:]\d+)+",
    re.IGNORECASE,
)
_IDENTITY_SPAN_RE = re.compile(
    r"(?:" + _DESIGNATION_SPAN_RE.pattern + r"|" + _REFERENCE_SPAN_RE.pattern + r")" + r"(?:[\s_]*[-–—:][\s_]*\d{4})?",
    re.IGNORECASE,
)


def identity_spans(text: str) -> list[tuple[int, int]]:
    """Where the DOCUMENT IDENTIFIERS sit in ``text``: designation plus its year/edition suffix.

    Offsets are into ``text`` exactly as given, so the caller must pass the same flattened string it
    intends to address - re-normalising here would return offsets into a copy.

    This is the boundary the value rules need and the one they lacked: ``73286.2`` and the ``2026``
    of ``Q/GDW 73286.2-2026`` are parts of the document's NAME, and no frequency test can tell them
    from a measurement, because a document identifier is rare in a corpus precisely BECAUSE it
    identifies one document.

    It is also BOUNDED: a span covers the figures that spell the document's name and no more, so the
    year of ``投产年份是否为2026年`` - a year the question asks ABOUT rather than one that names an
    edition - is not inside any span.
    """
    return [(match.start(), match.end()) for match in _IDENTITY_SPAN_RE.finditer(str(text or ""))]


# --- What a figure IS: the published classes -------------------------------------------------
#
#: The classes a numeric OCCURRENCE can fall into. Published because the extraction that projects the
#: answer-value set is one reader and a diagnosis is another, and because each class names the EVIDENCE
#: that put the occurrence in it - evidence that conflicts is reported as UNKNOWN rather than resolved by
#: a guess about the corpus.
#:
#: The identity split is the audit's section 5: an identity occurrence is a NAME while it LOCATES the
#: document and an answer-bearing value while the question asks FOR it. `2026` locates in
#: `根据 Q/GDW 73286.2-2026，导体截面是多少？` and answers in `标准发布的是2026年版还是2025年版？`, so a
#: context-free `year -> identity` rule is wrong in one of the two sentences no matter which way it is set.
NUMERIC_IDENTITY_LOCATOR = "IDENTITY_USED_TO_LOCATE_DOCUMENT"
NUMERIC_IDENTITY_ASKED = "IDENTITY_VALUE_EXPLICITLY_ASKED_BY_USER"
NUMERIC_MODEL_IDENTITY = "MODEL_IDENTITY"
NUMERIC_TECHNICAL_MEASUREMENT = "TECHNICAL_MEASUREMENT"
NUMERIC_ANSWER_VALUE = "ANSWER_REQUESTED_NUMERIC_VALUE"
NUMERIC_UNKNOWN = "UNKNOWN_NUMERIC"

#: The classes that ARE a figure the question asks about. Pure identity - the locator kind and the model
#: code - is a name; the rest are kept, UNKNOWN included, because discarding an occurrence on a
#: classification the extraction could not make would be a silent regression. `NUMERIC_IDENTITY_ASKED`
#: is value-bearing: the user asked for the identity itself (its edition, its number, its model).
NUMERIC_VALUE_CLASSES = frozenset(
    {NUMERIC_TECHNICAL_MEASUREMENT, NUMERIC_ANSWER_VALUE, NUMERIC_UNKNOWN, NUMERIC_IDENTITY_ASKED}
)

#: The attributes a question can ask FOR. These cues bind the occurrences OF THAT ATTRIBUTE, which is how
#: `GB/T 12706.2-2020的标准号是多少？` returns the designation itself: the question is about the
#: attribute, so the figures spelling that attribute are what it asks for.
_ASKED_ATTRIBUTE_CUES = {
    "edition": re.compile(r"版本是|是什么版本|哪一版|哪版|发布的是|发布日期是|实施日期是|现行版本是|现行版是"),
    "designation": re.compile(r"标准号是多少|标准号是什么|标准编号是多少|是什么标准号|哪个标准号|标准号是(?:什么|多少)"),
    "model": re.compile(r"型号是什么|是什么型号|型号是多少|哪个型号|型号是(?:什么|多少)|型号(?:是|为)"),
    "reference": re.compile(r"第\s*几\s*部分|哪一部分|表\s*几|图\s*几|哪个表|哪个图"),
}

#: Prepositions that introduce a document LOCATOR - the figures after them say WHICH document, not what its
#: content is. A cue counts only at a clause edge, so the noun `依据` inside `投产依据` is not a phrase and
#: cannot demote the year that follows it.
_LOCATOR_CUES = ("根据", "依据", "按照", "依照", "遵照", "参照", "基于", "据")
_LOCATOR_GAP_LIMIT = 10

#: Characters that end a clause or open a bracket: a locator cue may start after one of them.
_CLAUSE_EDGE_CHARS = "，。；、？！,;?!：:（）()《》【】\"' \t\n\u3000"

#: The connectives that COMPARE two figures, and the interrogatives that ask which member of a preceding
#: LIST is meant. Both are LOCAL: they bind the figures they actually sit between or follow, never every
#: occurrence of a class that happens to appear somewhere in the sentence.
_COMPARISON_CONNECTIVE_RE = re.compile(r"还是|或者")
_CHOICE_INTERROGATIVE_RE = re.compile(r"哪一?[个部分版种条章节项表图]|哪几种?")
#: What may sit between two members of a list without ending it.
_LIST_CONNECTOR_RE = re.compile(r"[\s、,，]|和|与|及|以及|或")
#: Suffixes that belong to an edition or a designation rather than ending a list (`2025年版、`).
_ATTRIBUTE_SUFFIX_CHARS = "年版本号部分"


def _occurrence_attribute(text: str, occurrence: "NumericOccurrence") -> str | None:
    """The identity attribute of an occurrence, or ``None`` when it carries no identity."""
    return _attribute_of(text, occurrence.text, occurrence.end, occurrence.designation_span, occurrence.model_span)


def _locator_bound_starts(text: str, occurrences: Sequence["NumericOccurrence"]) -> set[int]:
    """Starts of the occurrences a locator preposition introduces, plus the rest of their designation.

    `根据 Q/GDW 73286.2-2026，厚度是3.9还是4.1mm？` binds `73286.2` and `2026` - both spell the document
    the question locates - and leaves `3.9`/`4.1` untouched, which is the audit's A1.
    """
    bound: set[int] = set()
    for cue in _LOCATOR_CUES:
        position = text.find(cue)
        while position != -1:
            clause_edge = position == 0 or text[position - 1] in _CLAUSE_EDGE_CHARS
            if clause_edge:
                after = position + len(cue)
                for occurrence in occurrences:
                    if occurrence.start < after or _occurrence_attribute(text, occurrence) is None:
                        continue
                    gap = text[after : occurrence.start]
                    if len(gap) > _LOCATOR_GAP_LIMIT or any(char in _CLAUSE_EDGE_CHARS for char in gap):
                        break
                    bound.add(occurrence.start)
                    if occurrence.designation_span is not None:
                        span_start, span_end = occurrence.designation_span
                        bound.update(item.start for item in occurrences if span_start <= item.start and item.end <= span_end)
                    break
            position = text.find(cue, position + 1)
    return bound


def _compared_starts(text: str, occurrences: Sequence["NumericOccurrence"]) -> set[int]:
    """Starts of the occurrences a comparison or a list interrogative actually asks about.

    Two shapes, both local:

    * a connective compares the figure in front of it with the figure behind it
      (`厚度是3.9还是4.1mm`), so only those two are bound;
    * an interrogative asks which member of the LIST in front of it is meant
      (`2026年版、2025年版，哪一个是现行版本？`, `Q/GDW 73286.2 和 73286.3 哪一部分…`), so the walk
      backwards stops at the first character that is not a list connector, whitespace or an attribute
      suffix.
    """
    asked: set[int] = set()
    for match in _COMPARISON_CONNECTIVE_RE.finditer(text):
        before = [item for item in occurrences if item.end <= match.start() and match.start() - item.end <= 6]
        after = [item for item in occurrences if item.start >= match.end() and item.start - match.end() <= 6]
        if before and after:
            left = max(before, key=lambda item: item.end)
            right = min(after, key=lambda item: item.start)
            if not any(char in _CLAUSE_EDGE_CHARS for char in text[left.end : match.start()]):
                asked.add(left.start)
            if not any(char in _CLAUSE_EDGE_CHARS for char in text[match.end() : right.start]):
                asked.add(right.start)

    for match in _CHOICE_INTERROGATIVE_RE.finditer(text):
        cursor = match.start()
        group: list[NumericOccurrence] = []
        while True:
            before = [item for item in occurrences if item.end <= cursor]
            if not before:
                break
            previous = max(before, key=lambda item: item.end)
            gap = text[previous.end : cursor]
            if len(gap) > 4 or not all(char.isspace() or _LIST_CONNECTOR_RE.fullmatch(char) or char in _ATTRIBUTE_SUFFIX_CHARS for char in gap):
                break
            group.append(previous)
            cursor = previous.start
        if len(group) >= 2:
            asked.update(item.start for item in group)
    return asked


def _asked_starts(text: str, occurrences: Sequence["NumericOccurrence"]) -> set[int]:
    """Starts of the occurrences the question asks FOR - by attribute cue, or by a COMPARISON/LIST ITEM.

    The rejected model asked "does the sentence contain a cue" and promoted every occurrence of a class.
    This asks "is THIS occurrence the thing the cue or the comparison is about", so a sentence-level
    connective cannot change a locator's verdict (the audit's A1, A2 and D1).
    """
    asked = _compared_starts(text, occurrences)
    for attribute, cue in _ASKED_ATTRIBUTE_CUES.items():
        if cue.search(text):
            asked.update(item.start for item in occurrences if _occurrence_attribute(text, item) == attribute)
    return asked

#: A year, for the edition rule.
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")

#: The cue that makes a year an EDITION rather than the quantity a question asks about: ``2026 年版``,
#: ``2026版``. Deliberately NOT a bare 年, which also ends an ordinary year the question wants the
#: answer to - ``投产年份是否为2026年，而不是2025年？`` names two years to compare and both are values.
_EDITION_CUE_RE = re.compile(r"\s*(?:年版|版)")

#: An ASCII letter: the only thing that can make a digit run part of a NAME. A unit is letters too,
#: which is why :func:`_unit_end` is consulted before the adjacency rule in every shape where both
#: apply.
_ASCII_LETTER_RE = re.compile(r"[A-Za-z]")

#: What an alphanumeric run is made of. Whether the run is a DESIGNATION is decided by what LEADS it:
#: a letter-led run is a model code (``WDZC-YJY-0.6/1kV``, ``AB123CD``), while a figure-led run is a
#: quantity whose trailing letters are its unit (``2000mm2``, ``1x800mm2``) - the corpus writes both.
_RUN_CHAR_RE = re.compile(r"[A-Za-z0-9]")
#: Separators that keep an alphanumeric run ONE token without being run characters themselves.
_RUN_CONNECTOR_RE = re.compile(r"[-–—/.·_]")
#: A range or ratio continuation: a figure on the other side of ``800～1200mm²``, ``0.6/1kV``.
_RANGE_SEPARATOR_RE = re.compile(r"[-–—~～×*·/:：]")


def _alnum_run(text: str, start: int, end: int) -> tuple[int, int]:
    """The alphanumeric run a digit run sits in, as ``(run_start, run_end)``.

    A connector counts towards the run only when a run character sits on its far side, so the run
    neither absorbs a leading dash nor trails one: ``WDZC-YJY-0.6/1kV`` is one run, ``- 800`` is not.
    """
    run_start, run_end = start, end
    while run_start > 0:
        char = text[run_start - 1]
        if _RUN_CHAR_RE.match(char):
            run_start -= 1
        elif _RUN_CONNECTOR_RE.match(char) and run_start >= 2 and _RUN_CHAR_RE.match(text[run_start - 2]):
            run_start -= 1
        else:
            break
    while run_end < len(text):
        char = text[run_end]
        if _RUN_CHAR_RE.match(char):
            run_end += 1
        elif _RUN_CONNECTOR_RE.match(char) and run_end + 1 < len(text) and _RUN_CHAR_RE.match(text[run_end + 1]):
            run_end += 1
        else:
            break
    return run_start, run_end


def _is_model_designation(text: str, start: int, end: int) -> bool:
    """Whether a digit run spells an article's MODEL/type code rather than a quantity.

    Shape only, three conditions, no token named: the run must be LETTER-LED, carry at least two
    letters, and put a letter AFTER its last figure. The third is what separates a code from a unit -
    ``WDZC-YJY-0.6/1kV`` and ``AB123CD`` are codes, while ``2000mm2`` and ``1x800mm2`` are quantities
    whose trailing letters ARE the unit - and the first is what keeps ``1x800mm2`` out, since a
    figure-led run is how this corpus writes a section.
    """
    run_start, run_end = _alnum_run(text, start, end)
    run = text[run_start:run_end]
    if not run or not _ASCII_LETTER_RE.fullmatch(run[0]):
        return False
    if len(_ASCII_LETTER_RE.findall(run)) < 2:
        return False
    last_figure = max((index for index, char in enumerate(run) if char.isdigit()), default=-1)
    if last_figure < 0:
        return False
    return _ASCII_LETTER_RE.search(run[last_figure + 1 :]) is not None


def _unit_end(text: str, start: int, end: int) -> int | None:
    """Where the digits' unit ends, or ``None`` when they carry none."""
    matched = _match_unit(text, end)
    return None if matched is None else matched[1]


#: The producer's unit lexicon, split into one anchored pattern per alternative. Parsed ONCE from
#: `query_router._NUMERIC_UNIT_RE` rather than restated: a second word list is what the audit rejected,
#: and a per-case whitelist (`kWh`, `MPa`, `dB`) would make the tests pass without fixing the adapter.
_UNIT_PATTERNS: tuple[re.Pattern[str], ...] | None = None


def _unit_patterns() -> tuple[re.Pattern[str], ...]:
    """One anchored pattern per unit the retrieval router already knows.

    Two deliberate ADAPTER transformations, both of them fixes rather than new vocabulary:

    * the trailing ``\\b`` is dropped. Word boundaries are ASCII-based, so ``m\\b`` cannot match the
      ``m`` of ``100m时`` and the unit vanished whenever a CJK character followed it - the audit's
      section 4. The boundary is enforced by :func:`_unit_boundary_ok` instead.
    * alternatives are kept separate so the CALLER can take the longest match. Matching the lexicon's
      alternation directly returns ``kW`` for ``100kWh`` because that alternative is listed first, and
      the leftover ``h`` then makes the digits look like a code.
    """
    global _UNIT_PATTERNS
    if _UNIT_PATTERNS is None:
        from rag.retrieval.query_router import _NUMERIC_UNIT_RE

        pattern = _NUMERIC_UNIT_RE.pattern
        body = pattern[pattern.rindex("(?:") + 3 : pattern.rindex(")")]
        alternatives = [re.sub(r"\\b$", "", alternative.strip()) for alternative in body.split("|")]
        _UNIT_PATTERNS = tuple(re.compile(alternative) for alternative in alternatives if alternative)
    return _UNIT_PATTERNS


def _unit_boundary_ok(text: str, end: int) -> bool:
    """Whether a unit ending at ``end`` really ends there.

    ASCII letters and digits continue the token (``123ABC``, ``mm2``); anything else - a space, punctuation,
    a CJK character - ends it. This is the check ``\\b`` cannot perform next to CJK text.
    """
    if end >= len(text):
        return True
    char = text[end]
    return not char.isascii() or not char.isalnum()


def _match_unit(text: str, digits_end: int) -> tuple[str, int] | None:
    """The longest valid unit after the digits, across whatever WHITESPACE the writer left.

    Any whitespace counts (space, tab, newline, ideographic space): they are one separator to a reader and
    different bytes to a regex, and the audit's section C is exactly that a tab must not turn a measurement
    into a code. Longest-match is what resolves ``kWh`` against ``kW`` without naming either one.
    """
    position = digits_end
    while position < len(text) and text[position].isspace():
        position += 1
    best: tuple[str, int] | None = None
    for pattern in _unit_patterns():
        match = pattern.match(text, position)
        if match and match.end() > position and (best is None or match.end() > best[1]):
            best = (match.group(0), match.end())
    if best is None:
        return None
    return best if _unit_boundary_ok(text, best[1]) else None


#: How a figure relates to the figures beside it. Recorded per occurrence rather than inferred later,
#: because ``0.6/1 kV`` and ``800～1200mm²`` are ranges/ratios whose members carry no unit of their own.
_RANGE_MARKS = "～~-–—"
_RATIO_MARKS = "/:×*·"
_TOLERANCE_MARKS = ("±", "+/-", "+-")


def _occurrence_relation(text: str, start: int, end: int, unit: str | None) -> str:
    """``tolerance`` / ``compound`` / ``range`` / ``ratio`` / ``bare`` for one occurrence."""
    window = text[max(0, start - 3) : start]
    if any(mark in window for mark in _TOLERANCE_MARKS):
        return "tolerance"
    if unit and ("·" in unit or "/" in unit):
        return "compound"
    if start >= 2 and text[start - 1] in _RANGE_MARKS and text[start - 2].isdigit():
        return "range"
    if end + 1 < len(text) and text[end] in _RANGE_MARKS and text[end + 1].isdigit():
        return "range"
    if start >= 2 and text[start - 1] in _RATIO_MARKS and text[start - 2].isdigit():
        return "ratio"
    if end + 1 < len(text) and text[end] in _RATIO_MARKS and text[end + 1].isdigit():
        return "ratio"
    return "bare"


@dataclass(frozen=True)
class NumericOccurrence:
    """ONE numeric occurrence and the local provenance that decides what it is.

    The audit's section 3: a class keyed by the digit string cannot express that ``0.6`` in
    ``额定电压0.6/1 kV`` is a measurement while ``0.6`` in ``WDZC-YJY-0.6/1kV`` is part of a name. Every
    field here is local to the occurrence - offsets into the text, the unit span it matched, whether it
    sits inside a designation span or a letter-led model run, and how it relates to the figures beside it.
    """

    text: str
    start: int
    end: int
    kind: str
    unit: str | None = None
    unit_end: int | None = None
    relation: str = "bare"
    designation_span: tuple[int, int] | None = None
    model_span: tuple[int, int] | None = None

    @property
    def counts_as_value(self) -> bool:
        return self.kind in NUMERIC_VALUE_CLASSES


#: The token shape a candidate figure has in a question (``800``, ``3.9``, ``0.6``).
_QUESTION_DIGITS_RE = re.compile(r"\d+(?:[.．]\d+)?")


def _containing_span(start: int, end: int, spans: Sequence[tuple[int, int]]) -> tuple[int, int] | None:
    for span_start, span_end in spans:
        if span_start <= start and end <= span_end:
            return (span_start, span_end)
    return None


#: The labels that make a span a STRUCTURAL reference rather than a document designation. `_REFERENCE_SPAN_RE`
#: carries the designation prefixes too (it exists to FIND the span, not to name it), so the attribute test
#: cannot use it: a `GB/T …` span would otherwise be called a reference and its own cue would never bind it.
_REFERENCE_LABEL_RE = re.compile(r"^(?:第|表|图|附录)\s*", re.IGNORECASE)


def _attribute_of(text: str, token: str, end: int, designation_span, model_span) -> str | None:
    """Which identity attribute an occurrence belongs to, or ``None`` when it is not an identity.

    ``model`` for a letter-led code, ``edition`` for a year carrying its edition cue, ``reference`` for a
    ``表``/``图``/``第``/``附录`` number, and ``designation`` for a standard's own number.
    """
    if model_span is not None:
        return "model"
    if _YEAR_RE.fullmatch(token) and _EDITION_CUE_RE.match(text[end : end + 6]):
        return "edition"
    if designation_span is not None:
        return "reference" if _REFERENCE_LABEL_RE.match(text[designation_span[0] :]) else "designation"
    return None


def numeric_occurrences(text: str) -> list[NumericOccurrence]:
    """Every numeric occurrence in ``text``, each with its class and its local provenance.

    This is the model the audit's section 3 requires and the reason the projection is derived from
    occurrences rather than from a map keyed by the digits: two occurrences of the same string can carry
    two different classes in one sentence, and both records have to survive.

    The evidence, per occurrence: a figure inside a document identity is a NAME, unless the question asks
    for that attribute (:data:`NUMERIC_IDENTITY_ASKED`); a letter-led run is a model code; a unit makes it
    a measurement; a range/ratio/tolerance relation makes it a measurement too; evidence that conflicts is
    UNKNOWN; anything left is the bare figure the question is asking about.
    """
    body = str(text or "")
    spans = identity_spans(body)
    candidates: list[NumericOccurrence] = []
    for match in _QUESTION_DIGITS_RE.finditer(body):
        token = match.group(0).replace("．", ".")
        start, end = match.start(), match.end()
        unit = _match_unit(body, end)
        is_model = _is_model_designation(body, start, end)
        candidates.append(
            NumericOccurrence(
                text=token,
                start=start,
                end=end,
                kind=NUMERIC_UNKNOWN,
                unit=None if unit is None else unit[0],
                unit_end=None if unit is None else unit[1],
                relation=_occurrence_relation(body, start, end, None if unit is None else unit[0]),
                designation_span=_containing_span(start, end, spans),
                model_span=_alnum_run(body, start, end) if is_model else None,
            )
        )

    asked = _asked_starts(body, candidates)
    locators = _locator_bound_starts(body, candidates)
    return [
        replace(
            occurrence,
            kind=_resolve_kind(
                body,
                occurrence,
                _attribute_of(body, occurrence.text, occurrence.end, occurrence.designation_span, occurrence.model_span),
                asked,
                locators,
            ),
        )
        for occurrence in candidates
    ]


def _resolve_kind(
    text: str,
    occurrence: NumericOccurrence,
    attribute: str | None,
    asked: set[int],
    locators: set[int] = frozenset(),
) -> str:
    """The class of one occurrence, from its own evidence and the intent bound to THAT occurrence."""
    if attribute is not None:
        # A name, unless this very occurrence is what the question asks for. A locator preposition wins:
        # `根据 Q/GDW 73286.2-2026` says which document, whatever else the sentence compares.
        if occurrence.start in locators:
            return NUMERIC_IDENTITY_LOCATOR
        if occurrence.start in asked:
            return NUMERIC_IDENTITY_ASKED
        return NUMERIC_MODEL_IDENTITY if attribute == "model" else NUMERIC_IDENTITY_LOCATOR

    if occurrence.unit is not None:
        adjacent = _letter_adjacent(text, occurrence.start, occurrence.end, occurrence.unit_end)
        return NUMERIC_UNKNOWN if adjacent else NUMERIC_TECHNICAL_MEASUREMENT
    if occurrence.relation in ("range", "ratio", "tolerance"):
        return NUMERIC_TECHNICAL_MEASUREMENT
    if _letter_adjacent(text, occurrence.start, occurrence.end):
        return NUMERIC_MODEL_IDENTITY
    return NUMERIC_ANSWER_VALUE


def classify_numeric_token(text: str, start: int, end: int, spans: Sequence[tuple[int, int]] = ()) -> str:
    """The class of the occurrence at ``text[start:end]`` - a thin reader of :func:`numeric_occurrences`.

    Kept because a caller may already hold offsets; it re-derives the occurrence list from ``text`` and
    returns the record covering those offsets. ``spans`` is accepted for the previous signature and is
    IGNORED: the occurrence list derives identity from the text itself, so a stale span list passed in
    could only disagree with it.
    """
    del spans
    for occurrence in numeric_occurrences(text):
        if occurrence.start == start and occurrence.end == end:
            return occurrence.kind
    return NUMERIC_UNKNOWN


def _is_multiplication_sign(text: str, index: int) -> bool:
    """Whether the character at ``index`` is a multiplication sign rather than a name letter.

    ``query_router._DIMENSION_PAIR_RE`` already reads ``3x25``/``3×25``/``4*16`` as a count times a
    section, so a letter ``x`` sitting directly after a figure is an OPERATOR: ``1x800mm2`` is how this
    corpus writes a section with no space, and treating its ``x`` as a name letter made the figure look
    like a code. The test needs the figure on the far side, so ``x800`` keeps reading as a prefix.
    """
    return text[index] in ("x", "X") and index > 0 and text[index - 1].isdigit()


def _letter_adjacent(text: str, start: int, end: int, unit_end: int | None = None) -> bool:
    """Whether a letter run touches the figure, with a connector allowed in between.

    ``AB123CD`` (letters on both sides), ``WDZC-YJY-0.6`` (letters behind one dash) and ``123ABC``
    are all instances; the letters a unit already claimed are excluded, and so is a multiplication sign.
    """
    if start > 0 and _ASCII_LETTER_RE.match(text[start - 1]) and not _is_multiplication_sign(text, start - 1):
        return True
    if (
        start >= 2
        and _RUN_CONNECTOR_RE.match(text[start - 1])
        and _ASCII_LETTER_RE.match(text[start - 2])
        and not _is_multiplication_sign(text, start - 2)
    ):
        return True
    after = end if unit_end is None else unit_end
    if after < len(text) and _ASCII_LETTER_RE.match(text[after]) and not _is_multiplication_sign(text, after):
        return True
    return (
        after + 1 < len(text)
        and bool(_RUN_CONNECTOR_RE.match(text[after]))
        and bool(_ASCII_LETTER_RE.match(text[after + 1]))
        and not _is_multiplication_sign(text, after + 1)
    )


def _is_range_continuation(text: str, start: int, end: int) -> bool:
    """Whether a figure continues into another figure across a range or ratio separator.

    Kept as a predicate over offsets for callers that hold them; :func:`_occurrence_relation` records the
    same relation on the occurrence itself.
    """
    if start >= 2 and _RANGE_SEPARATOR_RE.match(text[start - 1]) and text[start - 2].isdigit():
        return True
    return end + 1 < len(text) and bool(_RANGE_SEPARATOR_RE.match(text[end])) and text[end + 1].isdigit()


def designation_spans(text: str) -> list[str]:
    """The designations a question NAMES, as literal text, in the order it names them.

    :func:`standard_designations` answers "which standard is this about" and normalizes the
    answer hard (``Q/GDW73286.2``, uppercase, no slash, no spacing), which is what a
    comparison against a file name needs. A retrieval ROUTE needs the other thing: the words
    to actually search for, spelled the way the question and the corpus spell them
    (``Q/GDW 73286.2``). Same pattern, same matches, no second vocabulary - only the match
    text is kept instead of the normalized key.
    """
    spans: list[str] = []
    for match in _STANDARD_DESIGNATION_RE.finditer(_normalized_name(text)):
        span = " ".join(match.group(0).split())
        if span and span not in spans:
            spans.append(span)
    return spans


#: The context prefix the ingest writes into every chunk it can identify
#: (``[标准号: Q/GDW 73286.1-2026 | 文档: … | 章节: …]``). It is the only place a
#: multi-part standard's PART designation reaches the text - the file name carries
#: the tier ("第1部分：通用技术规范") but often no number at all - so the pipeline
#: reads it back out of the passage when it has to name the sibling part.
_CONTEXT_DESIGNATION_RE = re.compile(r"标准号:\s*([^|\]]+)", re.UNICODE)

#: The part a multi-part designation names: ``Q/GDW 73286.2-2026`` -> 2. A designation
#: without one is a single document, and has no sibling to fall back to.
_DESIGNATION_PART_RE = re.compile(r"^(?P<prefix>[A-Z]+)\s*(?P<base>\d+(?:\.\d+)*?)(?:\.(?P<part>\d+))?(?:-(?P<year>\d{4}))?$")


def designation_parts(designation: str) -> tuple[str, int | None, str] | None:
    """``(family, part, year)`` for a normalized designation, or ``None``.

    ``Q/GDW73286.2-2026`` -> ``("Q/GDW73286", 2, "2026")``. The family is what two
    parts of one standard share, so it is the key that lets a passage from Part 2
    point at Part 1.
    """
    text = re.sub(r"\s+", "", str(designation or "")).upper()
    match = _DESIGNATION_PART_RE.match(text)
    if not match:
        return None
    prefix = match.group("prefix")
    base = match.group("base")
    part = int(match.group("part")) if match.group("part") else None
    year = match.group("year") or ""
    # A qualifier slash is dropped by the normalizer, so "Q/GDW" arrives as "QGDW":
    # the family keeps that spelling, because matching is done against the same
    # normalized form on both sides.
    return prefix + base, part, year


def generic_sibling_designation(designation: str) -> str | None:
    """The GENERIC part of the same standard: ``Q/GDW73286.2-2026`` -> ``Q/GDW73286.1-2026``.

    A multi-part standard is split so that one part states the rules and the others
    state what a project must respond with: 《第1部分：通用技术规范》 carries the
    mandatory baseline (``内衬层厚度 ≥1.5mm``, ``出厂交流耐压 2.5U0/30min``) while
    《第2部分：专用技术规范》 is a bidder fill-in template whose table cells are
    empty. A question about a requirement therefore has to be able to reach Part 1
    from a pool that only found Part 2, and the designation is what names it.
    """
    parsed = designation_parts(designation)
    if not parsed:
        return None
    family, part, year = parsed
    if part is None or part < 2:
        return None
    return f"{family}.1-{year}" if year else f"{family}.1"


def context_designation(chunk: dict) -> str:
    """The ``[标准号: …]`` the ingest wrote into this passage, normalized, or "".

    The prefix carries the year and the part (``Q/GDW 73286.1-2026``) while
    :func:`standard_designations` deliberately matches the year-less form, so the raw
    value is normalized here instead - the part is what this reader is after, and the
    year is worth keeping for the sibling it derives.
    """
    match = _CONTEXT_DESIGNATION_RE.search(_content(chunk))
    if not match:
        return ""
    text = re.sub(r"[\s/]+", "", match.group(1)).upper()
    return text if designation_parts(text) else ""


def document_designations(chunk: dict) -> set[str]:
    """Every designation that identifies this passage's DOCUMENT.

    Two sources, both of them the document speaking about itself: its file name and
    the context prefix inside its text. They disagree for real documents - the Part 3
    file of the 220kV standard carries the tier in its name and no number, and nine of
    the live corpus's seventeen documents carry no prefix at all - which is why both
    are read rather than one.
    """
    found = set(standard_designations(document_name(chunk)))
    context = context_designation(chunk)
    if context:
        found.add(context)
    return found


#: The part marker a multi-part file name carries: 《…采购标准+第2部分：…》. What comes
#: BEFORE it is the family - the text every part of that standard shares - which is the
#: only thing that groups the parts of a standard whose file names carry no designation
#: at all (measured on the live corpus: the 220kV 第3部分 document has no standard
#: number in its name and NO ``[标准号: …]`` prefix on any of its 51 chunks).
_PART_MARKER_RE = re.compile(r"第\s*([0-9一二三四五六七八九十]{1,3})\s*部分")


def name_family(name: str) -> str:
    """The text a multi-part standard's parts share, or "" for a single-part name.

    ``220kV海底电力电缆系统采购标准+第2部分：220kV单芯…`` -> ``220kV海底电力电缆系统采购标准``.
    """
    text = _normalized_name(name)
    match = _PART_MARKER_RE.search(text)
    if not match:
        return ""
    family = text[: match.start()].strip(" +-_+＋、,，：:")
    return family if len(family) >= 4 else ""


def document_family(chunk: dict) -> str:
    """The family key of a passage's document: its designation's, else its name's.

    A designation is the precise answer (``QGDW73286`` groups ``.1``/``.2``/``.3``), and
    the name is the fallback that still groups a standard whose parts were archived
    without numbers.
    """
    for designation in sorted(document_designations(chunk)):
        parsed = designation_parts(designation)
        if parsed:
            return parsed[0]
    return name_family(document_name(chunk))


def generic_part_documents(chunks: Sequence[dict]) -> dict[str, tuple[str, str]]:
    """``family -> (document key, name)`` for the GENERIC part of each standard in the pool.

    A document counts as the generic part when its name says 通用技术规范, or when its
    designation is a ``.1`` of a multi-part standard. This is the lookup the cross-part
    fallback needs in order to scope a pass to Part 1 when Part 1 is already in the pool.
    """
    found: dict[str, tuple[str, str]] = {}
    for chunk in chunks or []:
        name = _normalized_name(document_name(chunk))
        key = document_key(chunk)
        if not key:
            continue
        families = set()
        for designation in document_designations(chunk):
            parsed = designation_parts(designation)
            if parsed and parsed[1] == 1:
                families.add(parsed[0])
        if "通用技术规范" in name:
            for designation in document_designations(chunk):
                parsed = designation_parts(designation)
                if parsed:
                    families.add(parsed[0])
            # A generic part whose parts were archived without any designation is
            # grouped by the name it shares with its siblings.
            named = name_family(name)
            if named:
                families.add(named)
        for family in families:
            found.setdefault(family, (key, document_name(chunk)))
    return found


def core_document_score(chunk_or_name) -> int:
    """How strongly a document presents itself as the corpus's standard.

    2 = carries a standard designation, 1 = carries a tier name (采购标准 /
    通用技术规范 / 专用技术规范), 0 = neither.
    """
    name = chunk_or_name if isinstance(chunk_or_name, str) else document_name(chunk_or_name)
    if not name:
        return 0
    score = 0
    if standard_designations(name):
        score += 2
    normalized = _normalized_name(name)
    if any(cue in normalized for cue in CORE_DOCUMENT_NAME_CUES):
        score += 1
    return score


#: Cues that a question wants TWO sources read together rather than one answer.
#: "分别" is here because "…分别是多少？单芯与三芯是否一致" asks for both documents even
#: when the comparison verb itself is implied.
COMPARISON_CUES = (
    "对比",
    "对照",
    "比较",
    "区别",
    "差异",
    "异同",
    "是否一致",
    "一致吗",
    "分别",
    "各自",
    "compare",
    "comparison",
    "versus",
    " vs ",
    "difference",
)

#: The sides a comparison names: a part number ("第2部分", "Part 3") or a core count
#: ("单芯", "三芯", "3芯"). A corpus splits a standard by part and by construction, so
#: these two families are what a comparative cable question actually points at.
_COMPARISON_SIDE_PATTERNS = (
    re.compile(r"第\s*[0-9一二三四五六七八九十]{1,3}\s*部分"),
    re.compile(r"part\s*[0-9]{1,2}", re.IGNORECASE),
    re.compile(r"[单双两三四五六七八九十0-9]{1,2}\s*芯"),
)


def comparison_sides(question: str) -> list[str]:
    """The sources a comparative question names, in the order they appear.

    ``"单芯与三芯要求是否一致"`` -> ``["单芯", "三芯"]``; ``"第2部分和第3部分的差异"`` ->
    ``["第2部分", "第3部分"]``; ``"Part 2 vs Part 3"`` -> ``["Part 2", "Part 3"]``.
    """
    text = _normalized_name(question)
    sides: list[str] = []
    for pattern in _COMPARISON_SIDE_PATTERNS:
        for match in pattern.finditer(text):
            side = " ".join(match.group(0).split())
            if side and side not in sides:
                sides.append(side)
    return sides


def is_comparative_question(question: str) -> bool:
    """Whether the question asks for more than one source to answer it.

    A cue word, or two named sides by themselves: "单芯与三芯要求是否一致" carries both,
    while a single-subject question ("400mm² 导体最大直流电阻是多少") carries neither and
    keeps a plain top-N.
    """
    text = _normalized_name(question)
    if any(cue in text for cue in COMPARISON_CUES):
        return True
    return len(comparison_sides(question)) >= 2


def resolve_compared_documents(chunks: Sequence[dict], question: str) -> set[str]:
    """The documents the question's own sides point at.

    A side is matched against a document NAME, which is where a corpus that splits a
    standard by part says so: 《…Q/GDW 73286.2-2026 第2部分：单芯…》 carries "单芯". A
    document that advertises a designation without naming a side is deliberately NOT
    guessed at - the side routes are what make such a document findable, and this
    function only guarantees that a document the question explicitly named is
    represented in the window.
    """
    sides = comparison_sides(question)
    if len(sides) < 2:
        return set()

    names: dict[str, str] = {}
    for chunk in chunks or []:
        key = document_key(chunk)
        if key and key not in names:
            names[key] = _normalized_name(document_name(chunk))
    hit: set[str] = set()
    for side in sides:
        wanted = _normalized_name(side)
        if not wanted:
            continue
        for key, name in names.items():
            if wanted in name:
                hit.add(key)
    return hit


def resolve_core_documents(chunks: Sequence[dict], question: str = "") -> set[str]:
    """The documents that ARE the standard this question is about, if any.

    1. the question names a designation (``Q/GDW 73237.1``) - the documents whose
       file name or whose own passage text carries it are the core;
    2. otherwise every document whose name carries a designation or a tier name.

    An empty result means the corpus does not advertise a standard at all (a
    folder of supplier datasheets, product manuals, test reports). Callers must
    then leave document-level policy alone rather than guess which file is
    "main" - guessing is how an auxiliary working document gets promoted or a
    legitimate single-document answer gets truncated.
    """
    by_document: dict[str, list[dict]] = {}
    for chunk in chunks or []:
        key = document_key(chunk)
        if key:
            by_document.setdefault(key, []).append(chunk)
    if not by_document:
        return set()

    named = standard_designations(question)
    if named:
        hit = {key for key, group in by_document.items() if standard_designations(document_name(group[0])) & named or any(named & standard_designations(_content(chunk)) for chunk in group)}
        if hit:
            return hit

    return {key for key, group in by_document.items() if core_document_score(group[0]) > 0}


def summarize(chunks: Sequence[dict]) -> str:
    """One line describing a passage pool or a context: types and provenance."""
    chunks = list(chunks or [])
    tables = sum(1 for chunk in chunks if is_table_chunk(chunk))
    images = sum(1 for chunk in chunks if is_image_chunk(chunk))
    prose = sum(1 for chunk in chunks if is_prose_chunk(chunk))
    documents = {document_key(chunk) for chunk in chunks if document_key(chunk)}
    return f"{len(chunks)} passage(s): {prose} prose / {tables} table / {images} image from {len(documents)} document(s)"


def document_breakdown(chunks: Sequence[dict], limit: int = 3) -> str:
    """``Q/GDW 73237.1…pdf x5, 抽检工作规范.pdf x4`` - who filled the context.

    The measurement that started this: nine recalled passages, seven of them from
    one auxiliary working document (22,684 characters) and two from the standard
    the question was about (1,130 characters). A count per document makes that
    visible in one line of the transcript.
    """
    counts: dict[str, int] = {}
    for chunk in chunks or []:
        key = document_name(chunk) or document_key(chunk) or "?"
        counts[key] = counts.get(key, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    shown = [f"{name} x{count}" for name, count in ordered[:limit]]
    if len(ordered) > limit:
        shown.append(f"+{len(ordered) - limit} more")
    return ", ".join(shown)
