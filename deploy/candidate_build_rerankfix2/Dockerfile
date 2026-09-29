# Disposable candidate: the compared-document reservation contract repair ONLY.
#
# Base is the CURRENT PRODUCTION image (tag resolves to
# sha256:26a44ae5749dbb2e666ede8e8a3ddce323a5b2c2526cc4ae355fd2e502200ee5, which already carries the
# Elasticsearch healthy-hybrid fusion fix).
#
# EXACTLY ONE product file is overlaid: rag/retrieval/rerank.py
#   c70969200234afbc86a65bc814d360d71477aecc3bd7005e0e9c75688eadb315  (repaired)
# vs the deployed
#   1152c59a782766bfb219474cc9a00b7df5168c08c802d280252d8965af3e25cc  (original)
#
# The change is the step-1b iteration in select_context: the compared-document reservation is taken at
# most ONCE per compared document (deduplicated document identities, first-seen score order) instead of
# once per compared CHUNK. No constant, cap, floor, threshold, weight, fusion or metadata is touched.
FROM my-wenruorag:candidate-fusionfix-2daccc2f

COPY rag/retrieval/rerank.py /ragflow/rag/retrieval/rerank.py
