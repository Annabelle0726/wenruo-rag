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
"""Auto metadata tagging for the ingest, wired for BOTH chunking paths.

The extraction itself lives in :mod:`rag.nlp.auto_metadata` (a zero-token regex pass
over the file name and the document head, then at most one chat call). What a
chunking path has to get right AROUND it is what this module owns, so that neither
path can get it subtly wrong on its own:

* RESOLVING the chat model the optional call is made with - the id the task
  carries, falling back to the workspace's default chat model, and never failing
  the parse when the workspace has neither. The call goes through ``LLMBundle``
  like every other chat call in the ingest, so it is metered, budget-checked and
  attributed to the detached job exactly like they are;
* PERSISTING the fields - read the document's metadata first and merge, so the
  operator's own fields and the parser's ``outline`` survive, a field that is
  already stored is not overwritten by a later page-range task re-reading a CITED
  standard, and then write - and REPORT a rejected write. The document store
  returns ``False`` rather than raising, so an unchecked call is precisely the
  silent "0 fields" this feature exists to remove.

Both executors call :func:`tag_document_metadata`:

* ``rag.svr.task_executor.build_chunks`` - the original executor, chosen when
  ``TE_RUN_MODE`` is neither 0 nor 1;
* ``rag.svr.task_executor_refactor.chunk_service.ChunkService.build_chunks`` - the
  path ``TE_RUN_MODE=0`` selects, which is the DEFAULT.

Wiring only one of them is how this feature first shipped doing nothing at all: the
default path is the refactored one, so the metadata was never written and the file
list kept saying "0 fields" while every log line looked healthy.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Sequence

from api.db.joint_services.tenant_model_service import get_tenant_default_model_by_type, resolve_model_config
from api.db.services.doc_metadata_service import DocMetadataService
from api.db.services.llm_service import LLMBundle
from common.constants import LLMType
from common.metadata_utils import update_metadata_to
from rag.nlp.auto_metadata import LLM_SCAN_CHARS, LLM_TIMEOUT_SECONDS, auto_tag, document_text

#: The one write this module performs, named as the write interceptor and the
#: dry-run comparator know it.
METADATA_WRITE = "DocMetadataService.update_document_metadata"


def resolve_chat_model(tenant_id: str, llm_id: str | None = None, language: str = "Chinese") -> Any | None:
    """The chat model one metadata pass may spend, or ``None``.

    The task's own chat model first; when the task carries none (a knowledge base
    that never configured one for parsing, which is the common case for a plain
    naive parse) the workspace's DEFAULT chat model, because that is the model the
    operator expects a chat-shaped extra to use. Returns ``None`` - and says why -
    when neither resolves, which leaves the caller with the zero-token regex pass
    rather than an exception.

    Never raises: metadata is an enhancement, and a workspace without a chat model
    must still ingest documents.
    """
    if not tenant_id:
        return None

    config = None
    if llm_id:
        try:
            config = resolve_model_config(tenant_id, LLMType.CHAT, llm_id)
        except Exception:
            logging.warning(
                "auto metadata tagging: chat model %s is not usable in workspace %s; trying the workspace default",
                llm_id,
                tenant_id,
                exc_info=True,
            )
    if not config:
        try:
            config = get_tenant_default_model_by_type(tenant_id, LLMType.CHAT)
            logging.info("auto metadata tagging: using the workspace default chat model for workspace %s", tenant_id)
        except Exception:
            logging.warning(
                "auto metadata tagging: no chat model in workspace %s; the regex pass runs alone",
                tenant_id,
                exc_info=True,
            )
            return None

    try:
        return LLMBundle(tenant_id, config, lang=language)
    except Exception:
        logging.warning(
            "auto metadata tagging: could not build the chat model for workspace %s; the regex pass runs alone",
            tenant_id,
            exc_info=True,
        )
        return None


def persist_document_metadata(
    doc_id: str,
    fields: dict[str, str],
    *,
    write_interceptor: Any = None,
    on_write_result: Callable[[bool], Any] | None = None,
) -> bool:
    """Merge ``fields`` into the document's stored metadata and report the outcome.

    The read-modify-write is what keeps the other writers alive: the operator sets
    metadata by hand and ``extract_outline`` stores the PDF outline through the same
    call, so a write that replaced the whole row would delete them. It also makes a
    page-range task harmless - a later task's regex re-reads a standard the document
    only CITES, finds the key already present, and hands it back unchanged.

    ``write_interceptor`` is the refactored executor's dry-run switch: the recorded
    value is consumed instead of writing, exactly like the outline write does.
    """
    if write_interceptor is not None:
        write_interceptor.intercept(METADATA_WRITE)
        if on_write_result is not None:
            on_write_result(True)
        return True

    existing = DocMetadataService.get_document_metadata(doc_id) or {}
    merged = update_metadata_to(dict(fields), existing)
    written = bool(DocMetadataService.update_document_metadata(doc_id, merged))
    if on_write_result is not None:
        on_write_result(written)
    if not written:
        # Not an exception: the store declined (a missing document row, an index it
        # could not create, a backend error). Without this line the file list would
        # keep showing "0 fields" with nothing in the log to explain it.
        logging.warning(
            "auto metadata tagging could not persist %d field(s) for document %s (%s); the document keeps its previous metadata",
            len(fields),
            doc_id,
            ", ".join(sorted(fields)),
        )
    return written


async def tag_document_metadata(
    *,
    doc_id: str,
    name: str,
    chunks: Sequence[dict],
    tenant_id: str,
    llm_id: str | None = None,
    language: str = "Chinese",
    timeout_seconds: float = LLM_TIMEOUT_SECONDS,
    write_interceptor: Any = None,
    on_write_result: Callable[[bool], Any] | None = None,
) -> dict[str, str]:
    """Tag one parsed document and persist the fields. Never raises.

    ``chunks`` are the parsed (and, by the caller's design, context-bound) chunks of
    the page range this task covers; only their head is read (:data:`LLM_SCAN_CHARS`),
    so a large document costs nothing extra.

    Returns the fields the document yielded. A write the store rejected is reported
    as ``False`` through ``on_write_result`` and logged, and the extracted fields are
    still returned - the caller decides what that means.
    """
    try:
        text = document_text(chunks, limit=LLM_SCAN_CHARS)
        llm = resolve_chat_model(tenant_id, llm_id, language)
        result = await auto_tag(name, text, llm=llm, timeout_seconds=timeout_seconds)
    except Exception:
        # ``auto_tag`` is documented never to raise; this belt is for the import of
        # the model stack above it, because a metadata enhancement must not be the
        # reason an ingest fails.
        logging.exception("auto metadata tagging failed for %s; continuing without it", name)
        return {}

    if not result.fields:
        logging.info("auto metadata tagging found nothing for %s (source=%s)", name, result.source)
        return {}

    persist_document_metadata(doc_id, result.fields, write_interceptor=write_interceptor, on_write_result=on_write_result)
    logging.info(
        "auto metadata tagging (%s) for %s: %s",
        result.source,
        name,
        ", ".join(f"{key}={value}" for key, value in result.fields.items()),
    )
    return result.fields


__all__ = [
    "METADATA_WRITE",
    "persist_document_metadata",
    "resolve_chat_model",
    "tag_document_metadata",
]
