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
"""Module C — rerank the merged pool against the original question and cut the
context the answer model receives.

Two decisions here are what separate this stage from the fused score the routes
computed:

* the query handed to the reranker is the user's ORIGINAL question, not a
  sub-query. The sub-queries exist to make recall per topic possible; relevance
  to what was actually asked is what decides which passages reach the answer, so
  a passage that only answers part of the question is not silently promoted
  because some sub-query matched it alone;
* the reranker's own score replaces the fused score instead of being averaged
  with it. The fused score's text leg is a query-recall ratio, and for a
  multi-dimensional question that ratio penalizes every passage for the
  dimensions it does not cover - the same dilution that motivated module A.
  ``fused_similarity`` keeps the pre-rerank value for diagnosis.

Without a reranker (a tenant with none configured, or a reranker that fails) the
pool is returned ordered by the fused score, so the answer still gets the routes'
own best passages.

The CUT is not a plain top-N, and that is the third decision here. A composite
question's routes recall different chapters, and those chapters do not score
equally against the whole question: measured on the cable corpus with a
five-parameter question, twelve near-identical parameter tables of the dimension
the question leads with scored 0.596-0.603 and filled all twelve slots, while the
``6.2.3 交流电压试验`` clause the corpus does hold sat at 0.577 and was dropped -
the same "the window is filled by one topic" failure the routes exist to undo,
one stage later. One slot per route is therefore reserved before the remaining
slots take the highest scoring passages left.

The fourth decision is about passage TYPE, and it is the one four live smoke
tests turned up. A 专用技术规范's bidder fill-in tables repeat every parameter
name and unit a question uses, so they out-score the normative prose of the
通用技术规范 and take the whole window; the answer layer then reports "只有表格，
没有正文规定" for a question whose clause IS in the corpus. When the question asks
for a rule (``seeks_clause``), the cut therefore reserves a PROSE floor, caps how
much of the window tables may take, and orders the pool with a small table
penalty (:class:`DiversityPolicy`). Nothing here can invent a prose passage that
never entered the pool - that is a recall failure and is reported as one.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Sequence

from common.misc_utils import thread_pool_exec
from rag.retrieval.chunk_profile import (
    document_breakdown,
    document_key,
    document_name,
    is_comparative_question,
    is_prose_chunk,
    is_table_chunk,
    resolve_compared_documents,
    resolve_core_documents,
    summarize,
)
from rag.retrieval.decomposition import mentions_requirement, seeks_clause
from rag.retrieval.multi_route import chunk_key

_LOG = logging.getLogger(__name__)

#: Passages kept for the answer. The recommended band is 6-8; a configured
#: ``top_n`` always wins (the cable assistant sets 12 for a measured reason - see
#: ``api/db/cable_defaults.py``).
DEFAULT_FINAL_TOP_N = 8
FINAL_TOP_N_RECOMMENDED = (6, 8)

#: Room the context must leave for prose when the question asks for a rule.
#: 4 is the "3-4 slots for the 通用技术规范 clause" the smoke tests asked for, and
#: it is affordable inside both the 6-8 band and the cable assistant's 12.
MIN_PROSE_PASSAGES = 4
#: Share of the window tables may take at most, for the same question shape.
MAX_TABLE_SHARE = 0.5
#: Ordering nudge for a tabular passage: enough to put a comparable prose clause
#: first, not enough to reorder passages whose scores actually differ.
TABLE_PENALTY = 0.85
#: Share of the window ONE auxiliary document may take.
#:
#: Document flooding, measured: nine recalled passages, seven of them from
#: 《20_架空绝缘导线抽检工作规范.pdf》 (22,684 characters) and two from the standard
#: the question was about (1,130 characters). A working document whose whole text
#: repeats 例行试验 out-scores the clause that defines the test, and a plain
#: top-N then hands the answer model the working document and little else.
#: 0.4 is the generous end of the 30-40% band, so an auxiliary file still
#: contributes while it cannot own the window. The standard itself is exempt:
#: the earlier milestone's winning answer came from eleven passages of ONE
#: document and must keep doing so.
MAX_AUXILIARY_DOCUMENT_SHARE = 0.4
#: Ordering nudge for a passage from the standard the question is about.
CORE_DOCUMENT_BOOST = 1.15
#: Share of the window ONE document may take when the question COMPARES documents.
#:
#: Measured: "…单芯与三芯要求是否一致？" over 《Q/GDW 73286.2 第2部分(单芯)》 and
#: 《Q/GDW 73286.3 第3部分(三芯)》 recalled Part 2 only. Both files are standards, so
#: the auxiliary quota above never applied to either, and Part 2's higher-scoring table
#: - split into row-batches, so a dozen near-identical passages - owned the window. The
#: comparison cannot be answered from one side, so when the question names two sides and
#: the pool holds both documents, no single one may take more than this: the other side
#: keeps the rest even when it scores lower. Non-comparative questions are untouched,
#: including the earlier milestone's winning eleven-passage single-document answer.
MAX_COMPARED_DOCUMENT_SHARE = 0.5


@dataclass(frozen=True)
class DiversityPolicy:
    """How the context cut balances passage TYPE and DOCUMENT.

    Two strengths on the type axis, because the two intents differ. A RULE
    question ("例行交流电压试验的维持时间是多少", "两份规范对不上时以谁为准") gets the
    full policy: a window reserved for prose is the only way it gets answered,
    since a fill-in table cannot state a rule. A question that merely mentions a
    requirement or a test gets the ordering nudge alone - a parameter table IS
    the right source for 绝缘电阻试验的数值是多少, so its window is not reserved for
    prose.

    On the document axis the policy applies ONLY when the corpus advertises a
    standard (``core_documents``): a per-document quota for the auxiliary files,
    and a boost for the standard itself. A corpus that identifies no standard
    (supplier datasheets, product manuals, test reports) keeps a plain top-N - a
    quota invented for a corpus we could not read would truncate exactly the
    answer it was meant to protect.

    A COMPARATIVE question adds one axis, because it is the one shape where the
    standard-is-exempt rule is wrong: two standards are being read against each
    other, and the one that scores higher (its table split into row-batches, so many
    near-identical passages) must not own the window. When the question names two
    sides and the pool holds the documents those sides point at, no single document
    may take more than :data:`MAX_COMPARED_DOCUMENT_SHARE` of it and each of those
    documents is reserved a slot (see :func:`select_context`).
    """

    min_prose: int = 0
    max_table_share: float = 1.0
    table_penalty: float = 1.0
    max_auxiliary_document_share: float = 1.0
    core_document_boost: float = 1.0
    core_documents: frozenset[str] = frozenset()
    max_document_share: float = 1.0
    compared_documents: frozenset[str] = frozenset()

    @classmethod
    def for_question(cls, question: str, chunks: Sequence[dict] = ()) -> "DiversityPolicy":
        core = frozenset(resolve_core_documents(chunks, question))
        compared = frozenset(resolve_compared_documents(chunks, question)) if is_comparative_question(question) else frozenset()
        document_axes = {
            "max_auxiliary_document_share": MAX_AUXILIARY_DOCUMENT_SHARE if core else 1.0,
            "core_document_boost": CORE_DOCUMENT_BOOST if core else 1.0,
            "core_documents": core,
            # Two documents actually present is what makes a comparison answerable;
            # a question that names two sides the corpus does not separate keeps the
            # plain behaviour rather than capping the only document there is.
            "max_document_share": MAX_COMPARED_DOCUMENT_SHARE if len(compared) >= 2 else 1.0,
            "compared_documents": compared if len(compared) >= 2 else frozenset(),
        }
        if seeks_clause(question):
            return cls(
                min_prose=MIN_PROSE_PASSAGES,
                max_table_share=MAX_TABLE_SHARE,
                table_penalty=TABLE_PENALTY,
                **document_axes,
            )
        return cls(
            table_penalty=TABLE_PENALTY if mentions_requirement(question) else 1.0,
            **document_axes,
        )

    @property
    def active(self) -> bool:
        return (
            self.min_prose > 0 or self.max_table_share < 1.0 or self.table_penalty != 1.0 or self.max_auxiliary_document_share < 1.0 or self.core_document_boost != 1.0 or self.max_document_share < 1.0
        )

    def is_core_document(self, chunk: dict) -> bool:
        """Whether ``chunk`` belongs to the standard this question is about.

        A passage with no document identity belongs to no auxiliary file, so it is
        treated as core: an unidentifiable passage must never be charged against a
        quota it cannot be counted against.
        """
        key = document_key(chunk)
        return True if not key else key in self.core_documents

    def is_compared_document(self, chunk: dict) -> bool:
        """Whether ``chunk`` belongs to one of the documents a comparison names."""
        key = document_key(chunk)
        return bool(key) and key in self.compared_documents


def _score(chunk: dict, *, key: str = "similarity") -> float:
    try:
        return float(chunk.get(key) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def apply_rank_adjustments(chunks: Sequence[dict], policy: DiversityPolicy) -> list[dict]:
    """Order the pool by its score, nudged by passage type and by document.

    Writes ``rank_score`` (the value the cut orders by) and leaves the model's own
    numbers untouched: ``similarity`` still means what the reranker or the fused
    score said, so a transcript can tell a relevance decision from a tie-break.
    """
    for chunk in chunks:
        base = _score(chunk, key="rerank_score") or _score(chunk)
        penalty = policy.table_penalty if is_table_chunk(chunk) else 1.0
        boost = policy.core_document_boost if policy.is_core_document(chunk) else 1.0
        chunk["rank_score"] = base * penalty * boost
    return sorted(chunks, key=lambda chunk: _score(chunk, key="rank_score"), reverse=True)


def dedupe_chunks(chunks: Sequence[dict]) -> list[dict]:
    """Drop repeated ``chunk_id``s, keeping the first occurrence.

    The pool arriving here was already merged across routes, so a duplicate now
    can only come from a caller assembling its own pool (e.g. a web-search
    passage that repeats a document passage). Order is preserved so the
    pre-rerank ordering stays meaningful for ties and for the no-reranker path.
    """
    seen: set[str] = set()
    out: list[dict] = []
    for chunk in chunks or []:
        key = chunk_key(chunk)
        if key in seen:
            continue
        seen.add(key)
        out.append(chunk)
    return out


def routes_of(chunk: dict) -> list[str]:
    """The routes that recalled ``chunk`` (empty for a passage from elsewhere)."""
    routes = chunk.get("retrieval_routes")
    return [str(route) for route in routes] if isinstance(routes, list) else []


def ensure_route_coverage(ordered: Sequence[dict], top_n: int) -> list[dict]:
    """Cut ``ordered`` to ``top_n`` while keeping every route represented.

    A pool with fewer passages than slots, or one that came from a single route,
    is cut the ordinary way - there is nothing to balance. This is
    :func:`select_context` with an inert policy; see it for the reservation order
    and for the type floor a rule-seeking question adds.
    """
    return select_context(ordered, top_n)


def select_context(ordered: Sequence[dict], top_n: int, policy: DiversityPolicy = DiversityPolicy()) -> list[dict]:
    """Cut a score-ordered pool to ``top_n``, reserving slots before filling.

    ``ordered`` is score-ordered and is NOT truncated before this runs: the
    passage a reservation exists for can sit below the cut, which is exactly the
    case this is for. Slots are handed out in priority order:

    1. one slot per route, so a composite question's chapters are all
       represented (the failure the routes themselves exist to undo, one stage
       later), and one slot per document a COMPARATIVE question names;
    2. the prose floor, when the question asks for a rule: normative clauses
       first, because a parameter table cannot state one;
    3. everything else by score - non-table passages first, then tables up to
       ``policy.max_table_share`` of the window, and never more than
       ``policy.max_auxiliary_document_share`` of it from ONE auxiliary
       document (or ``policy.max_document_share`` from any one document, when the
       question compares sources).

    Both caps are quotas, not preferences: a slot a cap withholds is not handed
    to the passage the cap excluded just because nothing else is left, so a
    window can come back SHORTER than ``top_n`` (twelve tables and three clauses
    at a 12-slot window is nine passages, and a flooding auxiliary document at a
    40% quota frees slots the standard fills). Two exceptions, both deliberate:
    a pool with nothing but tables fills the window anyway - a window of tables
    is worse than a mixed one but not worse than a short one - and a document
    that carries no identity is never charged against the document quota.

    A pool that FITS the window is cut the same way, and that is deliberate: the
    measured flooding case recalled nine passages for a twelve-slot window, so
    seven auxiliary passages and two standard clauses were all "inside" the
    window and a shortcut for a fitting pool would have changed nothing. The
    quota is relative to ``top_n``, the window, not to how full the pool happens
    to be.

    The result keeps ``ordered``'s order, so the prompt and its citation numbers
    stay relevance-ordered. The caller is told what the cut cost and who filled
    it (see :func:`_select`).
    """
    if top_n <= 0:
        return []

    chosen_keys: set[str] = set()
    chosen: list[str] = []
    table_count = 0
    document_counts: dict[str, int] = {}

    table_cap = top_n if policy.max_table_share >= 1.0 else min(top_n, math.ceil(top_n * policy.max_table_share))
    # At least one slot, so an auxiliary document still contributes its best
    # passage instead of vanishing behind its own quota.
    document_cap = 0 if policy.max_auxiliary_document_share >= 1.0 else max(1, min(top_n, math.ceil(top_n * policy.max_auxiliary_document_share)))
    # The comparative cap is not the auxiliary one: it charges EVERY document,
    # including the standards, because a comparison read from one side is not an
    # answer. See ``MAX_COMPARED_DOCUMENT_SHARE``.
    every_document_cap = 0 if policy.max_document_share >= 1.0 else max(1, min(top_n, math.ceil(top_n * policy.max_document_share)))

    def document_of(chunk: dict) -> str:
        """The quota bucket a passage is charged to (its own key when unknown)."""
        key = document_key(chunk)
        return f"chunk:{chunk_key(chunk)}" if not key else key

    def document_quota_blocks(chunk: dict) -> bool:
        count = document_counts.get(document_of(chunk), 0)
        if every_document_cap and count >= every_document_cap:
            return True
        if document_cap and not policy.is_core_document(chunk) and count >= document_cap:
            return True
        return False

    def quota_blocks(chunk: dict) -> bool:
        if is_table_chunk(chunk) and table_count >= table_cap:
            return True
        return document_quota_blocks(chunk)

    def take(chunk: dict, *, ignore_table_quota: bool = False) -> bool:
        """Claim a slot. ``ignore_table_quota`` is step 4's escape hatch: a
        table-only pool may exceed the table cap, but never a document quota."""
        nonlocal table_count
        if len(chosen) >= top_n:
            return False
        key = chunk_key(chunk)
        if key in chosen_keys:
            return False
        if ignore_table_quota:
            if document_quota_blocks(chunk):
                return False
        elif quota_blocks(chunk):
            return False
        chosen.append(key)
        chosen_keys.add(key)
        if is_table_chunk(chunk):
            table_count += 1
        bucket = document_of(chunk)
        document_counts[bucket] = document_counts.get(bucket, 0) + 1
        return True

    # 1. one slot per route
    route_order: list[str] = []
    for chunk in ordered:
        for route in routes_of(chunk):
            if route not in route_order:
                route_order.append(route)
    if len(route_order) > 1:
        for route in route_order:
            for chunk in ordered:
                if route in routes_of(chunk) and take(chunk):
                    break

    # 1b. one slot per document the question COMPARES. A route can come back with
    # the wrong side's passage (both sides' tables match the same parameters), so
    # the document itself is reserved for: without this the comparison is answered
    # from whichever document the score fill happens to prefer.
    if policy.compared_documents:
        for key in [document_key(chunk) for chunk in ordered if policy.is_compared_document(chunk)]:
            for chunk in ordered:
                if document_key(chunk) == key and take(chunk):
                    break

    # 2. the prose floor
    if policy.min_prose > 0:
        prose_taken = sum(1 for chunk in ordered if chunk_key(chunk) in chosen_keys and is_prose_chunk(chunk))
        for chunk in ordered:
            if prose_taken >= policy.min_prose or len(chosen) >= top_n:
                break
            if is_prose_chunk(chunk) and take(chunk):
                prose_taken += 1

    # 3. everything else by score. A table-capped cut takes non-table passages
    # first; an uncapped one is a plain top-N and must not prefer anything.
    if table_cap < top_n:
        for chunk in ordered:
            if len(chosen) >= top_n:
                break
            if not is_table_chunk(chunk):
                take(chunk)
        # 4. A pool with nothing but tables cannot satisfy the cap; a window of
        # tables is worse than a mixed one but not worse than a short one.
        table_only_pool = not any(not is_table_chunk(chunk) for chunk in ordered)
        for chunk in ordered:
            if len(chosen) >= top_n:
                break
            take(chunk, ignore_table_quota=table_only_pool and is_table_chunk(chunk))
    else:
        for chunk in ordered:
            if len(chosen) >= top_n:
                break
            take(chunk)

    return [chunk for chunk in ordered if chunk_key(chunk) in chosen_keys]


def _shortfall_reason(ordered: Sequence[dict], selected: Sequence[dict], top_n: int, policy: DiversityPolicy) -> str:
    """Name the quota that actually cost the window a slot.

    A cap that is configured but could not bind (no tables in the pool, no
    auxiliary document over its quota) must not be blamed in the transcript, or
    the next investigation tunes the wrong number.
    """
    if len(selected) >= min(top_n, len(ordered)):
        return ""
    caps = []
    if policy.max_table_share < 1.0:
        table_cap = math.ceil(top_n * policy.max_table_share)
        if sum(1 for chunk in ordered if is_table_chunk(chunk)) > table_cap:
            caps.append(f"table cap {table_cap}")
    if policy.max_auxiliary_document_share < 1.0:
        document_cap = math.ceil(top_n * policy.max_auxiliary_document_share)
        counts: dict[str, int] = {}
        for chunk in ordered:
            if not policy.is_core_document(chunk):
                counts[document_key(chunk) or chunk_key(chunk)] = counts.get(document_key(chunk) or chunk_key(chunk), 0) + 1
        if any(count > document_cap for count in counts.values()):
            caps.append(f"per-document quota {document_cap}")
    if policy.min_prose > 0 and sum(1 for chunk in ordered if is_prose_chunk(chunk)) < policy.min_prose:
        caps.append(f"prose floor {policy.min_prose}")
    return f"; window cut to {len(selected)} of {min(top_n, len(ordered))} because the {' and the '.join(caps) or 'configured quotas'} left no eligible passage"


def _select(ordered: Sequence[dict], top_n: int, *, policy: DiversityPolicy, reason: str) -> list[dict]:
    selected = select_context(ordered, top_n, policy)
    tables = sum(1 for chunk in selected if is_table_chunk(chunk))
    prose = sum(1 for chunk in selected if is_prose_chunk(chunk))
    _LOG.info(
        "[Rerank] %d candidate(s) -> %d passage(s) kept%s (%d prose / %d table; best scores %s; documents: %s)%s",
        len(ordered),
        len(selected),
        reason,
        prose,
        tables,
        ", ".join(f"{_score(chunk):.4f}" for chunk in selected[:3]) or "-",
        document_breakdown(selected),
        _shortfall_reason(ordered, selected, top_n, policy),
    )
    if policy.max_auxiliary_document_share < 1.0:
        core = next((document_name(chunk) for chunk in ordered if policy.is_core_document(chunk) and document_name(chunk)), "-")
        _LOG.info(
            "[Rerank] the standard for this question is %s; auxiliary documents are capped at %d of %d passage(s)",
            core,
            math.ceil(top_n * policy.max_auxiliary_document_share),
            top_n,
        )
    return selected


def _warn_when_the_pool_cannot_satisfy_the_floor(pool: Sequence[dict], policy: DiversityPolicy) -> None:
    """Say which stage failed when a clause question has no clause to answer from.

    A prose floor can only promote a passage that is IN the pool. When the pool
    holds none, the tables crowded the prose out of every route's own window
    before this stage ever saw it - a recall failure, and the transcript has to
    say so, or the next smoke test reads as "the fix did not work".
    """
    if not policy.min_prose:
        return
    if any(is_prose_chunk(chunk) for chunk in pool):
        return
    _LOG.warning(
        "[Rerank] none of the %d merged candidate(s) is prose: the %d-passage prose floor cannot be met. "
        "The tables won every route's own window - this is a RECALL problem (raise the per-route window or "
        "add a route aimed at the prose tier), not a cut problem.",
        len(pool),
        policy.min_prose,
    )


def _by_fused_score(chunks: Sequence[dict], top_n: int, policy: DiversityPolicy = DiversityPolicy()) -> list[dict]:
    return _select(apply_rank_adjustments(list(chunks), policy), top_n, policy=policy, reason="")


def resolve_final_top_n(value: Any) -> int:
    """``top_n`` from configuration, defaulting to :data:`DEFAULT_FINAL_TOP_N`."""
    if value is None:
        return DEFAULT_FINAL_TOP_N
    try:
        top_n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_FINAL_TOP_N
    return top_n if top_n > 0 else DEFAULT_FINAL_TOP_N


async def rerank_chunks(rerank_mdl, chunks: Sequence[dict], question: str, top_n: Any = DEFAULT_FINAL_TOP_N) -> list[dict]:
    """Score the de-duplicated pool against ``question`` and assemble the context.

    The scoring order decides which passages are eligible and
    :func:`select_context` decides the cut: every route of a composite question is
    represented, and a rule-seeking question also gets its prose floor.

    Never raises: a reranker that is missing, misconfigured, or counting a
    different number of scores than documents degrades to the fused-score
    ordering, because a broken reranker must not turn a question the knowledge
    base can answer into an empty answer.
    """
    limit = resolve_final_top_n(top_n)
    pool = dedupe_chunks(chunks)
    if not pool:
        return []
    policy = DiversityPolicy.for_question(question, pool)
    _warn_when_the_pool_cannot_satisfy_the_floor(pool, policy)
    if rerank_mdl is None or not str(question or "").strip():
        # A deployment with no reranker reaches here by design (see
        # ``dialog_service.resolve_rerank_mdl``): say so once per search, so a
        # transcript can tell "no rerank model configured" from "the reranker ran
        # and agreed with the fused order".
        if rerank_mdl is None:
            _LOG.warning("[Rerank] no rerank model; keeping the fused order for %d candidate(s)", len(pool))
        return _by_fused_score(pool, limit, policy)

    docs = [str(chunk.get("content_with_weight") or chunk.get("content") or "") for chunk in pool]
    if not any(doc.strip() for doc in docs):
        _LOG.warning("[Rerank] %d candidate(s) carry no text; keeping the fused order", len(pool))
        return _by_fused_score(pool, limit, policy)

    try:
        scores, _ = await thread_pool_exec(rerank_mdl.similarity, question, docs)
    except Exception as exc:  # noqa: BLE001 - reranking is an ordering pass
        _LOG.warning("[Rerank] reranker failed on %d candidate(s); keeping the fused order: %s", len(pool), exc)
        return _by_fused_score(pool, limit, policy)

    scores = [] if scores is None else list(scores)
    if len(scores) != len(pool):
        _LOG.warning("[Rerank] reranker returned %d score(s) for %d candidate(s); keeping the fused order", len(scores), len(pool))
        return _by_fused_score(pool, limit, policy)

    for chunk, score in zip(pool, scores):
        try:
            value = float(score)
        except (TypeError, ValueError):
            continue
        chunk.setdefault("fused_similarity", chunk.get("similarity"))
        chunk["rerank_score"] = value
        chunk["similarity"] = value

    selected = _select(apply_rank_adjustments(pool, policy), limit, policy=policy, reason=" by rerank score")
    _LOG.info("[Rerank] pool %s -> context %s", summarize(pool), summarize(selected))
    return selected
