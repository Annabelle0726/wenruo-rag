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
"""The chunk auditor's pure core: shape, pages, hits and the verdict.

The tool itself talks to the doc store; these cases pin the part that decides WHICH
side of the pipeline a missing value belongs to, because that decision is the whole
point of running it.
"""

import importlib.util
from pathlib import Path

import pytest

_TOOL = Path(__file__).resolve().parents[3] / "tools" / "audit_document_chunks.py"
_spec = importlib.util.spec_from_file_location("audit_document_chunks", _TOOL)
audit_tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit_tool)

pytestmark = pytest.mark.p2


def _chunk(body, *, shape=None, page=None, chunk_id="c1"):
    chunk = {"chunk_id": chunk_id, "content_with_weight": body, "doc_id": "doc-1"}
    if shape:
        chunk["doc_type_kwd"] = shape
    if page:
        chunk["position_int"] = [[page, 0, 0, 0, 0]]
    return chunk


def test_a_shape_tells_the_parse_path_apart():
    assert audit_tool.classify(_chunk("<table><tr><th>截面</th></tr></table>", shape="table")) == "table-html"
    assert audit_tool.classify(_chunk("表1 电缆结构\n| 截面 | 厚度 |\n| --- | --- |\n| 800 | 3.9 |", shape="table")) == "table-markdown"
    assert audit_tool.classify(_chunk("1×800 3.9", shape="text")) == "text"
    assert audit_tool.classify(_chunk("图2 结构示意图", shape="image")) == "image"


def test_pages_are_read_from_both_position_fields_and_reported_once():
    chunk = _chunk("x", shape="table")
    # `page_num_int` is 0-based, the way the chunkers write it.
    chunk["page_num_int"] = [11]
    assert audit_tool.pages_of(chunk) == [12]

    # `position_int` is 1-based, the way the parser writes it: the same page.
    chunk["position_int"] = [[12, 0, 0, 0, 0]]
    assert audit_tool.pages_of(chunk) == [12]

    chunk["position_int"] = [[12, 0, 0, 0, 0], [13, 0, 0, 0, 0]]
    assert audit_tool.pages_of(chunk) == [12, 13]


def test_a_value_in_no_chunk_is_reported_as_a_parse_gap():
    chunks = [_chunk("<table><tr><td>1×400</td><td>3.8</td></tr></table>", shape="table", page=11)]

    report = audit_tool.audit(chunks, ["3.9", "1200"])

    assert report["patterns"]["3.9"] == []
    assert "NO chunk" in audit_tool.verdict(report, ["3.9", "1200"])
    assert "PARSE lost them" in audit_tool.verdict(report, ["3.9", "1200"])


def test_a_value_in_a_chunk_is_reported_as_a_retrieval_question():
    chunks = [
        _chunk("<table><tr><td>1×800</td><td>3.9</td></tr></table>", shape="table", page=12),
        _chunk("正文", shape="text", page=1),
    ]

    report = audit_tool.audit(chunks, ["3.9"])

    assert len(report["patterns"]["3.9"]) == 1
    hit = report["patterns"]["3.9"][0]
    assert hit["shape"] == "table-html"
    assert hit["pages"] == [12]
    assert "RETRIEVAL" in audit_tool.verdict(report, ["3.9"])


def test_an_empty_document_is_named_as_a_parse_failure():
    report = audit_tool.audit([], ["3.9"])

    assert "NO chunks at all" in audit_tool.verdict(report, ["3.9"])


def test_the_report_shows_only_a_window_around_the_hit():
    body = "x" * 400 + "3.9" + "y" * 400

    report = audit_tool.audit([_chunk(body, shape="table")], ["3.9"])

    excerpt = report["patterns"]["3.9"][0]["excerpt"]
    assert "3.9" in excerpt
    assert len(excerpt) <= audit_tool.EXCERPT_CHARS + 4


def test_a_document_with_no_hits_still_reports_what_was_searched():
    chunks = [_chunk("正文一", shape="text"), _chunk("<table><tr><td>x</td></tr></table>", shape="table")]

    report = audit_tool.audit(chunks, ["3.9"])

    assert report["chunks"] == 2
    assert report["shapes"] == {"table-html": 1, "text": 1}
    assert "NOT FOUND" in audit_tool.render(report)


# ---------------------------------------------------------------------------
# Standing up the document store: the first version of this tool forgot this
# ---------------------------------------------------------------------------


def test_the_connector_is_initialized_when_settings_are_not(monkeypatch):
    """`docStoreConn` is None until `init_settings()` runs - running the tool as a
    plain script must do what the server does at startup, or every query raises
    `'NoneType' object has no attribute 'search'`."""
    from common import settings

    calls = []
    monkeypatch.setattr(settings, "docStoreConn", None)
    monkeypatch.setattr(settings, "init_settings", lambda: (calls.append(True), setattr(settings, "docStoreConn", "connector"))[0])

    assert audit_tool.doc_store_conn() == "connector"
    assert calls == [True], "the initialization ran exactly once"


def test_an_already_initialized_connector_is_used_as_is(monkeypatch):
    from common import settings

    monkeypatch.setattr(settings, "docStoreConn", "already-there")
    monkeypatch.setattr(settings, "init_settings", lambda: pytest.fail("must not re-initialize"))

    assert audit_tool.doc_store_conn() == "already-there"


def test_a_misconfigured_engine_says_so_instead_of_raising_attribute_error(monkeypatch):
    from common import settings

    monkeypatch.setattr(settings, "docStoreConn", None)
    monkeypatch.setattr(settings, "init_settings", lambda: None)

    with pytest.raises(SystemExit) as exit_info:
        audit_tool.doc_store_conn()

    message = str(exit_info.value)
    assert "docStoreConn None" in message
    assert "DOC_ENGINE" in message
    assert "service_conf.yaml" in message
