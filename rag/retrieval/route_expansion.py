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
"""Deterministic supplemental routes for a two-axis question (entity x fact type).

Reads TWO axes out of a question's own wording - the objects it is about, and the fact types it
asks for - and returns their bounded cross product as routes to ADD to whatever the caller has.

WHY THIS EXISTS
===============

A question of the shape

    …（终端与接头）的设计使用寿命与结构有何要求

carries an entity axis (终端 / 接头) and a fact-type axis (design life / structure). The deployed
pipeline hands such a question to an LLM decomposition node, and that node's granularity varies
between sessions: it has produced four narrow routes in one session (design-life table recalled) and
two composite routes in another (ZERO design-life passages) for the same question on the same build.
This module removes the dependency: the narrowing is produced deterministically.

WHAT CHANGED IN 1.1 (GENERALIZED AXIS READER)
=============================================

Version 1 read the entity axis only out of a parenthesised group, so it fired on 1 of 6 natural
paraphrases of the same question, and its fact reader emitted predicate residue ("结构分别有",
"结构有") that became route text. This version reads the axes from the sentence's structure:

* **Entity axis** - the enumeration run joined by the enumerating conjunctions the deployed
  dimension reader already uses (``、；;和与及以及`` plus ``/``), with each member cleaned by
  structural boundaries. A parenthesised group is used when present, but is no longer required.
* **Fact axis** - the domain's declared fact types (:mod:`rag.retrieval.domain_facts`), resolved to
  the term the corpus uses. The reader holds no vocabulary of its own.

The cleaning is purely structural: a member is cut at the first question/predicate marker it
contains, at the last framing prefix before it, and rejected if what remains is a fragment rather
than a noun phrase. No complete question wording is matched anywhere.

ADDITIVE, BOUNDED, AND INERT WHEN IT DOES NOT APPLY
===================================================

Nothing here removes, reorders or rewrites a route the caller already has. The cross product is
capped at :data:`MAX_SUPPLEMENTAL_ROUTES` over at most :data:`MAX_AXIS_MEMBERS` members per axis, the
caller's ``budget`` can lower it further, and a question that does not carry BOTH axes - two or more
entities AND two or more fact types - gets an empty list and a byte-identical route set.
"""

from __future__ import annotations

import re
from typing import Sequence

from rag.nlp.retrieval_projection import classify_category
from rag.retrieval.decomposition import ENUMERATING_CONJUNCTION_RE, MAX_SUB_QUERY_CHARS
from rag.retrieval.domain_facts import is_fact_text, mentioned, resolve_domain

#: Most supplemental routes this rule may ever add: one 2x2 cross product. Four narrow routes are
#: what the working (4-route) decomposition produced, so this reproduces it and cannot exceed it.
MAX_SUPPLEMENTAL_ROUTES = 4

#: Members read from one axis. A question enumerating four entities and three fact types would ask
#: a twelve-route cross product, which is a route explosion, not a fix.
MAX_AXIS_MEMBERS = 3

#: Longest an entity member may be. An entity is a name ("电缆终端", "接头"); anything longer is a
#: clause the fragmenter failed to cut, and admitting it would put a whole phrase into a route.
MAX_ENTITY_CHARS = 8

#: Shortest an entity member may be, and it must carry an ideograph: a lone latin/number fragment is
#: not an entity in this domain.
MIN_AXIS_MEMBER_CHARS = 2

_IDEOGRAPH_RE = re.compile(r"[\u3400-\u9fff]")
_WHITESPACE_RE = re.compile(r"\s+")

#: An enumeration group inside brackets is the cleanest form and is used when present. It is NOT
#: required: the conjunction reader below handles the unbracketed forms.
_PAREN_RE = re.compile(r"[（(]([^（()）]{2,80})[)）]")

#: Fragment separators. The enumerating conjunctions come from the deployed dimension reader, so the
#: two readers cannot disagree about what an enumeration is; the rest are the structural boundaries
#: that separate an enumeration from the phrase it sits in.
_FRAGMENT_SPLIT_RE = re.compile(
    ENUMERATING_CONJUNCTION_RE.pattern + r"|[/／]|的|其|在|方面|[，,。？?！!：:；;（）()【】\[\]「」]"
)

#: Where a member ENDS: the question's own predicate. Cutting here is what removes the residue
#: ("结构分别有什么要求" -> "结构", "接头能使用多少年" -> "接头").
_TRAIL_CUT_RE = re.compile(r"有|是|多少|什么|怎样|怎么|如何|哪些|分别|以及|能不能|能|可以|要求|规定|构成|类型|各")

#: Where a member's LEADING FRAMING ends: "标准对终端" -> "终端". Applied at the LAST occurrence so a
#: nested phrase keeps its inner boundary.
_LEAD_CUT_RE = re.compile(r"^(?:.*(?:对于|关于|请问|针对|对))", re.DOTALL)

#: Locative scope words. "电缆附件中" is where the question looks, not an object it asks about.
_LOCATIVE_TAIL_RE = re.compile(r"[中内里上下]$|之中$|之内$")

#: Generic non-referential nouns. They are never an entity axis member, and they are not domain
#: vocabulary - they are the question's own scaffolding.
_GENERIC_STOPLIST = frozenset(
    {
        "技术", "要求", "规定", "方面", "内容", "情况", "资料", "条件", "指标", "数值", "参数",
        "标准", "规范", "数据", "说明", "问题", "相关", "具体", "主要", "重要", "一般",
    }
)


def _clean(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", str(text or "")).strip()


def _key(text: str) -> str:
    """Comparison form for de-duplication: whitespace removed, case folded."""
    return _WHITESPACE_RE.sub("", str(text or "")).lower()


def _trim_member(raw: str, category: str) -> str:
    """Reduce one fragment to an entity member, or to ``""`` when it is not one.

    Structural only, in this order:

    1. the question's predicate is cut off at its first marker;
    2. the leading framing ("标准对", "关于") is cut off;
    3. punctuation and a trailing locative are dropped;
    4. what is left must be a short ideographic noun phrase that is not a fact type and not generic
       scaffolding.
    """
    member = _clean(raw).strip("，。、,;；:： 　")
    cut = _TRAIL_CUT_RE.search(member)
    if cut is not None:
        member = member[: cut.start()] if cut.start() > 0 else ""
    member = _LEAD_CUT_RE.sub("", member)
    member = member.strip("，。、,;；:： 　")
    if _LOCATIVE_TAIL_RE.search(member):
        # "电缆附件中" is where the question looks, not an object it asks about. STRIP the locative
        # and the scope noun becomes a phantom entity that displaces a real one from the bounded
        # cross product, so the fragment is dropped instead.
        return ""
    if not member or not _IDEOGRAPH_RE.search(member):
        return ""
    if not (MIN_AXIS_MEMBER_CHARS <= len(member) <= MAX_ENTITY_CHARS):
        return ""
    if member in _GENERIC_STOPLIST or is_fact_text(member, category):
        return ""
    return member


def _bracketed_entities(text: str, category: str) -> list[str]:
    """Entity members from a parenthesised enumeration, or ``[]``.

    Preferred when present because its members are already bare nouns, and because it is what tells
    a scope noun from the enumeration: in "电缆附件（终端与接头）" the bracket carries the
    enumeration and 电缆附件 is the scope, so the scope never becomes a member.
    """
    for group in _PAREN_RE.findall(text):
        members: list[str] = []
        for raw in ENUMERATING_CONJUNCTION_RE.split(group):
            member = _trim_member(raw, category)
            if member and member not in members:
                members.append(member)
        if len(members) >= 2:
            return members
    return []


def _conjunction_entities(text: str, category: str) -> list[str]:
    """Entity members read from the sentence's enumeration structure, brackets not required.

    Every fragment between two structural boundaries is offered to :func:`_trim_member`; a fragment
    that is a fact type ("结构") or the question's scaffolding ("技术要求") is refused, and what
    survives is the entity axis in the order the question names it.
    """
    members: list[str] = []
    for raw in _FRAGMENT_SPLIT_RE.split(text):
        member = _trim_member(raw, category)
        if member and member not in members:
            members.append(member)
    return members


def read_axes(question: str) -> dict:
    """The two axes this rule can cross, or empty axes. Pure; no I/O, no model.

    ``reason`` is filled on every path where nothing is emitted, so a caller can report WHY the rule
    declined instead of guessing.
    """
    text = _clean(question)
    trace: dict = {"entities": [], "fact_types": [], "fact_keys": [], "reason": "", "profile": None}
    if not text:
        trace["reason"] = "empty_question"
        return trace

    # The domain is resolved from the question's FACT VOCABULARY, with the deployed classifier's
    # answer as a preference. Requiring a domain cue word here rejected questions that name two fact
    # types of the profile and no domain word at all (measured: V3, V5, V6), which is most of the
    # paraphrases this reader exists to cover.
    hint = classify_category(text)
    category, facts = resolve_domain(text, "" if hint == "unknown" else hint)
    if not category:
        trace["reason"] = "no_fact_enumeration"
        return trace
    trace["profile"] = category
    trace["profile_hint"] = hint
    trace["fact_types"] = [item["route_term"] for item in facts]
    trace["fact_keys"] = [item["key"] for item in facts]

    entities = _bracketed_entities(text, category)
    trace["entity_source"] = "bracketed" if entities else "conjunctions"
    if not entities:
        entities = _conjunction_entities(text, category)
    # Recorded BEFORE the gates so a declined question still reports what the reader saw; a caller
    # that only sees "no_fact_enumeration" cannot tell a question with one entity from one with four.
    trace["entities"] = entities[:MAX_AXIS_MEMBERS]

    if len(entities) < 2:
        trace["reason"] = "single_entity" if entities else "no_entity_enumeration"
        return trace

    trace["facts_ordered"] = [(item["route_term"], item["at"]) for item in facts][:MAX_AXIS_MEMBERS]
    return trace


def entity_fact_routes(question: str) -> tuple[list[str], dict]:
    """The bounded entity x fact-type cross product for ``question``.

    Route text is ``"<entity> <canonical fact term>"`` - the entity as the question names it, and the
    fact type as the CORPUS names it, so the route matches lexically without relying on a global
    synonym entry.
    """
    trace = read_axes(question)
    if trace["reason"]:
        return [], trace
    facts = [item["route_term"] for item in mentioned(_clean(question), trace["profile"])][:MAX_AXIS_MEMBERS]

    routes: list[str] = []
    for entity in trace["entities"]:
        for fact in facts:
            text = _clean(f"{entity} {fact}")[:MAX_SUB_QUERY_CHARS].strip()
            if text and text not in routes:
                routes.append(text)
    trace["reason"] = "expanded" if routes else "no_route_text"
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
    route allowance; when it is smaller than ``max_routes`` it wins, so a caller under its own route
    cap cannot be pushed past it by this rule.
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
