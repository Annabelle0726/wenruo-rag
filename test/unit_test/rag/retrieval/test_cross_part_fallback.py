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
"""Falling back from a standard's specialized part to its generic part.

The reported trap, with the live corpus's own numbers: 《Q/GDW 73286.2 第2部分：220kV
单芯…专用技术规范》 is 54 chunks, 40 of them tables, and its 表1/表2 are BIDDER
FILL-IN templates - the value cells are empty - while the mandatory baseline
(内衬层厚度 ≥1.5mm, 外被层厚度 ≥4.0mm, 偏心度 ≤6%, 出厂交流耐压 2.5U0/30min) is stated in
《Q/GDW 73286.1 第1部分：通用技术规范》, a different document of the same standard. A
question about a requirement therefore has to be able to reach Part 1 from a pool that
only found Part 2, and the DESIGNATION is what names it: the ingest writes
``[标准号: Q/GDW 73286.1-2026 | 文档: …第1部分：通用技术规范…]`` into that part's 27
prefixed chunks, so a route naming the sibling matches them by full text as well as by
vector.

Everything below is derived from the corpus (name + designation + prefix), never from a
hardcoded table of standard numbers: this platform holds 国网, GB/T and DL/T families,
and the next one it is given will have a different numbering.
"""

import pytest

from rag.retrieval import chunk_profile, pipeline
from rag.retrieval.chunk_profile import name_family

pytestmark = pytest.mark.p1

PART2_NAME = "220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范.pdf"
PART1_NAME = "220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf"
PART2_DOC = "doc-73286-2"
PART1_DOC = "doc-73286-1"

REQUIREMENT_QUESTION = "内衬层厚度和外被层厚度分别应不小于多少？"
VALUE_QUESTION = "800 mm² 的金属套平均厚度是多少？"


def _chunk(chunk_id, doc_id, name, content, score, doc_type="table"):
    return {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "docnm_kwd": name,
        "doc_type_kwd": doc_type,
        "content_with_weight": content,
        "similarity": score,
    }


#: A 专用技术规范 table the way the live one is stored: caption, header, dashes, and
#: empty value cells after each parameter.
TEMPLATE_TABLE = """<table><caption>表1 技术参数特性表</caption>
<tr><th>序号</th><th>项目</th><th>单位</th><th>标准参数值</th><th>备注</th></tr>
<tr><td>1</td><td>内衬层厚度</td><td>mm</td><td></td><td></td></tr>
<tr><td>2</td><td>外被层厚度</td><td>mm</td><td></td><td></td></tr>
<tr><td>3</td><td>偏心度</td><td>%</td><td></td><td></td></tr>
</table>"""

SPECIALIZED_PREFIX = "[标准号: Q/GDW 73286.2-2026 | 文档: 220kV海底电力电缆系统采购标准+第2部分：220kV单芯]"
GENERIC_PREFIX = "[标准号: Q/GDW 73286.1-2026 | 文档: 220kV海底电力电缆系统采购标准+第1部分：通用技术规范]"

KEPT = "5.3.4 内衬层厚度应不小于1.5mm，外被层厚度应不小于4.0mm，偏心度应不大于6%。"


def _pool(part1_prose=False, part1_tables=False, template=True):
    pool = [
        _chunk("p2-table-1", PART2_DOC, PART2_NAME, f"{SPECIALIZED_PREFIX} {TEMPLATE_TABLE}" if template else f"{SPECIALIZED_PREFIX} 5.1 电缆应符合本规范要求。", 0.66, doc_type="table"),
        _chunk("p2-table-2", PART2_DOC, PART2_NAME, f"{SPECIALIZED_PREFIX} <table><caption>表2 电气参数表</caption><tr><th>项目</th><th>标准参数值</th></tr><tr><td>出厂交流耐压</td><td></td></tr></table>", 0.64),
        _chunk("aux-1", "doc-inspection", "20_架空绝缘导线抽检工作规范.pdf", "抽检工作规定 第3条 例行试验要求。", 0.63, doc_type="text"),
    ]
    if part1_prose:
        pool.append(_chunk("p1-clause", PART1_DOC, PART1_NAME, f"{GENERIC_PREFIX} {KEPT}", 0.55, doc_type="text"))
    if part1_tables:
        # Part 1 IS in the pool, but only with tables: the pass can be scoped to it,
        # and its clauses are still missing from the window.
        pool.append(_chunk("p1-table", PART1_DOC, PART1_NAME, f"{GENERIC_PREFIX} <table><caption>表A.1 试验项目</caption><tr><th>项目</th><th>要求</th></tr><tr><td>交流耐压</td><td></td></tr></table>", 0.58))
    return pool


# ---------------------------------------------------------------------------
# The designation arithmetic
# ---------------------------------------------------------------------------


def test_the_generic_part_of_a_multi_part_designation_is_derived_from_it():
    assert chunk_profile.generic_sibling_designation("QGDW73286.2-2026") == "QGDW73286.1-2026"
    assert chunk_profile.generic_sibling_designation("QGDW73286.3-2026") == "QGDW73286.1-2026"
    # A `.1` IS the generic part: it has no sibling of its own.
    assert chunk_profile.generic_sibling_designation("QGDW13242.1") is None


def test_a_single_part_designation_has_no_sibling():
    # "GB/T 12527-2008" is one document: there is no second part to fall back to.
    assert chunk_profile.generic_sibling_designation("GBT12527-2008") is None
    assert chunk_profile.generic_sibling_designation("QGDW13237") is None


def test_a_designation_is_split_into_family_part_and_year():
    assert chunk_profile.designation_parts("QGDW73286.2-2026") == ("QGDW73286", 2, "2026")
    assert chunk_profile.designation_parts("QGDW13237") == ("QGDW13237", None, "")


def test_the_context_prefix_is_read_back_out_of_a_passage():
    chunk = _chunk("c", PART2_DOC, PART2_NAME, f"{SPECIALIZED_PREFIX} 内容", 0.5)

    assert chunk_profile.context_designation(chunk) == "QGDW73286.2-2026"
    assert chunk_profile.document_designations(chunk) == {"QGDW73286.2-2026"}


def test_the_generic_part_is_recognised_from_name_or_designation():
    pool = _pool(part1_prose=True)

    generics = chunk_profile.generic_part_documents(pool)

    assert generics["QGDW73286"][1] == PART1_NAME


# ---------------------------------------------------------------------------
# The fallback decision
# ---------------------------------------------------------------------------


def test_a_requirement_question_falls_back_to_the_generic_part():
    followup = pipeline.cross_part_fallback(_pool(), REQUIREMENT_QUESTION)

    assert followup is not None
    scope, scope_name, queries = followup
    assert scope is None, "Part 1 is not in the pool, so only a text route can reach it"
    assert "73286.1" in scope_name
    assert "73286.1" in queries[0] and "通用技术规范" in queries[0]


def test_the_fallback_scopes_to_part_one_when_the_pool_already_holds_it():
    followup = pipeline.cross_part_fallback(_pool(part1_tables=True), REQUIREMENT_QUESTION)

    assert followup is not None
    scope, scope_name, _queries = followup

    assert scope == [PART1_DOC]
    assert scope_name == PART1_NAME


def test_a_value_question_does_not_fall_back():
    """A parameter table IS the right source for a value: only rules live in Part 1."""
    assert pipeline.cross_part_fallback(_pool(), VALUE_QUESTION) is None


def test_nothing_to_fall_back_to_when_part_one_is_already_answering():
    pool = _pool(part1_prose=True)

    assert pipeline.cross_part_fallback(pool, REQUIREMENT_QUESTION) is None


def test_a_pool_without_a_specialized_part_does_not_fall_back():
    pool = [
        _chunk("p1-clause", PART1_DOC, PART1_NAME, f"{GENERIC_PREFIX} {KEPT}", 0.6, doc_type="text"),
        _chunk("aux", "doc-x", "某种工作规范.pdf", "正文。", 0.5, doc_type="text"),
    ]

    assert pipeline.cross_part_fallback(pool, REQUIREMENT_QUESTION) is None


def test_the_fallback_works_for_a_part_that_carries_no_designation_at_all():
    """Measured on the live corpus: 《…第3部分：220kV三芯…》 has no standard number in its
    name and NO ``[标准号: …]`` prefix on any of its 51 chunks, so the family has to come
    from the name the parts share."""
    part3_name = "220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用技术规范.pdf"
    pool = [
        _chunk("p3-table-1", "doc-73286-3", part3_name, f"{TEMPLATE_TABLE}", 0.67),
        _chunk("p3-table-2", "doc-73286-3", part3_name, "<table><caption>表5 GIS终端参数表</caption><tr><td></td></tr></table>", 0.65),
        _chunk("aux-1", "doc-inspection", "20_架空绝缘导线抽检工作规范.pdf", "抽检工作规定 第3条 例行试验要求。", 0.63, doc_type="text"),
    ]

    followup = pipeline.cross_part_fallback(pool, REQUIREMENT_QUESTION)

    assert followup is not None
    _scope, scope_name, queries = followup
    assert "第1部分" in queries[0] and "通用技术规范" in queries[0]
    assert name_family(part3_name) in scope_name
    # The three-core part and the single-core part are the SAME standard: one family.
    assert chunk_profile.document_family(pool[0]) == name_family(part3_name)


# ---------------------------------------------------------------------------
# The retrieval it triggers
# ---------------------------------------------------------------------------


class _Store:
    """The live shape: Part 2's template is what a general search returns, and the
    requirement only answers to a search that NAMES the generic part."""

    def __init__(self):
        self.calls = []

    async def retrieval(self, question, embd_mdl, tenant_ids, kb_ids, page, page_size, threshold, **kwargs):
        self.calls.append({"question": question, "doc_ids": kwargs.get("doc_ids")})
        if "73286.1" in question or kwargs.get("doc_ids") == [PART1_DOC]:
            chunks = [_chunk("p1-clause", PART1_DOC, PART1_NAME, f"{GENERIC_PREFIX} {KEPT}", 0.7, doc_type="text")]
        else:
            chunks = list(_pool())
        return {"total": len(chunks), "chunks": chunks[:page_size], "doc_aggs": []}

    @staticmethod
    def retrieval_by_children(chunks, _tenant_ids):
        return chunks


async def test_the_requirement_reaches_the_pool_and_is_reported_to_the_answer_layer():
    store = _Store()

    infos = await pipeline.retrieve_multi_route(
        retriever=store,
        question=REQUIREMENT_QUESTION,
        chat_mdl=None,
        embd_mdl=object(),
        tenant_ids=["t-1"],
        kb_ids=["kb-1"],
        similarity_threshold=0.2,
        final_top_n=8,
    )

    ids = {chunk["chunk_id"] for chunk in infos["chunks"]}
    assert "p1-clause" in ids, ids
    # The answer layer is told where the figure came from, so it can say so instead of
    # presenting a Part 1 figure as if it were Part 2's own table value.
    assert infos["generic_fallback"]["scope"]
    assert PART1_NAME in infos["generic_fallback"]["documents"]
    assert any("73286.1" in call["question"] for call in store.calls), store.calls


async def test_an_ordinary_question_pays_no_extra_retrieval():
    store = _Store()

    infos = await pipeline.retrieve_multi_route(
        retriever=store,
        question=VALUE_QUESTION,
        chat_mdl=None,
        embd_mdl=object(),
        tenant_ids=["t-1"],
        kb_ids=["kb-1"],
        similarity_threshold=0.2,
        final_top_n=8,
    )

    assert "generic_fallback" not in infos
    assert not any("73286.1" in call["question"] for call in store.calls)
