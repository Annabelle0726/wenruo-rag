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
"""The cable vertical's defaults for a new dataset, chat assistant, or search app.

The values are asserted here because they are a product decision, and because
the DB models, the REST API and (in Go) the chat/dataset services all read them:
a silent drift in one of those would only show up as a wrong retrieval setting
on every newly created row.
"""

import json
import re
from pathlib import Path

from api.db import cable_defaults
from api.db.db_models import Dialog, Knowledgebase, Search

CABLE_PROMPT_OPENING = "你是一位经验丰富且亲切的线缆技术专家顾问。"

#: Rule headings of the system prompt, in the order they must appear in.
PROMPT_RULE_HEADINGS = (
    "1. 自然表达与拒答：",
    "2. 弹性与例外条款优先：",
    "3. 合理工程推理：",
    "4. 标准号归属判定：",
    "5. 证据不足时严格拒答：",
    "6. 检索片段与原文的区分：",
)

REPO_ROOT = Path(__file__).resolve().parents[4]


def _go_string_constant(source: str, name: str) -> str:
    """Joins the quoted segments of a Go `const` string concatenation."""
    lines = source.splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip().startswith(f"{name} = "))

    segments: list[str] = []
    for line in lines[start:]:
        segments.extend(re.findall(r'"((?:[^"\\]|\\.)*)"', line))
        if not line.rstrip().endswith("+"):
            break

    return "".join(json.loads(f'"{segment}"') for segment in segments)


def test_retrieval_defaults():
    # A business operator never opens the settings drawer, so these are the only
    # parameters the platform is judged by on a first search.
    assert cable_defaults.SIMILARITY_THRESHOLD == 0.55
    assert cable_defaults.VECTOR_SIMILARITY_WEIGHT == 0.50
    # The full-text leg takes the remainder of the vector weight.
    assert round(1 - cable_defaults.VECTOR_SIMILARITY_WEIGHT, 2) == 0.50
    assert cable_defaults.RERANK_CANDIDATES_COUNT == 30
    # 6 truncated real answers on a standards corpus (the retrieved passage that
    # held the answer sat at rank 7 and rank 10), so the default has to clear
    # single-document corpora rather than the smallest useful number.
    assert cable_defaults.TOP_N == 12


def test_prompt_defaults():
    assert cable_defaults.SYSTEM_PROMPT.startswith(CABLE_PROMPT_OPENING)
    assert cable_defaults.SYSTEM_PROMPT.rstrip().endswith("以上是知识库。")
    # The retrieval step fills {knowledge}, so the parameter must be declared.
    assert "{knowledge}" in cable_defaults.SYSTEM_PROMPT
    assert {"key": "knowledge", "optional": False} in cable_defaults.PROMPT_PARAMETERS
    assert cable_defaults.PROLOGUE.strip() != ""
    assert cable_defaults.EMPTY_RESPONSE.strip() != ""


def test_prompt_keeps_every_rule_in_order():
    """Adding a rule must not drop or reorder the ones already there."""
    offsets = [cable_defaults.SYSTEM_PROMPT.index(heading) for heading in PROMPT_RULE_HEADINGS]

    assert offsets == sorted(offsets)
    assert len(set(offsets)) == len(PROMPT_RULE_HEADINGS)


def test_prompt_rule_5_rejects_answers_without_evidence():
    """Rule 5 is the anti-hallucination guardrail: no entity, no number, no answer."""
    prompt = cable_defaults.SYSTEM_PROMPT

    assert "证据不足时严格拒答" in prompt
    assert "禁止给出证据中没有的数字" in prompt
    assert "禁止用训练知识补全" in prompt
    # Each sub-clause says what to answer instead of inventing one.
    assert "知识库中未包含 XXX 的信息" in prompt
    assert "另一个未在知识库中找到" in prompt
    assert "知识库中未找到该数值" in prompt
    assert "禁止给出“接近但不完全一致”的数值。" in prompt


def test_prompt_rule_6_scopes_a_gap_to_the_retrieved_passages():
    """Rule 6 stops the model from blaming the source document for a retrieval gap.

    Rule 5 already forbids inventing an answer; rule 6 covers what the model says
    instead. A live answer to 《MT/T 818.11-2009》 reported the standard's own 表3 as
    "原文残缺" when the passage simply had not been retrieved — the reader is told
    the source is defective and has no next step.
    """
    prompt = cable_defaults.SYSTEM_PROMPT

    assert "检索片段与原文的区分" in prompt
    assert "当前检索到的片段暂未包含" in prompt
    assert "不要据此判断标准原文缺失、残缺或不完整" in prompt
    # The degradation has to be actionable, not just honest.
    assert "建议补充关键词或指定条款号/表号" in prompt


def test_go_mirror_carries_the_same_prompt_byte_for_byte():
    """The Go backend hands new assistants the same prompt as the Python one."""
    go_source = (REPO_ROOT / "internal/service/cable_defaults.go").read_text(encoding="utf-8")

    assert _go_string_constant(go_source, "CableDefaultSystemPrompt") == cable_defaults.SYSTEM_PROMPT


def test_go_mirror_carries_the_same_retrieval_defaults():
    """A row must land on the same configuration whichever backend created it."""
    go_source = (REPO_ROOT / "internal/service/cable_defaults.go").read_text(encoding="utf-8")

    assert re.search(r"CableDefaultTopN\s*=\s*(\d+)", go_source).group(1) == str(cable_defaults.TOP_N)
    assert re.search(r"CableDefaultRerankCandidatesCount\s*=\s*(\d+)", go_source).group(1) == str(cable_defaults.RERANK_CANDIDATES_COUNT)


def test_prompt_config_returns_an_independent_copy():
    prompt_config = cable_defaults.prompt_config()
    prompt_config["parameters"].append({"key": "extra", "optional": True})
    prompt_config["system"] = "edited"

    assert cable_defaults.prompt_config()["parameters"] == cable_defaults.PROMPT_PARAMETERS
    assert cable_defaults.prompt_config()["system"] == cable_defaults.SYSTEM_PROMPT


def test_search_config_returns_an_independent_copy():
    search_config = cable_defaults.search_config()
    search_config["llm_setting"]["temperature"] = 0.9
    search_config["kb_ids"].append("kb-1")

    assert cable_defaults.search_config()["llm_setting"]["temperature"] == 0.1
    assert cable_defaults.search_config()["kb_ids"] == []


def test_search_config_carries_the_retrieval_defaults():
    """A search app is created by name alone, so its config is born here."""
    search_config = cable_defaults.search_config()

    assert search_config["similarity_threshold"] == cable_defaults.SIMILARITY_THRESHOLD
    assert search_config["vector_similarity_weight"] == cable_defaults.VECTOR_SIMILARITY_WEIGHT
    assert search_config["rerank_candidates_count"] == cable_defaults.RERANK_CANDIDATES_COUNT
    # A model id belongs to a tenant; the retrieval path resolves the tenant's
    # own reranker for an app that names none, so the stored default stays empty
    # instead of pinning one deployment's model into every row.
    assert search_config["rerank_id"] == ""


def test_search_config_with_defaults_keeps_what_the_app_wrote():
    stored = {"similarity_threshold": 0.2, "kb_ids": ["kb-1"], "summary": True}

    effective = cable_defaults.search_config_with_defaults(stored)

    assert effective["similarity_threshold"] == 0.2
    assert effective["kb_ids"] == ["kb-1"]
    assert effective["summary"] is True
    # A parameter the app never wrote comes from the platform defaults.
    assert effective["rerank_candidates_count"] == cable_defaults.RERANK_CANDIDATES_COUNT
    assert effective["vector_similarity_weight"] == cable_defaults.VECTOR_SIMILARITY_WEIGHT


def test_search_config_with_defaults_reads_an_absent_config():
    """A row written before the config column existed still retrieves on them."""
    effective = cable_defaults.search_config_with_defaults(None)

    assert effective["similarity_threshold"] == cable_defaults.SIMILARITY_THRESHOLD
    assert effective["rerank_candidates_count"] == cable_defaults.RERANK_CANDIDATES_COUNT


def test_search_model_default_uses_the_cable_config():
    assert Search.search_config.default == cable_defaults.search_config


def test_chat_model_defaults_use_the_cable_values():
    assert Dialog.similarity_threshold.default == cable_defaults.SIMILARITY_THRESHOLD
    assert Dialog.vector_similarity_weight.default == cable_defaults.VECTOR_SIMILARITY_WEIGHT
    assert Dialog.top_n.default == cable_defaults.TOP_N
    assert Dialog.rerank_candidates_count.default == cable_defaults.RERANK_CANDIDATES_COUNT

    # A JSONField default that is callable is evaluated per insert, which keeps
    # one row's prompt edits out of every other row.
    prompt_config = Dialog.prompt_config.default()
    assert prompt_config["system"] == cable_defaults.SYSTEM_PROMPT
    assert prompt_config["prologue"] == cable_defaults.PROLOGUE
    assert prompt_config["empty_response"] == cable_defaults.EMPTY_RESPONSE


def test_dataset_model_defaults_use_the_cable_values():
    assert Knowledgebase.similarity_threshold.default == cable_defaults.SIMILARITY_THRESHOLD
    assert Knowledgebase.vector_similarity_weight.default == cable_defaults.VECTOR_SIMILARITY_WEIGHT


# ---------------------------------------------------------------------------
# Metadata matching: a new assistant starts with it ON
# ---------------------------------------------------------------------------


def test_metadata_matching_defaults_to_auto():
    """A corpus of standards is reached by the name the question uses."""
    assert cable_defaults.META_DATA_FILTER_METHOD == "auto"
    assert cable_defaults.meta_data_filter() == {"method": "auto"}


def test_metadata_matching_returns_an_independent_copy():
    first = cable_defaults.meta_data_filter()
    first["method"] = "manual"

    assert cable_defaults.meta_data_filter() == {"method": "auto"}


def test_metadata_defaults_fill_in_an_absent_or_empty_configuration():
    """Not configured means the platform default; configured means the operator."""
    assert cable_defaults.meta_data_filter_with_defaults(None) == {"method": "auto"}
    assert cable_defaults.meta_data_filter_with_defaults({}) == {"method": "auto"}


def test_metadata_defaults_never_override_a_stated_mode():
    """`disabled` is a decision, not an absent value.

    The settings form sends it when an operator turns matching off, and defaulting
    over it would make the control impossible to use.
    """
    for stated in ({"method": "disabled"}, {"method": "auto"}, {"method": "manual", "manual": [{"key": "k", "op": "=", "value": "v"}]}):
        assert cable_defaults.meta_data_filter_with_defaults(stated) == stated


def test_metadata_defaults_do_not_alias_the_caller_configuration():
    stated = {"method": "semi_auto", "semi_auto": ["k"]}

    effective = cable_defaults.meta_data_filter_with_defaults(stated)
    effective["semi_auto"].append("other")

    assert stated == {"method": "semi_auto", "semi_auto": ["k"]}
    assert effective is not stated


def test_chat_model_metadata_default_is_the_cable_auto_mode():
    """A `Dialog.create()` with no metadata field must come out filtering."""
    assert Dialog.meta_data_filter.default is cable_defaults.meta_data_filter
    assert Dialog.meta_data_filter.default() == {"method": "auto"}
