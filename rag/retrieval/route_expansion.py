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
"""Deterministic supplemental routes for a two-axis question (entity x fact-type).

WHY THIS EXISTS
===============

A question of the shape

    …（终端与接头）的设计使用寿命与结构有何要求

carries TWO enumerations: an entity axis (终端 / 接头) and a fact-type axis (设计使用寿命 /
结构). The deployed pipeline hands such a question to the LLM decomposition node, and the node's
GRANULARITY varies between sessions: it has produced both

    A. four narrow routes (终端/接头 x 寿命/结构) - the design-life table is recalled, and
    B. two composite routes (寿命, 结构)      - the composite life route returns ZERO
                                               design-life passages,

for the same question on the same build. Which one a session gets decides whether the answer can
state the design life at all. That was measured, not inferred: see
``docs/evaluation/rag_qa_004_instability.md``.

This module removes that dependency. It reads the two enumerations out of the question
STRUCTURALLY - the same way :func:`rag.retrieval.planner.dimension_heads` reads a single
enumeration - and emits the bounded cross product, so the narrowing that made case A work is
produced deterministically instead of being hoped for from the model.

IT IS ADDITIVE
==============

Nothing here removes, reorders or rewrites a route the caller already has. The caller passes its
current route list in and gets supplementary routes back; every emitted route is distinct from
every existing one.

IT HOLDS NO DOMAIN VOCABULARY
=============================

There is no list of cable words in this file. Both axes are read from the question's own wording,
and the only domain input is the existing profile table: expansion is offered only for a question
the deployed :mod:`rag.nlp.retrieval_projection` profiles already recognise as belonging to a known
domain. A new domain is a new entry in that table, not a new branch here.

IT IS BOUNDED
=============

The cross product is capped at :data:`MAX_SUPPLEMENTAL_ROUTES` routes over at most
:data:`MAX_AXIS_MEMBERS` members per axis, and the caller can lower it further with ``budget``.
"""

from __future__ import annotations

import re
from typing import Sequence

from rag.nlp.retrieval_projection import classify_category, profile_for
from rag.retrieval.decomposition import ENUMERATING_CONJUNCTION_RE, MAX_SUB_QUERY_CHARS

#: Most supplemental routes this rule may ever add: one 2x2 cross product. Four narrow routes are
#: what the working (4-route) decomposition produced, so this reproduces it and cannot exceed it.
MAX_SUPPLEMENTAL_ROUTES = 4

#: Members read from one axis. A question enumerating four entities and three fact types would ask
#: a twelve-route cross product, which is a route explosion, not a fix; the first members in the
#: question's own order are used and the rest are dropped.
MAX_AXIS_MEMBERS = 3

#: A member shorter than this carries no information ("与", "的"), and a member with no ideograph is
#: a number or a latin fragment that the axes rule was not written for.
MIN_AXIS_MEMBER_CHARS = 2

_IDEOGRAPH_RE = re.compile(r"[\u3400-\u9fff]")
_WHITESPACE_RE = re.compile(r"\s+")
_PAREN_RE = re.compile(r"[（(]([^（()）]{2,80})[)）]")
#: The tail that belongs to the QUESTION rather than to a member: "结构有何要求" -> "结构".
_PREDICATE_CUT_RE = re.compile(r"(?:有何|有哪|是什|是怎|如何|怎样|怎么|多少|哪些|什么|要求|规定|标准|参数|数值|数值)")
#: The shared subject that precedes the first member of the fact axis: "标准对电缆附件 的设计使用
#: 寿命" -> "设计使用寿命". The subject is stated once, before the first 的, and every member of the
#: enumeration inherits it.
_LEADING_SUBJECT_RE = re.compile(r"^.*?的", re.DOTALL)


def _clean(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", str(text or "")).strip()


def _key(text: str) -> str:
    """Comparison form for de-duplication: whitespace removed, case folded."""
    return _WHITESPACE_RE.sub("", str(text or "")).lower()


def _is_member(text: str) -> bool:
    return len(text) >= MIN_AXIS_MEMBER_CHARS and bool(_IDEOGRAPH_RE.search(text))


def _axis_members(segment: str) -> list[str]:
    """The enumeration members in ``segment``, in the order the segment names them.

    Splitting uses the SAME enumerating-conjunction pattern the dimension planner uses, so the two
    readers cannot disagree about what an enumeration is.
    """
    out: list[str] = []
    for raw in ENUMERATING_CONJUNCTION_RE.split(str(segment or "")):
        member = _clean(raw).strip("，。、,;；:： ")
        if _is_member(member) and member not in out:
            out.append(member)
    return out


def _fact_members(segment: str) -> list[str]:
    """The fact-type members in ``segment``, with the shared subject and the predicate removed.

    Two deterministic cuts, both needed because the fact axis sits in the middle of a sentence
    rather than in parentheses:

    * the leading subject is dropped up to and including the first 的
      (``标准对电缆附件 的设计使用寿命`` -> ``设计使用寿命``);
    * the question's own predicate is dropped from the first interrogative or requirement marker
      (``结构有何要求`` -> ``结构``).
    """
    out: list[str] = []
    for raw in ENUMERATING_CONJUNCTION_RE.split(str(segment or "")):
        member = _clean(raw)
        member = _LEADING_SUBJECT_RE.sub("", member, count=1) if "的" in member else member
        cut = _PREDICATE_CUT_RE.search(member)
        if cut and cut.start() > 0:
            member = member[: cut.start()]
        member = member.strip("，。、,;；:： ")
        if _is_member(member) and member not in out:
            out.append(member)
    return out


def domain_profile(question: str):
    """The domain profile that recognises ``question``, or ``None``.

    Reuses the deployed projector rather than a list of its own: ``classify_category`` answers
    from the profile ``cues``, which is where the cable domain's vocabulary already lives.
    """
    category = classify_category(str(question or ""))
    if not category or category == "unknown":
        return None
    return profile_for(category)


def read_axes(question: str) -> dict:
    """The two enumerations this rule can cross, or empty axes. Pure; no I/O, no model.

    Returns ``{"entities": [...], "fact_types": [...], "reason": str}``. ``reason`` is filled on
    every path where nothing is emitted, so a caller can report WHY the rule declined instead of
    guessing.
    """
    text = _clean(question)
    trace: dict = {"entities": [], "fact_types": [], "reason": ""}
    if not text:
        trace["reason"] = "empty_question"
        return trace

    # Axis A - the entity enumeration. Parenthesised is the shape whose members are already bare
    # nouns, so nothing has to be cut away from them.
    for group in _PAREN_RE.findall(text):
        members = _axis_members(group)
        if len(members) >= 2:
            trace["entities"] = members
            break
    if not trace["entities"]:
        trace["reason"] = "no_entity_enumeration"
        return trace

    # Axis B - the fact-type enumeration, read from everything OUTSIDE the parenthesised group so
    # axis A's members cannot leak into axis B.
    outside = _PAREN_RE.sub(" ", text)
    facts = _fact_members(outside)
    # The leading subject survives the split as part of the FIRST member only when it carried no 的;
    # it must not become a fact type of its own.
    facts = [fact for fact in facts if _key(fact) not in {_key(entity) for entity in trace["entities"]}]
    if len(facts) < 2:
        trace["reason"] = "no_fact_enumeration"
        return trace
    trace["fact_types"] = facts
    return trace


def entity_fact_routes(question: str) -> tuple[list[str], dict]:
    """The bounded entity x fact-type cross product for ``question``.

    Gated on a KNOWN domain profile AND at least two members on EACH axis: one axis alone means the
    question declares one information need per member and the existing single-axis readers
    (:func:`comparative_routes`, :func:`clause_route`) already cover it.
    """
    trace = read_axes(question)
    trace["profile"] = None
    if trace["entities"] and trace["fact_types"]:
        profile = domain_profile(question)
        trace["profile"] = getattr(profile, "category", None)
        if profile is None:
            trace["reason"] = "unknown_domain"
            return [], trace
    else:
        return [], trace

    routes: list[str] = []
    for entity in trace["entities"][:MAX_AXIS_MEMBERS]:
        for fact in trace["fact_types"][:MAX_AXIS_MEMBERS]:
            text = _clean(f"{entity} {fact}")[:MAX_SUB_QUERY_CHARS].strip()
            if text and text not in routes:
                routes.append(text)
    trace["reason"] = "expanded"
    return routes[:MAX_SUPPLEMENTAL_ROUTES], trace


def supplemental_routes(
    question: str,
    *,
    existing_routes: Sequence[str] = (),
    max_routes: int = MAX_SUPPLEMENTAL_ROUTES,
    budget: int | None = None,
) -> tuple[list[str], dict]:
    """Routes to ADD for ``question``, de-duplicated against what the caller already has.

    ``existing_routes`` is never modified and never re-ordered. ``budget`` is the caller's remaining
    route allowance; when it is smaller than ``max_routes`` it wins, so a caller under its own
    route cap cannot be pushed past it by this rule.
    """
    trace: dict = {"added": [], "dropped_duplicates": [], "reason": ""}
    produced, axes = entity_fact_routes(question)
    trace.update(axes)
    if not produced:
        trace["reason"] = axes.get("reason") or "declined"
        return [], trace

    ceiling = max(0, int(max_routes))
    if budget is not None:
        ceiling = min(ceiling, max(0, int(budget)))
    if ceiling == 0:
        trace["reason"] = "no_route_budget"
        return [], trace

    seen = {_key(route) for route in existing_routes}
    added: list[str] = []
    for route in produced:
        key = _key(route)
        if key in seen:
            trace["dropped_duplicates"].append(route)
            continue
        seen.add(key)
        added.append(route)
        if len(added) >= ceiling:
            break
    trace["added"] = list(added)
    trace["reason"] = "expanded" if added else "all_duplicates"
    return added, trace
