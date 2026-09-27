FROM my-wenruorag@sha256:c50436820cb99f0244b29d2443c9de184b97896c82c060ac8bd58ef04aa190b0
# Option A / P0-B derived image. Base pinned by digest: the verified rollback image.
# Only the observability delta is copied; nothing from HEAD is included.
#
# rag/nlp/search.py is included because it owns the two evidence-leg execution facts that the route
# layer cannot observe: the dense leg's query-embedding request (Dealer.get_vector) and the store
# round trip that carries the lexical expression.
COPY pipeline.py /ragflow/rag/retrieval/pipeline.py
COPY multi_route.py /ragflow/rag/retrieval/multi_route.py
COPY health.py /ragflow/rag/retrieval/health.py
COPY health_producers.py /ragflow/rag/retrieval/health_producers.py
COPY health_bridge.py /ragflow/rag/retrieval/health_bridge.py
COPY search.py /ragflow/rag/nlp/search.py
