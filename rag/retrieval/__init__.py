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
"""Multi-route retrieval for multi-dimensional questions.

``retrieve_multi_route`` is the entry point a chat turn calls; the three modules
underneath it are independently usable and independently testable:

* :mod:`~rag.retrieval.decomposition` — question -> atomic sub-queries (module A);
* :mod:`~rag.retrieval.multi_route` — concurrent hybrid routes + merge (module B);
* :mod:`~rag.retrieval.rerank` — rerank against the original question + cut (module C).
"""

from rag.retrieval.decomposition import (
    MAX_SUB_QUERIES,
    decompose_question,
    looks_composite,
    parse_sub_queries,
    strip_section_references,
)
from rag.retrieval.chunk_profile import (
    CORE_DOCUMENT_NAME_CUES,
    core_document_score,
    document_breakdown,
    document_key,
    document_name,
    is_image_chunk,
    is_prose_chunk,
    is_table_chunk,
    resolve_core_documents,
    standard_designations,
    summarize,
)
from rag.retrieval.decomposition import (
    CLAUSE_ROUTE_ANCHOR,
    clause_route,
    seeks_clause,
)
from rag.retrieval.multi_route import (
    DEFAULT_ROUTES_TOP_K,
    DEFAULT_VECTOR_SIMILARITY_WEIGHT,
    RECALL_FLOOR,
    ROUTES_TOP_K_RECOMMENDED,
    RouteResult,
    merge_route_hits,
    multi_route_retrieve,
    resolve_routes_top_k,
)
# Imported before `pipeline` on purpose: `pipeline` imports the planner, so the planner has to be
# fully loaded by the time the package gets there. A direct `import rag.retrieval.planner` must
# work too, and it does not if the planner is only reachable through `pipeline`.
from rag.retrieval.planner import (
    PLAN_HASH_VERSION,
    PLAN_VERSION,
    PlanCache,
    PlanRoute,
    PlannerProvenance,
    QuestionProfile,
    RetrievalPlan,
    cache_scope,
    canonical_json,
    canonical_text,
    compile_plan,
    compile_retrieval_plan,
    compute_plan_hash,
    dimension_heads,
    plan_from_routes,
    profile_question,
    resolve_plan_cache,
    validate_plan,
    validate_routes,
)
from rag.retrieval.pipeline import empty_kbinfos, retrieve_multi_route
from rag.retrieval.query_router import (
    CONCEPTUAL,
    CONCEPTUAL_TOP_K,
    CONCEPTUAL_VECTOR_WEIGHT,
    NUMERIC,
    NUMERIC_TOP_K,
    NUMERIC_VECTOR_WEIGHT,
    PASS_THROUGH,
    REVISION,
    REVISION_TOP_K,
    REVISION_VECTOR_WEIGHT,
    RouteDecision,
    route_question,
)
from rag.retrieval.rerank import (
    CORE_DOCUMENT_BOOST,
    DEFAULT_FINAL_TOP_N,
    FINAL_TOP_N_RECOMMENDED,
    MAX_AUXILIARY_DOCUMENT_SHARE,
    MAX_TABLE_SHARE,
    MIN_PROSE_PASSAGES,
    TABLE_PENALTY,
    DiversityPolicy,
    apply_rank_adjustments,
    dedupe_chunks,
    ensure_route_coverage,
    rerank_chunks,
    resolve_final_top_n,
    routes_of,
    select_context,
)

__all__ = [
    "CLAUSE_ROUTE_ANCHOR",
    "CONCEPTUAL",
    "CONCEPTUAL_TOP_K",
    "CONCEPTUAL_VECTOR_WEIGHT",
    "CORE_DOCUMENT_BOOST",
    "CORE_DOCUMENT_NAME_CUES",
    "DEFAULT_FINAL_TOP_N",
    "DEFAULT_ROUTES_TOP_K",
    "DEFAULT_VECTOR_SIMILARITY_WEIGHT",
    "FINAL_TOP_N_RECOMMENDED",
    "MAX_AUXILIARY_DOCUMENT_SHARE",
    "MAX_SUB_QUERIES",
    "MAX_TABLE_SHARE",
    "MIN_PROSE_PASSAGES",
    "NUMERIC",
    "NUMERIC_TOP_K",
    "NUMERIC_VECTOR_WEIGHT",
    "PASS_THROUGH",
    "PLAN_HASH_VERSION",
    "PLAN_VERSION",
    "PlanCache",
    "PlanRoute",
    "PlannerProvenance",
    "QuestionProfile",
    "RECALL_FLOOR",
    "REVISION",
    "REVISION_TOP_K",
    "REVISION_VECTOR_WEIGHT",
    "ROUTES_TOP_K_RECOMMENDED",
    "RetrievalPlan",
    "RouteDecision",
    "TABLE_PENALTY",
    "DiversityPolicy",
    "RouteResult",
    "apply_rank_adjustments",
    "cache_scope",
    "canonical_json",
    "canonical_text",
    "clause_route",
    "compile_plan",
    "compile_retrieval_plan",
    "compute_plan_hash",
    "core_document_score",
    "dedupe_chunks",
    "decompose_question",
    "dimension_heads",
    "document_breakdown",
    "document_key",
    "document_name",
    "empty_kbinfos",
    "ensure_route_coverage",
    "is_image_chunk",
    "is_prose_chunk",
    "is_table_chunk",
    "looks_composite",
    "merge_route_hits",
    "multi_route_retrieve",
    "parse_sub_queries",
    "plan_from_routes",
    "profile_question",
    "rerank_chunks",
    "resolve_core_documents",
    "resolve_final_top_n",
    "resolve_plan_cache",
    "resolve_routes_top_k",
    "retrieve_multi_route",
    "route_question",
    "routes_of",
    "seeks_clause",
    "select_context",
    "standard_designations",
    "strip_section_references",
    "summarize",
    "validate_plan",
    "validate_routes",
]
