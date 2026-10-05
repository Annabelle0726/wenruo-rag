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

"""Surface selected internal INFO logs to the client as ``<think>`` content.

During an agentic ``rag_agent`` turn we attach a context-scoped logging sink so
the pipeline's bracket-tagged progress logs — ``[Agentic RAG]``,
``[Formalizing the question]``, ``[Preliminary search]``, ``[Planner]``,
``[Orchestrator]``, ``[Agentic research]``, ``[Hybrid search]``,
``[BM25 search]``, ``[Web search]``, ``[Composing the answer]``,
``[Tool loop]``, ``[Function tool]`` … — can be streamed to the front end as
reasoning without instrumenting every call site. The tags double as
human-readable stage labels, so the same message serves the backend log and
the user-facing thinking stream.

The sink is stored in a :class:`contextvars.ContextVar`, so only the async task
tree of the current request (which inherits the context) forwards its logs —
concurrent requests stay isolated. Logs emitted from ``thread_pool_exec``
workers that did not inherit the context are simply skipped.
"""

from __future__ import annotations

import contextvars
import logging
from typing import Callable

# Per-request sink: a callable(str) that forwards one log line, or None when no
# agentic turn is streaming in the current context.
_think_log_sink: contextvars.ContextVar[Callable[[str], None] | None] = contextvars.ContextVar("think_log_sink", default=None)

# Only bracket-tagged INFO lines from these logger namespaces are surfaced.
_SCOPED_PREFIXES = ("rag.advanced_rag", "rag.llm.chat_model", "rag.llm.tool_decorator")

_installed = False


class ThinkLogHandler(logging.Handler):
    """Forward in-scope, bracket-tagged records to the active per-request sink."""

    def emit(self, record: logging.LogRecord) -> None:
        sink = _think_log_sink.get()
        if sink is None:
            return
        name = record.name or ""
        if not name.startswith(_SCOPED_PREFIXES):
            return
        try:
            msg = record.getMessage()
        except Exception:
            return
        # Only the bracket-tagged progress lines ("[Hybrid search] ...").
        if not msg or not msg.lstrip().startswith("["):
            return
        try:
            sink(render_think_log_line(msg))
        except Exception:
            # Never let think-log forwarding break the request or the logging
            # subsystem itself.
            pass


def render_think_log_line(msg: str) -> str:
    """One forwarded record, on one line, closed by its own break.

    The client collapses a forwarded record by matching its leading ``[Stage]``
    tag, then treats whatever follows as answer text unless it looks like a
    continuation. A record whose own message spans lines therefore leaks: the
    lines after the first carry no tag, and the stage that logs immediately
    before composing leaves the answer glued to the last of them —
    ``pre_summary=''直接说结论：…`` reached the answer body exactly that way.

    Escaping the newlines keeps the record's content — it stays readable in the
    collapsed panel, tables included — while leaving exactly one line for the
    tag rule to match, and the trailing break means the answer that follows
    always starts a line of its own. Only the forwarded copy is escaped: the
    same record still reaches the log file with its own formatting.
    """
    escaped = msg.strip().replace("\r\n", "\n").replace("\n", "\\n")
    return "<br>" + escaped + "<br>"


def install_think_log_handler() -> None:
    """Install the forwarding handler on the root logger exactly once."""
    global _installed
    if _installed:
        return
    handler = ThinkLogHandler(level=logging.INFO)
    logging.getLogger().addHandler(handler)
    _installed = True


def set_think_log_sink(sink: Callable[[str], None] | None):
    """Activate ``sink`` for the current context; returns the reset token."""
    return _think_log_sink.set(sink)


def reset_think_log_sink(token) -> None:
    try:
        _think_log_sink.reset(token)
    except Exception:
        pass
