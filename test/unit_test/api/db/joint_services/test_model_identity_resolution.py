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

"""Provider identity from a ``tenant_model`` id: by primary key, or not at all.

The values are the live ones: workspace ``a9e28731...``, provider ``ee6cb91b...``
(``Gemini``), instance ``f7825d47...``, model ``f79e37e5...``
(``gemini-embedding-001``). What matters here is not the happy path but the
refusals - a name must never be turned into an identity, a workspace must never be
able to name another workspace's provider, and a lookup that goes wrong must
return nothing instead of raising into a call path that is only being observed.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.db.joint_services import tenant_model_service as models
from common.constants import LLMType
from common.workspace_context import execution_user

WORKSPACE = "a9e28731ab7011f19b833887d563fb04"
OTHER_WORKSPACE = "89a9df92b5bb11f182935728a82b1fe8"
PROVIDER_ID = "ee6cb91bab7611f18f0b3887d563fb04"
INSTANCE_ID = "f7825d47ab7611f18d8d3887d563fb04"
MODEL_ID = "f79e37e5ab7611f18ecb3887d563fb04"

#: What a knowledgebase stores when it did NOT keep a tenant_model id.
COMPOSITE_NAME = "gemini-embedding-001@G@Gemini"

PROVIDER = SimpleNamespace(id=PROVIDER_ID, provider_name="Gemini", tenant_id=WORKSPACE)
INSTANCE = SimpleNamespace(id=INSTANCE_ID, provider_id=PROVIDER_ID, instance_name="G")
MODEL = SimpleNamespace(id=MODEL_ID, provider_id=PROVIDER_ID, instance_id=INSTANCE_ID, model_name="gemini-embedding-001")


def _resolve(model_id=MODEL_ID, *, model=MODEL, provider=PROVIDER, instance=INSTANCE, model_ok=True, provider_ok=True, instance_ok=True):
    with (
        patch.object(models.TenantModelService, "get_by_id", return_value=(model_ok, model)),
        patch.object(models.TenantModelProviderService, "get_by_id", return_value=(provider_ok, provider)),
        patch.object(models.TenantModelInstanceService, "get_by_id", return_value=(instance_ok, instance)),
    ):
        return models.resolve_model_identity_by_id(WORKSPACE, LLMType.EMBEDDING, model_id)


def test_a_tenant_model_id_resolves_to_its_workspace_provider_instance_and_capability():
    identity = _resolve()

    assert identity == models.ModelIdentity(
        tenant_id=WORKSPACE,
        provider_id=PROVIDER_ID,
        instance_id=INSTANCE_ID,
        provider_name="Gemini",
        capability="embedding",
    )


def test_identity_carries_nothing_but_the_five_scalars():
    """The shape is the guarantee: there is no field a credential could occupy."""
    identity = _resolve()

    assert identity._fields == ("tenant_id", "provider_id", "instance_id", "provider_name", "capability")
    for forbidden in ("api_key", "api_base", "model_config", "extra", "llm_name", "md5"):
        assert forbidden not in identity._fields


def test_the_capability_comes_from_the_caller_not_from_the_model_row():
    """A model that can embed AND rerank must still report the use it was resolved for."""
    with (
        patch.object(models.TenantModelService, "get_by_id", return_value=(True, MODEL)),
        patch.object(models.TenantModelProviderService, "get_by_id", return_value=(True, PROVIDER)),
        patch.object(models.TenantModelInstanceService, "get_by_id", return_value=(True, INSTANCE)),
    ):
        identity = models.resolve_model_identity_by_id(WORKSPACE, LLMType.EMBEDDING, MODEL_ID)

    assert identity.capability == "embedding"
    # A plain word, not the enum member: ``LLMType`` is a str subclass, so the
    # member would compare equal and store correctly while still being the wrong
    # type for a value that is a group key.
    assert type(identity.capability) is str
    assert len(identity.capability) <= 16, "must fit the capability column"


def test_a_capability_passed_as_a_plain_string_is_returned_unchanged():
    with (
        patch.object(models.TenantModelService, "get_by_id", return_value=(True, MODEL)),
        patch.object(models.TenantModelProviderService, "get_by_id", return_value=(True, PROVIDER)),
        patch.object(models.TenantModelInstanceService, "get_by_id", return_value=(True, INSTANCE)),
    ):
        identity = models.resolve_model_identity_by_id(WORKSPACE, "embedding", MODEL_ID)

    assert identity.capability == "embedding"


@pytest.mark.parametrize("model_id", [None, "", COMPOSITE_NAME, "not-a-real-id"])
def test_a_composite_model_name_is_never_turned_into_an_identity(model_id):
    """A name is shared by every workspace that configured it, so it proves nothing."""
    model = MODEL if model_id == COMPOSITE_NAME else None
    identity = _resolve(model_id, model=model, model_ok=False)

    assert identity is None


def test_a_reference_that_names_a_disabled_or_foreign_model_yields_no_identity():
    assert _resolve(model_ok=False) is None


def test_a_workspace_can_never_be_told_about_another_workspaces_provider():
    foreign_provider = SimpleNamespace(id=PROVIDER_ID, provider_name="Gemini", tenant_id=OTHER_WORKSPACE)

    assert _resolve(provider=foreign_provider) is None


def test_an_instance_that_does_not_belong_to_the_provider_yields_no_identity():
    mismatched = SimpleNamespace(id=INSTANCE_ID, provider_id="99999999999999999999999999999999", instance_name="G")

    assert _resolve(instance=mismatched) is None


def test_a_missing_provider_or_instance_yields_no_identity():
    assert _resolve(provider_ok=False) is None
    assert _resolve(instance_ok=False) is None


def test_a_lookup_that_raises_returns_nothing_instead_of_raising():
    with patch.object(models.TenantModelService, "get_by_id", side_effect=RuntimeError("database is gone")):
        assert models.resolve_model_identity_by_id(WORKSPACE, LLMType.EMBEDDING, MODEL_ID) is None


def test_a_missing_workspace_or_reference_is_refused_before_any_lookup():
    with patch.object(models.TenantModelService, "get_by_id") as lookup:
        assert models.resolve_model_identity_by_id("", LLMType.EMBEDDING, MODEL_ID) is None
        assert models.resolve_model_identity_by_id(WORKSPACE, LLMType.EMBEDDING, "") is None
        assert models.resolve_model_identity_by_id(WORKSPACE, LLMType.EMBEDDING, None) is None

    lookup.assert_not_called()


def test_the_identity_is_normalised_to_the_workspace_the_config_was_resolved_for():
    """The parse worker runs as a detached job, so the tenant is normalised the
    same way the config resolver normalises it - identity must describe the config
    the caller actually received."""
    normalized = SimpleNamespace(id=PROVIDER_ID, provider_name="Gemini", tenant_id=OTHER_WORKSPACE)
    token = execution_user.set("user-1")
    try:
        with (
            patch.object(models.TenantService, "resolve_config_tenant_id", return_value=OTHER_WORKSPACE) as normalize,
            patch.object(models.TenantModelService, "get_by_id", return_value=(True, MODEL)),
            patch.object(models.TenantModelProviderService, "get_by_id", return_value=(True, normalized)),
            patch.object(models.TenantModelInstanceService, "get_by_id", return_value=(True, INSTANCE)),
        ):
            identity = models.resolve_model_identity_by_id(WORKSPACE, LLMType.EMBEDDING, MODEL_ID)
    finally:
        execution_user.reset(token)

    normalize.assert_called_once_with("user-1", WORKSPACE)
    assert identity is not None
    assert identity.tenant_id == OTHER_WORKSPACE
