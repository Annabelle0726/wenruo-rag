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
"""Module B — multi-route hybrid retrieval over the original and atomic queries.

Every route is one ``Dealer.retrieval`` call, which is itself hybrid: a vector
(kNN) leg and a full-text (BM25-style) leg fused inside the doc store, with
``vector_similarity_weight`` splitting the two. Running one call per route is
what buys the recall a composite question needs — the assistant's single call
fills its whole candidate window with the chapters one topic matches, and
chapter 5's thickness clause never reaches the pool that chapter 6's
routine-test clause has already filled.

The routes are retrieved concurrently and merged by ``chunk_id``, keeping the
best score each chunk earned on any route and recording which routes found it.

Each route that comes back empty at the caller's threshold is retried once at a
recall floor (:data:`RECALL_FLOOR`): an absolute similarity threshold is only
comparable inside one corpus/embedding pair, and a gate sitting above the whole
pool reads downstream as "the knowledge base cannot answer this" when the corpus
answers it verbatim.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

_LOG = logging.getLogger(__name__)

#: Passages recalled per route. The recommended band is 10-15: wide enough that a
#: chapter's answering clause survives the fused gate inside one route, narrow
#: enough that N routes stay inside the reranker's window.
DEFAULT_ROUTES_TOP_K = 12
ROUTES_TOP_K_RECOMMENDED = (10, 15)

#: Hybrid split of the two legs: dense (vector) 0.6, sparse (keyword) 0.4. A
#: caller's own configured weight always wins - see ``Dealer.retrieval``.
DEFAULT_VECTOR_SIMILARITY_WEIGHT = 0.6

#: Fallback candidate window (``rerank_candidates_count``) per route when the
#: caller configures none. The floor is ``routes_top_k``:
#: ``Dealer.retrieval`` rejects ``page * page_size > rerank_candidates_count``.
DEFAULT_RERANK_CANDIDATES = 64

#: Similarity a route falls back to when the configured threshold returned
#: nothing at all. An absolute similarity threshold is only comparable inside ONE
#: corpus/embedding pair, because the fused score is
#: ``vector_weight * cosine + term_weight * term_recall`` and both legs' scales are
#: properties of the deployed models: on the cable corpus the embedding leg alone
#: contributes ~0.45 for EVERY chunk (measured cosines 0.88-0.92), so a threshold
#: calibrated on a setup with a wider cosine spread can sit above the entire
#: candidate pool. When that happens the knowledge base was searched and the gate,
#: not the corpus, produced the empty result - an answer layer that reads "no
#: chunks" as "the knowledge base cannot answer this" then refuses a question the
#: corpus answers verbatim. The floor is the long-standing hybrid default and is
#: applied ONLY when the configured threshold returned nothing, so a threshold
#: that does discriminate keeps its effect on the tail.
#:
#: This is the ONE place the rescue lives: the agentic search tools used to carry
#: their own copy (``_THRESHOLD_RESCUE_FLOOR`` in ``harness/tools/search.py``),
#: deleted when that search moved onto this pipeline.
RECALL_FLOOR = 0.2


@dataclass
class RouteResult:
    """One route's retrieval output."""

    query: str
    chunks: list[dict] = field(default_factory=list)
    doc_aggs: list[dict] = field(default_factory=list)
    failed: bool = False


def resolve_routes_top_k(value: Any) -> int:
    """``routes_top_k`` from configuration, defaulting to
    :data:`DEFAULT_ROUTES_TOP_K`. A value outside the recommended band is kept
    (configuration wins) and reported."""
    if value is None:
        return DEFAULT_ROUTES_TOP_K
    try:
        top_k = int(value)
    except (TypeError, ValueError):
        return DEFAULT_ROUTES_TOP_K
    if top_k <= 0:
        return DEFAULT_ROUTES_TOP_K
    low, high = ROUTES_TOP_K_RECOMMENDED
    if not low <= top_k <= high:
        _LOG.warning("[Multi-route] routes_top_k=%s is outside the recommended %s-%s band", top_k, low, high)
    return top_k


def chunk_key(chunk: dict) -> str:
    """Identity of a passage for cross-route de-duplication.

    ``chunk_id`` is what the doc store assigns; web-search results and test
    doubles may carry only ``id``, and a passage with neither is identified by
    its document and text so the same passage found by two routes still merges.
    """
    for name in ("chunk_id", "id"):
        value = chunk.get(name)
        if value:
            return str(value)
    return f"{chunk.get('doc_id') or ''}|{str(chunk.get('content_with_weight') or chunk.get('content') or '')[:64]}"


def _score(chunk: dict) -> float:
    try:
        return float(chunk.get("similarity") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def merge_route_hits(hits: Sequence[RouteResult], existing: dict | None = None) -> dict:
    """De-duplicate and merge the passages every route returned.

    A passage found by several routes keeps the best score it earned on any of
    them, and carries ``retrieval_routes`` / ``route_hits`` so a transcript can
    show which sub-query reached which chapter. ``doc_aggs`` counts are summed
    per document, which makes the reference list reflect the merged pool rather
    than whichever route happened to run first.

    ``existing`` seeds the merge with an already-merged pool (a second retrieval
    pass whose result must be ADDED to the first). Provenance is preserved by
    construction: the seeded passages keep the routes that found them and gain
    the new one when the same passage comes back, instead of having their
    ``retrieval_routes`` reset - the context cut's route coverage reads that list.
    """
    merged: dict[str, dict] = {}
    doc_aggs: dict[str, dict] = {}
    if existing:
        for chunk in existing.get("chunks") or []:
            merged[chunk_key(chunk)] = dict(chunk)
        for agg in existing.get("doc_aggs") or []:
            doc_id = str(agg.get("doc_id") or agg.get("doc_name") or "")
            doc_aggs[doc_id] = {
                "doc_name": agg.get("doc_name") or "",
                "doc_id": agg.get("doc_id") or "",
                "count": int(agg.get("count") or 0),
            }

    for hit in hits:
        for chunk in hit.chunks or []:
            key = chunk_key(chunk)
            existing = merged.get(key)
            if existing is None:
                record = dict(chunk)
                record["retrieval_routes"] = [hit.query]
                record["route_hits"] = 1
                merged[key] = record
            else:
                routes = existing.setdefault("retrieval_routes", [])
                if hit.query not in routes:
                    routes.append(hit.query)
                existing["route_hits"] = int(existing.get("route_hits") or 0) + 1
                for name in ("similarity", "vector_similarity", "term_similarity"):
                    value = chunk.get(name)
                    if value is None:
                        continue
                    try:
                        better = float(value) > float(existing.get(name) or 0.0)
                    except (TypeError, ValueError):
                        continue
                    if better:
                        existing[name] = value

        for agg in hit.doc_aggs or []:
            doc_id = str(agg.get("doc_id") or agg.get("doc_name") or "")
            entry = doc_aggs.get(doc_id)
            if entry is None:
                doc_aggs[doc_id] = {
                    "doc_name": agg.get("doc_name") or "",
                    "doc_id": agg.get("doc_id") or "",
                    "count": int(agg.get("count") or 0),
                }
            else:
                entry["count"] += int(agg.get("count") or 0)

    chunks = sorted(merged.values(), key=_score, reverse=True)
    return {
        "total": len(chunks),
        "chunks": chunks,
        "doc_aggs": sorted(doc_aggs.values(), key=lambda agg: agg["count"], reverse=True),
    }


async def _retrieve_route(
    retriever,
    query: str,
    *,
    embd_mdl,
    tenant_ids,
    kb_ids,
    routes_top_k: int,
    similarity_threshold: float,
    vector_similarity_weight: float,
    knn_top_k: int,
    rerank_candidates_count: int,
    doc_ids,
    rank_feature,
    must_not,
    allow_dense_fallback: bool,
) -> RouteResult:
    """One route's hybrid retrieval, with the empty-pool rescue."""

    async def _call(threshold: float) -> dict:
        kwargs = {
            "vector_similarity_weight": vector_similarity_weight,
            "knn_top_k": knn_top_k,
            "aggs": True,
            "highlight": False,
            "doc_ids": doc_ids,
            "rank_feature": rank_feature,
            "rerank_candidates_count": rerank_candidates_count,
            "allow_dense_fallback": allow_dense_fallback,
        }
        if must_not:
            kwargs["must_not"] = must_not
        result = await retriever.retrieval(
            query,
            embd_mdl,
            tenant_ids,
            kb_ids,
            1,
            routes_top_k,
            threshold,
            **kwargs,
        )
        return result or {}

    result = await _call(similarity_threshold)
    chunks = result.get("chunks") or []
    if not chunks and float(similarity_threshold or 0.0) > RECALL_FLOOR:
        _LOG.warning(
            "[Multi-route] route %r -> 0 chunk(s) at threshold=%s; retrying at the %.2f recall floor.",
            query[:80],
            similarity_threshold,
            RECALL_FLOOR,
        )
        rescued = await _call(RECALL_FLOOR)
        if rescued.get("chunks"):
            result = rescued
            chunks = result.get("chunks") or []
    return RouteResult(query=query, chunks=list(chunks), doc_aggs=list(result.get("doc_aggs") or []))


async def multi_route_retrieve(
    *,
    retriever,
    queries: Sequence[str],
    embd_mdl,
    tenant_ids,
    kb_ids,
    routes_top_k: Any = DEFAULT_ROUTES_TOP_K,
    similarity_threshold: float = 0.2,
    vector_similarity_weight: float = DEFAULT_VECTOR_SIMILARITY_WEIGHT,
    knn_top_k: int = 1024,
    rerank_candidates_count: Any = None,
    doc_ids=None,
    rank_feature=None,
    must_not=None,
    allow_dense_fallback: bool = True,
) -> dict:
    """Retrieve every route concurrently and return the merged pool.

    Reranking is deliberately *not* part of this stage: each route contributes
    its own candidates and module C scores the union once, against the user's
    original question.
    """
    routes = [str(query).strip() for query in queries if str(query or "").strip()]
    # A repeated route is a repeated round trip and a repeated set of passages to
    # merge; order is preserved so the original question stays route 0.
    routes = list(dict.fromkeys(routes))
    if not routes:
        return {"total": 0, "chunks": [], "doc_aggs": []}

    top_k = resolve_routes_top_k(routes_top_k)
    configured_candidates = DEFAULT_RERANK_CANDIDATES if rerank_candidates_count is None else int(rerank_candidates_count or 0)
    candidates = max(configured_candidates, top_k)
    _LOG.info(
        "[Multi-route] %d route(s), routes_top_k=%s, threshold=%s, vector_weight=%s, rerank_candidates=%s",
        len(routes),
        top_k,
        similarity_threshold,
        vector_similarity_weight,
        candidates,
    )

    async def _guard(query: str) -> RouteResult:
        try:
            result = await _retrieve_route(
                retriever,
                query,
                embd_mdl=embd_mdl,
                tenant_ids=tenant_ids,
                kb_ids=kb_ids,
                routes_top_k=top_k,
                similarity_threshold=similarity_threshold,
                vector_similarity_weight=vector_similarity_weight,
                knn_top_k=knn_top_k,
                rerank_candidates_count=candidates,
                doc_ids=doc_ids,
                rank_feature=rank_feature,
                must_not=must_not,
                allow_dense_fallback=allow_dense_fallback,
            )
            report_route_success()
            return result
        except Exception as exc:  # noqa: BLE001 - one dead route must not sink the others
            _LOG.warning("[Multi-route] route %r failed: %s", query[:80], exc)
            report_route_failure(exc)
            return RouteResult(query=query, failed=True)

    hits = await asyncio.gather(*[_guard(query) for query in routes])
    merged = merge_route_hits(hits)
    failed = [hit.query for hit in hits if hit.failed]
    _LOG.info(
        "[Multi-route] %d route(s) -> %d merged passage(s) from %d document(s)%s",
        len(routes),
        merged["total"],
        len(merged["doc_aggs"]),
        f"; failed routes: {failed}" if failed else "",
    )
    return merged
