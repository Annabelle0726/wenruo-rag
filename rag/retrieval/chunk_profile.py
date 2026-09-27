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
