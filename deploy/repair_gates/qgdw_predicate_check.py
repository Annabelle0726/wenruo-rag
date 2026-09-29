"""FINAL READ-ONLY PREDICATE CHECK - corrected run.

The previous attempt staged the question through a PowerShell/python stdout round-trip that mangled
the Chinese text (90 chars -> 117). This run reads the frozen INCIDENT question DIRECTLY from the
attribution artifact copied in byte-exactly, and writes its report to a file so no console codec can
touch the result on the way back.

One pinned chunk fetched by id (a direct document GET, not a retrieval query). Nothing else read,
no query issued, nothing written to any datastore.
"""
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, "/ragflow")

from common import settings

settings.init_settings()

from rag.retrieval.chunk_profile import (  # noqa: E402
    carries_value,
    is_hollow_table,
    is_table_chunk,
    paired_values,
    result_figures,
    table_fill_ratio,
    _body_text,
    _values_text,
)
from rag.retrieval.decomposition import (  # noqa: E402
    question_numeric_occurrences,
    question_values,
    seeks_clause,
    mentions_requirement,
)

INDEX = "ragflow_a9e28731ab7011f19b833887d563fb04"
CONTROL = "b5aaf72bcd33d44a"

question = json.loads(pathlib.Path("/tmp/attr.json").read_text(encoding="utf-8"))["queries"][0]["question"]
chunk = settings.docStoreConn.es.get(index=INDEX, id=CONTROL)["_source"]

values = question_values(question)
paired = sorted(paired_values(chunk, values))
carries = carries_value(chunk, values)
hollow = is_hollow_table(chunk)
body = _body_text(chunk)
values_text = _values_text(chunk)

occurrences = [{"text": o.text, "kind": o.kind, "start": o.start, "end": o.end}
               for o in question_numeric_occurrences(question)]

windows = []
for value in values:
    start = 0
    found = 0
    while found < 3:
        hit = values_text.find(value, start)
        if hit < 0:
            break
        lo, hi = max(0, hit - 20), min(len(values_text), hit + len(value) + 20)
        windows.append({"value": value, "offset": hit, "excerpt": values_text[lo:hi].replace("\n", " ")})
        start = hit + 1
        found += 1

report = {
    "question_sha256": hashlib.sha256(question.encode("utf-8")).hexdigest(),
    "question_chars": len(question),
    "question": question,
    "chunk_id": CONTROL,
    "is_table": is_table_chunk(chunk),
    "doc_type_kwd": chunk.get("doc_type_kwd"),
    "provenance_present": "content_prefix_kind_kwd" in chunk,
    "body_chars": len(body),
    "seeks_clause": seeks_clause(question),
    "mentions_requirement": mentions_requirement(question),
    "question_occurrences": occurrences,
    "QUESTION_VALUES": values,
    "CONTROL_PAIRED_VALUES": paired,
    "CONTROL_IS_HOLLOW": hollow,
    "CONTROL_CARRIES_VALUE": carries,
    "table_fill_ratio": table_fill_ratio(chunk),
    "result_figures": sorted(result_figures(chunk)),
    "pairing_windows": windows,
    "body_head": body[:300].replace("\n", " "),
    "body_tail": body[-200:].replace("\n", " "),
}
pathlib.Path("/tmp/predicate_check.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
print("CHECK_WRITTEN", report["question_chars"], len(values), paired, hollow, carries)
