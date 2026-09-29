#!/bin/sh
echo "=== consumers of retrieval_projection in /ragflow product code ==="
grep -rn "retrieval_projection" --include=*.py /ragflow \
  | grep -v "^/ragflow/.venv/" | grep -v "^/ragflow/web/" | head -20
echo "=== count ==="
grep -rln "retrieval_projection" --include=*.py /ragflow | grep -v "^/ragflow/.venv/" | wc -l

echo "=== who imports apply_projection / resolve_metadata ==="
grep -rn "apply_projection\|resolve_metadata" --include=*.py /ragflow \
  | grep -v "^/ragflow/.venv/" | grep -v "retrieval_projection.py" | head -20

echo "=== frozen runtime consumer hashes ==="
for f in rerank.py multi_route.py query_router.py pipeline.py health.py health_bridge.py health_producers.py; do
  if [ -f "/ragflow/rag/retrieval/$f" ]; then sha256sum "/ragflow/rag/retrieval/$f"; else echo "ABSENT $f"; fi
done

echo "=== frontend aggregate ==="
find /ragflow/web/dist -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum
echo "frontend_file_count=$(find /ragflow/web/dist -type f | wc -l)"
