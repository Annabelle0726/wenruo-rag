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
"""Rule-based table extraction for cable datasheets and standards.

Cable documents are table-dense, and their tables are exactly the ones a
model-based structure recogniser struggles with:

* **Large parameter tables** (Q/GDW 73286.3 表1 and friends) - dozens of rows,
  merged header cells, and a ruling grid that is only partly drawn. The model
  reads them as a handful of text lines, so the answer row arrives as
  ``3x630mm² 26.0mm`` with no column to belong to.
* **Borderless tables** - the vertical rules are simply not printed, only
  whitespace separates the columns. A lines-based table finder returns NOTHING
  for them, which is the "表1 漏解析" report: the table content stays in the page
  text, loses its grid, and the chunk that carries it reads as garbled prose.

This module is the deterministic counterpart to the model path: it uses
pdfplumber's geometry-driven table finder, with an explicit strategy per kind of
table (ruled vs borderless), merges a table that continues on the next page into
ONE logical table with a single header, renders Markdown, and splits a table that
is too long for one chunk while REPEATING the caption and header row in every
part - so a data row never travels without the columns it belongs to.

Everything here is a pure function over extracted rows, apart from
:func:`extract_tables_from_pdf`, which opens and closes its own handle.
"""

from __future__ import annotations

import logging
import re
import sys
import threading
from dataclasses import dataclass, field
from typing import Any, Sequence

import pdfplumber

_LOG = logging.getLogger(__name__)

#: The lock every pdfplumber use in this repository takes (``deepdoc/parser``
#: and ``deepdoc/vision`` share it through ``sys.modules``).
LOCK_KEY_pdfplumber = "global_shared_lock_pdfplumber"
if LOCK_KEY_pdfplumber not in sys.modules:
    sys.modules[LOCK_KEY_pdfplumber] = threading.Lock()

#: A ruled table: the grid is drawn, so both strategies follow the rules. The
#: tolerances are pdfplumber's own defaults, written out because they are the
#: settings this module is about - a rule broken by a scanned page or a table
#: whose lines stop short is joined within ``join_tolerance`` points.
RULED_VERTICAL_STRATEGY = "lines"
RULED_HORIZONTAL_STRATEGY = "lines"
DEFAULT_SNAP_TOLERANCE = 3.0
DEFAULT_JOIN_TOLERANCE = 3.0
DEFAULT_INTERSECTION_TOLERANCE = 3.0
DEFAULT_EDGE_MIN_LENGTH = 3.0

#: A borderless table: there are no rules to follow, so the columns are inferred
#: from where the words line up. ``min_words_vertical`` is 2 rather than
#: pdfplumber's default 3 on purpose - a cable table has short columns (单位, 序号)
#: whose words are sparse, and one of them missing shifts every column after it.
BORDERLESS_VERTICAL_STRATEGY = "text"
BORDERLESS_HORIZONTAL_STRATEGY = "text"
BORDERLESS_MIN_WORDS_VERTICAL = 2
BORDERLESS_MIN_WORDS_HORIZONTAL = 1

#: A table with fewer rows/columns than this is a stray ruling, not a table.
MIN_TABLE_ROWS = 2
MIN_TABLE_COLUMNS = 2

#: A table whose cells are mostly empty carries no structure worth keeping; the
#: ratio is measured over the body rows only (a header may legitimately be sparse).
MAX_EMPTY_CELL_RATIO = 0.6

#: A caption is the line just above the table. Cable documents title a table with
#: ``表1 架空绝缘导线抽检项目``; the prefix requirement keeps the finder from
#: adopting an ordinary paragraph that happens to sit above the grid.
CAPTION_RE = re.compile(r"^\s*(?:附?表\s*[A-Za-z]?\s*\d*|Table\s*\d+)\b", re.IGNORECASE)
#: How close above the table a caption may sit, in points.
CAPTION_MAX_GAP = 40.0

#: Continuation detection: a table that starts this close to the top of its page
#: is the continuation of the previous page's table rather than a new one.
CONTINUATION_TOP_BAND = 90.0

#: A cell holding only a number (or a number with a unit) is DATA; a row of such
#: cells is not a header. Used to tell "table continues without a header" from
#: "a different table with its own header starts here".
_NUMERIC_CELL_RE = re.compile(r"^[<>≤≥约±]?\s*\d+(?:[.,]\d+)?\s*[A-Za-z%°℃²³/·×*.-]*$")
#: A placeholder is data too: cable tables write an unused cell as a dash, and a
#: continuation row of dashes must not read as a header row.
_PLACEHOLDER_CELL_RE = re.compile(r"^(?:[-—–~～/\\]+|n/?a|无|不适用)$", re.IGNORECASE)

_TABLE_CAPTION_LINE_LIMIT = 160

#: Character budget for ONE table chunk. A Markdown table longer than this is
#: split into row-batches, each carrying the caption and header (see
#: :func:`split_markdown_table`): 表1 of a cable standard runs to dozens of rows,
#: and the row a question asks about (``3x630`` / ``60.0``) is meaningless in a
#: chunk that lost the columns it belongs to. ~1200 characters is roughly 600
#: tokens, which keeps a table chunk comparable to a text chunk instead of
#: dominating the context window.
DEFAULT_TABLE_CHUNK_CHARS = 1200


@dataclass(frozen=True)
class TableStrategy:
    """The pdfplumber ``TableSettings`` this module asks for, by table kind."""

    name: str
    vertical_strategy: str
    horizontal_strategy: str
    snap_tolerance: float = DEFAULT_SNAP_TOLERANCE
    join_tolerance: float = DEFAULT_JOIN_TOLERANCE
    intersection_tolerance: float = DEFAULT_INTERSECTION_TOLERANCE
    edge_min_length: float = DEFAULT_EDGE_MIN_LENGTH
    min_words_vertical: int = 3
    min_words_horizontal: int = 1

    def as_table_settings(self) -> dict[str, Any]:
        """pdfplumber keyword arguments for ``Page.find_tables``."""
        return {
            "vertical_strategy": self.vertical_strategy,
            "horizontal_strategy": self.horizontal_strategy,
            "snap_tolerance": self.snap_tolerance,
            "join_tolerance": self.join_tolerance,
            "intersection_tolerance": self.intersection_tolerance,
            "edge_min_length": self.edge_min_length,
            "min_words_vertical": self.min_words_vertical,
            "min_words_horizontal": self.min_words_horizontal,
        }


#: A fully ruled table.
RULED = TableStrategy("ruled", RULED_VERTICAL_STRATEGY, RULED_HORIZONTAL_STRATEGY)
#: A table whose rules are missing or invisible.
BORDERLESS = TableStrategy(
    "borderless",
    BORDERLESS_VERTICAL_STRATEGY,
    BORDERLESS_HORIZONTAL_STRATEGY,
    min_words_vertical=BORDERLESS_MIN_WORDS_VERTICAL,
    min_words_horizontal=BORDERLESS_MIN_WORDS_HORIZONTAL,
)


@dataclass
class ExtractedTable:
    """One logical table: its rows, where it came from, and how it was found."""

    rows: list[list[str]]
    page_index: int = 0
    bbox: tuple[float, float, float, float] | None = None
    caption: str = ""
    strategy: str = ""
    merged_pages: list[int] = field(default_factory=list)

    @property
    def header(self) -> list[str]:
        return self.rows[0] if self.rows else []

    @property
    def body(self) -> list[list[str]]:
        return self.rows[1:] if self.rows else []

    @property
    def column_count(self) -> int:
        return len(self.header)


def normalize_cell(value: Any) -> str:
    """A cell as one line of plain text.

    pdfplumber returns ``None`` for an empty cell and may return a value with
    embedded newlines (a wrapped label); a Markdown cell cannot carry a newline,
    and a row that does is what makes a table read as garbled text downstream.
    """
    if value is None:
        return ""
    text = str(value).replace("\u00a0", " ")
    text = re.sub(r"\s*[\r\n]+\s*", " ", text)
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text


def normalize_rows(rows: Sequence[Sequence[Any]] | None) -> list[list[str]]:
    """Normalize a raw extraction, dropping rows and columns that are entirely empty."""
    if not rows:
        return []
    grid = [[normalize_cell(cell) for cell in row] for row in rows]
    grid = [row for row in grid if any(cell for cell in row)]
    if not grid:
        return []
    width = max(len(row) for row in grid)
    grid = [row + [""] * (width - len(row)) for row in grid]
    keep = [index for index in range(width) if any(row[index] for row in grid)]
    if not keep:
        return []
    return [[row[index] for index in keep] for row in grid]


def is_well_formed_table(rows: Sequence[Sequence[Any]] | None, *, min_rows: int = MIN_TABLE_ROWS, min_columns: int = MIN_TABLE_COLUMNS) -> bool:
    """Whether an extraction is a table worth keeping.

    The empty-cell ratio is what separates a real table from the stray rectangle a
    lines-based finder returns around a figure or a page footer: those come back
    as a grid of blank cells.
    """
    grid = normalize_rows(rows)
    if len(grid) < min_rows:
        return False
    if max(len(row) for row in grid) < min_columns:
        return False
    body = grid[1:] or grid
    cells = [cell for row in body for cell in row]
    if not cells:
        return False
    empty = sum(1 for cell in cells if not cell)
    return empty / len(cells) <= MAX_EMPTY_CELL_RATIO


def _row_is_value_like(row: Sequence[str]) -> bool:
    """Whether every non-empty cell of ``row`` is a value rather than a label."""
    filled = [cell for cell in row if cell]
    if not filled:
        return False
    return all(_NUMERIC_CELL_RE.match(cell) or _PLACEHOLDER_CELL_RE.match(cell) for cell in filled)


def looks_like_header(row: Sequence[str], other_columns: Sequence[str] = ()) -> bool:
    """Whether ``row`` reads as a header rather than as a first data row.

    A header cell is a label: every cell is filled in, and no cell is a bare
    number or a placeholder dash. A data row normally carries numbers under some of
    its columns, which is what this uses - the alternative (comparing against the
    previous table's header) cannot see a table that simply has no header at all.
    """
    cells = [normalize_cell(cell) for cell in row]
    filled = [cell for cell in cells if cell]
    if len(filled) < 2:
        return False
    if _row_is_value_like(cells):
        return False
    numeric_cells = sum(1 for cell in filled if _NUMERIC_CELL_RE.match(cell) or _PLACEHOLDER_CELL_RE.match(cell))
    if numeric_cells and len(filled) > 2:
        return False
    if other_columns and len(cells) == len(other_columns):
        # A repeated header is a header even when every cell of it is short.
        return True
    return all(len(cell) <= 24 for cell in filled)


def _same_header(left: Sequence[str], right: Sequence[str]) -> bool:
    if len(left) != len(right):
        return False
    return all(normalize_cell(a).lower() == normalize_cell(b).lower() for a, b in zip(left, right))


def merge_over_page_tables(tables: Sequence[ExtractedTable], *, continuation_top_band: float = CONTINUATION_TOP_BAND) -> list[ExtractedTable]:
    """Join a table that continues on the next page into ONE logical table.

    A table split by a page break comes back as two extractions, and the second
    one either repeats the header row (a well-typeset standards document does) or
    starts straight into data. Both are merged here, and the repeated header is
    dropped so the merged table has exactly one.

    The merge is deliberately narrow, because joining two DIFFERENT tables is
    worse than leaving a split one alone:

    * the continuation must be on the very next page;
    * it must start at the TOP of that page (:data:`CONTINUATION_TOP_BAND`), which
      is where a page break leaves a table and where a new table does not
      normally begin;
    * it must have the same number of columns;
    * and its first row must be either the previous table's header (repeated) or
      not a header at all. A different header means a different table.
    """
    merged: list[ExtractedTable] = []
    for table in tables:
        previous = merged[-1] if merged else None
        if previous is None or not _continues(previous, table, continuation_top_band):
            merged.append(table)
            continue

        repeated_header = _same_header(table.rows[0], previous.header)
        rows = table.rows[1:] if repeated_header else table.rows
        previous.rows.extend(rows)
        previous.merged_pages.append(table.page_index)
        _LOG.info(
            "[Table] merged the continuation on page %d into the table from page %d (%s header, %d row(s) added)",
            table.page_index + 1,
            previous.page_index + 1,
            "repeated" if repeated_header else "no",
            len(rows),
        )
    return merged


def _continues(previous: ExtractedTable, table: ExtractedTable, top_band: float) -> bool:
    if table.page_index != previous.page_index + 1:
        return False
    if table.column_count != previous.column_count or not table.rows:
        return False
    bbox = table.bbox
    if bbox is None:
        return False
    if float(bbox[1]) > top_band:
        return False
    if _same_header(table.rows[0], previous.header):
        return True
    return not looks_like_header(table.rows[0], previous.header)


def table_to_markdown(rows: Sequence[Sequence[Any]] | None, caption: str = "") -> str:
    """Render a table as Markdown, with its caption on the line above.

    Markdown is what the answer model reads best and what a chunk can be split
    while staying readable: ``| 列1 | 列2 |`` plus the separator row is the small
    amount of state that makes a row of numbers mean something.
    """
    grid = normalize_rows(rows)
    if not grid:
        return ""
    width = max(len(row) for row in grid)
    header = grid[0] + [""] * (width - len(grid[0]))

    def _line(cells: Sequence[str]) -> str:
        padded = list(cells) + [""] * (width - len(cells))
        return "| " + " | ".join(cell.replace("|", "\\|") for cell in padded) + " |"

    lines = []
    title = normalize_cell(caption)[:_TABLE_CAPTION_LINE_LIMIT]
    if title:
        lines.append(title)
    lines.append(_line(header))
    lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
    lines.extend(_line(row) for row in grid[1:])
    return "\n".join(lines)


def parse_markdown_table(markdown: str) -> tuple[str, list[str], list[str]]:
    """Split a Markdown table into ``(caption, header, body_lines)``.

    Used by the chunker, which receives an already-rendered table and has to
    repeat its first two lines in every part.
    """
    lines = [line.rstrip() for line in str(markdown or "").splitlines() if line.strip()]
    if not lines:
        return "", [], []
    caption = ""
    if not lines[0].lstrip().startswith("|"):
        caption = lines.pop(0)
    if len(lines) < 2 or not lines[1].lstrip().startswith("|"):
        return caption, [], lines
    return caption, [lines[0], lines[1]], lines[2:]


def split_markdown_table(markdown: str, max_chars: int) -> list[str]:
    """Split a Markdown table into parts that each carry the caption and header.

    This is the "header injection" the long cable tables need: 表1 runs to dozens
    of rows, and a chunk holding rows 40-52 without the header is a set of numbers
    (``3x630mm² 26.0mm``) that means nothing to the model - it cannot tell which
    column is the 截面 and which is the 外径.

    A table that already fits is returned whole, unchanged.
    """
    text = str(markdown or "").rstrip()
    if not text:
        return []
    limit = int(max_chars or 0)
    if limit <= 0 or len(text) <= limit:
        return [text]

    caption, head, body = parse_markdown_table(text)
    if not head:
        return _split_by_lines(text, limit)

    prefix = "\n".join([part for part in (caption, *head) if part])
    parts: list[str] = []
    current = [prefix]
    current_len = len(prefix)
    for line in body:
        if current_len + len(line) + 1 > limit and len(current) > 1:
            parts.append("\n".join(current))
            current = [prefix]
            current_len = len(prefix)
        current.append(line)
        current_len += len(line) + 1
    if len(current) > 1:
        parts.append("\n".join(current))
    return parts or [text]


def _split_by_lines(text: str, limit: int) -> list[str]:
    """Last resort for a table-shaped blob with no parseable header."""
    parts: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.splitlines():
        if size + len(line) + 1 > limit and current:
            parts.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += len(line) + 1
    if current:
        parts.append("\n".join(current))
    return parts


#: One ``<tr>`` block, tags included.
_HTML_ROW_RE = re.compile(r"<tr\b.*?</tr>|<tr\b[^>]*/>", re.IGNORECASE | re.DOTALL)
_HTML_CAPTION_RE = re.compile(r"<caption\b[^>]*>(.*?)</caption>", re.IGNORECASE | re.DOTALL)
_HTML_TABLE_RE = re.compile(r"<table\b", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def parse_html_table(html: str) -> tuple[str, list[str], list[str]]:
    """Split an HTML table into ``(caption, header_rows, body_rows)``.

    Rows are kept as raw markup, because this runs on the chunker's path: the table
    has already been rendered once by the structure recogniser, and re-parsing cells
    (``colspan``/``rowspan``) here would be a second, worse renderer. A ``<tr>`` block
    is the unit a part needs to stay readable, and it is what the splitter repeats.

    A leading run of rows carrying ``<th>`` is the header; everything after it is body.
    """
    text = str(html or "")
    if not _HTML_TABLE_RE.search(text):
        return "", [], []
    caption_match = _HTML_CAPTION_RE.search(text)
    caption = normalize_cell(_HTML_TAG_RE.sub("", caption_match.group(1))) if caption_match else ""
    rows = _HTML_ROW_RE.findall(text)
    header: list[str] = []
    body: list[str] = []
    for row in rows:
        if not body and re.search(r"<th\b", row, re.IGNORECASE):
            header.append(row)
            continue
        body.append(row)
    return caption, header, body


def split_html_table(html: str, max_chars: int) -> list[str]:
    """Split an HTML table into parts that each carry its caption and header row.

    The structure recogniser emits HTML, and an over-long HTML table used to become
    ONE chunk. That is the "tail of 表1 is missing" failure: the embedding only reads
    the head of what it is given, so the rows past it (800mm², 1200mm²) contributed
    nothing to the vector and could not be recalled by any question, no matter how the
    cut rebalanced the window.

    Every part repeats ``<table><caption>…`` and the header row(s), so a row is always
    present underneath the columns it belongs to. A table that already fits is
    returned whole, unchanged.
    """
    text = str(html or "").rstrip()
    if not text:
        return []
    limit = int(max_chars or 0)
    if limit <= 0 or len(text) <= limit:
        return [text]

    caption, header, body = parse_html_table(text)
    if not body:
        # Table-shaped markup with no rows to batch (or not a table at all).
        return _split_by_lines(text, limit)

    opening = "<table>" if _HTML_TABLE_RE.search(text) else ""
    if caption:
        opening += f"<caption>{caption}</caption>"
    prefix = opening + "".join(header)
    suffix = "</table>" if opening else ""
    budget = max(limit - len(prefix) - len(suffix), 1)

    parts: list[str] = []
    current: list[str] = []
    current_len = 0
    for row in body:
        if current and current_len + len(row) > budget:
            parts.append(prefix + "".join(current) + suffix)
            current, current_len = [], 0
        current.append(row)
        current_len += len(row)
    if current:
        parts.append(prefix + "".join(current) + suffix)
    return parts or [text]


def count_table_rows(table_text: Any) -> int:
    """How many DATA rows a rendered table carries, in either shape this project emits.

    Used by the parser's per-table evidence line: a table the model recognised as its
    HEAD only is the "the tail rows are missing" report, and the row count is what tells
    a partial grid from a complete one. The header is not counted, so an HTML reading and
    a Markdown reading of the same region are comparable.
    """
    text = str(table_text or "")
    if not text.strip():
        return 0
    html_rows = _HTML_ROW_RE.findall(text)
    if html_rows:
        _, _, body = parse_html_table(text)
        return len(body) if body else len(html_rows)
    _, header, body = parse_markdown_table(text)
    if header:
        return len(body)
    return len([line for line in text.splitlines() if line.strip()])


def _find_caption(page: Any, bbox: tuple[float, float, float, float] | None, gap: float = CAPTION_MAX_GAP) -> str:
    """The ``表N …`` line just above ``bbox``, if there is one."""
    if bbox is None:
        return ""
    top = float(bbox[1])
    try:
        lines = page.extract_text_lines() or []
    except Exception:  # noqa: BLE001 - a caption is a nicety, never a failure
        _LOG.warning("[Table] caption lookup failed on page %s", getattr(page, "page_number", "?"))
        return ""
    best = ""
    best_bottom = None
    for line in lines:
        bottom = float(line.get("bottom") or 0.0)
        if bottom > top or top - bottom > gap:
            continue
        text = normalize_cell(line.get("text"))
        if not CAPTION_RE.match(text):
            continue
        if best_bottom is None or bottom > best_bottom:
            best, best_bottom = text, bottom
    return best[:_TABLE_CAPTION_LINE_LIMIT]


def extract_page_tables(page: Any, *, strategy: TableStrategy | None = None, borderless_fallback: bool = True) -> list[ExtractedTable]:
    """Every table on ``page``, ruled first and borderless when that finds none.

    The fallback is the point: a page whose tables carry no vertical rules comes
    back as prose from the ruled strategy, and that is the "missed table" report
    this exists for. It is tried only when the ruled strategy produced nothing
    usable, so a normal ruled page pays for one extraction, not two.
    """
    attempts = [strategy or RULED]
    if borderless_fallback and (strategy is None or strategy.name != BORDERLESS.name):
        attempts.append(BORDERLESS)

    for attempt in attempts:
        tables = _find_tables(page, attempt)
        if tables:
            return tables
    return []


def _find_tables(page: Any, strategy: TableStrategy) -> list[ExtractedTable]:
    try:
        found = page.find_tables(strategy.as_table_settings())
    except Exception:  # noqa: BLE001 - a malformed page must not abort the parse
        _LOG.exception("[Table] %s table finding failed on page %s", strategy.name, getattr(page, "page_number", "?"))
        return []

    out: list[ExtractedTable] = []
    for table in found or []:
        rows = normalize_rows(table.extract())
        if not is_well_formed_table(rows):
            continue
        bbox = tuple(float(value) for value in table.bbox) if getattr(table, "bbox", None) else None
        out.append(
            ExtractedTable(
                rows=rows,
                page_index=int(getattr(page, "page_number", 1)) - 1,
                bbox=bbox,  # type: ignore[arg-type]
                caption=_find_caption(page, bbox),  # type: ignore[arg-type]
                strategy=strategy.name,
            )
        )
    _LOG.debug("[Table] %s strategy found %d usable table(s) on page %s", strategy.name, len(out), getattr(page, "page_number", "?"))
    return out


def extract_tables_from_pdf(
    fnm: Any,
    page_from: int = 0,
    page_to: int | None = None,
    binary: bytes | None = None,
    *,
    merge_pages: bool = True,
) -> list[ExtractedTable]:
    """Extract (and merge) the tables of a page window, closing its own handle.

    The handle is opened and closed inside one ``with``, under the repository's
    shared pdfplumber lock - the same contract every other reader in this package
    keeps, and the reason a batch ingest cannot leak a file descriptor per
    document through this path.
    """
    from io import BytesIO

    tables: list[ExtractedTable] = []
    try:
        with sys.modules[LOCK_KEY_pdfplumber]:
            source = fnm if binary is None else BytesIO(binary)
            with pdfplumber.open(source) as pdf:
                pages = pdf.pages[page_from:page_to]
                for page in pages:
                    tables.extend(extract_page_tables(page))
    except Exception:  # noqa: BLE001 - tables are an enhancement, not the parse
        _LOG.exception("[Table] extraction failed for %s pages %s:%s", fnm, page_from, page_to)
        return []
    if merge_pages:
        tables = merge_over_page_tables(tables)
    _LOG.info("[Table] extracted %d table(s) from %s pages %s:%s", len(tables), fnm, page_from, page_to)
    return tables
