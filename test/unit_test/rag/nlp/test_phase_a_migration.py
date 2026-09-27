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
"""The migration converges, and it converges from any state a corpus can be in.

Function-level idempotence (`project(project(raw)) == project(raw)`) is not enough: the
section walk is STATEFUL - the heading in force is carried from chunk to chunk in reading
order - so a migration can be idempotent on one passage and drift on the next. These tests
therefore run the real storage lifecycle over a whole document sequence:

    S0 (raw | legacy+raw | current+raw) -> S1 -> S2 -> S3,  S1 == S2 == S3

comparing exactly what the doc store holds: `content_with_weight`, `content_ltks`,
`content_sm_ltks`. `S1 == S2` is the idempotence the canary needed; `S1 == S3` says a third
run is also a no-op.
"""

import pytest

from rag.nlp import retrieval_projection as rp
from rag.nlp.doc_context import document_sections

pytestmark = pytest.mark.p1

PART2 = "220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范.pdf"
LEGACY = "[标准号: Q/GDW 73286.2-2026 | 文档: 220kV海底电力电缆系统采购标准+第2部分：220kV单芯] "
CURRENT = "[标准号: Q/GDW 73286.2-2026 | 文档: 220kV海底电力电缆系统采购标准+第2部分：220kV单芯 | 电压: 220kV | 芯数: 单芯] "

#: A document as a sequence: a heading, prose that belongs to it, a second heading, a table.
DOCUMENT = [
    "5.3.3 绝缘标称厚度",
    "绝缘标称厚度应不小于3.4mm，任一点最小厚度不小于标称厚度的90%。",
    "6.2.2 例行试验",
    "交流电压试验按表6规定进行。",
    "<table><caption>表6 试验电压</caption><tr><th>项目</th><th>要求</th></tr><tr><td>交流耐压</td><td>18kV/12kV 1min</td></tr></table>",
]


def _metadata():
    return rp.resolve_metadata(
        [rp.MetadataCandidate("document_standard_no", "QGDW73286.2-2026", rp.SOURCE_FILE_NAME, 0.9), rp.MetadataCandidate("core_count", "单芯", rp.SOURCE_FILE_NAME, 0.9)],
        document_id="doc-2",
        title=PART2,
        category="power_cable",
    )


def _initial(head: str, bodies) -> list[dict]:
    prefix = {"raw": "", "legacy": LEGACY, "current": CURRENT}[head]
    return [{"content_with_weight": prefix + body} for body in bodies]


def _migrate(rows, metadata) -> list[dict]:
    """One migration pass over the whole sequence, exactly as storage would do it."""
    raw_bodies = [rp.split_retrieval_header(row["content_with_weight"])[1] for row in rows]
    sections = document_sections(raw_bodies)
    out = []
    for row, section in zip(rows, sections):
        _header, text = rp.project_chunk(row["content_with_weight"], metadata, section)
        tokens = rp.token_fields(text)
        out.append(
            {
                "content_with_weight": text,
                "content_ltks": tokens.get("content_ltks", ""),
                "content_sm_ltks": tokens.get("content_sm_ltks", ""),
            }
        )
    return out


@pytest.mark.parametrize("head", ["raw", "legacy", "current"])
def test_three_migration_rounds_are_a_no_op_after_the_first(head):
    metadata = _metadata()
    state = _initial(head, DOCUMENT)

    s1 = _migrate(state, metadata)
    s2 = _migrate(s1, metadata)
    s3 = _migrate(s2, metadata)

    assert s1 == s2, "the second run must change nothing"
    assert s2 == s3, "the third run must change nothing"
    assert all(row["content_with_weight"].count("[") == 1 for row in s1), "one header, never stacked"
    assert all(row["content_ltks"] for row in s1), "the lexical fields were rebuilt"


def test_every_initial_state_converges_to_the_same_stored_representation():
    """A legacy header and a current header both collapse to the same state."""
    metadata = _metadata()

    from_raw = _migrate(_initial("raw", DOCUMENT), metadata)
    from_legacy = _migrate(_initial("legacy", DOCUMENT), metadata)
    from_current = _migrate(_initial("current", DOCUMENT), metadata)

    assert from_raw == from_legacy
    assert from_legacy == from_current


def test_the_section_of_a_passage_comes_from_its_own_heading():
    """Not from the previous chunk's state: the table after 6.2.2 must say 6.2.2."""
    metadata = _metadata()
    migrated = _migrate(_initial("legacy", DOCUMENT), metadata)

    headers = [rp.split_retrieval_header(row["content_with_weight"])[0] for row in migrated]

    assert "章节: 5.3.3 绝缘标称厚度" in headers[0]
    assert "章节: 5.3.3 绝缘标称厚度" in headers[1], "prose inherits the heading above it"
    assert "章节: 6.2.2 例行试验" in headers[3]
    assert "章节: 6.2.2 例行试验" in headers[4], "the table belongs to the clause that introduced it"
    assert "章节: 表6 试验电压" not in headers[4], "the caption is the table's own name, not the section"


def test_the_raw_body_is_never_touched_by_a_pass():
    metadata = _metadata()
    state = _initial("legacy", DOCUMENT)

    migrated = _migrate(state, metadata)

    for row, original in zip(migrated, DOCUMENT):
        _header, raw = rp.split_retrieval_header(row["content_with_weight"])
        assert raw == original
