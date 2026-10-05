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
"""Per-domain fact vocabulary: what a question asks ABOUT, and the term the CORPUS uses for it.

This is the domain layer. The generic axis reader (:mod:`rag.retrieval.route_expansion`) holds no
vocabulary of its own - it asks this module "which fact types does this question name, and what
should a route call them?" and gets back canonical terms.

WHY A CANONICAL ROUTE TERM, NOT THE USER'S WORDS
================================================

Measured on this corpus (317 chunks), for the design-life fact type:

    user phrasings        设计使用寿命 0 · 设计寿命 0 · 使用寿命 0 chunks
    corpus phrasing       设计使用年限 20 chunks · 使用年限 20 chunks
    bare 寿命             26 chunks, including clauses unrelated to attachment life

A route built from the user's own wording therefore carries a term the corpus does not contain, and
retrieves on the dense leg alone - which this corpus's flat cosine separation (~0.0145 between the
two competing halves) cannot be trusted to resolve. A route built from ``route_term`` matches
lexically. Mapping the surface form to the corpus term here, in the domain layer, is also what keeps
bare ``寿命`` OUT of the global synonym dictionary: the canonicalisation is scoped to route
construction and cannot affect an unrelated question's tokens.

A cue must be a phrase that only a question about that fact type would contain. Bare ``寿命`` is
listed because it is unambiguous IN A CABLE STANDARD question, and because it is resolved to a
canonical term here rather than expanded globally.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Domains are keyed by the SAME category string the deployed
#: :func:`rag.nlp.retrieval_projection.classify_category` returns, so the domain is chosen by the
#: existing profile table rather than by a second classifier.
POWER_CABLE = "power_cable"


@dataclass(frozen=True)
class FactType:
    """One thing a question can ask about."""

    key: str
    #: Surface forms a question may use. Longer forms first, so an earlier cue cannot mask a later,
    #: more specific one when both occur at the same offset.
    cues: tuple[str, ...]
    #: The term a supplemental route carries, spelled the way the CORPUS spells it.
    route_term: str


FACT_TYPES: dict[str, tuple[FactType, ...]] = {
    POWER_CABLE: (
        FactType(
            key="design_life",
            cues=(
                "设计使用寿命",
                "设计使用年限",
                "设计寿命",
                "使用寿命",
                "使用年限",
                "使用年数",
                "使用多少年",
                "能用多少年",
                "多少年",
                "寿命年限",
                "寿命",
                "年限",
            ),
            route_term="设计使用年限",
        ),
        FactType(
            key="structure",
            cues=("结构图纸", "结构要求", "结构尺寸", "结构"),
            route_term="结构",
        ),
    ),
}


def fact_types(category: str) -> tuple[FactType, ...]:
    """The fact types declared for a domain, or ``()`` for a domain with none."""
    return FACT_TYPES.get(str(category or ""), ())


def mentioned(question: str, category: str) -> list[dict]:
    """Which declared fact types ``question`` names, in the order it names them.

    Each entry is ``{"key", "route_term", "cue", "at"}``. A fact type is reported once, at the
    offset of the EARLIEST cue that matches it, and the list is ordered by that offset so the
    question's own ordering ("结构以及设计使用年限") survives into the route order.
    """
    text = str(question or "")
    if not text:
        return []
    found: list[dict] = []
    for fact in fact_types(category):
        best: tuple[int, str] | None = None
        for cue in fact.cues:
            at = text.find(cue)
            if at >= 0 and (best is None or at < best[0]):
                best = (at, cue)
        if best is not None:
            found.append({"key": fact.key, "route_term": fact.route_term, "cue": best[1], "at": best[0]})
    found.sort(key=lambda item: item["at"])
    return found


def resolve_domain(question: str, hint: str = "") -> tuple[str, list[dict]]:
    """The domain a question's FACT VOCABULARY belongs to, and the fact types it named.

    The domain is identified by the vocabulary rather than by a mention of the domain's own name.
    Requiring a cue word ("电缆" / "海缆") was measured to reject legitimate questions about the same
    corpus - "终端与接头能使用多少年？结构上有什么规定？" names two fact types of the cable profile
    and no cable word at all - so the fact table itself is the evidence: a question that names two or
    more fact types of one domain is asking in that domain.

    ``hint`` is the category the deployed domain classifier returned, and is preferred when it is
    consistent with the fact vocabulary, so a question that DOES name its domain keeps that domain
    and its profile.
    """
    text = str(question or "")
    candidates: list[tuple[str, list[dict]]] = []
    for category in FACT_TYPES:
        facts = mentioned(text, category)
        if len(facts) >= 2:
            candidates.append((category, facts))
    if not candidates:
        return "", []
    for category, facts in candidates:
        if category == str(hint or ""):
            return category, facts
    return candidates[0]



def is_fact_text(fragment: str, category: str) -> bool:
    """Whether a fragment is part of a fact type rather than a nameable entity.

    Used by the entity reader to refuse a fact as an axis member ("结构" is a fact type, not an
    object the question is about).
    """
    text = str(fragment or "")
    if not text:
        return False
    return any(cue in text for fact in fact_types(category) for cue in fact.cues)
