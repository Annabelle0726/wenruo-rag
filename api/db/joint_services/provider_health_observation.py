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
"""Put Provider Health on a model bundle, at the layer that knows who the provider is.

A call site cannot report a provider incident on its own: to say WHICH provider
failed it must hold a proven identity, and the only thing that proves one is a
``tenant_model`` primary key, resolved against the workspace that owns it. That is
this module's whole job - take the reference the call site already used to resolve
its model config, resolve the identity behind it, and hand the bundle to
``CapabilityObserver``.

It exists as a joint service because it joins two domains that must not import each
other: model identity (``joint_services.tenant_model_service``) and the incident
store (``services.provider_health_service``). Both the parse worker
(``rag/svr/task_executor_refactor``) and the serving layer (``api/apps``,
``agent/tools``) install observation through this one function, so a workspace's
provider instance is described the same way wherever it is called from - a parse
task and a retrieval query against the same instance are the same provider health
identity, not two.

**Fail-open is the contract.** The alternative to a missing notification is not a
working one, it is a broken parse or a failed search, so every way this can go
wrong - no reference, an unresolvable reference, a resolver that raises, a bundle
that refuses the installation - leaves the caller running exactly as it would have
without any of this.
"""

import logging

from api.db.joint_services.tenant_model_service import resolve_model_identity_by_id
from api.db.services import provider_health_service
from common.constants import LLMType
from rag.llm.chat_model import ERROR_PREFIX

#: The marker a chat connector puts in front of a refusal it RETURNS rather than
#: raises - the connector's own official marker, read from the connector so that
#: renaming it there cannot silently switch returned-failure detection off. A test
#: pins this equality.
CHAT_FAILURE_MARKER = ERROR_PREFIX


def _observe(model, tenant_id: str, identity_ref: str | None, *, capability: str, model_type, methods, failure_marker=None) -> None:
    """Install observation for one capability on *model*; never raises.

    ``identity_ref`` is the reference the caller just used to resolve this model's
    config - a ``tenant_model`` id, or ``None`` when the config came from the
    workspace default and no id can be attributed to it. The model config itself is
    never passed here, and never read: it holds the API key, and nothing about
    recording a health fact requires it.

    Identity is resolved ONCE per call site, from that id alone, and reaches the
    observer as explicit scalars. A reference that is not a primary key - a legacy
    ``model@instance@provider`` name - resolves to no identity, and a provider NAME
    is never substituted for one: a name belongs to every workspace that configured
    that provider, so a fact derived from it could name the wrong workspace's
    provider. An unrecorded observation is better than a misattributed one.
    """
    if not identity_ref:
        # No reference, no proof - and never a guess.
        return

    try:
        identity = resolve_model_identity_by_id(tenant_id, model_type, identity_ref)
        if identity is None:
            logging.info(
                "Provider health observation skipped for tenant %s: %s reference %s proves no provider identity",
                tenant_id,
                capability,
                identity_ref,
            )
            return
        provider_health_service.observe_calls(
            model,
            identity,
            capability=capability,
            methods=methods,
            failure_marker=failure_marker,
        )
    except Exception:
        logging.exception("Provider health observation could not be installed for tenant %s", tenant_id)


def observe_embedding_calls(embedding_model, tenant_id: str, identity_ref: str | None) -> None:
    """Let Provider Health watch this call site's EMBEDDING calls. Pure side-channel.

    Used by the parse worker and by every serving retrieval entry point, so a
    workspace's embedding provider instance is described the same way wherever its
    ``encode``/``encode_queries`` are dispatched from.
    """
    _observe(
        embedding_model,
        tenant_id,
        identity_ref,
        capability=provider_health_service.CAPABILITY_EMBEDDING,
        model_type=LLMType.EMBEDDING,
        methods=provider_health_service.EMBEDDING_CALL_METHODS,
    )


def observe_chat_calls(chat_model, tenant_id: str, identity_ref: str | None) -> None:
    """Let Provider Health watch this call site's CHAT calls. Pure side-channel.

    The chat capability is a SEPARATE capability from embedding, even on one
    provider instance: a workspace can be out of chat quota while its vectors still
    work, so the two never share an incident and one answering never closes the
    other's. All three chat shapes - the awaited answer and both streaming
    generators - are observed through this one installation.

    Chat is also the one capability whose connector reports a refusal as its
    ANSWER rather than as an exception, so observation here additionally recognises
    the connector's own failure marker on a returned value. The marker is read from
    the connector, not restated here, so renaming it there cannot quietly turn this
    detection off; and a returned value is only ever classified, never stored.
    """
    _observe(
        chat_model,
        tenant_id,
        identity_ref,
        capability=provider_health_service.CAPABILITY_CHAT,
        model_type=LLMType.CHAT,
        methods=provider_health_service.CHAT_CALL_METHODS,
        failure_marker=CHAT_FAILURE_MARKER,
    )
