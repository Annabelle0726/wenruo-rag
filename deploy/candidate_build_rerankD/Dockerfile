# Disposable candidate: Variant D, the minimal repair.
#
# Base is CURRENT PRODUCTION:
#   my-wenruorag:candidate-fusionfix-2daccc2f
#   sha256:26a44ae5749dbb2e666ede8e8a3ddce323a5b2c2526cc4ae355fd2e502200ee5
#
# EXACTLY ONE product file is overlaid: rag/retrieval/rerank.py
#   4498c2ed2b2ce64d11af05106e4b85815c9dc4249e974329500467b4e42de96d  (Variant D)
# vs the deployed
#   1152c59a782766bfb219474cc9a00b7df5168c08c802d280252d8965af3e25cc
#
# Variant D = deployed + step-1b compared-document dedup + combined reservation budget
# + ONE score-ordered fill (replacing pass-3 prose-first / pass-4 table-second).
# Original stage order kept. No penalty, ranking, cap, Top-N, threshold or weight change.
FROM my-wenruorag:candidate-fusionfix-2daccc2f

COPY rag/retrieval/rerank.py /ragflow/rag/retrieval/rerank.py
