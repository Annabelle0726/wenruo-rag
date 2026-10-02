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
"""Coverage reservation for a multi-fact question's context window.

THE GAP THIS ADDRESSES
======================

Route expansion (Phase 1/1.1) guarantees that a route aimed at each fact type exists and is
retrieved. It does not guarantee that the passage which actually STATES that fact survives the
context cut. Measured on V5 ("标准对终端和接头的结构以及设计使用年限是怎样规定的？"):

* the question's own route and both structure routes return the structure-drawing clause;
* the merged pool therefore CONTAINS it;
* the final 12-slot window does not - 6 design-life passages and 6 generic structure passages win
  the slots, and the clause-bearing passage is cut.

The deployed cut already reserves **one slot per route**. That is the wrong granularity for this
failure: the reserved slot goes to the route's best-scoring passage, and the best-scoring passage
for "接头 结构" is a generic structure passage, not the clause. The reservation has to be per FACT
TYPE and it has to pick the passage that carries that fact type's evidence.

WHAT THIS IS NOT
================

It is not a rerank change. Scores are untouched and the global ordering is untouched; this only
decides which members of the already-ordered pool occupy the fixed window. It is not a
final_top_n change - the window stays the caller's size. And it holds no question-specific
vocabulary: "which passages are evidence for fact type F" is answered from F's own cues, which the
domain layer already declares for route construction.

THREE STRATEGIES
================

* ``current``    - the deployed cut, unchanged.
* ``fact``       - for each fact type the question names, reserve the single highest-evidence
                   passage if the window does not already carry evidence for that fact type.
* ``route``      - for each supplemental route, reserve the single best passage it retrieved, if
                   the window does not already represent that route. Measured to be a no-op: the
                   deployed cut already does exactly this.

Reserved passages displace the WEAKEST members of the deployed selection (which is in score
order), so an already-correct window is never emptied of its evidence and the document/quota rules
that produced the base selection still hold.
"""

from __future__ import annotations

import re
from typing import Sequence

_TAG_RE = re.compile(r"<[^>]{0,300}?>")


def flat(text: str) -> str:
    """Comparison form: markup stripped to separators, whitespace removed, case folded."""
    return re.sub(r"\s+", "", _TAG_RE.sub("|", str(text or "")).lower().replace("×", "x"))


def chunk_key(chunk: dict) -> str:
    return str(chunk.get("chunk_id") or chunk.get("id") or "")


def chunk_text(chunk: dict) -> str:
    return str(chunk.get("content_with_weight") or chunk.get("content") or "")


def score_of(chunk: dict) -> float:
    try:
        return float(chunk.get("rerank_score", chunk.get("similarity")) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def fact_evidence(chunk: dict, fact_type) -> int:
    """How strongly a passage carries a fact type, from that fact type's own cue vocabulary.

    Weighted by cue length, so a passage stating the clause's own longer term outranks a passage
    that merely mentions the general word: for ``structure`` a "结构图纸" passage scores 8
    (6 + 2) while a passage mentioning only "结构" scores 2; for ``design_life`` a passage stating
    "设计使用年限" scores 12 while one mentioning only "寿命" scores 2.
    """
    text = flat(chunk_text(chunk))
    if not text or fact_type is None:
        return 0
    return sum(len(cue) for cue in fact_type.cues if cue in text)


def _representatives(ordered: Sequence[dict], base: Sequence[dict], facts) -> list[dict]:
    """One passage per fact type whose window evidence is WEAKER than the pool's best.

    The first version asked only whether the window carried *any* passage mentioning the fact type,
    and that test is too weak to do anything: for V5 the window holds six passages containing 结构,
    so structure read as "covered" and the reservation never fired, while the passage that actually
    states the requirement (the 结构图纸 list, evidence 6 against their 2) stayed outside the window.

    The rule is therefore EVIDENCE PARITY: reserve unless the window's strongest evidence for the
    fact type is already as strong as the strongest evidence the pool offers. A window that mentions
    the topic is not a window that answers the question.
    """
    picks: list[dict] = []
    picked: set[str] = set()
    for fact in facts:
        pool_best = max((fact_evidence(c, fact) for c in ordered), default=0)
        window_best = max((fact_evidence(c, fact) for c in base), default=0)
        if pool_best <= 0 or window_best >= pool_best:
            continue
        best: tuple[tuple[int, float], dict] | None = None
        for chunk in ordered:
            key = chunk_key(chunk)
            if key in picked:
                continue
            evidence = fact_evidence(chunk, fact)
            if evidence <= window_best:
                continue
            rank = (evidence, score_of(chunk))
            if best is None or rank > best[0]:
                best = (rank, chunk)
        if best is not None:
            picks.append(best[1])
            picked.add(chunk_key(best[1]))
    return picks


def _route_representatives(ordered: Sequence[dict], base: Sequence[dict], routes: Sequence[str]) -> list[dict]:
    """One passage per supplemental route the window does not already represent."""
    if not routes:
        return []
    base_routes = {r for c in base for r in (c.get("retrieval_routes") or [])}
    picks: list[dict] = []
    picked: set[str] = set()
    for route in routes:
        if route in base_routes:
            continue
        for chunk in ordered:
            if route not in (chunk.get("retrieval_routes") or []):
                continue
            key = chunk_key(chunk)
            if key in picked:
                break
            picks.append(chunk)
            picked.add(key)
            break
    return picks


def select_with_reservation(
    ordered: Sequence[dict],
    top_n: int,
    base: Sequence[dict],
    *,
    strategy: str = "current",
    facts=(),
    routes: Sequence[str] = (),
) -> list[dict]:
    """The window: ``base`` (the deployed selection) plus reservations, in score order.

    ``ordered`` is the score-ordered pool the deployed cut sees, and ``base`` is what it selected.
    A reservation displaces the weakest members of ``base`` rather than extending it, so the window
    size is unchanged and already-present evidence is not evicted to make room.
    """
    if strategy == "current" or len(base) == 0:
        return list(base)

    picks: list[dict] = []
    if strategy == "fact":
        picks = _representatives(ordered, base, facts)
    elif strategy == "route":
        picks = _route_representatives(ordered, base, routes)
    else:
        raise ValueError(f"unknown reservation strategy {strategy!r}")
    if not picks:
        return list(base)

    seen = {chunk_key(c) for c in base}
    added = [c for c in picks if chunk_key(c) not in seen]
    if not added:
        return list(base)

    keep_n = max(1, len(base) - len(added))
    kept = list(base)[:keep_n]
    final_keys = {chunk_key(c) for c in kept} | {chunk_key(c) for c in added}
    # Score order is preserved: the result is read back out of `ordered`, which is already ordered.
    return [c for c in ordered if chunk_key(c) in final_keys][:top_n]


def required_fact_types(question: str) -> list:
    """The fact types ``question`` names, or ``[]`` when it names fewer than two.

    This reuses the domain layer's resolver, which applies the SAME gate the axis reader applies: a
    question that names two or more declared fact types is a multi-fact question. A single-fact or
    single-axis question returns nothing here, so the reservation cannot fire on it and its context
    is unchanged.

    The import is deliberately function-local: it keeps ``rerank``'s module graph unchanged at import
    time, so this stays a change to the selection step rather than to the module's dependencies.
    """
    from rag.retrieval.domain_facts import FACT_TYPES, resolve_domain

    category, mentioned = resolve_domain(str(question or ""))
    if not category:
        return []
    by_key = {fact.key: fact for fact in FACT_TYPES.get(category, ())}
    return [by_key[item["key"]] for item in mentioned if item["key"] in by_key]


def reserve_for_question(
    ordered: Sequence[dict],
    top_n: int,
    selected: Sequence[dict],
    question: str,
    *,
    strategy: str = "fact",
) -> list[dict]:
    """Fact-type evidence parity for a multi-fact question, applied to an already-scored selection.

    Called between the scored pool and the returned context: ``ordered`` is the reranker-ordered
    pool, ``selected`` is what the cut chose, and the result is a selection of the same size drawn
    from the same pool. Scores, models and the ordering formula are untouched.
    """
    facts = required_fact_types(question)
    if not facts or not selected:
        return list(selected)
    return select_with_reservation(ordered, top_n, selected, strategy=strategy, facts=facts)
