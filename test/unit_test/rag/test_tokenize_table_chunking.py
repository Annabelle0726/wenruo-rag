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
"""Header injection when a long table becomes several chunks.

A cable parameter table runs to dozens of rows. Stored as one chunk it dominates
the context window; stored as row-batches without the header, the row a question
asks about (``3x630`` / ``60.0``) arrives with no column to belong to. Every part
therefore repeats the table's name and its header row.
"""

from rag.nlp import tokenize_table

CAPTION = "表1 额定电压1kV架空绝缘导线结构尺寸"
HEADER = "| 序号 | 标称截面 mm2 | 绝缘厚度 mm | 平均外径 mm | 偏心度 % |"
SEPARATOR = "| --- | --- | --- | --- | --- |"
ROWS = [
    "| 1 | 3x25 | 0.9 | 18.2 | 10 |",
    "| 2 | 3x35 | 0.9 | 19.8 | 10 |",
    "| 3 | 3x50 | 1.0 | 21.4 | 10 |",
    "| 4 | 3x70 | 1.1 | 23.6 | 12 |",
    "| 5 | 3x95 | 1.1 | 26.0 | 12 |",
    "| 6 | 3x120 | 1.2 | 28.4 | 12 |",
    "| 7 | 4x240 | 1.7 | 38.6 | 15 |",
    "| 8 | 3x630 | 2.4 | 60.0 | 15 |",
]
MARKDOWN = "\n".join([CAPTION, HEADER, SEPARATOR, *ROWS])
DOC = {"docnm_kwd": "datasheet.pdf", "title_tks": "datasheet"}


def _chunks(table_text, max_table_chars, img=None):
    return tokenize_table([((img, table_text), [])], dict(DOC), True, language="Chinese", max_table_chars=max_table_chars)


def test_a_table_with_no_budget_stays_one_chunk():
    chunks = _chunks(MARKDOWN, 0)

    assert len(chunks) == 1
    assert chunks[0]["content_with_weight"] == MARKDOWN
    assert chunks[0]["doc_type_kwd"] == "table"


def test_a_table_that_fits_stays_one_chunk():
    chunks = _chunks(MARKDOWN, 100000)

    assert len(chunks) == 1


def test_a_long_table_is_split_and_every_part_carries_the_header():
    chunks = _chunks(MARKDOWN, 200)

    assert len(chunks) > 1
    for chunk in chunks:
        lines = chunk["content_with_weight"].splitlines()
        assert lines[0] == CAPTION, "the table name travels with every part"
        assert lines[1] == HEADER, "the header row travels with every part"
        assert lines[2] == SEPARATOR
        assert chunk["doc_type_kwd"] == "table"
        assert chunk["docnm_kwd"] == DOC["docnm_kwd"], "document metadata is inherited"


def test_no_row_is_lost_or_duplicated_by_the_split():
    chunks = _chunks(MARKDOWN, 200)

    data_lines = []
    for chunk in chunks:
        data_lines.extend(chunk["content_with_weight"].splitlines()[3:])

    assert data_lines == ROWS


def test_the_table_image_is_attached_to_every_part():
    chunks = _chunks(MARKDOWN, 200, img="<image>")

    assert chunks
    assert all(chunk.get("image") == "<image>" for chunk in chunks)


HTML_CAPTION = "<caption>表1 电缆结构技术参数表</caption>"
HTML_HEADER = "<tr><th>标称截面</th><th>金属套平均厚度</th><th>外径</th></tr>"
HTML_ROWS = [
    "<tr><td>400</td><td>3.8</td><td>54.0</td></tr>",
    "<tr><td>630</td><td>3.8</td><td>62.0</td></tr>",
    "<tr><td>800</td><td>3.9</td><td>68.0</td></tr>",
    "<tr><td>1000</td><td>4.0</td><td>74.0</td></tr>",
    "<tr><td>1200</td><td>4.1</td><td>80.0</td></tr>",
]
HTML = "<table>" + HTML_CAPTION + HTML_HEADER + "".join(HTML_ROWS) + "</table>"


def test_a_long_html_table_is_split_and_every_part_carries_caption_and_header():
    """The structure recogniser emits HTML, and an over-long HTML table used to be ONE
    chunk: the embedding reads only the head of what it is given, so the rows past it
    (800mm², 1200mm² of 表1) were unreachable by any question."""
    chunks = _chunks(HTML, 220)

    assert len(chunks) > 1
    for chunk in chunks:
        body = chunk["content_with_weight"]
        assert body.startswith("<table>"), "each part is a table of its own"
        assert HTML_CAPTION in body, "the table name travels with every part"
        assert HTML_HEADER in body, "so do the columns the rows belong to"
        assert body.endswith("</table>")
        assert chunk["doc_type_kwd"] == "table"


def test_no_html_row_is_lost_or_duplicated_by_the_split():
    chunks = _chunks(HTML, 220)

    rows = []
    for chunk in chunks:
        body = chunk["content_with_weight"]
        assert HTML_HEADER not in body.replace(HTML_HEADER, "", 1), "the header appears once per part"
        rows.extend([row for row in HTML_ROWS if row in body])

    assert rows == HTML_ROWS
    for row in HTML_ROWS:
        assert sum(row in chunk["content_with_weight"] for chunk in chunks) == 1


def test_an_html_table_that_fits_stays_one_chunk():
    chunks = _chunks(HTML, 100000)

    assert len(chunks) == 1
    assert chunks[0]["content_with_weight"] == HTML


def test_an_html_table_without_a_caption_still_repeats_its_header():
    html = "<table>" + HTML_HEADER + "".join(HTML_ROWS) + "</table>"

    chunks = _chunks(html, 220)

    assert len(chunks) > 1
    assert all(chunk["content_with_weight"].startswith("<table>" + HTML_HEADER) for chunk in chunks)


def test_a_figure_row_list_is_untouched():
    """A list means a figure (several caption lines), not a table."""
    tbls = [((None, [CAPTION, "图2 结构示意图"]), [])]

    chunks = tokenize_table(tbls, dict(DOC), True, language="Chinese", max_table_chars=50)

    assert len(chunks) == 1
    assert chunks[0]["doc_type_kwd"] == "image"


def test_an_empty_table_produces_no_chunk():
    assert _chunks("", 200) == []
