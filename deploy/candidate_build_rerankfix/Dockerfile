# Disposable one-file candidate: the repaired retrieval ordering/selection policy.
# Base is the CURRENT PRODUCTION image, pinned by its production tag (resolves to
# sha256:a41dcc649780eee2e1676157ad279bac61e00478005b5529eacd71e453404990).
# The build context holds ONLY rag/retrieval/rerank.py, so no other runtime file can enter.
FROM my-wenruorag:candidate-nine-91b8bfc6

COPY rag/retrieval/rerank.py /ragflow/rag/retrieval/rerank.py
