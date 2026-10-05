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
"""Module E — the deterministic retrieval planner (P1-2, Route B).

Before this module, the routes a retrieval turn executed were decided by a CHAT MODEL:
:func:`~rag.retrieval.decomposition.decompose_question` asked it for atomic sub-queries and the
pipeline concatenated whatever came back. P1-0 measured what that costs - six frozen queries,
ten cold-cache runs each, and every single one produced a different executable topology; two
non-composite controls oscillated between 0 and 1 routes, one comparative query's runs differed
by up to 8 routes, and the same six queries produced 23 distinct raw-output hashes against 19
canonical ones. The pipeline could not be replayed, so nothing downstream of it could be
compared or trusted.

This module moves the authority for TOPOLOGY from the model to the input:

    Normalised Input -> Deterministic Profiling -> Deterministic Ordered Slots
                     -> Canonical RetrievalPlan -> Validate -> plan_hash -> Cache/Execute

Three properties define the architecture, and they are the whole point of the change:

1. **Slot count, identity and order are functions of the input alone.** The profiler reads the
   question and nothing else. It declares an ordered list of slots - one per executable route -
   and each slot's canonical query text is built from the input's own tokens.
2. **The model cannot create, delete, reorder, rename or re-text a slot.** Its output is
   accepted only as PROVENANCE: which slots it happened to agree with is recorded, and a
   proposal that canonicalises to a slot's own text can only ever re-label that slot, never
   change it. A model proposal is therefore topology-inert by construction, not by discipline.
3. **Every failure collapses to the same input-derived plan.** There is no failure mode in
   which a missing, malformed, slow or absent model response produces a different topology: the
   plan is compiled BEFORE the model is consulted, and the fallback plan is the plan.

The rule the architecture obeys, stated so it can be checked rather than believed:

    Schema-valid is not topology-determined. A plan that parses can still differ in *how many*
    routes it has, *which* they are and *in what order* - and that triple is what retrieval
    topology means. Only an input-derived plan is stable in all three.

``plan_hash`` is computed over the CANONICAL ORDERED EXECUTABLE PLAN (P1-1 §3.3, rules S1-S6) and
never over a raw model response: raw hashing would report serialization noise as if it were a
topology change, which is precisely the 23-vs-19 over-report P1-0 measured.

Vocabulary discipline (P1-2 red line). This module introduces **no retrieval term of its own**.
Every pattern it reads the question with is imported from the existing deterministic classifier:

* :data:`~rag.retrieval.decomposition.ENUMERATING_CONJUNCTION_RE` — the enumerating slice of
  Module A's conjunction pattern, i.e. the conjunctions that put two noun phrases side by side;
* :data:`~rag.retrieval.decomposition.DISTRIBUTIVE_ADVERB_RE` — 同时/分别/各自, which say a clause
  is being distributed over an enumeration;
* :data:`~rag.retrieval.decomposition.CONJUNCTION_RE` and
  :data:`~rag.retrieval.decomposition.INTERROGATIVE_RE` — where a question's shared predicate
  begins;
* :func:`~rag.retrieval.chunk_profile.comparison_sides` and
  :func:`~rag.retrieval.chunk_profile.designation_spans` for the sides and the designations the
  input names, plus the existing :func:`~rag.retrieval.decomposition.clause_route` and
  :func:`~rag.retrieval.decomposition.comparative_routes` for the two deterministic routes the
  pipeline already had.

Extending that vocabulary is how new retrieval dimensions are meant to be added - reviewably, at
build time, under a bumped :data:`PLAN_VERSION` - and it is deliberately NOT part of P1-2.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any, Iterable, Sequence

from rag.retrieval.chunk_profile import comparison_sides, designation_spans, is_comparative_question
from rag.retrieval.decomposition import (
    CONJUNCTION_RE,
    DISTRIBUTIVE_ADVERB_RE,
    ENUMERATING_CONJUNCTION_RE,
    INTERROGATIVE_RE,
    MAX_SUB_QUERIES,
    MAX_SUB_QUERY_CHARS,
    clause_route,
    comparative_routes,
    decompose_question,
    mentions_requirement,
    seeks_clause,
    strip_section_references,
)

_LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Frozen contract
# ---------------------------------------------------------------------------

#: The semantics of the planner. A change to slot declaration, ordering, canonicalisation,
#: fallback or the profiler's vocabulary bumps this - and, per S6, :data:`PLAN_HASH_VERSION`.
PLAN_VERSION = "p1-2.0"

#: The CANONICALISATION + SERIALIZATION version (P1-1 §3.3, rule S6). Hashes from two different
#: versions are non-comparable by construction, so a hash never silently means two things.
PLAN_HASH_VERSION = "1"

#: Domain separator + field separator of the hash input (§3.3):
#: ``SHA-256("P1PLAN" 0x1F plan_hash_version 0x1F plan_version 0x1F canonical_json)``.
PLAN_HASH_DOMAIN = "P1PLAN"
PLAN_HASH_SEPARATOR = "\x1f"
PLAN_HASH_HEX_CHARS = 16

#: Slot kinds. The executable route list is closed over these; nothing else may execute.
KIND_BASE = "base"
KIND_DIMENSION = "dimension"
KIND_SIDE = "side"
KIND_CLAUSE = "clause"
SLOT_KINDS = (KIND_BASE, KIND_DIMENSION, KIND_SIDE, KIND_CLAUSE)

#: Where a slot's EXECUTED TEXT came from. Provenance only - excluded from ``plan_hash`` by
#: design, because two runs in which the model agreed with a slot and the model was silent must
#: hash identically: the executed plan is the same plan.
SOURCE_DETERMINISTIC = "deterministic"
SOURCE_MODEL_CANONICALISED = "model_canonicalised"
SOURCE_DETERMINISTIC_FALLBACK = "deterministic_fallback"
SLOT_SOURCES = (SOURCE_DETERMINISTIC, SOURCE_MODEL_CANONICALISED, SOURCE_DETERMINISTIC_FALLBACK)

#: Deterministic-fallback triggers (P1-1 §1.4). Bounded, closed, sorted, deduped when recorded.
T1_TRANSPORT = "T1"   # the model call failed, timed out, or returned something unparseable
T2_SCHEMA = "T2"      # the payload arrived but nothing usable survived parsing
T3_CLOSURE = "T3"     # non-empty proposals, none of which canonicalise into a declared slot
T4_MISMATCH = "T4"    # some proposals canonicalise into declared slots, some do not
T5_EMPTINESS = "T5"   # the compiled plan was empty where the input declared at least one slot
T6_NON_COMPOSITE = "T6"  # the input declares no decomposition, so the model is not consulted
FALLBACK_TRIGGERS = (T1_TRANSPORT, T2_SCHEMA, T3_CLOSURE, T4_MISMATCH, T5_EMPTINESS, T6_NON_COMPOSITE)

#: Cardinality freeze: the plan may never exceed this many executable routes. Slot declaration
#: is already bounded by the input (at most :data:`~rag.retrieval.decomposition.MAX_SUB_QUERIES`
#: dimensions), so this ceiling is a contract assertion rather than a routine truncation; when it
#: does fire the truncation keeps the earliest slots in canonical order and is recorded.
MAX_PLAN_ROUTES = 1 + MAX_SUB_QUERIES + 6 + 1

#: The base route is the user's own question and is never truncated. Derived routes are capped
#: at the same length the module-A sub-queries were capped at, so P1-2 changes the SOURCE of a
#: route's text, not its shape.
MAX_BASE_CHARS = 4096
MAX_DERIVED_CHARS = MAX_SUB_QUERY_CHARS

# ---------------------------------------------------------------------------
# Cache states (P1-1 §4)
# ---------------------------------------------------------------------------

CACHE_STATE_COLD_MISS = "cold_miss"
CACHE_STATE_WARM_HIT = "warm_hit"
CACHE_STATE_STALE_ENTRY = "stale_entry"
CACHE_STATE_UNAVAILABLE = "unavailable"
CACHE_STATE_DISABLED = "disabled"
CACHE_STATES = (
    CACHE_STATE_COLD_MISS,
    CACHE_STATE_WARM_HIT,
    CACHE_STATE_STALE_ENTRY,
    CACHE_STATE_UNAVAILABLE,
    CACHE_STATE_DISABLED,
)

#: Every stored plan lives under this prefix, so the planner's keys are greppable, auditable and
#: separable from every other Redis user (the LLM cache included).
CACHE_KEY_PREFIX = "p1plan"
CACHE_TTL_SECONDS = 7 * 24 * 3600

#: Environment controls. ``off`` disables the cache entirely (which is the fourth state of the
#: G2 matrix, and never a correctness change). A URL isolates the cache - the P1-2 gates point it
#: at a throwaway Redis so that no verification step can read or write the deployed one.
ENV_CACHE_MODE = "WENRUO_PLAN_CACHE"
ENV_CACHE_REDIS_URL = "WENRUO_PLAN_CACHE_REDIS_URL"
CACHE_MODE_OFF = "off"

# ---------------------------------------------------------------------------
# Canonicalisation (P1-1 §3.2, rules C1-C4 used as text operations)
# ---------------------------------------------------------------------------

_WHITESPACE_RE = re.compile(r"\s+")

#: Rule C3's set: sentence punctuation a question may open or close with. NFKC has already
#: folded the full-width forms onto their ASCII counterparts; both spellings are listed anyway so
#: the rule survives a future decision to canonicalise in another order.
_EDGE_PUNCTUATION = "？?。.！!，,、;；:： 　\u3000"

#: A dimension HEAD must name something. A head with no ideograph is a quantity or a bare
#: designation ("220kv"), never a dimension name, and the designation already reaches the route
#: through the anchor; dropping such a head is a Unicode property test, not a lexicon.
_IDEOGRAPH_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

MIN_DIMENSION_HEAD_CHARS = 2


class PlanSerializationError(ValueError):
    """The plan carried a value S1-S5 forbid (a float, ``null``, ``NaN``, a non-string key)."""


def canonical_text(text: Any) -> str:
    """Rules C1-C4: the canonical form of ONE route text.

    NFKC (C1), whitespace collapsed and trimmed (C2), leading/trailing sentence punctuation
    removed (C3), case folded (C4). Idempotent by construction - which is what lets a cached plan
    be re-validated on read (P1-1 §4) instead of trusted.
    """
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = _WHITESPACE_RE.sub(" ", value).strip()
    value = value.strip(_EDGE_PUNCTUATION)
    value = _WHITESPACE_RE.sub(" ", value).strip()
    return value.casefold()


# ---------------------------------------------------------------------------
# plan_hash serialization (P1-1 §3.3, rules S1-S5)
# ---------------------------------------------------------------------------


def _s3_value(value: Any, path: str) -> Any:
    """Enforce S2/S3 recursively: integers only, strings NFC-normalised, nothing else.

    ``null`` is rejected rather than passed through, so "the key is absent" is the only way to
    express absence and absent can never be confused with an empty string (S3: absent is not
    null). Floats, ``NaN`` and booleans are rejected because none of them is an integer and the
    plan has no business carrying one.
    """
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, bool):
        raise PlanSerializationError(f"S3: {path} is a boolean; the plan carries integers and strings only")
    if isinstance(value, int):
        return value
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise PlanSerializationError(f"S1: {path} has a non-string key {key!r}")
            out[unicodedata.normalize("NFC", key)] = _s3_value(item, f"{path}.{key}")
        return out
    if isinstance(value, (list, tuple)):
        return [_s3_value(item, f"{path}[{index}]") for index, item in enumerate(value)]
    raise PlanSerializationError(f"S3: {path} is {type(value).__name__}; the plan carries integers, strings, lists and objects only")


def canonical_json(value: Any) -> str:
    """Rules S1-S3: sorted keys, ``","``/``":"`` separators, no insignificant whitespace.

    ``ensure_ascii=False`` is deliberate: CJK route text stays as CJK, so the serialization is a
    function of the plan rather than of a locale or of a Python version's escaping table. JSON's
    own minimal escaping is the only escaping applied (S2).
    """
    return json.dumps(_s3_value(value, "$"), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def route_fingerprint(route: "PlanRoute") -> dict:
    """The hashed projection of one slot - identity, and nothing that is provenance."""
    return {
        "attribute_key": route.attribute_key,
        "kind": route.kind,
        "slot_id": route.slot_id,
        "text": route.text,
    }


def compute_plan_hash(
    routes: Sequence["PlanRoute"],
    *,
    plan_version: str = PLAN_VERSION,
    plan_hash_version: str = PLAN_HASH_VERSION,
) -> str:
    """S4/S5: hash the ORDERED route list, under the versioned domain-separated input.

    Order is inside the hash because the route list is serialized as a JSON array: a pure
    reordering with an identical set of routes produces a different ``plan_hash``, which is what
    makes G1's ordered requirement enforceable through the hash instead of through a comment.
    """
    payload = {"routes": [route_fingerprint(route) for route in routes]}
    body = canonical_json(payload)
    digest_input = PLAN_HASH_SEPARATOR.join((PLAN_HASH_DOMAIN, str(plan_hash_version), str(plan_version), body))
    return hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:PLAN_HASH_HEX_CHARS]


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanRoute:
    """One executable route: a slot, its identity, and the CANONICAL TEXT it executes.

    ``source`` is provenance and is excluded from :func:`route_fingerprint`; ``slot_id``,
    ``kind`` and ``attribute_key`` are identity and are included.
    """

    slot_id: str
    kind: str
    attribute_key: str
    text: str
    source: str = SOURCE_DETERMINISTIC


@dataclass(frozen=True)
class PlannerProvenance:
    """Everything about a plan that is NOT the plan.

    This is where the model's contribution lives, and it is deliberately inert: a reviewer can
    see what the model proposed, whether it agreed with any slot, how long it took and why the
    plan did not depend on it - and none of those fields can reach the executable route list.
    """

    consulted: bool = False
    proposals: tuple[str, ...] = ()
    accepted_slots: tuple[str, ...] = ()
    fallback_reasons: tuple[str, ...] = ()
    model_latency_ms: int | None = None
    cache_state: str = CACHE_STATE_DISABLED
    truncated: bool = False
    validation: str = "valid"

    def as_dict(self) -> dict:
        """A JSON-safe view, in the shape the (still gated) ``retrieval_plan`` event would take."""
        return {
            "consulted": self.consulted,
            "proposals": list(self.proposals),
            "accepted_slots": list(self.accepted_slots),
            "fallback_reasons": list(self.fallback_reasons),
            "model_latency_ms": self.model_latency_ms,
            "cache_state": self.cache_state,
            "truncated": self.truncated,
            "validation": self.validation,
        }


@dataclass(frozen=True)
class RetrievalPlan:
    """The canonical ordered executable plan, with its hash and its provenance."""

    routes: tuple[PlanRoute, ...]
    plan_version: str = PLAN_VERSION
    plan_hash_version: str = PLAN_HASH_VERSION
    plan_hash: str = ""
    provenance: PlannerProvenance = field(default_factory=PlannerProvenance)

    @property
    def topology_size(self) -> int:
        return len(self.routes)

    @property
    def texts(self) -> tuple[str, ...]:
        """The ordered route texts the retrieval layer executes."""
        return tuple(route.text for route in self.routes)

    def of_kind(self, kind: str) -> tuple[str, ...]:
        return tuple(route.text for route in self.routes if route.kind == kind)

    @property
    def slot_sources(self) -> tuple[str, ...]:
        """One source per slot, in order - the provenance the gated event would report."""
        return tuple(route.source for route in self.routes)

    def with_provenance(self, provenance: PlannerProvenance) -> "RetrievalPlan":
        """A new plan object carrying new provenance and the SAME routes, hash and versions.

        The signature is the guarantee: provenance is attached to a plan, it cannot be woven into
        one.
        """
        return replace(self, provenance=provenance)

    def as_cache_record(self) -> dict:
        """The only thing Redis is ever allowed to hold: an already-determined canonical plan."""
        return {
            "plan_hash": self.plan_hash,
            "plan_hash_version": self.plan_hash_version,
            "plan_version": self.plan_version,
            "routes": [route_fingerprint(route) for route in self.routes],
        }


# ---------------------------------------------------------------------------
# Deterministic profiling
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QuestionProfile:
    """What the INPUT declares, read deterministically and recorded for audit.

    ``dimension_heads`` is the ordered list of attributes the question names more than once - the
    slots the model used to paraphrase. ``predicate`` is the shared tail those attributes are
    asked about ("有什么技术要求"). Both are pure functions of the text.
    """

    question: str
    canonical_question: str
    designations: tuple[str, ...]
    sides: tuple[str, ...]
    dimension_heads: tuple[str, ...]
    predicate: str
    comparative: bool
    clause: bool
    requirement: bool
    composite: bool
    profile_key: str

    @property
    def declares_slots(self) -> bool:
        return bool(self.canonical_question)


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    out: list[str] = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return tuple(out)


def _tail_start(segment: str) -> int | None:
    """Where a dimension HEAD ends inside the last segment, or ``None`` if nothing ends it.

    The head ends at the first position the classifier's own patterns match - a conjunction
    (``CONJUNCTION_RE``) or an interrogative marker (``INTERROGATIVE_RE``). Reusing both keeps the
    profiler vocabulary-free: "铠装层分别有什么技术要求" yields the head 铠装层 because 分别 is a
    conjunction the classifier already knew about, not because the planner learned a new word.
    """
    starts = [match.start() for match in (CONJUNCTION_RE.search(segment), INTERROGATIVE_RE.search(segment)) if match]
    return min(starts) if starts else None


def _predicate_of(tail: str) -> str:
    """The shared predicate a distributed enumeration is asked about.

    A LEADING distributive adverb belongs to the enumeration and is dropped ("分别有什么技术
    要求" -> "有什么技术要求"); a LATER one opens a second clause and truncates ("要求分别是多少"
    -> "要求"). Both operations are pure text handling over a pattern the classifier already had.
    """
    text = DISTRIBUTIVE_ADVERB_RE.sub(" ", tail, count=1) if DISTRIBUTIVE_ADVERB_RE.match(tail) else tail
    following = DISTRIBUTIVE_ADVERB_RE.search(text)
    if following:
        text = text[: following.start()]
    return canonical_text(strip_section_references(text))[:MAX_DERIVED_CHARS].strip()


def dimension_heads(canonical_question: str) -> tuple[tuple[str, ...], str]:
    """Rules for reading the input's declared dimensions - deterministic, vocabulary-free.

    1. The question is split at the ENUMERATING conjunctions: the ones that put two noun phrases
       side by side. Fewer than two segments means the input declares no enumeration at all, and
       a question that declares one information need gets one route.
    2. The last segment also carries the shared PREDICATE; it is cut off at the first conjunction
       or interrogative marker and the remainder becomes the predicate the enumeration is asked
       about.
    3. Heads are canonicalised, normalised by the same :func:`strip_section_references` the
       module-A sub-queries were normalised by, then filtered: a head needs at least
       :data:`MIN_DIMENSION_HEAD_CHARS` characters, needs an ideograph, and is dropped if it is
       contained in another head.
    4. Fewer than two surviving heads is not an enumeration: the base route already carries them.

    The comparison SIDES are deliberately NOT removed before the split. Removing them was tried
    and rejected: it makes the reading of "…单芯和三芯海底电缆的内衬层要求…" collapse to a single
    head, loses the cable-type context from every head on the "Q/GDW … 220kV 单芯…的内衬层厚度和
    铠装层要求" shape, and needs a second rule to decide whether an enumeration was of sides or of
    dimensions. The cost of not removing them is one redundant route on the "A与B在X和Y上…" shape
    (C_MULTI in P1-0), which is a phrasing-quality matter that G4 gates - not a determinism matter.
    """
    segments = [segment.strip() for segment in ENUMERATING_CONJUNCTION_RE.split(canonical_question)]
    segments = [segment for segment in segments if segment]
    if len(segments) < 2:
        return (), ""

    last = segments[-1]
    cut = _tail_start(last)
    predicate = _predicate_of(last[cut:]) if cut is not None else ""
    raw_heads = list(segments[:-1])
    raw_heads.append(last[:cut] if cut is not None else last)

    heads: list[str] = []
    for raw in raw_heads:
        head = canonical_text(strip_section_references(raw))[:MAX_DERIVED_CHARS].strip()
        if len(head) < MIN_DIMENSION_HEAD_CHARS or not _IDEOGRAPH_RE.search(head):
            continue
        if head not in heads:
            heads.append(head)
    heads = [head for head in heads if not any(head != other and head in other for other in heads)]
    if len(heads) < 2:
        return (), ""
    return tuple(heads), predicate


def profile_question(question: str) -> QuestionProfile:
    """Read the input. Pure: no I/O, no model, no configuration, no clock, no randomness."""
    raw = _WHITESPACE_RE.sub(" ", str(question or "")).strip()
    canonical = canonical_text(raw)
    if not canonical:
        return QuestionProfile(
            question=raw,
            canonical_question="",
            designations=(),
            sides=(),
            dimension_heads=(),
            predicate="",
            comparative=False,
            clause=False,
            requirement=False,
            composite=False,
            profile_key="",
        )

    sides = _ordered_unique(canonical_text(side) for side in comparison_sides(canonical))
    designations = _ordered_unique(side for side in designation_spans(canonical))
    heads, predicate = dimension_heads(canonical)
    comparative = is_comparative_question(canonical)
    clause = seeks_clause(canonical)
    requirement = mentions_requirement(canonical)
    # The tightened classifier (P1-1 §5, rule P-c). The deployed gate let the model become
    # topology-authoritative on inputs that declare nothing to decompose, because it counted
    # interrogative MARKERS rather than information NEEDS: "Q/GDW 73286.2-2026 是什么标准？" carries
    # two markers (是什么, 标准) and zero second dimensions, and its route count oscillated 0/1.
    # Composite now means exactly "the input declares more than one executable dimension".
    composite = len(heads) >= 2 or comparative
    return QuestionProfile(
        question=raw,
        canonical_question=canonical,
        designations=designations,
        sides=sides,
        dimension_heads=heads,
        predicate=predicate,
        comparative=comparative,
        clause=clause,
        requirement=requirement,
        composite=composite,
        profile_key=hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16],
    )


# ---------------------------------------------------------------------------
# Deterministic compilation
# ---------------------------------------------------------------------------


def _dimension_text(head: str, predicate: str, designations: Sequence[str]) -> str:
    """Rule C6: the slot's canonical template form, built from input tokens only.

    An anchor (a designation the question names) is prepended when the head does not already
    carry it, and the shared predicate is appended. Every part comes from the input; nothing is
    invented and nothing is asked of a model.
    """
    parts = [token for token in designations if token and token not in head]
    parts.append(head)
    if predicate:
        parts.append(predicate)
    return canonical_text(" ".join(parts))[:MAX_DERIVED_CHARS].strip()


def compile_plan(profile: QuestionProfile) -> RetrievalPlan:
    """Rules C5-C7: the canonical ORDERED executable plan, from the profile alone.

    Order σ is fixed and input-derived: the base question route, then the declared dimensions in
    the order the input names them, then the comparative side routes, then the clause route. It is
    the order the pipeline used before P1-2, so the change is the SOURCE of the routes, not their
    arrangement.
    """
    candidates: list[tuple[str, str, str]] = []  # (kind, attribute_key, text)
    if profile.canonical_question:
        candidates.append((KIND_BASE, "question", profile.canonical_question[:MAX_BASE_CHARS]))
    for head in profile.dimension_heads:
        text = _dimension_text(head, profile.predicate, profile.designations)
        if text:
            candidates.append((KIND_DIMENSION, head, text))
    for route in comparative_routes(profile.canonical_question, profile.sides) if profile.comparative else []:
        text = canonical_text(route)
        if text:
            candidates.append((KIND_SIDE, text, text))
    clause = clause_route(profile.canonical_question)
    if clause:
        text = canonical_text(clause)
        if text:
            candidates.append((KIND_CLAUSE, text, text))

    # C5: drop empty and duplicate routes, keeping the first occurrence in canonical order.
    kept: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for kind, key, text in candidates:
        if text in seen:
            continue
        seen.add(text)
        kept.append((kind, key, text))

    truncated = len(kept) > MAX_PLAN_ROUTES
    if truncated:
        kept = kept[:MAX_PLAN_ROUTES]

    counters: dict[str, int] = {}
    routes: list[PlanRoute] = []
    for kind, key, text in kept:
        ordinal = counters.get(kind, 0)
        counters[kind] = ordinal + 1
        slot_id = kind if kind in (KIND_BASE, KIND_CLAUSE) else f"{kind}:{ordinal}"
        routes.append(PlanRoute(slot_id=slot_id, kind=kind, attribute_key=key, text=text))

    plan_hash = compute_plan_hash(routes)
    return RetrievalPlan(
        routes=tuple(routes),
        plan_hash=plan_hash,
        provenance=PlannerProvenance(truncated=truncated),
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanValidation:
    """``valid`` plus, when it is not, the single rule that failed - a closed reason set."""

    valid: bool
    reason: str = "valid"


def validate_routes(routes: Sequence[PlanRoute], *, plan_version: str, plan_hash_version: str, plan_hash: str) -> PlanValidation:
    """Re-check a plan against the contract, structurally. Used on compile AND on cache read.

    The read-path check is the defence-in-depth half of P1-1 §4: a stored value that fails any of
    these is treated as a MISS and recompiled deterministically, so a stale or poisoned entry can
    change availability but never correctness.
    """
    if plan_version != PLAN_VERSION:
        return PlanValidation(False, "plan_version_mismatch")
    if plan_hash_version != PLAN_HASH_VERSION:
        return PlanValidation(False, "plan_hash_version_mismatch")
    if not routes:
        return PlanValidation(False, "empty_plan")
    if len(routes) > MAX_PLAN_ROUTES:
        return PlanValidation(False, "topology_over_ceiling")
    seen: set[str] = set()
    for route in routes:
        if route.kind not in SLOT_KINDS:
            return PlanValidation(False, "unknown_kind")
        if route.source not in SLOT_SOURCES:
            return PlanValidation(False, "unknown_source")
        if not route.text:
            return PlanValidation(False, "empty_route_text")
        if route.text in seen:
            return PlanValidation(False, "duplicate_route_text")
        seen.add(route.text)
        # The executed text must already be canonical, or the plan does not describe what runs.
        if canonical_text(route.text) != route.text:
            return PlanValidation(False, "route_text_not_canonical")
        limit = MAX_BASE_CHARS if route.kind == KIND_BASE else MAX_DERIVED_CHARS
        if len(route.text) > limit:
            return PlanValidation(False, "route_text_over_limit")
        if not route.slot_id or not route.attribute_key:
            return PlanValidation(False, "missing_slot_identity")
    if compute_plan_hash(routes, plan_version=plan_version, plan_hash_version=plan_hash_version) != plan_hash:
        return PlanValidation(False, "plan_hash_mismatch")
    return PlanValidation(True)


def validate_plan(plan: RetrievalPlan) -> PlanValidation:
    """Re-check a whole plan object, hash recomputed from its own routes.

    Topology emptiness is not asserted here, because an empty question legitimately declares no
    slot; the rule "a declared slot may not vanish" belongs to compilation, where it is trigger
    ``T5`` in :func:`compile_retrieval_plan`.
    """
    check = validate_routes(
        plan.routes,
        plan_version=plan.plan_version,
        plan_hash_version=plan.plan_hash_version,
        plan_hash=plan.plan_hash,
    )
    if not check.valid:
        return check
    return PlanValidation(True)


def plan_from_routes(
    routes: Sequence[PlanRoute],
    *,
    plan_version: str = PLAN_VERSION,
    plan_hash_version: str = PLAN_HASH_VERSION,
    provenance: PlannerProvenance | None = None,
) -> RetrievalPlan:
    """Rebuild a plan object from stored routes, recomputing the hash rather than trusting it."""
    materialised = tuple(routes)
    return RetrievalPlan(
        routes=materialised,
        plan_version=plan_version,
        plan_hash_version=plan_hash_version,
        plan_hash=compute_plan_hash(materialised, plan_version=plan_version, plan_hash_version=plan_hash_version),
        provenance=provenance or PlannerProvenance(),
    )


# ---------------------------------------------------------------------------
# The model channel: provenance only
# ---------------------------------------------------------------------------


def provenance_from_proposal(
    plan: RetrievalPlan,
    profile: QuestionProfile,
    proposal: Any,
    *,
    latency_ms: int | None = None,
    consulted: bool = True,
    transport_failed: bool = False,
    initial_reasons: Sequence[str] = (),
) -> PlannerProvenance:
    """Turn a model response into provenance, and decide which fallback triggers it earned.

    A proposal is ACCEPTED for a slot when its canonical form equals that slot's own canonical
    text - in which case the slot is re-labelled ``model_canonicalised`` and its text is
    unchanged, because the text was already equal. Anything else is recorded and discarded. There
    is no third outcome: no code path here can produce a text, an identity, an order or a count.

    ``initial_reasons`` carries triggers that were already earned before the model was reached
    (T5), so the decision procedure below ADDS to the trace instead of replacing it.
    """
    reasons: set[str] = {reason for reason in initial_reasons if reason in FALLBACK_TRIGGERS}
    texts: list[str] = []
    raw_items = proposal if isinstance(proposal, (list, tuple)) else []

    if transport_failed:
        reasons.add(T1_TRANSPORT)
    for item in raw_items:
        text = canonical_text(item)
        if text and text not in texts:
            texts.append(text)
    if not transport_failed and not texts:
        # The call returned, but nothing usable survived parsing (empty, malformed, or the
        # server sent a shape with no route text in it).
        reasons.add(T2_SCHEMA)

    by_text = {route.text: route.slot_id for route in plan.routes}
    accepted = [by_text[text] for text in texts if text in by_text]
    if texts and not accepted:
        reasons.add(T3_CLOSURE)
    elif accepted and len(accepted) != len(texts):
        reasons.add(T4_MISMATCH)

    return PlannerProvenance(
        consulted=consulted,
        proposals=tuple(texts),
        accepted_slots=tuple(accepted),
        fallback_reasons=tuple(sorted(reasons, key=FALLBACK_TRIGGERS.index)),
        model_latency_ms=latency_ms,
        truncated=plan.provenance.truncated,
    )


#: The triggers under which a slot that the model did NOT agree with is labelled
#: ``deterministic_fallback`` rather than ``deterministic``: they are exactly the cases in which the
#: model was consulted and could not supply the slot, so the slot's text is the input-derived
#: fallback. T6 is excluded on purpose - there the model was never asked, so there is nothing to
#: fall back FROM.
FALLBACK_LABELLING_TRIGGERS = (T1_TRANSPORT, T2_SCHEMA, T3_CLOSURE, T4_MISMATCH, T5_EMPTINESS)


def source_labelled(plan: RetrievalPlan, provenance: PlannerProvenance) -> RetrievalPlan:
    """The plan with the per-slot source labels applied - same routes, same hash, same version.

    ``model_canonicalised`` marks a slot the model happened to propose in its own canonical form;
    ``deterministic_fallback`` marks the other slots of a plan whose model channel failed
    (T1-T5); ``deterministic`` is the default. ALL THREE are provenance: the hash is computed over
    identity and text only, and the assertion below fails loudly if a future edit ever let a label
    reach it.
    """
    accepted = set(provenance.accepted_slots)
    falling_back = any(reason in FALLBACK_LABELLING_TRIGGERS for reason in provenance.fallback_reasons)
    if not accepted and not falling_back:
        return plan.with_provenance(provenance)

    def label(route: PlanRoute) -> PlanRoute:
        if route.slot_id in accepted:
            return replace(route, source=SOURCE_MODEL_CANONICALISED)
        if falling_back:
            return replace(route, source=SOURCE_DETERMINISTIC_FALLBACK)
        return replace(route, source=SOURCE_DETERMINISTIC)

    routes = tuple(label(route) for route in plan.routes)
    if compute_plan_hash(routes) != plan.plan_hash:
        raise PlanSerializationError("provenance re-labelling changed plan_hash")
    return replace(plan, routes=routes, provenance=provenance)


# ---------------------------------------------------------------------------
# Cache (P1-1 §4)
# ---------------------------------------------------------------------------


def cache_key(canonical_question: str, scope: Sequence[str] = (), *, plan_version: str = PLAN_VERSION, plan_hash_version: str = PLAN_HASH_VERSION) -> str:
    """``(plan_hash_version, plan_version, scope, canonical question)`` -> one key.

    The scope carries the tenant/workspace, the knowledge-base set and the frozen-config digest,
    so two assistants that configure retrieval differently cannot read each other's plan.
    """
    question_digest = hashlib.sha256(canonical_question.encode("utf-8")).hexdigest()[:24]
    scope_digest = hashlib.sha256("\x1f".join(str(part) for part in scope).encode("utf-8")).hexdigest()[:16]
    return f"{CACHE_KEY_PREFIX}:{plan_hash_version}:{plan_version}:{scope_digest}:{question_digest}"


class PlanCache:
    """A cache of DETERMINED canonical plans, which re-validates everything it reads.

    Redis's role changes here. It used to be what made the pipeline look reproducible - whichever
    random result arrived first got frozen and replayed. It is now a cache of an artifact that is
    deterministic without it: a cold miss, a warm hit, a stale entry and an unavailable cache all
    produce the same ordered topology and the same ``plan_hash``, so the cache buys latency and
    nothing else (P1-1 §4).
    """

    def __init__(self, client: Any = None, *, prefix: str = CACHE_KEY_PREFIX, ttl: int = CACHE_TTL_SECONDS) -> None:
        self._client = client
        self._prefix = prefix
        self._ttl = ttl

    @property
    def available(self) -> bool:
        return self._client is not None

    def _key(self, canonical_question: str, scope: Sequence[str]) -> str:
        key = cache_key(canonical_question, scope)
        if self._prefix == CACHE_KEY_PREFIX:
            return key
        return key.replace(f"{CACHE_KEY_PREFIX}:", f"{self._prefix}:", 1)

    def load(self, canonical_question: str, scope: Sequence[str] = (), expected: RetrievalPlan | None = None) -> tuple[RetrievalPlan | None, str]:
        """``(plan or None, state)``. Never raises: a broken cache is a miss, not an outage.

        ``expected`` is the plan this process just compiled from the input. When it is supplied, a
        stored entry must match it ROUTE FOR ROUTE - identity, text and order - or it is rejected as
        a stale entry. That closes the one hole a self-consistent forgery would otherwise walk
        through: an entry whose routes and hash agree with each other but not with the input. It
        also catches a plan compiled under a different configuration, and (via the version checks)
        an entry written by an older ``plan_version``.
        """
        if not self.available:
            return None, CACHE_STATE_DISABLED
        try:
            raw = self._client.get(self._key(canonical_question, scope))
        except Exception as exc:  # noqa: BLE001 - a cache is never allowed to fail a retrieval
            _LOG.warning("[Planner] plan cache read failed; treating as unavailable: %s", exc)
            return None, CACHE_STATE_UNAVAILABLE
        if raw is None:
            return None, CACHE_STATE_COLD_MISS
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")

        record = None
        try:
            record = json.loads(raw)
        except Exception:  # noqa: BLE001
            record = None
        if not isinstance(record, dict):
            return None, CACHE_STATE_STALE_ENTRY

        stored_version = str(record.get("plan_version", ""))
        stored_hash_version = str(record.get("plan_hash_version", ""))
        stored_hash = str(record.get("plan_hash", ""))
        raw_routes = record.get("routes")
        if not isinstance(raw_routes, list) or not raw_routes:
            return None, CACHE_STATE_STALE_ENTRY
        try:
            routes = tuple(
                PlanRoute(
                    slot_id=str(item["slot_id"]),
                    kind=str(item["kind"]),
                    attribute_key=str(item["attribute_key"]),
                    text=str(item["text"]),
                )
                for item in raw_routes
            )
        except Exception:  # noqa: BLE001
            return None, CACHE_STATE_STALE_ENTRY

        # Re-canonicalise and re-validate on READ (P1-1 §4): the stored hash is recomputed from
        # the stored routes, so an entry whose text or order was edited in Redis cannot be served.
        if compute_plan_hash(routes, plan_version=stored_version, plan_hash_version=stored_hash_version) != stored_hash:
            return None, CACHE_STATE_STALE_ENTRY
        check = validate_routes(routes, plan_version=stored_version, plan_hash_version=stored_hash_version, plan_hash=stored_hash)
        if not check.valid:
            _LOG.warning("[Planner] stored plan under %s rejected on read: %s", self._key(canonical_question, scope), check.reason)
            return None, CACHE_STATE_STALE_ENTRY
        if expected is not None and [route_fingerprint(route) for route in routes] != [route_fingerprint(route) for route in expected.routes]:
            _LOG.warning(
                "[Planner] stored plan under %s does not match the plan this input compiles to; treating it as a miss",
                self._key(canonical_question, scope),
            )
            return None, CACHE_STATE_STALE_ENTRY
        return (
            plan_from_routes(routes, plan_version=stored_version, plan_hash_version=stored_hash_version, provenance=PlannerProvenance(cache_state=CACHE_STATE_WARM_HIT)),
            CACHE_STATE_WARM_HIT,
        )

    def store(self, plan: RetrievalPlan, canonical_question: str, scope: Sequence[str] = ()) -> bool:
        """Store ONLY an already-determined canonical plan. Never a raw model response."""
        if not self.available or not plan.routes:
            return False
        try:
            self._client.set(self._key(canonical_question, scope), canonical_json(plan.as_cache_record()), ex=self._ttl)
            return True
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("[Planner] plan cache write failed; continuing without it: %s", exc)
            return False


def cache_scope(
    tenant_ids: Sequence[Any] = (),
    kb_ids: Sequence[Any] = (),
    config: Sequence[tuple[str, Any]] = (),
) -> tuple[str, ...]:
    """The scope half of the cache key: who is asking, about which corpora, under which config.

    Sorted and stringified, so two requests that configure retrieval identically share a plan and
    two that do not never do. The config digest is what keeps a plan compiled under one set of
    frozen retrieval parameters from being replayed under another.
    """
    return (
        "tenants=" + ",".join(sorted(str(item) for item in tenant_ids)),
        "kbs=" + ",".join(sorted(str(item) for item in kb_ids)),
        "config=" + ",".join(f"{key}={value}" for key, value in sorted((str(key), value) for key, value in config)),
    )


@lru_cache(maxsize=1)
def resolve_plan_cache() -> PlanCache | None:
    """The cache the retrieval path uses, or ``None`` when it is switched off.

    ``WENRUO_PLAN_CACHE=off`` disables it (a supported state: correctness does not depend on the
    cache). ``WENRUO_PLAN_CACHE_REDIS_URL`` points it at a specific Redis, which is how the P1-2
    gates exercise all four cache states without reading or writing the deployed instance.
    Otherwise the application's own Redis is used, under the ``p1plan:`` prefix.

    Resolved once per process: the value is a connection, and re-deciding it per retrieval would
    put an environment lookup and a client construction on the hot path for no benefit. Call
    ``resolve_plan_cache.cache_clear()`` to re-resolve.
    """
    if str(os.environ.get(ENV_CACHE_MODE, "")).strip().lower() == CACHE_MODE_OFF:
        return None
    url = str(os.environ.get(ENV_CACHE_REDIS_URL, "")).strip()
    if url:
        try:
            # The application talks to Redis through `valkey` (see rag/utils/redis_conn.py); the
            # `redis` package is the same client under its older name and is not installed here.
            try:
                import valkey as redis_client  # type: ignore
            except ImportError:
                import redis as redis_client  # type: ignore

            return PlanCache(redis_client.Redis.from_url(url, decode_responses=True))
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("[Planner] %s is set but unusable (%s); continuing without a plan cache", ENV_CACHE_REDIS_URL, exc)
            return None
    try:
        from rag.utils.redis_conn import REDIS_CONN  # type: ignore

        return PlanCache(REDIS_CONN)
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("[Planner] no Redis available for the plan cache (%s); continuing without it", exc)
        return None


# ---------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------


def _annotate(plan: RetrievalPlan, provenance: PlannerProvenance) -> RetrievalPlan:
    return replace(plan, provenance=provenance)


async def compile_retrieval_plan(
    *,
    question: str,
    chat_mdl: Any = None,
    max_sub_queries: int = MAX_SUB_QUERIES,
    plan_cache: PlanCache | None = None,
    cache_scope: Sequence[str] = (),
    consult_model: bool = True,
    use_cache: bool = True,
    injected_proposal: Any = None,
) -> RetrievalPlan:
    """Compile the plan for ``question``, then - and only then - consult the model.

    The order is the architecture, not a detail. The plan exists, hashed, before the model is
    asked anything, so no model behaviour can reach it: a timeout, a malformed payload, an empty
    list or a confident hallucination all land in ``plan.provenance`` and nowhere else.

    The cache sits AFTER compilation and BEFORE the model, which is the only place it can be both
    useful and honest:

    * it is asked for the plan this input compiles to (``expected=``), so an entry that disagrees
      with the input is a miss - a stale configuration, a stale version or a forgery can never be
      served;
    * a hit therefore lets the turn SKIP the model consultation, which under Route B is the only
      cost left on this path (the compilation itself is a few regexes and a hash);
    * a miss is a normal, fully supported state, and changes nothing but that cost.

    ``injected_proposal`` replaces the model call with a supplied response, which is how the
    offline gates feed several legal model outputs to one input; it changes provenance only. A warm
    hit skips it, exactly as it skips a real call.
    """
    profile = profile_question(question)
    cache = plan_cache if use_cache else None

    plan = compile_plan(profile)

    prior_reasons: tuple[str, ...] = ()
    if not plan.routes and profile.declares_slots:
        # T5, defensive: a declared slot may not vanish. Reconstruct the one route the input always
        # determines, so even an internal contradiction yields a deterministic plan. The reason is
        # carried forward into whatever provenance is built below rather than being lost here.
        _LOG.error("[Planner] the compiled plan was empty for a question that declares slots; using the input-derived base route")
        plan = plan_from_routes(
            (PlanRoute(slot_id=KIND_BASE, kind=KIND_BASE, attribute_key="question", text=profile.canonical_question[:MAX_BASE_CHARS]),),
            provenance=PlannerProvenance(cache_state=CACHE_STATE_DISABLED if cache is None else CACHE_STATE_COLD_MISS),
        )
        prior_reasons = (T5_EMPTINESS,)

    cache_state = CACHE_STATE_DISABLED if cache is None else CACHE_STATE_COLD_MISS
    if cache is not None:
        stored, state = cache.load(profile.canonical_question, cache_scope, expected=plan)
        cache_state = state
        if stored is not None:
            # Byte-identical to what this input compiles to, so there is nothing to compile, nothing
            # for the model to add and no reason to pay for the call.
            _LOG.info(
                "[Planner] plan cache hit: hash=%s slots=%d question=%r (model not consulted)",
                stored.plan_hash,
                stored.topology_size,
                profile.canonical_question[:80],
            )
            return stored

    provenance = PlannerProvenance(cache_state=cache_state, truncated=plan.provenance.truncated, fallback_reasons=prior_reasons)

    if not profile.composite:
        # T6 (P1-1 §5): the input declares no decomposition, so the model is not consulted at all.
        # This is what makes the P1-0 [0, 1] route-count jitter on the non-composite controls
        # structurally impossible rather than merely unobserved.
        provenance = replace(
            provenance,
            fallback_reasons=tuple(sorted((*provenance.fallback_reasons, T6_NON_COMPOSITE), key=FALLBACK_TRIGGERS.index)),
        )
        plan = _annotate(plan, provenance)
    elif injected_proposal is not None or (consult_model and chat_mdl is not None):
        started = time.perf_counter()
        transport_failed = False
        if injected_proposal is not None:
            proposal = injected_proposal
        else:
            outcome: dict = {}
            try:
                proposal = await decompose_question(chat_mdl, profile.canonical_question, max_sub_queries, outcome=outcome)
            except Exception as exc:  # noqa: BLE001 - the model is never allowed to fail a retrieval
                _LOG.warning("[Planner] model consultation failed; the plan does not depend on it: %s", exc)
                proposal, transport_failed = [], True
            else:
                # T1 vs T2 is only decidable at the boundary where the call actually happened, so
                # `decompose_question` reports it back rather than leaving the planner to guess.
                transport_failed = outcome.get("error") == "transport"
        latency_ms = max(0, int(round((time.perf_counter() - started) * 1000)))
        provenance = provenance_from_proposal(
            plan, profile, proposal, latency_ms=latency_ms, transport_failed=transport_failed, initial_reasons=prior_reasons
        )
        provenance = replace(provenance, cache_state=cache_state)
        plan = source_labelled(plan, provenance)
    else:
        plan = _annotate(plan, provenance)

    if cache is not None:
        cache.store(plan, profile.canonical_question, cache_scope)

    _LOG.info(
        "[Planner] question=%r -> %d route(s) hash=%s slots=%s sources=%s cache=%s triggers=%s",
        profile.canonical_question[:80],
        plan.topology_size,
        plan.plan_hash,
        [route.slot_id for route in plan.routes],
        list(plan.slot_sources),
        cache_state,
        list(plan.provenance.fallback_reasons),
    )
    return plan
