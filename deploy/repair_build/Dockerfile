# Candidate image for the FALSE_EMPTY_BY_DENSE_EXCEPTION_SHORT_CIRCUIT repair.
#
# Verification artifact, exactly like the earlier phase-Dockerfile pattern: it derives an immutable
# tag from the CURRENT production image by copying ONLY the two files this window is authorised to
# change. Release still requires the normal compose build; this image exists so the repair can be
# gated at image level and deployed as a frozen, byte-identified artifact.
#
# The base is pinned by TAG, not by digest, and that is deliberate: this repository is local-only, so
# a digest FROM makes BuildKit issue a registry HEAD that the configured mirror rejects with 403.
# `my-wenruorag:p0-7-obs-9f3d2c79` resolves to image id sha256:ea93cd3bb7953e518c8694d86fe7a58af381ca4593ec42656bfd4e4964b5dba5,
# which recipe's own FROM line records so the lineage is auditable.
#
# WHAT IS COPIED, AND WHY NOTHING ELSE IS:
#
#   rag/nlp/search.py          deployed bytes + the approved repair (dense-failure isolation, the
#                              dedicated embedding pool with its 60 s retrieval-side wait boundary,
#                              the LEXICAL_DEGRADED execution state, the corrected recoverability
#                              classification, and the absent-chunk-vector tolerance in
#                              insert_citations).
#   rag/retrieval/multi_route.py  deployed bytes + the approved mixed-state merge.
#
# The rest of the retrieval package is deliberately NOT copied. The repository tree currently also
# carries the SUSPENDED P1-2 planner work (rag/retrieval/planner.py, a rewritten pipeline.py,
# decomposition.py, chunk_profile.py, __init__.py); P1-2 is paused and none of it may enter this
# image. Everything else in the image - the P0 health modules, the P0-C leg attribution, the P0-7
# emitter, the P0-6 frontend bundle - comes from the base and is therefore byte-identical to
# production.
FROM my-wenruorag:p0-7-obs-9f3d2c79

COPY search.py /ragflow/rag/nlp/search.py
COPY multi_route.py /ragflow/rag/retrieval/multi_route.py

# Fail the build rather than ship an image that quietly contains suspended work.
RUN set -eux; \
    test ! -e /ragflow/rag/retrieval/planner.py; \
    if grep -rIl -e 'rag.retrieval.planner' -e 'compile_retrieval_plan' -e 'plan_hash' /ragflow/rag /ragflow/api 2>/dev/null; then \
        echo "P1-2 leakage detected in the candidate image" >&2; exit 1; \
    fi; \
    python -c "import sys; sys.path.insert(0, '/ragflow'); import common.settings; import rag.nlp.search as s; assert hasattr(s, 'EmbeddingCapacityError'); assert s.Dealer._embedding_wait_seconds == 60.0; import rag.retrieval.multi_route as m; assert hasattr(m, '_merge_degraded_routes'); print('candidate payload imports')"
