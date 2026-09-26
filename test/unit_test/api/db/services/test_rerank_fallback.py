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
"""Rerank resolution: assistant -> workspace default -> no reranking, never an error.

Reranking is an ORDERING pass. A deployment with no reranker, or one whose catalog
row was deleted, must still answer from the fused hybrid order - the pipeline
already produced a ranked pool before the reranker is consulted. These cases pin
each level of the fallback and, most importantly, that a failure at any level
degrades instead of propagating.
"""

import logging

import pytest

from api.db.services import dialog_service

pytestmark = pytest.mark.p1


@pytest.fixture
def wiring(monkeypatch):
    """Control each level of the resolution and record what was consulted."""
    seen = {"by_id": [], "by_default": [], "bundles": []}

    def _install(*, bound_config=None, bound_error=None, default_config=None, bundle_none_for=()):
        def _resolve_model_config(tenant_id, model_type, model_id):
            seen["by_id"].append((tenant_id, str(model_type), model_id))
            if bound_error is not None:
                raise bound_error
            if bound_config is None:
                raise LookupError("model %s not found" % model_id)
            return bound_config

        def _get_model_config_by_id(tenant_id, model_type, model_id):
            return _resolve_model_config(tenant_id, model_type, model_id)

        def _get_default_rerank_model_config(tenant_id):
            seen["by_default"].append(tenant_id)
            return default_config

        def _llm_bundle(tenant_id, model_config, **kwargs):
            seen["bundles"].append((tenant_id, model_config))
            if model_config in bundle_none_for:
                return None
            return "bundle:%s" % (model_config,)

        monkeypatch.setattr(dialog_service, "resolve_model_config", _resolve_model_config)
        monkeypatch.setattr(dialog_service, "get_model_config_by_id", _get_model_config_by_id)
        monkeypatch.setattr(dialog_service, "get_default_rerank_model_config", _get_default_rerank_model_config)
        monkeypatch.setattr(dialog_service, "LLMBundle", _llm_bundle)
        return seen

    return _install


def test_the_assistant_own_reranker_wins(wiring):
    seen = wiring(bound_config={"model_name": "bound"}, default_config={"model_name": "default"})

    bundle = dialog_service.resolve_rerank_mdl("t-1", "rerank-1")

    assert bundle == "bundle:{'model_name': 'bound'}"
    assert seen["by_default"] == [], "the workspace default must not be consulted when the bound model resolved"


def test_a_tenant_model_id_is_preferred_over_the_legacy_id(wiring):
    seen = wiring(bound_config={"model_name": "by-tenant-model"})

    dialog_service.resolve_rerank_mdl("t-1", "rerank-1", tenant_rerank_id="tm-9")

    assert seen["by_id"] == [("t-1", str(dialog_service.LLMType.RERANK), "tm-9")]


def test_no_bound_model_falls_back_to_the_workspace_default(wiring):
    """The assistant names no reranker: the workspace's default one runs."""
    seen = wiring(default_config={"model_name": "default"})

    bundle = dialog_service.resolve_rerank_mdl("t-1", "")

    assert bundle == "bundle:{'model_name': 'default'}"
    assert seen["by_id"] == []


def test_an_unresolvable_bound_model_falls_back_instead_of_raising(wiring):
    """A stale id - a deleted catalog row - must not fail the question."""
    seen = wiring(bound_config=None, default_config={"model_name": "default"})

    bundle = dialog_service.resolve_rerank_mdl("t-1", "deleted-rerank")

    assert bundle == "bundle:{'model_name': 'default'}"
    assert seen["by_default"] == ["t-1"]


def test_a_bound_model_that_resolves_to_nothing_falls_back(wiring):
    seen = wiring(bound_config={"model_name": "bound"}, default_config={"model_name": "default"}, bundle_none_for=({"model_name": "bound"},))

    bundle = dialog_service.resolve_rerank_mdl("t-1", "rerank-1")

    assert bundle == "bundle:{'model_name': 'default'}"
    assert seen["by_default"] == ["t-1"]


def test_an_unexpected_resolution_error_falls_back_instead_of_raising(wiring):
    """Not just LookupError: any failure to build the bundle degrades."""
    seen = wiring(bound_error=RuntimeError("provider catalog exploded"), default_config={"model_name": "default"})

    bundle = dialog_service.resolve_rerank_mdl("t-1", "rerank-1")

    assert bundle == "bundle:{'model_name': 'default'}"
    assert seen["by_default"] == ["t-1"]


def test_a_failing_workspace_default_degrades_to_no_reranking(wiring, monkeypatch):
    wiring(bound_error=LookupError("gone"), default_config=None)

    def _boom(tenant_id):
        raise RuntimeError("tenant model table unreachable")

    monkeypatch.setattr(dialog_service, "get_default_rerank_model_config", _boom)

    assert dialog_service.resolve_rerank_mdl("t-1", "rerank-1") is None


def test_nothing_configured_returns_none_and_warns(wiring, caplog):
    """Level 3: no model anywhere. Retrieval continues on the fused order."""
    seen = wiring()

    with caplog.at_level(logging.WARNING):
        bundle = dialog_service.resolve_rerank_mdl("t-1", "")

    assert bundle is None
    assert seen["bundles"] == []
    assert "no rerank model is configured" in caplog.text
    assert "t-1" in caplog.text


def test_the_search_surface_takes_the_same_path(wiring):
    """A search app inherits the workspace reranker when it names none."""
    seen = wiring(default_config={"model_name": "default"})

    bundle = dialog_service._search_rerank_model("t-1", {"rerank_id": ""})

    assert bundle == "bundle:{'model_name': 'default'}"
    assert seen["by_default"] == ["t-1"]


def test_the_search_surface_honours_its_own_model_first(wiring):
    seen = wiring(bound_config={"model_name": "app"}, default_config={"model_name": "default"})

    bundle = dialog_service._search_rerank_model("t-1", {"rerank_id": "app-rerank", "tenant_rerank_id": "tm-3"})

    assert bundle == "bundle:{'model_name': 'app'}"
    assert seen["by_id"] == [("t-1", str(dialog_service.LLMType.RERANK), "tm-3")]
    assert seen["by_default"] == []
