# Disposable candidate: the Elasticsearch healthy-hybrid fusion contract fix.
#
# Base is the CURRENT PRODUCTION image (tag resolves to
# sha256:a41dcc649780eee2e1676157ad279bac61e00478005b5529eacd71e453404990).
#
# EXACTLY TWO product files are overlaid:
#   rag/nlp/search.py        - ES branch builds the fusion expr from the requested vector weight
#   rag/utils/es_conn.py     - emits BOTH contributions explicitly (lexical bool boost, kNN boost)
# plus the two test files whose pins described the old hardcoded literal.
#
# NOT included: the earlier undeployed rag/retrieval/rerank.py repair, and any metadata change
# (the metadata repair is datastore state, not image content).
FROM my-wenruorag:candidate-nine-91b8bfc6

COPY rag/nlp/search.py /ragflow/rag/nlp/search.py
COPY rag/utils/es_conn.py /ragflow/rag/utils/es_conn.py
COPY test/unit_test/rag/test_search_fusion_weight.py /ragflow/test/unit_test/rag/test_search_fusion_weight.py
COPY test/unit_test/rag/nlp/test_gaussdb_retrieval.py /ragflow/test/unit_test/rag/nlp/test_gaussdb_retrieval.py
