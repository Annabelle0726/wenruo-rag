# Candidate construction, authorised for this window only.
#
# Base is exactly the deployed repair image; the build adds exactly the seven approved Python runtime
# files and nothing else. No checkout copy, no tests, no gates, no Go parity files, no planner/pipeline.
FROM my-wenruorag:repair-798288f8

COPY rag/nlp/doc_context.py /ragflow/rag/nlp/doc_context.py
COPY rag/nlp/retrieval_projection.py /ragflow/rag/nlp/retrieval_projection.py
COPY rag/retrieval/chunk_profile.py /ragflow/rag/retrieval/chunk_profile.py
COPY rag/nlp/search.py /ragflow/rag/nlp/search.py
COPY api/apps/restful_apis/chunk_api.py /ragflow/api/apps/restful_apis/chunk_api.py
COPY rag/svr/task_executor_refactor/dataflow_service.py /ragflow/rag/svr/task_executor_refactor/dataflow_service.py
COPY rag/advanced_rag/harness/tools/text_processing.py /ragflow/rag/advanced_rag/harness/tools/text_processing.py
