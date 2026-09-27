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
"""Auto metadata tagging: the regex fast path, and the one-call fallback.

The contract these pin is not just "the fields come out right" but "the ingest never
depends on them": every failure path returns what the fast path had, the model is
asked at most once, and the model's answer can only FILL what the fast path missed -
the document's own text outranks a model's guess about it.
"""

import asyncio
import json
import logging

import pytest

from rag.nlp import auto_metadata as am

pytestmark = pytest.mark.p1

FILENAME = "Q_GDW 73289.2-2026 450_750V聚氯乙烯绝缘电缆采购标准+第2部分：专用技术规范_2.pdf"
BODY = "Q/GDW 73289.2-2026\n" "额定电压450/750V及以下聚氯乙烯绝缘电缆\n" "第2部分：专用技术规范\n" "本文件规定了额定电压450/750V及以下聚氯乙烯绝缘电缆的技术要求、试验方法和检验规则。\n"
FULL = FILENAME + "\n" + BODY


class _FakeLLM:
    """A chat model that returns a scripted answer and records every prompt."""

    def __init__(self, answer=None, error=None):
        self.answer = answer
        self.error = error
        self.prompts = []

    async def async_chat(self, system_prompt, messages, *args, **kwargs):
        self.prompts.append((system_prompt, messages))
        if self.error is not None:
            raise self.error
        return self.answer


def _json_answer(**fields):
    payload = {name: "" for name in am.METADATA_FIELDS}
    payload.update(fields)
    return "```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"


# ---------------------------------------------------------------------------
# Step 1: the regex fast path
# ---------------------------------------------------------------------------


def test_the_fast_path_reads_the_standard_number_voltage_type_and_year():
    fields = am.extract_by_regex(FILENAME, BODY)

    assert fields["standard_no"] == "Q/GDW 73289.2-2026"
    assert fields["voltage_level"] == "450/750V"
    assert fields["doc_type"] == "专用技术规范"
    assert fields["year"] == "2026"


def test_the_fast_path_reads_the_file_name_too():
    """A name-only pass still identifies the document."""
    fields = am.extract_by_regex(FILENAME, "")

    assert fields["standard_no"] == "Q/GDW 73289.2-2026"
    assert fields["doc_type"] in {"专用技术规范", "采购范本"}


def test_the_fast_path_reads_a_standard_number_from_the_text_only():
    fields = am.extract_by_regex("20_架空绝缘导线抽检工作规范.pdf", "Q/GDW 13237 本规范适用于1kV～10kV架空绝缘导线。")

    assert fields["standard_no"] == "Q/GDW 13237"
    assert fields["voltage_level"] == "1kV～10kV", "a range is kept whole: a question naming 10kV still matches"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("额定电压0.6/1kV电缆", "0.6/1kV"),
        ("450/750V及以下", "450/750V"),
        ("适用于10kV系统", "10kV"),
        ("直流1500V", "1500V"),
    ],
)
def test_a_voltage_level_is_captured_with_its_compound_and_its_cjk_neighbour(text, expected):
    """``\\b`` does not fire between "V" and a CJK character, which is why the pattern
    uses an ASCII lookahead; "450/750V及以下" must still match."""
    assert am.extract_by_regex("x.pdf", text)["voltage_level"] == expected


def test_a_voltage_level_is_not_read_out_of_a_longer_word():
    """ "10VA" is an apparent power, not 10 volts."""
    assert "voltage_level" not in am.extract_by_regex("x.pdf", "容量10VA的电源")


@pytest.mark.parametrize("keyword", am.DOC_TYPE_KEYWORDS)
def test_every_documented_document_type_is_recognised(keyword):
    assert am.extract_by_regex("x.pdf", f"本文件为{keyword}。")["doc_type"] == keyword


def test_a_year_is_taken_from_the_head_of_the_document():
    assert am.extract_by_regex("x.pdf", "2024年发布实施的规范")["year"] == "2024"


def test_a_document_with_nothing_to_extract_yields_no_fields():
    assert am.extract_by_regex("unknown.pdf", "本文没有标准号、电压等级、年份或文档类型。") == {}


def test_the_fast_path_only_scans_the_document_head():
    """A standard number buried past the scan window is not this document's."""
    buried = "x" * (am.REGEX_SCAN_CHARS + 50) + " Q/GDW 13237-2017"

    assert "standard_no" not in am.extract_by_regex("plain.pdf", buried)


# ---------------------------------------------------------------------------
# The two-core-field rule
# ---------------------------------------------------------------------------


def test_two_identifying_fields_are_enough_to_skip_the_model():
    assert am.needs_llm({"standard_no": "Q/GDW 13237", "voltage_level": "1kV"}) is False
    assert am.missing_core_fields({"standard_no": "Q/GDW 13237", "voltage_level": "1kV"}) == []


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"standard_no": "Q/GDW 13237"},
        {"voltage_level": "1kV"},
        {"doc_type": "数据手册", "year": "2024"},
    ],
)
def test_fewer_than_two_identifying_fields_asks_the_model(fields):
    assert am.needs_llm(fields) is True


def test_cable_type_alone_does_not_skip_the_model():
    """`cable_type` is not an identifying field: it is what the model adds."""
    assert am.CORE_FIELDS == ("standard_no", "voltage_level")
    assert am.needs_llm({"cable_type": "架空绝缘导线"}) is True


# ---------------------------------------------------------------------------
# Step 2: the LLM fallback
# ---------------------------------------------------------------------------


async def test_the_model_is_called_once_with_the_documented_prompt_and_window():
    llm = _FakeLLM(answer=_json_answer(standard_no="Q/GDW 13237", voltage_level="1kV", cable_type="架空绝缘导线"))

    await am.auto_tag("unknown.pdf", "正文" * 3000, llm=llm)

    assert len(llm.prompts) == 1, "at most one call per document"
    system_prompt, messages = llm.prompts[0]
    assert "JSON" in system_prompt
    for name in am.METADATA_FIELDS:
        assert name in system_prompt, f"the prompt must name the field {name}"
    assert "不要 Markdown 代码块" in system_prompt
    # The user message carries the head of the document, capped at the LLM window.
    body = messages[0]["content"]
    assert len(body) <= am.LLM_SCAN_CHARS + len("文档名：unknown.pdf\n正文片段：\n") + 2


async def test_the_model_fills_what_the_fast_path_missed():
    llm = _FakeLLM(answer=_json_answer(standard_no="Q/GDW 13237", cable_type="架空绝缘导线", doc_type="数据手册"))

    result = await am.auto_tag("20_架空绝缘导线抽检工作规范.pdf", "本规范适用于1kV架空绝缘导线。", llm=llm)

    assert result.used_llm is True
    assert result.source == "regex+llm"
    assert result.fields["standard_no"] == "Q/GDW 13237"  # the document's own text won
    assert result.fields["voltage_level"] == "1kV"  # filled by the fast path
    assert result.fields["cable_type"] == "架空绝缘导线"  # only the model could add this


async def test_a_field_the_fast_path_read_is_never_overwritten_by_the_model():
    """The document's own text outranks a model's guess about it."""
    llm = _FakeLLM(answer=_json_answer(standard_no="GB/T 9999-1999", voltage_level="35kV"))

    result = await am.auto_tag(FILENAME, BODY, llm=llm)

    assert result.fields["standard_no"] == "Q/GDW 73289.2-2026"
    assert result.fields["voltage_level"] == "450/750V"


async def test_a_model_that_is_not_needed_is_never_called():
    llm = _FakeLLM(answer=_json_answer(cable_type="架空绝缘导线"))

    result = await am.auto_tag(FILENAME, BODY, llm=llm)

    assert llm.prompts == [], "a document the fast path identified must not cost a call"
    assert result.used_llm is False
    assert result.source == "regex"


async def test_the_model_supplies_everything_when_the_fast_path_is_empty():
    llm = _FakeLLM(answer=_json_answer(standard_no="q/gdw73289.2-2026", voltage_level="0.6/1kV", cable_type="电力电缆", doc_type="技术条件", year="2026"))

    result = await am.auto_tag("scan_0001.pdf", "没有可提取字段的说明文字。", llm=llm)

    assert result.source == "llm"
    assert result.fields == {
        "standard_no": "Q/GDW 73289.2-2026",  # normalized to the corpus spelling
        "voltage_level": "0.6/1kV",
        "cable_type": "电力电缆",
        "doc_type": "技术条件",
        "year": "2026",
    }


async def test_the_answer_is_parsed_out_of_a_fenced_json_block_with_a_think_block():
    llm = _FakeLLM(
        answer='<think>思考</think>\n以下是结果：\n```json\n{"standard_no": "GB/T 12706.1-2020", "voltage_level": "", "cable_type": "电力电缆", "doc_type": "通用技术规范", "year": "2020"}\n```'
    )

    result = await am.auto_tag("scan.pdf", "无关文字", llm=llm)

    assert result.fields["standard_no"] == "GB/T 12706.1-2020"
    assert "voltage_level" not in result.fields, "an empty field is dropped, not stored as an empty string"


# ---------------------------------------------------------------------------
# Fault tolerance: an enhancement must never fail an ingest
# ---------------------------------------------------------------------------


async def test_a_failing_model_degrades_to_the_fast_path(caplog):
    llm = _FakeLLM(error=RuntimeError("provider down"))

    with caplog.at_level(logging.WARNING):
        # One identifying field only: the model IS consulted, and its failure is
        # what the fast path has to survive.
        result = await am.auto_tag("20_架空绝缘导线抽检工作规范.pdf", "Q/GDW 13237 适用于架空绝缘导线", llm=llm)

    assert len(llm.prompts) == 1, "the failure below is only meaningful if the model was asked"
    assert result.fields["standard_no"] == "Q/GDW 13237"
    assert result.used_llm is False
    assert "model pass failed" in caplog.text


async def test_a_timeout_degrades_to_the_fast_path():
    class _SlowLLM:
        def __init__(self):
            self.calls = 0

        async def async_chat(self, *args, **kwargs):
            self.calls += 1
            await asyncio.sleep(5)
            return _json_answer(cable_type="电力电缆")

    slow = _SlowLLM()
    result = await am.auto_tag("20_架空绝缘导线抽检工作规范.pdf", "Q/GDW 13237 适用于架空绝缘导线", llm=slow, timeout_seconds=0.05)

    assert slow.calls == 1, "a slow provider is abandoned, not awaited"
    assert result.fields["standard_no"] == "Q/GDW 13237"
    assert result.used_llm is False


async def test_an_unparseable_answer_degrades_to_the_fast_path(caplog):
    llm = _FakeLLM(answer="我不确定这个文档的标准号。")

    with caplog.at_level(logging.WARNING):
        result = await am.auto_tag("unknown.pdf", "普通说明文字", llm=llm)

    assert result.fields == {}
    assert result.source == "none"
    assert "carries no JSON object" in caplog.text


async def test_no_model_at_all_keeps_the_fast_path():
    result = await am.auto_tag(FILENAME, BODY, llm=None)

    assert result.fields["standard_no"] == "Q/GDW 73289.2-2026"


async def test_an_empty_document_yields_nothing_and_calls_nothing():
    llm = _FakeLLM(answer=_json_answer(standard_no="X"))

    result = await am.auto_tag("", "", llm=llm)

    assert result.fields == {}
    assert llm.prompts == [], "nothing to read means nothing to ask"


def test_a_broken_answer_shape_is_ignored():
    assert am.parse_llm_fields("") == {}
    assert am.parse_llm_fields("not json at all") == {}
    assert am.parse_llm_fields([1, 2, 3]) == {}
    assert am.parse_llm_fields({"standard_no": None, "year": "  "}) == {}
    assert am.parse_llm_fields({"standard_no": "无", "year": "2026"}) == {"year": "2026"}


def test_values_are_normalized_to_one_line():
    fields = am.parse_llm_fields({"standard_no": " q/gdw 13237 - 2017 ", "cable_type": "架空\n绝缘导线"})

    assert fields["standard_no"] == "Q/GDW 13237-2017"
    assert fields["cable_type"] == "架空 绝缘导线"


# ---------------------------------------------------------------------------
# Reading the document head out of parsed chunks
# ---------------------------------------------------------------------------


def test_the_document_head_is_reassembled_from_chunks_in_reading_order():
    chunks = [{"content_with_weight": "A" * 100}, {"content_with_weight": "B" * 100}]

    assert am.document_text(chunks, limit=150) == "A" * 100 + "\n" + "B" * 50


def test_the_document_head_skips_chunks_without_a_body():
    chunks = [{"content_with_weight": ""}, {"text": "正文"}, {"content_with_weight": "尾"}]

    assert am.document_text(chunks, limit=100) == "正文\n尾"


def test_the_document_head_of_nothing_is_empty():
    assert am.document_text([], limit=100) == ""
    assert am.document_text(None, limit=100) == ""
