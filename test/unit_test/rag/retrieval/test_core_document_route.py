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
"""The document-scoped route: search the standard itself for the buried clause.

The last measured gap, after the cut-stage work: a three-parameter question
(标称厚度 / 绝缘电阻 / 交流电压试验) recalled two passages from 《Q/GDW 73237.1
通用技术规范》 and seven from an auxiliary working document, and the standard's
6.2.2 clause (绝缘电阻 ≥1500/1000 MΩ·km) - which Test 2 found easily when the
question NAMED the standard - never entered the pool at all.

A cut can only rebalance what was recalled, so the fix has to be a retrieval: once
the pool shows the standard losing its own question, the pipeline runs one more
pass scoped to that document's ``doc_ids``, with the atomic sub-queries first
because they are what find an individual clause. An ordinary turn pays nothing -
the pass needs an identifiable standard, a multi-parameter or rule-shaped
question, and a non-core document that out-recalled the standard.
"""

import logging

import pytest

from rag.retrieval import decomposition, pipeline

pytestmark = pytest.mark.p1

_STANDARD_DOC = "doc-73237-1"
_AUXILIARY_DOC = "doc-20-inspection"
_QUESTION = "普通绝缘的标称厚度、绝缘电阻和交流电压试验要求分别是多少？"

#: What a general (unscoped) search returns: the auxiliary document floods the
#: window and the standard contributes two of its clauses - but not 6.2.2.
_UNSCOPED = {
    "standard": [
        ("std-thickness", "5.3.3 绝缘标称厚度应不小于 3.4mm", 0.59),
        ("std-voltage", "6.2.3 例行交流电压试验 18kV/12kV 1min", 0.585),
    ],
    "auxiliary": [(f"aux-{i}", f"抽检工作规定 第{i}条 例行试验", 0.63 - i * 0.005) for i in range(7)],
}

#: What a search scoped to the standard returns - the clause the question needs.
_SCOPED = {
    "厚度是多少": [("std-thickness", "5.3.3 绝缘标称厚度应不小于 3.4mm", 0.68)],
    "绝缘电阻是多少": [("std-resistance", "6.2.2 绝缘电阻应不小于 1500/1000 MΩ·km", 0.67)],
    "交流电压试验要求是什么": [("std-voltage", "6.2.3 例行交流电压试验 18kV/12kV 1min", 0.66)],
}

_SUB_QUERIES = ["厚度是多少", "绝缘电阻是多少", "交流电压试验要求是什么"]


def _chunk(chunk_id, doc_id, content, score):
    return {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "docnm_kwd": "Q_GDW_73237.1-2026_通用技术规范.pdf" if doc_id == _STANDARD_DOC else "20_架空绝缘导线抽检工作规范.pdf",
        "doc_type_kwd": "text",
        "content_with_weight": content,
        "similarity": score,
    }


class _Store:
    """A doc store whose scoped and unscoped answers differ, as the live one did."""

    def __init__(self, scoped=_SCOPED):
        self.scoped = scoped
        self.calls = []

    async def retrieval(self, question, embd_mdl, tenant_ids, kb_ids, page, page_size, threshold, **kwargs):
        doc_ids = kwargs.get("doc_ids")
        self.calls.append({"question": question, "doc_ids": list(doc_ids) if doc_ids else None, "page_size": page_size})
        if doc_ids:
            rows = self.scoped.get(question, [])
            chunks = [_chunk(cid, _STANDARD_DOC, text, score) for cid, text, score in rows]
        else:
            chunks = [_chunk(cid, _STANDARD_DOC, text, score) for cid, text, score in _UNSCOPED["standard"]]
            chunks += [_chunk(cid, _AUXILIARY_DOC, text, score) for cid, text, score in _UNSCOPED["auxiliary"]]
        return {"total": len(chunks), "chunks": chunks[:page_size], "doc_aggs": []}

    @staticmethod
    def retrieval_by_children(chunks, _tenant_ids):
        return chunks


def _scoped_calls(store):
    return [call for call in store.calls if call["doc_ids"]]


@pytest.fixture
def decomposition_node(monkeypatch):
    async def _gen_json(*_args, **_kwargs):
        return {"sub_queries": list(_SUB_QUERIES)}

    monkeypatch.setattr(decomposition, "gen_json", _gen_json)


async def _run(store, question=_QUESTION, **kwargs):
    return await pipeline.retrieve_multi_route(
        retriever=store,
        question=question,
        chat_mdl=object(),
        embd_mdl=object(),
        tenant_ids=["t-1"],
        kb_ids=["kb-1"],
        similarity_threshold=0.55,
        final_top_n=12,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# The reported gap
# ---------------------------------------------------------------------------


async def test_the_buried_clause_is_retrieved_from_the_standard_itself(decomposition_node):
    store = _Store()

    result = await _run(store)

    kept = [chunk["chunk_id"] for chunk in result["chunks"]]
    assert "std-resistance" in kept, "6.2.2 is the clause the pool never held"
    assert "std-thickness" in kept and "std-voltage" in kept


async def test_the_follow_up_searches_the_standard_scoped_to_its_doc_id(decomposition_node):
    store = _Store()

    await _run(store)

    scoped = _scoped_calls(store)
    unscoped = [call for call in store.calls if not call["doc_ids"]]
    assert scoped, "the standard was out-numbered, so it must be searched directly"
    assert {call["doc_ids"][0] for call in scoped} == {_STANDARD_DOC}
    assert [call["question"] for call in scoped] == _SUB_QUERIES, "the atomic dimensions come first"
    # The same per-route window the first pass used. The claim is "the deep pass does not
    # narrow it", not a number: the query router widens the window for a question shape
    # that leans on exact tokens (this one does), so the caller's own window is the only
    # value the follow-up has to agree with.
    assert unscoped
    assert {call["page_size"] for call in scoped} == {call["page_size"] for call in unscoped}, "the deep pass uses the same per-route window"


async def test_the_follow_up_is_capped_and_logged(decomposition_node, caplog):
    store = _Store()

    with caplog.at_level(logging.INFO):
        await _run(store)

    assert len(_scoped_calls(store)) <= pipeline.MAX_CORE_DOCUMENT_ROUTES
    assert "searching the standard's own prose" in caplog.text
    assert "document-scoped follow-up" in caplog.text


async def test_the_merged_pool_keeps_its_route_provenance(decomposition_node):
    """The follow-up ADDS to the pool; every passage still names what found it."""
    store = _Store()

    result = await _run(store)

    assert all(chunk.get("retrieval_routes") for chunk in result["chunks"]), "provenance survives the second pass"
    scoped_ids = {chunk["chunk_id"] for chunk in result["chunks"] if chunk.get("core_scoped")}
    assert "std-resistance" in scoped_ids, "the clause that only the scoped pass found is marked"


# ---------------------------------------------------------------------------
# When it must not fire
# ---------------------------------------------------------------------------


async def test_no_follow_up_when_the_standard_leads_its_question(decomposition_node):
    class _StandardLeads(_Store):
        async def retrieval(self, question, *args, **kwargs):
            if kwargs.get("doc_ids"):
                return await super().retrieval(question, *args, **kwargs)
            self.calls.append({"question": question, "doc_ids": None, "page_size": args[4]})
            chunks = [_chunk(cid, _STANDARD_DOC, text, score) for cid, text, score in _UNSCOPED["standard"]]
            chunks += [_chunk("aux-0", _AUXILIARY_DOC, "抽检工作规定 第0条", 0.40)]
            return {"total": len(chunks), "chunks": chunks, "doc_aggs": []}

    store = _StandardLeads()

    await _run(store)

    assert _scoped_calls(store) == [], "two standard passages beat one auxiliary passage: nothing is missing"


async def test_no_follow_up_for_a_value_question(monkeypatch):
    """A parameter question has no buried clause to go looking for."""
    store = _Store()
    monkeypatch.setattr(decomposition, "gen_json", lambda *_a, **_k: None)

    await _run(store, question="绝缘标称厚度是多少")

    assert _scoped_calls(store) == []


async def test_no_follow_up_when_no_standard_is_identifiable():
    class _NoStandard(_Store):
        async def retrieval(self, question, *args, **kwargs):
            self.calls.append({"question": question, "doc_ids": kwargs.get("doc_ids"), "page_size": args[4]})
            rows = _UNSCOPED["auxiliary"] + [(f"manual-{i}", "供应商数据表", 0.5) for i in range(3)]
            chunks = [_chunk(cid, "doc-supplier", text, score) for cid, text, score in rows]
            return {"total": len(chunks), "chunks": chunks, "doc_aggs": []}

    store = _NoStandard()

    await _run(store)

    assert _scoped_calls(store) == []


async def test_no_follow_up_without_a_doc_store_id(decomposition_node, caplog):
    """A file name is not a doc id: a scoped search on one would hide the standard."""

    class _NoDocId(_Store):
        async def retrieval(self, question, *args, **kwargs):
            result = await super().retrieval(question, *args, **kwargs)
            if not kwargs.get("doc_ids"):
                for chunk in result["chunks"]:
                    chunk.pop("doc_id", None)
            return result

    store = _NoDocId()

    with caplog.at_level(logging.INFO):
        await _run(store)

    assert _scoped_calls(store) == []
    assert "has no doc id" in caplog.text


async def test_a_question_that_names_the_standard_still_scopes_when_needed(decomposition_node):
    """Naming the standard is a hint for resolving it, not a reason to skip the pass."""
    store = _Store()

    await _run(store, question="Q/GDW 73237.1 的标称厚度、绝缘电阻和交流电压试验要求分别是多少？")

    assert _scoped_calls(store), "the pool still shows the auxiliary document out-recalling the standard"


# ---------------------------------------------------------------------------
# The trigger must count PROSE, not passages
# ---------------------------------------------------------------------------

_PART_1 = "doc-73237-1-general"
_PART_2 = "doc-73237-2-specific"
_PART_1_NAME = "Q_GDW_73237.1-2026_第1部分：通用技术规范.pdf"
_PART_2_NAME = "Q_GDW_73237.2-2026_第2部分：专用技术规范.pdf"

#: The live pool that exposed the table-blind count: the clauses' document has
#: two passages, the TABLES' document has four, and the auxiliary file three.
#: Adding the two parts (6) made the standard look ahead of the auxiliary (3).
_TABLE_PADDED_POOL = [
    ("p1-a", _PART_1, _PART_1_NAME, "text", 0.59),
    ("p1-b", _PART_1, _PART_1_NAME, "text", 0.585),
    ("p2-a", _PART_2, _PART_2_NAME, "table", 0.63),
    ("p2-b", _PART_2, _PART_2_NAME, "table", 0.625),
    ("p2-c", _PART_2, _PART_2_NAME, "table", 0.62),
    ("p2-d", _PART_2, _PART_2_NAME, "table", 0.615),
    ("aux-a", _AUXILIARY_DOC, "20_架空绝缘导线抽检工作规范.pdf", "text", 0.60),
    ("aux-b", _AUXILIARY_DOC, "20_架空绝缘导线抽检工作规范.pdf", "text", 0.598),
    ("aux-c", _AUXILIARY_DOC, "20_架空绝缘导线抽检工作规范.pdf", "text", 0.596),
]


class _TablePaddedStore:
    """Unscoped: the measured pool. Scoped: the clause the question needs."""

    def __init__(self):
        self.calls = []

    async def retrieval(self, question, embd_mdl, tenant_ids, kb_ids, page, page_size, threshold, **kwargs):
        doc_ids = kwargs.get("doc_ids")
        self.calls.append({"question": question, "doc_ids": list(doc_ids) if doc_ids else None})
        if doc_ids:
            rows = [(cid, text, score) for cid, text, score in _SCOPED.get(question, [])]
            rows.append(("p1-resistance", "6.2.2 绝缘电阻应不小于 1500/1000 MΩ·km", 0.69))
            chunks = [
                {
                    "chunk_id": cid,
                    "doc_id": _PART_1,
                    "docnm_kwd": _PART_1_NAME,
                    "doc_type_kwd": "text",
                    "content_with_weight": text,
                    "similarity": score,
                }
                for cid, text, score in rows
            ]
        else:
            chunks = [
                {
                    "chunk_id": cid,
                    "doc_id": doc_id,
                    "docnm_kwd": name,
                    "doc_type_kwd": kind,
                    "content_with_weight": f"{cid} 绝缘标称厚度 绝缘电阻 交流电压试验 例行试验",
                    "similarity": score,
                }
                for cid, doc_id, name, kind, score in _TABLE_PADDED_POOL
            ]
        return {"total": len(chunks), "chunks": chunks[:page_size], "doc_aggs": []}

    @staticmethod
    def retrieval_by_children(chunks, _tenant_ids):
        return chunks


async def test_table_passages_do_not_pad_the_standard_out_of_a_follow_up(decomposition_node):
    """The reported miss: 2 clauses + 4 tables looked like 6 clauses."""
    store = _TablePaddedStore()

    result = await _run(store)

    scoped = _scoped_calls(store)
    assert scoped, "the clauses' document held two passages, whatever the table part held"
    assert {doc_id for call in scoped for doc_id in call["doc_ids"]} == {_PART_1}, "and the TABLE part is not searched for a clause"
    assert "p1-resistance" in [chunk["chunk_id"] for chunk in result["chunks"]]
    assert "p1-b" in [chunk["chunk_id"] for chunk in result["chunks"]]


async def test_a_thin_clause_tier_triggers_even_when_no_auxiliary_file_shouts(decomposition_node):
    """(B): a clause question seeing two standard passages fires on its own."""
    pool = [
        {"chunk_id": "p1-a", "doc_id": _PART_1, "docnm_kwd": _PART_1_NAME, "doc_type_kwd": "text", "content_with_weight": "5.3.3 绝缘标称厚度", "similarity": 0.59},
        {"chunk_id": "p1-b", "doc_id": _PART_1, "docnm_kwd": _PART_1_NAME, "doc_type_kwd": "text", "content_with_weight": "6.2.3 交流电压试验", "similarity": 0.585},
        {"chunk_id": "aux-a", "doc_id": _AUXILIARY_DOC, "docnm_kwd": "20_抽检工作规范.pdf", "doc_type_kwd": "text", "content_with_weight": "抽检", "similarity": 0.51},
    ]

    class _ThinProse(_Store):
        async def retrieval(self, question, *args, **kwargs):
            self.calls.append({"question": question, "doc_ids": list(kwargs["doc_ids"]) if kwargs.get("doc_ids") else None, "page_size": args[4]})
            if kwargs.get("doc_ids"):
                chunks = [_chunk("p1-resistance", _PART_1, "6.2.2 绝缘电阻应不小于 1500/1000 MΩ·km", 0.69)]
            else:
                chunks = [dict(chunk) for chunk in pool]
            return {"total": len(chunks), "chunks": chunks, "doc_aggs": []}

    store = _ThinProse()

    result = await _run(store, question="例行交流电压试验的维持时间和绝缘电阻是怎么规定的？")

    assert _scoped_calls(store), "two standard passages for a clause question is the symptom"
    assert "p1-resistance" in [chunk["chunk_id"] for chunk in result["chunks"]]


async def test_a_thick_clause_tier_is_left_alone(decomposition_node, caplog):
    """Eleven standard passages for a clause question: nothing says one is missing."""
    pool = [
        {"chunk_id": f"p1-{i}", "doc_id": _PART_1, "docnm_kwd": _PART_1_NAME, "doc_type_kwd": "text", "content_with_weight": f"6.2.{i} 例行交流电压试验规定", "similarity": 0.70 - i * 0.001}
        for i in range(11)
    ]

    class _ThickProse(_Store):
        async def retrieval(self, question, *args, **kwargs):
            self.calls.append({"question": question, "doc_ids": list(kwargs["doc_ids"]) if kwargs.get("doc_ids") else None, "page_size": args[4]})
            return {"total": len(pool), "chunks": pool, "doc_aggs": []}

    store = _ThickProse()

    with caplog.at_level(logging.INFO):
        await _run(store, question="例行交流电压试验的维持时间是怎么规定的？")

    assert _scoped_calls(store) == []
    assert "no document-scoped route needed" in caplog.text, "and the skip is visible instead of silent"


# ---------------------------------------------------------------------------
# The merge primitive the follow-up uses
# ---------------------------------------------------------------------------


def test_merging_adds_to_a_pool_without_resetting_provenance():
    from rag.retrieval.multi_route import RouteResult, merge_route_hits

    first = merge_route_hits([RouteResult(query="q1", chunks=[_chunk("c1", _STANDARD_DOC, "text", 0.5)])])
    assert first["chunks"][0]["retrieval_routes"] == ["q1"]

    second = merge_route_hits(
        [RouteResult(query="q2", chunks=[_chunk("c1", _STANDARD_DOC, "text", 0.6), _chunk("c2", _STANDARD_DOC, "text", 0.4)])],
        existing=first,
    )

    by_id = {chunk["chunk_id"]: chunk for chunk in second["chunks"]}
    assert by_id["c1"]["retrieval_routes"] == ["q1", "q2"], "the first pass keeps credit"
    assert by_id["c1"]["similarity"] == pytest.approx(0.6), "and takes the better score"
    assert by_id["c1"]["route_hits"] == 2
    assert by_id["c2"]["retrieval_routes"] == ["q2"]
