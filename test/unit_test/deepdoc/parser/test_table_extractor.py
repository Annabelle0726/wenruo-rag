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
"""Rule-based table extraction, over PDFs built for the purpose.

The three failures these cover are the ones the cable corpus reports: a large
ruled table the model-based recogniser reads as text lines, a table with NO
vertical rules (which a lines-based finder does not see at all), and a table that
continues across a page break. The PDFs are generated here with reportlab, so the
input is exactly the geometry the assertions describe rather than whatever a
fixture file happens to contain.
"""

import io

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas as pdf_canvas

from deepdoc.parser import table_extractor as tables

pytestmark = pytest.mark.p1

PAGE_WIDTH, PAGE_HEIGHT = A4

#: A CJK font, so the fixture carries the labels a cable table really has. The
#: Adobe CID font needs no embedded file and reportlab writes its own ToUnicode
#: map, so pdfplumber reads 序号 back as text rather than as glyph ids.
TABLE_FONT = "STSong-Light"
pdfmetrics.registerFont(UnicodeCIDFont(TABLE_FONT))

#: A cable parameter table: a header plus the data rows a question asks about
#: (截面 / 外径 / 偏心度).
HEADER = ["序号", "标称截面 mm2", "绝缘厚度 mm", "平均外径 mm", "偏心度 %"]
ROWS = [
    ["1", "3x25", "0.9", "18.2", "10"],
    ["2", "3x35", "0.9", "19.8", "10"],
    ["3", "3x50", "1.0", "21.4", "10"],
    ["4", "3x70", "1.1", "23.6", "12"],
    ["5", "3x95", "1.1", "26.0", "12"],
    ["6", "3x120", "1.2", "28.4", "12"],
    ["7", "4x240", "1.7", "38.6", "15"],
    ["8", "3x630", "2.4", "60.0", "15"],
]
#: The rows as they reach the renderer: header first.
TABLE_ROWS = [HEADER] + ROWS
CAPTION = "表1 额定电压1kV架空绝缘导线结构尺寸"

COLUMN_X = [60, 130, 230, 320, 420]
ROW_HEIGHT = 20.0


def _draw_grid(canv, *, left, top, rows, header_row=None, caption="", ruled=True):
    """Draw a table at ``(left, top)``; ``ruled=False`` prints no marks at all."""
    x_positions = [left + (x - COLUMN_X[0]) for x in COLUMN_X]
    x_positions.append(x_positions[-1] + 80)
    all_rows = ([header_row] if header_row else []) + list(rows)
    height = ROW_HEIGHT * len(all_rows)

    if caption:
        canv.setFont(TABLE_FONT, 10)
        canv.drawString(left, top + height + 8, caption)

    canv.setFont(TABLE_FONT, 8)
    for row_index, row in enumerate(all_rows):
        baseline = top + height - (row_index + 1) * ROW_HEIGHT + 6
        for column_index, cell in enumerate(row):
            if column_index >= len(x_positions) - 1:
                break
            canv.drawString(x_positions[column_index] + 3, baseline, str(cell))

    if ruled:
        canv.setLineWidth(0.6)
        for x in x_positions:
            canv.line(x, top, x, top + height)
        for row_index in range(len(all_rows) + 1):
            y = top + height - row_index * ROW_HEIGHT
            canv.line(x_positions[0], y, x_positions[-1], y)
    return height


def _pdf(pages) -> bytes:
    """Build a PDF from a list of per-page drawing callables."""
    buffer = io.BytesIO()
    canv = pdf_canvas.Canvas(buffer, pagesize=A4)
    for draw in pages:
        draw(canv)
        canv.showPage()
    canv.save()
    return buffer.getvalue()


def _ruled_page(canv):
    _draw_grid(canv, left=60, top=300, rows=ROWS, header_row=HEADER, caption=CAPTION)


def _borderless_page(canv):
    _draw_grid(canv, left=60, top=300, rows=ROWS, header_row=HEADER, caption=CAPTION, ruled=False)


def _split_table_first_page(canv):
    _draw_grid(canv, left=60, top=PAGE_HEIGHT - 260, rows=ROWS[:3], header_row=HEADER, caption=CAPTION)


def _split_table_second_page(canv):
    # Starts at the very top of the page, straight into data (no repeated header).
    _draw_grid(canv, left=60, top=760, rows=ROWS[3:6])


def _repeated_header_second_page(canv):
    _draw_grid(canv, left=60, top=760, rows=ROWS[3:6], header_row=HEADER)


def _two_unrelated_tables(canv):
    _draw_grid(canv, left=60, top=PAGE_HEIGHT - 260, rows=ROWS[:2], header_row=HEADER, caption=CAPTION)
    _draw_grid(
        canv,
        left=60,
        top=420,
        rows=[["1", "铠装", "0.2", "0.2", "—"]],
        header_row=["序号", "项目", "厚度 mm", "外径 mm", "偏心度 %"],
        caption="表2 其他要求",
    )


def _flat_text_page(canv):
    canv.setFont(TABLE_FONT, 11)
    canv.drawString(60, 700, "本页没有任何表格，只有一段说明文字。")


# ---------------------------------------------------------------------------
# Ruled tables
# ---------------------------------------------------------------------------


def test_a_ruled_table_is_extracted_with_its_caption():
    pdf = _pdf([_ruled_page])

    found = tables.extract_tables_from_pdf(io.BytesIO(pdf), 0, None)

    assert len(found) == 1
    table = found[0]
    assert table.strategy == "ruled"
    assert table.rows[0] == HEADER
    assert table.rows[1] == ROWS[0]
    assert table.rows[-1] == ROWS[-1]
    assert CAPTION in table.caption


def test_a_wide_table_keeps_every_row():
    """The reported failure: a large table arriving as a few text lines.

    Extraction is row-exact, which is what makes a single row (``3x630`` /
    ``60.0``) meaningful downstream.
    """
    pdf = _pdf([_ruled_page])

    table = tables.extract_tables_from_pdf(io.BytesIO(pdf), 0, None)[0]

    assert len(table.body) == len(ROWS)
    assert table.rows[-1][1] == "3x630"
    assert table.rows[-1][3] == "60.0"


# ---------------------------------------------------------------------------
# Borderless tables
# ---------------------------------------------------------------------------


def test_a_table_without_rules_is_still_found():
    """No rules printed: the ruled strategy sees nothing, the text one does."""
    pdf = _pdf([_borderless_page])

    found = tables.extract_tables_from_pdf(io.BytesIO(pdf), 0, None)

    assert found, "a borderless table must not be lost"
    table = found[0]
    assert table.strategy == "borderless"
    assert table.header[:2] == HEADER[:2]
    assert len(table.body) >= 5


def test_a_page_without_tables_yields_nothing():
    pdf = _pdf([_flat_text_page])

    assert tables.extract_tables_from_pdf(io.BytesIO(pdf), 0, None) == []


def test_the_ruled_strategy_is_tried_before_the_borderless_one(monkeypatch):
    """A ruled page pays for ONE extraction, not two."""
    attempts = []
    original = tables._find_tables

    def _spy(page, strategy):
        attempts.append(strategy.name)
        return original(page, strategy)

    monkeypatch.setattr(tables, "_find_tables", _spy)
    pdf = _pdf([_ruled_page])

    tables.extract_tables_from_pdf(io.BytesIO(pdf), 0, None)

    assert attempts[:2] == ["ruled"], attempts[:2]


# ---------------------------------------------------------------------------
# Over-page tables
# ---------------------------------------------------------------------------


def test_a_table_continuing_without_a_header_is_merged():
    pdf = _pdf([_split_table_first_page, _split_table_second_page])

    found = tables.extract_tables_from_pdf(io.BytesIO(pdf), 0, None)

    assert len(found) == 1, "the two halves are one logical table"
    table = found[0]
    assert table.header == HEADER
    assert len(table.body) == 6
    assert table.merged_pages == [1]
    assert table.rows[4][1] == ROWS[3][1]


def test_a_repeated_header_is_dropped_when_merging():
    """A well-typeset standard repeats the header on the next page."""
    pdf = _pdf([_split_table_first_page, _repeated_header_second_page])

    found = tables.extract_tables_from_pdf(io.BytesIO(pdf), 0, None)

    assert len(found) == 1
    assert found[0].rows.count(HEADER) == 1, "the repeated header must not appear as a data row"
    assert len(found[0].body) == 6


def test_the_merged_table_renders_as_one_markdown_table():
    pdf = _pdf([_split_table_first_page, _split_table_second_page])
    found = tables.extract_tables_from_pdf(io.BytesIO(pdf), 0, None)

    markdown = tables.table_to_markdown(found[0].rows, caption=CAPTION)
    lines = markdown.splitlines()

    assert lines[0] == CAPTION
    assert lines[1] == "| " + " | ".join(HEADER) + " |"
    assert any(ROWS[3][1] in line for line in lines[3:]), "the continuation's rows are part of it"
    assert sum(1 for line in lines[3:] if line.startswith("| ")) == 6


def test_two_different_tables_on_consecutive_pages_are_not_merged():
    """A different header is a different table, however close it sits."""
    pdf = _pdf([_two_unrelated_tables, _repeated_header_second_page])

    found = tables.extract_tables_from_pdf(io.BytesIO(pdf), 0, None)

    assert len(found) >= 2, "the second table has its own header and must stay separate"
    assert found[0].header == HEADER


def test_a_continuation_in_the_middle_of_a_page_is_not_merged():
    """Merging is only for a table that starts at the TOP of the next page."""
    first = tables.ExtractedTable(rows=[HEADER] + ROWS[:2], page_index=0, bbox=(60.0, 100.0, 500.0, 200.0))
    middle = tables.ExtractedTable(rows=ROWS[2:4], page_index=1, bbox=(60.0, 400.0, 500.0, 460.0))

    merged = tables.merge_over_page_tables([first, middle])

    assert len(merged) == 2


def test_a_continuation_with_a_different_column_count_is_not_merged():
    first = tables.ExtractedTable(rows=[HEADER] + ROWS[:2], page_index=0, bbox=(60.0, 100.0, 500.0, 200.0))
    other = tables.ExtractedTable(rows=[["1", "2"]], page_index=1, bbox=(60.0, 10.0, 500.0, 60.0))

    assert len(tables.merge_over_page_tables([first, other])) == 2


def test_a_continuation_on_a_later_page_is_not_merged():
    first = tables.ExtractedTable(rows=[HEADER] + ROWS[:2], page_index=0, bbox=(60.0, 100.0, 500.0, 200.0))
    third = tables.ExtractedTable(rows=ROWS[2:4], page_index=2, bbox=(60.0, 10.0, 500.0, 60.0))

    assert len(tables.merge_over_page_tables([first, third])) == 2


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def test_markdown_carries_the_caption_header_and_separator():
    markdown = tables.table_to_markdown(TABLE_ROWS, caption=CAPTION)

    lines = markdown.splitlines()
    assert lines[0] == CAPTION
    assert lines[1] == "| " + " | ".join(HEADER) + " |"
    assert lines[2] == "| " + " | ".join("---" for _ in HEADER) + " |"
    assert len(lines) == 2 + len(TABLE_ROWS)


def test_markdown_flattens_a_wrapped_cell():
    """A newline inside a cell is what makes a table read as garbled text."""
    markdown = tables.table_to_markdown([["序号", "项目"], ["1", "绝缘\n厚度"]], caption="")

    assert "绝缘 厚度" in markdown
    assert markdown.count("\n") == 2, "one line per table row"


def test_markdown_escapes_a_pipe_in_a_cell():
    markdown = tables.table_to_markdown([["a|b", "c"]], caption="")

    assert "a\\|b" in markdown


def test_markdown_of_nothing_is_empty():
    assert tables.table_to_markdown([], caption="表1") == ""
    assert tables.table_to_markdown(None) == ""


def test_markdown_survives_a_round_trip_through_the_parser():
    markdown = tables.table_to_markdown(TABLE_ROWS, caption=CAPTION)

    caption, head, body = tables.parse_markdown_table(markdown)

    assert caption == CAPTION
    assert head == ["| " + " | ".join(HEADER) + " |", "| " + " | ".join("---" for _ in HEADER) + " |"]
    assert len(body) == len(ROWS)


# ---------------------------------------------------------------------------
# Header injection when a table has to be split
# ---------------------------------------------------------------------------


def test_a_long_table_is_split_with_the_header_repeated():
    markdown = tables.table_to_markdown(TABLE_ROWS, caption=CAPTION)

    parts = tables.split_markdown_table(markdown, 200)

    assert len(parts) > 1
    for part in parts:
        lines = part.splitlines()
        assert lines[0] == CAPTION, "every part carries the table name"
        assert lines[1] == "| " + " | ".join(HEADER) + " |", "every part carries the header row"
        assert lines[2].startswith("| ---")


def test_splitting_loses_no_row():
    """Each part repeats caption and header; the DATA rows appear exactly once."""
    markdown = tables.table_to_markdown(TABLE_ROWS, caption=CAPTION)

    parts = tables.split_markdown_table(markdown, 200)

    data_lines = []
    for part in parts:
        data_lines.extend(part.splitlines()[3:])
    assert data_lines == ["| " + " | ".join(row) + " |" for row in ROWS]


def test_a_table_that_fits_is_returned_whole():
    markdown = tables.table_to_markdown(TABLE_ROWS, caption=CAPTION)

    assert tables.split_markdown_table(markdown, 100000) == [markdown]


def test_a_zero_budget_means_no_splitting():
    markdown = tables.table_to_markdown(TABLE_ROWS, caption=CAPTION)

    assert tables.split_markdown_table(markdown, 0) == [markdown]


def test_a_single_row_row_batch_still_carries_its_header():
    """The isolated-row case: one data row per part, header injected every time."""
    markdown = tables.table_to_markdown(TABLE_ROWS, caption=CAPTION)

    parts = tables.split_markdown_table(markdown, len(CAPTION) + 120)

    assert len(parts) == len(ROWS)
    for part, row in zip(parts, ROWS):
        assert HEADER[1] in part, "the header survives in a one-row part"
        assert row[1] in part


# ---------------------------------------------------------------------------
# Settings and grid hygiene
# ---------------------------------------------------------------------------


def test_the_strategy_profiles_are_explicit_about_their_geometry():
    ruled = tables.RULED.as_table_settings()
    borderless = tables.BORDERLESS.as_table_settings()

    assert ruled["vertical_strategy"] == "lines"
    assert ruled["horizontal_strategy"] == "lines"
    assert ruled["snap_tolerance"] == tables.DEFAULT_SNAP_TOLERANCE
    assert ruled["join_tolerance"] == tables.DEFAULT_JOIN_TOLERANCE
    assert ruled["intersection_tolerance"] == tables.DEFAULT_INTERSECTION_TOLERANCE

    assert borderless["vertical_strategy"] == "text"
    assert borderless["horizontal_strategy"] == "text"
    assert borderless["min_words_vertical"] == tables.BORDERLESS_MIN_WORDS_VERTICAL


def test_a_degenerate_grid_is_rejected():
    """A stray rectangle around a figure comes back as a grid of empty cells."""
    assert tables.is_well_formed_table([["", "", ""], ["", "", ""]]) is False
    assert tables.is_well_formed_table([["序号", "项目"]]) is False
    assert tables.is_well_formed_table([["序号", "项目"], ["", ""], ["", ""]]) is False
    assert tables.is_well_formed_table([["序号", "项目"], ["1", "绝缘"], ["2", "护套"]]) is True
    assert tables.is_well_formed_table([["序号", "项目"], ["1", "绝缘"]]) is True


def test_normalizing_drops_empty_rows_and_columns():
    rows = tables.normalize_rows([["", "", ""], ["序号", "项目", ""], ["1", "绝缘", ""]])

    assert rows == [["序号", "项目"], ["1", "绝缘"]]


def test_a_numeric_row_is_not_a_header():
    """A continuation starting with data must not be mistaken for a new table."""
    assert tables.looks_like_header(["1", "3x25", "0.9", "18.2", "10"]) is False
    assert tables.looks_like_header(HEADER) is True
    assert tables.looks_like_header(["—", "—"]) is False


# ---------------------------------------------------------------------------
# The HTML table the structure recogniser emits
# ---------------------------------------------------------------------------

HTML_CAPTION = "表1 电缆结构技术参数表"
HTML_HEADER = "<tr><th>标称截面</th><th>金属套平均厚度</th></tr>"
HTML_ROWS = [f"<tr><td>{section}</td><td>{thickness}</td></tr>" for section, thickness in ((400, 3.8), (630, 3.8), (800, 3.9), (1200, 4.1), (1600, 4.3))]
HTML = f"<table><caption>{HTML_CAPTION}</caption>{HTML_HEADER}{''.join(HTML_ROWS)}</table>"


def test_parsing_an_html_table_separates_caption_header_and_rows():
    caption, header, rows = tables.parse_html_table(HTML)

    assert caption == HTML_CAPTION
    assert header == [HTML_HEADER]
    assert rows == HTML_ROWS


def test_parsing_an_html_table_without_a_header_treats_every_row_as_data():
    html = "<table>" + "".join(HTML_ROWS) + "</table>"

    caption, header, rows = tables.parse_html_table(html)

    assert caption == ""
    assert header == []
    assert rows == HTML_ROWS


def test_parsing_something_that_is_not_a_table_yields_nothing():
    assert tables.parse_html_table("普通正文") == ("", [], [])


def test_a_html_table_that_fits_is_returned_unchanged():
    assert tables.split_html_table(HTML, len(HTML)) == [HTML]
    assert tables.split_html_table(HTML, 0) == [HTML]


def test_splitting_an_html_table_repeats_caption_and_header_in_every_part():
    parts = tables.split_html_table(HTML, 200)

    assert len(parts) > 1
    for part in parts:
        assert part.startswith("<table><caption>" + HTML_CAPTION + "</caption>" + HTML_HEADER)
        assert part.endswith("</table>")


def test_splitting_an_html_table_loses_no_row():
    parts = tables.split_html_table(HTML, 200)

    assert sorted(row for part in parts for row in HTML_ROWS if row in part) == sorted(HTML_ROWS)


def test_an_html_table_part_keeps_the_rows_within_its_budget():
    parts = tables.split_html_table(HTML, 220)

    assert len(parts) > 1
    # One row per part is the smallest a split can get; anything wider than that must
    # respect the budget, which is what keeps a part inside the embedding's window.
    for part in parts:
        assert len(part) <= 220 or len(part) <= len("<table><caption>" + HTML_CAPTION + "</caption>" + HTML_HEADER + "</table>") + max(len(row) for row in HTML_ROWS)

