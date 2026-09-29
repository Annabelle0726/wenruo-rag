# Clean nine-file candidate overlay.
# Base is the authoritative deployed image, pinned by tag (never `latest`).
# The build context contains ONLY the nine authorised runtime files, so no
# checkout-wide COPY is possible: the overlay is exactly the manifest.
FROM my-wenruorag:repair-798288f8

COPY rag/nlp/doc_context.py /ragflow/rag/nlp/doc_context.py
COPY rag/nlp/retrieval_projection.py /ragflow/rag/nlp/retrieval_projection.py
COPY rag/retrieval/chunk_profile.py /ragflow/rag/retrieval/chunk_profile.py
COPY rag/retrieval/decomposition.py /ragflow/rag/retrieval/decomposition.py
COPY rag/nlp/search.py /ragflow/rag/nlp/search.py
COPY api/apps/restful_apis/chunk_api.py /ragflow/api/apps/restful_apis/chunk_api.py
COPY rag/svr/task_executor_refactor/dataflow_service.py /ragflow/rag/svr/task_executor_refactor/dataflow_service.py
COPY rag/advanced_rag/harness/tools/text_processing.py /ragflow/rag/advanced_rag/harness/tools/text_processing.py
COPY api/db/services/dialog_service.py /ragflow/api/db/services/dialog_service.py
