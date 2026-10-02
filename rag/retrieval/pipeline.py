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
"""The multi-route retrieval pipeline: decompose, retrieve, rerank.

One entry point wires the three stages together for a chat turn:

1. :mod:`rag.retrieval.decomposition` — a composite question becomes an original
   route plus one atomic route per information need;
2. :mod:`rag.retrieval.multi_route` — every route is retrieved concurrently
   (hybrid, per-route candidate window) and the results are merged by
   ``chunk_id``;
3. :mod:`rag.retrieval.rerank` — the merged pool is scored against the ORIGINAL
   question and cut to the passages the answer model will see.

A question with a single information need does not call the LLM at all: it takes
one route, which is the behaviour this path had before the pipeline existed.
"""

from __future__ import annotations

import logging
from typing import Sequence

from rag.retrieval.chunk_profile import document_id, document_key, document_name, is_prose_chunk, resolve_core_documents
from rag.retrieval.chunk_profile import designation_parts, document_designations, document_family, generic_part_documents, generic_sibling_designation, name_family, standard_designations
from rag.retrieval.decomposition import MAX_SUB_QUERIES, looks_composite, mentions_requirement, seeks_clause
from rag.retrieval.multi_route import (
    DEFAULT_ROUTES_TOP_K,
    DEFAULT_VECTOR_SIMILARITY_WEIGHT,
    RouteResult,
    merge_route_hits,
    multi_route_retrieve,
)
from rag.retrieval.planner import (
    KIND_CLAUSE,
    KIND_DIMENSION,
    KIND_SIDE,
    MAX_PLAN_ROUTES,
    cache_scope,
    compile_retrieval_plan,
    resolve_plan_cache,
)
from rag.retrieval.health_bridge import (
    attach_retrieval_health,
    begin_retrieval_health,
    mark_empty_window,
    mark_no_question,
)
from rag.retrieval.query_router import route_question
from rag.retrieval.rerank import DEFAULT_FINAL_TOP_N, rerank_chunks, resolve_final_top_n
from rag.retrieval.route_expansion import MAX_SUPPLEMENTAL_ROUTES, supplemental_routes

_LOG = logging.getLogger(__name__)

#: How many routes the document-scoped follow-up may run. Each one is a retrieval
#: round trip, and the atomic sub-queries are the ones that find a standard's
#: individual clauses, so they are served first.
MAX_CORE_DOCUMENT_ROUTES = 3

#: The total route allowance for one question: the compiled plan's own cap plus the deterministic
#: supplemental cross product. A question already at the plan cap therefore has room for the
#: supplemental routes and nothing more, which is what keeps the entity x fact-type rule from
#: growing the route count without limit.
ROUTE_BUDGET = MAX_PLAN_ROUTES + MAX_SUPPLEMENTAL_ROUTES

#: How thin a standard's PROSE may be before a clause question triggers the
#: document-scoped follow-up regardless of what the auxiliary documents did. Two
#: passages from the standard, on a question that asks for a rule, means the rest
#: of its clauses are buried rather than absent - and that conclusion must not
#: depend on how loud some working document happens to be.
MIN_CORE_PROSE_PASSAGES = 4


def empty_kbinfos() -> dict:
    """A fresh empty result, in the shape every retrieval caller expects."""
    return {"total": 0, "chunks": [], "doc_aggs": []}


def core_document_followup(chunks, question: str, preferred_routes: Sequence[str] = ()) -> tuple[list[str], str, list[str]] | None:
    """``(doc_ids, scope_name, queries)`` for a standard losing its own PROSE.

    The measured gap this exists for: a three-parameter question whose pool held
    two passages from 《Q/GDW 73237.1 通用技术规范》 and seven from an auxiliary
    working document. The standard's 6.2.2 (绝缘电阻 ≥1500/1000 MΩ·km) is in the
    corpus, and Test 2 proved a question that NAMES the standard reaches it - but
    a composite question's fused score ranks the standard's clauses below whatever
    else matches the same words, so those clauses never enter any route's window.
    No cut-stage policy can recover a passage that was never recalled; the only
    lever left is to search the standard ITSELF, which is what this returns the
    material for: a retrieval scoped to the prose tier's ``doc_ids``.

    Counting is done on PROSE ONLY, and that is the refinement the second live
    round forced. The first version compared every core passage with every
    non-core passage, so a pool of

        《第1部分：通用技术规范》       2 passages (the normative clauses)
        《第2部分：专用技术规范》       4 passages (parameter TABLES)
        《20_抽检工作规范》             3 passages

    added the two parts together (6), declared the standard ahead of the
    auxiliary file (3), and silently skipped the follow-up - while the document
    that holds the CLAUSES had contributed two passages. A parameter table cannot
    state a rule, so it cannot stand in for one when deciding whether the
    standard was recalled. Both the count and the SCOPE are therefore prose-only:
    the pass searches the core documents that actually contributed prose, not the
    table part that padded the number.

    Fires when either symptom holds, so an ordinary turn pays nothing:

    * a standard must be identifiable (:func:`resolve_core_documents`) and the
      question must be about several parameters or about a rule;
    * **(A)** a non-core document contributed more PROSE passages than every core
      document together - the standard is losing its own question; or
    * **(B)** the question asks for a RULE and the standard's prose is thinner
      than :data:`MIN_CORE_PROSE_PASSAGES` - a clause question that sees two
      passages from the standard has clauses buried somewhere, whether or not an
      auxiliary file happens to be louder.

    ``preferred_routes`` are searched first inside the standard (the atomic
    sub-queries and the prose-tier route), then the question itself.
    """
    core = resolve_core_documents(chunks, question)
    if not core:
        return None
    if not (looks_composite(question) or seeks_clause(question)):
        return None

    prose_by_document: dict[str, int] = {}
    best_prose: dict[str, tuple[float, str]] = {}
    auxiliary_prose: dict[str, int] = {}
    auxiliary_total = 0
    for chunk in chunks or []:
        key = document_key(chunk)
        if key in core:
            if not is_prose_chunk(chunk):
                continue  # a table cannot answer a clause, and cannot pad the count
            prose_by_document[key] = prose_by_document.get(key, 0) + 1
            score = float(chunk.get("similarity") or 0.0)
            if score > best_prose.get(key, (-1.0, ""))[0]:
                best_prose[key] = (score, document_id(chunk))
        else:
            auxiliary_total += 1
            if is_prose_chunk(chunk):
                auxiliary_prose[key] = auxiliary_prose.get(key, 0) + 1

    core_prose = sum(prose_by_document.values())
    loudest_auxiliary = max(auxiliary_prose.values(), default=0)
    out_numbered = bool(core_prose) and loudest_auxiliary > core_prose
    thin_for_a_clause = seeks_clause(question) and core_prose < MIN_CORE_PROSE_PASSAGES

    if not out_numbered and not thin_for_a_clause:
        _LOG.info(
            "[Multi-route] the standard's prose holds %d passage(s) against %d auxiliary prose passage(s) and %d passage(s) in total; no document-scoped route needed",
            core_prose,
            loudest_auxiliary,
            auxiliary_total,
        )
        return None

    # The scope is the prose tier: core documents that actually contributed a
    # clause, best first, so the table part of a multi-part standard is not
    # searched again for something it cannot contain.
    scope: list[str] = []
    names: list[str] = []
    for key, _count in sorted(prose_by_document.items(), key=lambda item: (item[1], best_prose.get(item[0], (0.0, ""))[0]), reverse=True):
        doc_id = best_prose.get(key, (0.0, ""))[1]
        if doc_id and doc_id not in scope:
            scope.append(doc_id)
        name = next((document_name(chunk) for chunk in chunks if document_key(chunk) == key), "")
        if name and name not in names:
            names.append(name)
    if not scope:
        # Only file names are known, and a file name is not a doc-store id: a
        # scoped search on one matches nothing and would hide the standard.
        _LOG.info("[Multi-route] the standard for this question has no doc id (%s); skipping the document-scoped route", ", ".join(names) or "?")
        return None

    queries: list[str] = []
    for query in list(preferred_routes) + [question]:
        text = " ".join(str(query or "").split())
        if text and text not in queries:
            queries.append(text)
        if len(queries) >= MAX_CORE_DOCUMENT_ROUTES:
            break
    _LOG.info(
        "[Multi-route] %s; searching the standard's own prose %s (%d route(s))",
        (
            f"the standard's prose is out-numbered {loudest_auxiliary} to {core_prose} in the pool"
            if out_numbered
            else f"a clause question sees only {core_prose} prose passage(s) from the standard (floor {MIN_CORE_PROSE_PASSAGES})"
        ),
        ", ".join(names) or ", ".join(scope),
        len(queries),
    )
    return scope, ", ".join(names) or ", ".join(scope), queries


#: How many routes the cross-part fallback may run. One is usually enough - the
#: sibling is named by its designation, and that designation appears in every chunk
#: of it - so a second is only room for the question itself.
MAX_CROSS_PART_ROUTES = 2

#: The generic part of a multi-part standard, as the corpus names it. A document that
#: says this in its name IS the normative baseline of its standard.
GENERIC_PART_CUE = "通用技术规范"

#: A part that answers a project rather than stating a rule: its tables are templates
#: a bidder fills in, so a requirement question must not be answered from it alone.
SPECIALIZED_PART_CUE = "专用技术规范"


def cross_part_fallback(chunks, question: str, preferred_routes: Sequence[str] = ()) -> tuple[list[str] | None, str, list[str]] | None:
    """``(doc_ids or None, scope_name, queries)`` for the GENERIC part of the standard.

    The reported trap: a question about a mandatory requirement - the corpus's own
    example is 内衬层厚度 ≥1.5mm - was answered from 《第2部分：专用技术规范》, whose
    表1/表2 are bidder fill-in templates: the cells are empty, the requirement is not
    there, and the answer layer refuses. The requirement lives in 《第1部分：通用技术
    规范》, which is a DIFFERENT document of the SAME standard (``Q/GDW 73286.1``
    beside ``Q/GDW 73286.2``), and no route ever asked for it, because the question
    names a parameter and not a standard.

    The designation is what makes the sibling findable: the ingest writes
    ``[标准号: Q/GDW 73286.1-2026 | 文档: …第1部分：通用技术规范…]`` into that part's
    chunks, so a route naming ``Q/GDW 73286.1-2026 通用技术规范`` matches them by
    full text as well as by vector.

    Fires only when all three hold, so an ordinary turn pays nothing:

    * the question asks for a REQUIREMENT or a rule (a value question is answered by
      the specialized part's parameter tables, which is what they are for);
    * the pool holds the SPECIALIZED part of a multi-part standard;
    * the GENERIC part of that same standard contributed no PROSE to the pool - if it
      did, its clauses are already in the window and there is nothing to fall back to.

    Returns ``doc_ids`` when the generic part is in the pool (a scoped pass is then
    cheap and exact), and ``None`` when it is not, because then only a text route can
    reach it at all.
    """
    if not (mentions_requirement(question) or seeks_clause(question)):
        return None

    specialized: dict[str, str] = {}
    specialized_names: dict[str, str] = {}
    for chunk in chunks or []:
        name = document_name(chunk)
        if SPECIALIZED_PART_CUE not in name:
            continue
        family = document_family(chunk)
        if not family:
            continue
        # Both parts of the 220kV standard are 专用 (its 第2部分 is the single-core part
        # and its 第3部分 the three-core one), so the family - not the part number - is
        # what identifies the standard the pool is answering from.
        specialized_names.setdefault(family, name)
        for designation in document_designations(chunk):
            parsed = designation_parts(designation)
            if parsed and (parsed[1] is None or parsed[1] >= 2):
                specialized.setdefault(family, designation)
        specialized.setdefault(family, "")
    if not specialized:
        return None

    generics = generic_part_documents(chunks)
    generic_prose: dict[str, int] = {}
    for chunk in chunks or []:
        if not is_prose_chunk(chunk):
            continue
        family = document_family(chunk)
        if family:
            generic_prose[family] = generic_prose.get(family, 0) + 1

    for family, designation in sorted(specialized.items()):
        if family in generics and generic_prose.get(family):
            continue  # the baseline part is already answering
        scope: list[str] | None = None
        if family in generics:
            key, name = generics[family]
            doc_id = next((document_id(chunk) for chunk in chunks if document_key(chunk) == key and document_id(chunk)), "")
            if doc_id:
                scope = [doc_id]
        # The route names the sibling twice over, because a standard's parts are
        # archived with and without their numbers: by designation when the corpus
        # carries one, and by the name the parts share when it does not.
        anchors = [f"{name_family(specialized_names.get(family, ''))} 第1部分 {GENERIC_PART_CUE}"]
        sibling = generic_sibling_designation(designation) if designation else None
        if sibling:
            anchors.insert(0, f"{sibling} {GENERIC_PART_CUE}")
        sibling = sibling or f"{name_family(specialized_names.get(family, ''))} 第1部分 {GENERIC_PART_CUE}"
        scope_name = f"{sibling} ({GENERIC_PART_CUE})"
        if scope:
            scope_name = generics[family][1]
        queries: list[str] = []
        for anchor in anchors:
            for query in [f"{anchor} {question}", anchor]:
                text = " ".join(str(query or "").split())
                if text and text not in queries:
                    queries.append(text)
                if len(queries) >= MAX_CROSS_PART_ROUTES:
                    break
            if len(queries) >= MAX_CROSS_PART_ROUTES:
                break
        _LOG.info(
            "[Multi-route] the pool answers from the specialized part %s and its generic part has no prose in the window; falling back to %s (%d route(s), %s)",
            designation or specialized_names.get(family, family),
            scope_name,
            len(queries),
            "document-scoped" if scope else "unscoped",
        )
        return scope, scope_name, queries
    return None


async def retrieve_multi_route(
    *,
    retriever,
    question: str,
    tenant_ids,
    kb_ids,
    chat_mdl=None,
    embd_mdl=None,
    rerank_mdl=None,
    similarity_threshold: float = 0.2,
    vector_similarity_weight: float = DEFAULT_VECTOR_SIMILARITY_WEIGHT,
    routes_top_k=DEFAULT_ROUTES_TOP_K,
    final_top_n=DEFAULT_FINAL_TOP_N,
    knn_top_k: int = 1024,
    rerank_candidates_count=None,
    doc_ids=None,
    rank_feature=None,
    must_not=None,
    max_sub_queries: int = MAX_SUB_QUERIES,
    allow_dense_fallback: bool = True,
) -> dict:
    """Retrieve for ``question`` through decomposition + hybrid routes + rerank.

    Two knobs, deliberately separate:

    * ``routes_top_k`` - the recall window of ONE route. Default 12, inside the
      recommended 10-15 band: wide enough that a chapter's answering clause
      survives the fused gate inside its own route, narrow enough that N routes
      stay inside the reranker's window. Callers whose ``top_n`` already means
      "passages this search returns" pass it through (the harness search tools
      do), because a route that cannot fill the page it has to return cannot
      contribute to it.
    * ``final_top_n`` - the passages handed to the answer model. Default 8, in
      the recommended 6-8 band; a configured value wins (the cable assistant
      sets 12 for a measured reason - see ``api/db/cable_defaults.py``).
    """
    question = " ".join(str(question or "").split())
    begin_retrieval_health()
    if not question:
        mark_no_question()
        return attach_retrieval_health(empty_kbinfos())

    # Adaptive routing (module D): the query SHAPE decides the two legs' balance
    # and the recall window, in memory, for this request only. Nothing is written
    # to the assistant, so the configured sliders keep their values for every other
    # turn and every other question. A question that matches no rule leaves both
    # arguments exactly as the caller passed them.
    configured_top_k, configured_weight = routes_top_k, vector_similarity_weight
    decision = route_question(question)
    if decision.routes_top_k is not None:
        # A route cannot return more than its own window recalls, so the routed
        # window is a floor as well as a target: narrowing it below the page the
        # caller must fill would return fewer passages than asked for.
        required = resolve_final_top_n(final_top_n)
        routes_top_k = max(decision.routes_top_k, required)
        if routes_top_k != decision.routes_top_k:
            _LOG.info(
                "[QueryRouter] %s route asked for routes_top_k=%s but the caller returns %s passage(s); keeping %s",
                decision.name,
                decision.routes_top_k,
                required,
                routes_top_k,
            )
    if decision.vector_similarity_weight is not None:
        vector_similarity_weight = decision.vector_similarity_weight
    if decision.overrides:
        _LOG.info(
            "[QueryRouter] %s route (signal=%r) -> vector_weight=%s, routes_top_k=%s (configured %s / %s)",
            decision.name,
            decision.signal,
            vector_similarity_weight,
            routes_top_k,
            configured_weight,
            configured_top_k,
        )
    else:
        _LOG.debug("[QueryRouter] no rule matched %r; keeping the configured retrieval settings", question[:80])

    # P1-2 (module E): the executable route list is COMPILED from the input, not proposed by the
    # model. The plan - its slot count, its slot identities, their canonical texts and their
    # order - exists, hashed, before the model is asked anything, so no model behaviour can reach
    # the topology: a timeout, a malformed payload, an empty list or a confident hallucination all
    # land in `plan.provenance` and nowhere else. See `rag.retrieval.planner` for the authority
    # model and the `plan_hash` contract (S1-S6).
    plan = await compile_retrieval_plan(
        question=question,
        chat_mdl=chat_mdl,
        max_sub_queries=max_sub_queries,
        plan_cache=resolve_plan_cache(),
        cache_scope=cache_scope(
            tenant_ids,
            kb_ids,
            (
                ("similarity_threshold", similarity_threshold),
                ("vector_similarity_weight", vector_similarity_weight),
                ("routes_top_k", routes_top_k),
                ("final_top_n", final_top_n),
                ("knn_top_k", knn_top_k),
            ),
        ),
    )
    routes = list(plan.texts)
    # The three deterministic families, read back out of the plan in the order the plan put them,
    # so the follow-up passes below keep the route preference they have always had. These are the
    # same routes module A and the comparative/clause rules produce - what changed is who decides
    # that they exist.
    sub_queries = list(plan.of_kind(KIND_DIMENSION))
    side_routes = list(plan.of_kind(KIND_SIDE))
    targeted = next(iter(plan.of_kind(KIND_CLAUSE)), None)
    # P1-1: a question that enumerates BOTH an entity axis and a fact-type axis gets the bounded
    # cross product as deterministic supplemental routes, so its per-fact-type coverage no longer
    # depends on how granular the decomposition model happened to be in this session. Measured:
    # for "…（终端与接头）的设计使用寿命与结构有何要求" the model produced four narrow routes in
    # one session (design-life table recalled) and two composite routes in another (zero
    # design-life passages), which is the same question on the same build. This rule is additive -
    # every plan route is kept - and holds no domain vocabulary of its own; see
    # `rag.retrieval.route_expansion`.
    supplemental, expansion = supplemental_routes(
        question,
        existing_routes=routes,
        budget=max(0, ROUTE_BUDGET - len(routes)),
    )
    if supplemental:
        routes.extend(supplemental)
        # The follow-up passes prefer the routes that carry the question's narrower intents, so the
        # supplemental ones join that preference list rather than being retrieval-only.
        sub_queries.extend(supplemental)
    _LOG.info(
        "[Multi-route] question=%r -> %d route(s) (%d compiled + %d supplemental %s; expansion=%s): %s",
        question[:80],
        len(routes),
        len(routes) - len(supplemental),
        len(supplemental),
        supplemental,
        expansion.get("reason"),
        routes,
    )
    _LOG.info(
        "[Multi-route] question=%r -> %d compiled route(s) (plan_hash=%s, slots=%s, cache=%s)",
        question[:80],
        len(plan.texts),
        plan.plan_hash,
        [route.slot_id for route in plan.routes],
        plan.provenance.cache_state,
    )

    async def _retrieve(queries, doc_scope):
        return await multi_route_retrieve(
            retriever=retriever,
            queries=queries,
            embd_mdl=embd_mdl,
            tenant_ids=tenant_ids,
            kb_ids=kb_ids,
            routes_top_k=routes_top_k,
            similarity_threshold=similarity_threshold,
            vector_similarity_weight=vector_similarity_weight,
            knn_top_k=knn_top_k,
            rerank_candidates_count=rerank_candidates_count,
            doc_ids=doc_scope,
            rank_feature=rank_feature,
            must_not=must_not,
            allow_dense_fallback=allow_dense_fallback,
        )

    merged = await _retrieve(routes, doc_ids)
    if not merged.get("chunks"):
        mark_empty_window()
        return attach_retrieval_health(empty_kbinfos())

    # Second chance for the standard: the cut can rebalance what was recalled, but
    # it cannot bring back a clause no route retrieved. When an auxiliary document
    # out-recalled the standard on a question about several parameters (or about a
    # rule), one more pass searches the standard itself.
    followup = core_document_followup(merged["chunks"], question, preferred_routes=[*sub_queries, *side_routes, *([targeted] if targeted else [])])
    if followup:
        scope, scope_name, queries = followup
        scoped = await _retrieve(queries, scope)
        before = len(merged["chunks"])
        merged = merge_route_hits(
            [RouteResult(query=query, chunks=[dict(chunk, core_scoped=True) for chunk in scoped["chunks"]], doc_aggs=scoped["doc_aggs"]) for query in queries],
            existing=merged,
        )
        _LOG.info("[Multi-route] document-scoped follow-up on %s added %d passage(s) (%d -> %d in the pool)", scope_name, len(merged["chunks"]) - before, before, len(merged["chunks"]))

    # Third chance: a requirement question that only found the SPECIALIZED part of a
    # standard is answered from template tables it cannot fill. The normative baseline
    # is the GENERIC part of the same standard, which the designation names.
    generic_fallback: dict | None = None
    fallback = cross_part_fallback(merged["chunks"], question, preferred_routes=[*sub_queries, *side_routes, *([targeted] if targeted else [])])
    if fallback:
        scope, scope_name, queries = fallback
        scoped = await _retrieve(queries, scope)
        before = len(merged["chunks"])
        merged = merge_route_hits(
            [RouteResult(query=query, chunks=[dict(chunk, generic_fallback=True) for chunk in scoped["chunks"]], doc_aggs=scoped["doc_aggs"]) for query in queries],
            existing=merged,
        )
        added = len(merged["chunks"]) - before
        _LOG.info("[Multi-route] cross-part fallback on %s added %d passage(s) (%d -> %d in the pool)", scope_name, added, before, len(merged["chunks"]))
        if added:
            labels = sorted(standard_designations(scope_name))
            generic_fallback = {
                "scope": scope_name,
                "designation": labels[0] if labels else scope_name,
                "documents": [document_name(chunk) for chunk in merged["chunks"] if chunk.get("generic_fallback")][:3],
            }

    chunks = await rerank_chunks(rerank_mdl, merged["chunks"], question, final_top_n)
    infos = {"total": merged.get("total", len(chunks)), "chunks": chunks, "doc_aggs": merged.get("doc_aggs", [])}
    if generic_fallback:
        # The answer layer has to SAY that a mandatory figure came from the general
        # part of the standard rather than from the specialized one it was asked
        # about, or the citation reads as a contradiction of the question.
        infos["generic_fallback"] = generic_fallback
    return attach_retrieval_health(infos)
