"""Report how a live index classifies the passages a question's own figures point at.

The diagnostic that produced the value-pairing rule in ``rag/retrieval``. For a
question and an index it prints, per document, which table passages PAIR one of the
question's figures with a result and which merely LIST them - the distinction the cut
acts on, and the one the fused score cannot see.

    python tools/scripts/probe_value_signal.py --index ragflow_<tenant> --question "针对 800 mm² 与 1200 mm² …"

Credentials come from the environment (``ES_HOST``, ``ES_USER``, ``ES_PASSWORD``,
defaulting to the docker-compose stack's elasticsearch). The report is written to
``probe_out.txt`` because a Windows console mangles the Chinese file names.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from rag.retrieval.chunk_profile import carries_value, paired_values, result_figures  # noqa: E402
from rag.retrieval.decomposition import question_values  # noqa: E402

DEFAULT_QUESTION = "针对 800 mm² 与 1200 mm² 的单芯与三芯电缆，金属套平均厚度分别是多少？"


def _search(url, auth, body):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Authorization": auth, "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True, help="doc-store index, e.g. ragflow_<tenant_id>")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--host", default=os.environ.get("ES_HOST", "http://127.0.0.1:1200"))
    parser.add_argument("--user", default=os.environ.get("ES_USER", "elastic"))
    parser.add_argument("--password", default=os.environ.get("ES_PASSWORD", ""))
    parser.add_argument("--limit", type=int, default=300, help="passages read per document")
    args = parser.parse_args()

    url = f"{args.host.rstrip('/')}/{args.index}/_search"
    auth = "Basic " + base64.b64encode(f"{args.user}:{args.password}".encode()).decode()

    names = [bucket["key"] for bucket in _search(url, auth, {"size": 0, "aggs": {"docs": {"terms": {"field": "docnm_kwd", "size": 200}}}})["aggregations"]["docs"]["buckets"]]
    pool = []
    for name in names:
        body = {
            "size": args.limit,
            "_source": ["content_with_weight", "docnm_kwd", "doc_type_kwd", "doc_id", "id"],
            "query": {"bool": {"must": [{"term": {"docnm_kwd": name}}, {"term": {"doc_type_kwd": "table"}}]}},
        }
        pool.extend(hit["_source"] for hit in _search(url, auth, body)["hits"]["hits"])

    values = question_values(args.question, pool)
    lines = [f"index: {args.index}", f"question: {args.question}", f"question_values(pool={len(pool)}): {values}", ""]
    for name in sorted({chunk.get("docnm_kwd") for chunk in pool}):
        rows = [chunk for chunk in pool if chunk.get("docnm_kwd") == name]
        pairing = [chunk for chunk in rows if paired_values(chunk, values)]
        listing = [chunk for chunk in rows if not paired_values(chunk, values) and carries_value(chunk, values)]
        lines.append(f"{name}: {len(rows)} table passage(s); pairing={len(pairing)}; listing-only={len(listing)}")
        for chunk in pairing:
            lines.append(f"    PAIRING {str(chunk.get('id'))[:12]} results={sorted(result_figures(chunk))[:6]}")
        for chunk in listing[:4]:
            lines.append(f"    listing {str(chunk.get('id'))[:12]} results={sorted(result_figures(chunk))[:4]}")

    pathlib.Path("probe_out.txt").write_text("\n".join(lines), encoding="utf-8")
    print("wrote probe_out.txt")


if __name__ == "__main__":
    main()
