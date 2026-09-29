"""Excerpt + classification for the same pinned chunk. Explains WHY pairing was not detected.

Reads the same single chunk id and the same frozen question; no query, no other chunk, no writes.
"""
import json
import pathlib
import sys

sys.path.insert(0, "/ragflow")

from common import settings

settings.init_settings()

from rag.retrieval.chunk_profile import _body_text, _values_text, result_figures  # noqa: E402
from rag.retrieval.decomposition import question_numeric_occurrences, question_values  # noqa: E402

INDEX = "ragflow_a9e28731ab7011f19b833887d563fb04"
CONTROL = "b5aaf72bcd33d44a"

question = pathlib.Path("/tmp/incident_question.json").read_text(encoding="utf-8-sig").strip()
chunk = settings.docStoreConn.es.get(index=INDEX, id=CONTROL)["_source"]

body = _body_text(chunk)

print("--- QUESTION classification (why there are no question values) ---")
print(f"  question: {question}")
for occ in question_numeric_occurrences(question):
    print(f"    text={occ.text!r} kind={occ.kind}")
print(f"  question_values(INCIDENT) = {question_values(question)}")

prefix_len = len(chunk.get("content_with_weight", "")) - len(body)
print("\n--- CONTROL chunk own text (first 420 chars) ---")
print("  " + body[:420].replace("\n", " "))
print(f"\n  body_chars={len(body)} ingest_prefix_chars={prefix_len} "
      f"provenance_present={'content_prefix_kind_kwd' in chunk}")
print(f"  decimal result_figures in the chunk = {sorted(result_figures(chunk))}")
print(f"  values_text contains '99.9' = {'99.9' in _values_text(chunk)}")
