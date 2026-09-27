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
"""Retrieval metadata: candidates, canonical facts, profiles and the header they project.

The contract, in the order the module implements it:

* candidates carry a SOURCE and a confidence, and the losers are kept, so a wrong field
  can be explained (this exists because four defects in the last round were all
  "a value with no provenance": a cited standard posing as the document's own number, a
  year borrowed across documents, a three-core part read as single-core, a body count
  outranking a file name);
* ``document_standard_no`` and ``referenced_standard_nos`` never merge;
* a profile - not the renderer - names the fields, so a new domain is a new profile;
* the retrieval header is a PROJECTION, ``retrieval_text = header + raw_chunk``, and
  applying it twice cannot stack;
* a document whose domain is unknown still gets its identity and no invented attribute.

Three of the cases below (the OPGW profile, the fresh profile, the unknown category)
are the extensibility proof the report asked for: they add a domain to a data table and
render it without touching a line of the renderer.
"""

import pytest

from rag.nlp import auto_metadata as am
from rag.nlp import retrieval_projection as rp

pytestmark = pytest.mark.p1

PART2_NAME = "220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范.pdf"
PART3_NAME = "220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用技术规范.pdf"
PART1_NAME = "220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf"
INSPECTION_NAME = "20_架空绝缘导线抽检工作规范.pdf"


def _metadata(filename, text, **kwargs):
    """The whole pipeline for one document: candidates -> canonical -> header."""
    candidates = am.metadata_candidates(filename, text, **kwargs)
    category = rp.classify_category(filename, text)
    return rp.resolve_metadata(candidates, document_id="doc-1", title=filename, category=category)


# ---------------------------------------------------------------------------
# 1-4. The values themselves, with the rules the last round established
# ---------------------------------------------------------------------------


def test_the_two_core_parts_of_one_standard_keep_their_own_core_count():
    """Q/GDW 73286.2 -> 单芯, Q/GDW 73286.3 -> 三芯, both at 220kV."""
    single = _metadata(PART2_NAME, "表1 电缆结构技术参数表\n标称截面 mm2\n1×400\n1×800\nQ/GDW 73286.2-2026\n")
    three = _metadata(PART3_NAME, "表1（续）\n3×400\n3×800\n3×1200\nQ/GDW 73286.3\n")

    assert single.attributes["core_count"] == "单芯"
    assert three.attributes["core_count"] == "三芯"
    assert single.attributes["voltage_level"] == "220kV"
    assert three.attributes["voltage_level"] == "220kV"
    assert single.attributes["cable_environment"] == "海底"


def test_the_general_part_is_not_given_a_core_count():
    """《第1部分：通用技术规范》 lists every section of every core count."""
    general = _metadata(PART1_NAME, "表1 结构参数表\n1×400\n1×800\n3×400\n3×800\n1×1200\n3×1200\n")

    assert "core_count" not in general.attributes
    assert general.attributes["voltage_level"] == "220kV"


def test_a_fullwidth_slash_keeps_a_compound_rating_whole():
    fields = am.extract_by_regex("450／750V聚氯乙烯绝缘电缆采购标准+第2部分：专用技术规范.pdf", "")
    metadata = _metadata("450／750V聚氯乙烯绝缘电缆采购标准+第2部分：专用技术规范.pdf", "")

    assert fields["voltage_level"] == "450／750V"
    assert metadata.attributes["voltage_level"] == "450／750V"


# ---------------------------------------------------------------------------
# 5-6. Identity vs citation
# ---------------------------------------------------------------------------


def test_a_cited_standard_never_becomes_the_document_identity():
    """The 抽检工作规范 cites three standards and owns none of them in its name."""
    body = "本规范依据 Q/GDW 13237 编制，并引用 GB/T 14049 与 GB/T 12527 的规定。\n" + "GB/T 14049 适用于架空绝缘电缆。" * 4
    metadata = _metadata(INSPECTION_NAME, body)

    assert metadata.document_standard_no is None, "no identity in the name and none on the cover"
    assert set(metadata.referenced_standard_nos) >= {"QGDW13237", "GBT14049", "GBT12527"}


def test_a_cover_page_identity_that_repeats_is_believed():
    """A standard prints its own number on the cover and then throughout."""
    body = "Q/GDW 73289.2-2026\n额定电压450/750V及以下聚氯乙烯绝缘电缆\n" + "Q/GDW 73289.2-2026 " * 3
    metadata = _metadata("450／750V聚氯乙烯绝缘电缆采购标准+第2部分：专用技术规范.pdf", body)

    identity = [candidate for candidate in metadata.evidence if candidate.key == "document_standard_no"]
    assert metadata.document_standard_no in {"QGDW73289.2-2026", "QGDW73289"}
    assert identity, "the winning candidate has to be in the evidence"
    assert identity[0].source in {rp.SOURCE_TITLE_PAGE, rp.SOURCE_FILE_NAME}


def test_a_non_standard_document_is_left_without_a_standard_number():
    """A 规格书 applies a standard; the number it repeats is not its identity."""
    metadata = _metadata("低烟无卤阻燃电力电缆规格书.pdf", "本产品符合 GB/T 12706.1 的规定。GB/T 12706.1 " * 2)

    assert metadata.document_standard_no is None
    assert "GBT12706.1" in metadata.referenced_standard_nos


def test_the_standardisation_directive_is_never_an_identity():
    metadata = _metadata("某种电缆技术条件.pdf", "本标准按照 GB/T 1.1-2020 给出的规则起草。GB/T 1.1-2020 " * 2)

    assert metadata.document_standard_no is None
    assert "GBT1.1" not in metadata.referenced_standard_nos


def test_a_family_inference_never_outranks_what_the_document_says():
    """It is the last resort: allowed, lowest, and never a substitute for evidence."""
    named = "Q_GDW 73286.2-2026 220kV海底电力电缆系统采购标准+第2部分：单芯专用技术规范.pdf"
    candidates = am.metadata_candidates(named, "")
    candidates.append(am.family_candidate("QGDW00000", family="QGDW00000", part=2, year="2026"))
    metadata = rp.resolve_metadata(candidates, category="power_cable")

    # The file name printed the number, so the inference loses.
    assert metadata.document_standard_no == "QGDW73286.2-2026"
    # ... and it IS used when nothing else offers a value at all.
    inferred = rp.resolve_metadata([am.family_candidate("QGDW73286", family="QGDW73286", part=3, year="2026")], category="power_cable")
    assert inferred.document_standard_no == "QGDW73286.3-2026"
    assert inferred.evidence[0].source == rp.SOURCE_FAMILY_INFERENCE


# ---------------------------------------------------------------------------
# 7-9. Profiles, the renderer, and the fallback
# ---------------------------------------------------------------------------


def test_the_renderer_omits_a_field_the_document_does_not_have():
    metadata = _metadata(PART1_NAME, "")

    header = rp.render_retrieval_header(metadata)

    assert "芯数" not in header, "a domain field the document has no value for is absent"
    assert "-" not in header, "no dashed placeholder"
    assert header.startswith("[") and header.endswith("] ")


def test_the_same_renderer_prints_different_fields_for_a_different_domain():
    cable = rp.resolve_metadata([rp.MetadataCandidate("voltage_level", "220kV", rp.SOURCE_FILE_NAME, 0.9)], title="x", category="power_cable")
    optical_profile = rp.PROFILES["optical_cable"]
    optical = rp.resolve_metadata([rp.MetadataCandidate("fiber_count", "48", rp.SOURCE_DOCUMENT_BODY, 0.7)], title="x", category="optical_cable")

    cable_header = rp.render_retrieval_header(cable)
    optical_header = rp.render_retrieval_header(optical, optical_profile)

    assert "电压: 220kV" in cable_header and "纤芯数" not in cable_header
    assert "纤芯数: 48" in optical_header and "电压" not in optical_header


def test_a_profile_added_as_data_renders_without_touching_the_renderer():
    """The extensibility claim: a NEW domain is a table entry, not a code change."""
    fresh = rp.DocumentProfile(
        category="substation",
        identity_fields=rp._COMMON_IDENTITY,
        retrieval_fields=(rp.RetrievalField("bay_count", "间隔数"),),
        cues=("变电站",),
    )
    rp.PROFILES["substation"] = fresh
    try:
        category = rp.classify_category("某500kV变电站新建工程说明书.pdf")
        metadata = rp.resolve_metadata([rp.MetadataCandidate("bay_count", "12", rp.SOURCE_DOCUMENT_BODY, 0.7)], title="某500kV变电站新建工程说明书", category=category)

        header = rp.render_retrieval_header(metadata)

        assert category == "substation"
        assert "间隔数: 12" in header
        assert "芯数" not in header
    finally:
        rp.PROFILES.pop("substation", None)


def test_an_unknown_domain_keeps_identity_and_invents_nothing():
    metadata = _metadata("dsh-attrib-2eea05.txt", "")

    header = rp.render_retrieval_header(metadata)

    assert metadata.category == "unknown"
    assert "文档:" in header
    assert "芯数" not in header and "电压" not in header


# ---------------------------------------------------------------------------
# 10-11. The header as a projection: no stacking, idempotent
# ---------------------------------------------------------------------------


def test_a_legacy_header_is_recognised_and_replaced_never_stacked():
    legacy = "[标准号: Q/GDW 73286.2-2026 | 文档: 老格式] 正文内容"
    header, body = rp.split_retrieval_header(legacy)
    current = "[标准号: Q/GDW 73286.2-2026 | 文档: x | 芯数: 单芯] 正文内容"

    assert header == "[标准号: Q/GDW 73286.2-2026 | 文档: 老格式]"
    assert body == "正文内容"
    # The identity labels are in BOTH shapes, so only a retrieval-field label can tell
    # the live legacy header from the projection this module renders.
    assert rp.declared_prefix_kind(legacy) == rp.PREFIX_LEGACY
    assert rp.declared_prefix_kind(current) == rp.PREFIX_CURRENT
    assert rp.declared_prefix_kind("正文内容") == rp.PREFIX_NONE


def test_applying_the_projection_is_idempotent():
    raw = "4.5.2 内衬层厚度应不小于1.5mm"
    metadata = rp.resolve_metadata([rp.MetadataCandidate("voltage_level", "220kV", rp.SOURCE_FILE_NAME, 0.9)], title=PART2_NAME, category="power_cable")
    header = rp.render_retrieval_header(metadata)

    once = rp.retrieval_text(raw, header)
    twice = rp.retrieval_text(once, header)
    thrice = rp.retrieval_text(twice, header)

    assert once == twice == thrice
    assert once.count("[") == 1
    assert once.endswith(raw)


def test_a_changed_projection_replaces_the_old_header():
    raw = rp.retrieval_text("正文", "[标准号: 旧 | 文档: 旧] ")
    new_header = rp.render_retrieval_header(rp.resolve_metadata([], title="新标题", category="power_cable"))

    replaced = rp.retrieval_text(raw, new_header)

    assert "旧" not in replaced
    assert replaced.startswith("[文档: 新标题] ")
    assert replaced.endswith("正文")


# ---------------------------------------------------------------------------
# 12. Conflict evidence for review
# ---------------------------------------------------------------------------


def test_a_conflict_keeps_both_sides_and_the_winner_is_the_stronger_source():
    candidates = [
        rp.MetadataCandidate("document_standard_no", "GBT12706.1", rp.SOURCE_DOCUMENT_BODY, 0.55, "cited 9 times"),
        rp.MetadataCandidate("document_standard_no", "QGDW73286.3-2026", rp.SOURCE_FILE_NAME, 0.9, "printed in the file name"),
    ]

    metadata = rp.resolve_metadata(candidates, category="power_cable")

    assert metadata.document_standard_no == "QGDW73286.3-2026"
    assert {candidate.value for candidate in metadata.evidence} == {"GBT12706.1", "QGDW73286.3-2026"}
    assert "the stronger source wins" not in str(metadata.evidence[0])  # the winner is first, by order


def test_a_low_confidence_candidate_alone_is_not_written():
    metadata = rp.resolve_metadata([rp.MetadataCandidate("voltage_level", "220kV", rp.SOURCE_DOCUMENT_BODY, 0.2)], category="power_cable")

    assert "voltage_level" not in metadata.attributes


# ---------------------------------------------------------------------------
# Document family, blank templates, embedding staleness
# ---------------------------------------------------------------------------


def test_the_family_links_a_specific_part_to_its_common_part():
    families = [
        rp.resolve_family(designation="QGDW73286.1-2026", name=PART1_NAME),
        rp.resolve_family(designation="QGDW73286.2-2026", name=PART2_NAME),
        rp.resolve_family(designation="QGDW73286.3-2026", name=PART3_NAME),
    ]

    linked = rp.link_families(families)
    by_part = {family.part_no: family for family in linked}

    assert by_part[1].document_role == rp.ROLE_COMMON_SPEC
    assert by_part[2].document_role == rp.ROLE_SPECIFIC_SPEC
    assert by_part[2].related_common_spec == by_part[1].family_id
    assert by_part[3].related_common_spec == by_part[1].family_id
    assert by_part[1].needs_common_spec is False


def test_a_specific_part_whose_common_part_is_absent_stays_unlinked():
    family = rp.resolve_family(designation="QGDW73289.2-2026", name="450／750V聚氯乙烯绝缘电缆采购标准+第2部分：专用技术规范.pdf")

    linked = rp.link_families([family])[0]

    assert linked.related_common_spec is None
    assert linked.needs_common_spec is True


def test_a_bidder_template_is_recognised_and_a_real_parameter_table_is_not():
    template = {"doc_type_kwd": "table", "content_with_weight": "<table><tr><th>项目</th><th>标准参数值</th></tr><tr><td>内衬层厚度</td><td></td></tr><tr><td>外被层厚度</td><td>项目单位填写</td></tr></table>"}
    parameter = {"doc_type_kwd": "table", "content_with_weight": "<table><tr><th>标称截面</th><th>金属套厚度</th></tr><tr><td>1×800</td><td>3.9</td></tr><tr><td>1×1200</td><td>4.1</td></tr></table>"}
    prose = {"doc_type_kwd": "text", "content_with_weight": "5.3.4 内衬层厚度应不小于1.5mm。"}

    assert rp.is_blank_response_template(template) is True
    assert rp.blank_template_evidence(template)
    assert rp.is_blank_response_template(parameter) is False
    assert rp.is_blank_response_template(prose) is False


def test_a_missing_version_means_the_embedding_is_stale():
    assert rp.embedding_is_stale(retrieval_schema_version=None, embedding_schema_version=None) is True
    assert rp.embedding_is_stale(retrieval_schema_version="x", embedding_schema_version=1) is True
    assert rp.embedding_is_stale(retrieval_schema_version=rp.RETRIEVAL_SCHEMA_VERSION - 1, embedding_schema_version=rp.EMBEDDING_SCHEMA_VERSION) is True
    assert rp.embedding_is_stale(retrieval_schema_version=rp.RETRIEVAL_SCHEMA_VERSION, embedding_schema_version=rp.EMBEDDING_SCHEMA_VERSION) is False
