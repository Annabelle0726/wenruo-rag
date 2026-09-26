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
"""Defaults the create-chat endpoint seeds into a new assistant.

``_apply_prompt_defaults`` / ``_apply_retrieval_defaults`` are the whole of the
create path's defaulting, so they are exercised directly: the endpoint itself
needs an authenticated tenant, and the values it writes are what the Chat
Settings panel then shows.
"""

from api.apps.restful_apis.chat_api import (
    _DEFAULT_PROMPT_CONFIG,
    _apply_prompt_defaults,
    _apply_retrieval_defaults,
)
from api.db import cable_defaults


def test_default_prompt_config_is_the_cable_one():
    assert _DEFAULT_PROMPT_CONFIG["system"] == cable_defaults.SYSTEM_PROMPT
    assert _DEFAULT_PROMPT_CONFIG["prologue"] == cable_defaults.PROLOGUE
    assert _DEFAULT_PROMPT_CONFIG["empty_response"] == cable_defaults.EMPTY_RESPONSE
    assert _DEFAULT_PROMPT_CONFIG["quote"] is True
    assert _DEFAULT_PROMPT_CONFIG["refine_multiturn"] is True


def test_retrieval_defaults_fill_only_the_missing_settings():
    req = {"similarity_threshold": 0.5}
    _apply_retrieval_defaults(req)

    assert req["similarity_threshold"] == 0.5
    assert req["vector_similarity_weight"] == cable_defaults.VECTOR_SIMILARITY_WEIGHT
    assert req["top_n"] == cable_defaults.TOP_N
    assert req["rerank_candidates_count"] == cable_defaults.RERANK_CANDIDATES_COUNT
    assert req["top_k"] == 1024
    assert req["rerank_id"] == ""


def test_a_new_assistant_is_created_with_metadata_matching_on():
    """The create payload carries no metadata field, so the default decides."""
    req = {"kb_ids": ["kb-1"]}
    _apply_retrieval_defaults(req)

    assert req["meta_data_filter"] == {"method": cable_defaults.META_DATA_FILTER_METHOD}
    assert req["meta_data_filter"] == {"method": "auto"}


def test_an_empty_metadata_configuration_gets_the_default():
    """`{}` is what an older client sends for "never configured"."""
    req = {"meta_data_filter": {}}
    _apply_retrieval_defaults(req)

    assert req["meta_data_filter"] == {"method": "auto"}


def test_a_stated_metadata_mode_is_never_overwritten():
    """The settings form's `disabled`/`manual`/`semi_auto` choices survive."""
    stated = {"method": "manual", "logic": "and", "manual": [{"key": "物资类别", "op": "=", "value": "架空绝缘导线"}]}
    req = {"meta_data_filter": stated}
    _apply_retrieval_defaults(req)

    assert req["meta_data_filter"] == stated


def test_the_seeded_metadata_configuration_is_not_shared_between_requests():
    first = {}
    second = {}
    _apply_retrieval_defaults(first)
    _apply_retrieval_defaults(second)

    assert first["meta_data_filter"] is not second["meta_data_filter"]


def test_prompt_defaults_seed_the_cable_prompt_for_a_dataset_bound_chat():
    req = {"kb_ids": ["kb-1"]}
    _apply_prompt_defaults(req)

    prompt_config = req["prompt_config"]
    assert prompt_config["system"] == cable_defaults.SYSTEM_PROMPT
    assert prompt_config["prologue"] == cable_defaults.PROLOGUE
    assert prompt_config["empty_response"] == cable_defaults.EMPTY_RESPONSE
    assert {"key": "knowledge", "optional": False} in prompt_config["parameters"]
    assert {"key": "date", "optional": True} in prompt_config["parameters"]


def test_prompt_defaults_leave_the_system_prompt_empty_without_a_dataset():
    # With no dataset bound there is nothing to inject into {knowledge}, so the
    # dataset-oriented prompt must not be sent to the model verbatim.
    req = {"kb_ids": []}
    _apply_prompt_defaults(req)

    prompt_config = req["prompt_config"]
    assert prompt_config["system"] == ""
    assert prompt_config["prologue"] == cable_defaults.PROLOGUE
    assert prompt_config["empty_response"] == cable_defaults.EMPTY_RESPONSE


def test_prompt_defaults_never_overwrite_a_supplied_prompt():
    req = {
        "kb_ids": ["kb-1"],
        "prompt_config": {
            "system": "custom system {knowledge}",
            "prologue": "custom opener",
            "empty_response": "custom empty",
        },
    }
    _apply_prompt_defaults(req)

    prompt_config = req["prompt_config"]
    assert prompt_config["system"] == "custom system {knowledge}"
    assert prompt_config["prologue"] == "custom opener"
    assert prompt_config["empty_response"] == "custom empty"
