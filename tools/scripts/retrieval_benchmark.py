"""Read-only retrieval benchmark for the Phase A canary (a regression suite, not statistics).

For each query it prints the top 10 passages the LEXICAL leg returns from the live index,
with the document, the standard part, the rank, the score, the header kind of the passage
and whether the passage carries the evidence the query is about. It then reports
Recall@5, Recall@10 and MRR per query and per query class.

Why the lexical leg only: Phase A rewrites TEXT and TOKENS. The dense vector of a stored
chunk is not touched by it, so the dense leg returns exactly what it returns today and the
entire canary delta is measurable here. The hybrid leg is measured in the after-run by the
same script pointed at the same index, once the assertions above hold.

The evidence for a query is a document + a phrase the answer has to come from; a hit
"counts" when the phrase is in the passage text. Nothing here writes anything.

    ES_PASSWORD=... python tools/scripts/retrieval_benchmark.py --index ragflow_<tenant>
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

from rag.nlp import retrieval_projection as rp  # noqa: E402

#: The canary regression suite. ``evidence`` is a phrase the answering passage must
#: contain; ``expect_part`` is the standard part the answer is expected to come from, which
#: is what makes the disambiguation query (E) meaningful.
QUERIES: tuple[dict, str] = (
    {"id": "A", "class": "exact standard number", "question": "根据 Q/GDW 73286.2-2026 查找单芯 220kV 海缆参数", "evidence": "标称截面", "expect_part": "2"},
    {"id": "B", "class": "natural language, no number", "question": "220kV 单芯海底电缆的导体、内衬层、铠装层技术参数是多少", "evidence": "内衬层", "expect_part": "2"},
    {"id": "C", "class": "three-core", "question": "220kV 三芯海底电缆结构参数", "evidence": "3×", "expect_part": "3"},
    {"id": "D", "class": "generic part", "question": "220kV 海底电力电缆内衬层厚度要求", "evidence": "内衬层", "expect_part": "1"},
    {"id": "E", "class": "disambiguation", "question": "单芯 220kV 海缆", "evidence": "单芯", "expect_part": "2"},
    {"id": "F", "class": "blank template", "question": "220kV 单芯海缆接头规格 投标人填写", "evidence": "接头规格", "expect_part": "2"},
)


def _search(host, index, auth, body):
    url = f"{host.rstrip('/')}/{index}/_search"
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Authorization": auth, "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode())


def tokenized(question: str) -> str:
    """The question as the INGEST would tokenize it before matching `content_ltks`.

    `content_ltks` holds the ingest's own tokens (``单 芯 海底 电缆``), so a raw question
    string does not match it: an ES `match` on the whole sentence produces one token that
    is nothing like the stored ones. Measured while writing this: every query returned
    ZERO hits until the question went through the same tokenizer.
    """
    from rag.nlp import rag_tokenizer

    rag_tokenizer.tokenizer.set_language("Chinese")
    return " ".join(rag_tokenizer.tokenize(question).split())


def part_of(chunk: dict, body: str) -> str:
    """Which part of the standard a passage belongs to, from its name or its header."""
    import re

    name = str(chunk.get("docnm_kwd") or "")
    found = re.search(r"第\s*([0-9])\s*部分", name)
    if found:
        return found.group(1)
    found = re.search(r"标准号:[^|\]]*?\.(\d)-", body)
    return found.group(1) if found else "?"


def run_query(args, auth, spec) -> dict:
    body = {
        "size": 10,
        "_source": ["content_with_weight", "docnm_kwd", "doc_id", "page_num_int", "doc_type_kwd"],
        "query": {"bool": {"must": [{"match": {"content_ltks": tokenized(spec["question"])}}], "must_not": [{"exists": {"field": "knowledge_graph_kwd"}}]}},
    }
    hits = []
    for rank, hit in enumerate(_search(args.host, args.index, auth, body)["hits"]["hits"], 1):
        source = hit["_source"]
        text = str(source.get("content_with_weight") or "")
        hits.append(
            {
                "rank": rank,
                "id": hit["_id"],
                "score": hit["_score"],
                "document": str(source.get("docnm_kwd") or ""),
                "part": part_of(source, text),
                "kind": rp.declared_prefix_kind(text),
                "doc_type": str(source.get("doc_type_kwd") or ""),
                "evidence": spec["evidence"] in text,
                "page": source.get("page_num_int"),
            }
        )
    first_relevant = next((hit["rank"] for hit in hits if hit["evidence"] and hit["part"] == spec["expect_part"]), None)
    return {"spec": spec, "hits": hits, "first_relevant": first_relevant}


def render(results) -> str:
    lines: list[str] = []
    add = lines.append
    add("# Retrieval benchmark BEFORE the Phase A canary (lexical leg, read-only)")
    add("")
    add("| query | P@1 | P@3 | P@5 | rank of the first expected passage | Recall@5 | Recall@10 | RR |")
    add("|---|---|---|---|---|---|---|---|")
    recall5 = recall10 = 0
    reciprocal = 0.0
    for result in results:
        spec = result["spec"]
        hits = result["hits"]
        relevant = [hit for hit in hits if hit["evidence"] and hit["part"] == spec["expect_part"]]
        top5 = 1 if any(hit["rank"] <= 5 for hit in relevant) else 0
        top10 = 1 if any(hit["rank"] <= 10 for hit in relevant) else 0
        recall5 += top5
        recall10 += top10
        reciprocal += (1.0 / result["first_relevant"]) if result["first_relevant"] else 0.0
        add(f"| {spec['id']} {spec['class']} | {hits[0]['part'] if hits else '-'} | {'/'.join(hit['part'] for hit in hits[:3])} | {top5} | {result['first_relevant'] or '-'} | {top5} | {top10} | {(1.0 / result['first_relevant']) if result['first_relevant'] else 0:.3f} |")
    total = len(results) or 1
    add("")
    add(f"**Recall@5 = {recall5}/{total} = {recall5 / total:.2f}; Recall@10 = {recall10}/{total} = {recall10 / total:.2f}; MRR = {reciprocal / total:.3f}** (canary regression suite, NOT a statistical benchmark)")
    add("")
    for result in results:
        spec = result["spec"]
        add(f"## {spec['id']}. {spec['question']}")
        add("")
        add(f"class: {spec['class']}; expected evidence: `{spec['evidence']}` in part {spec['expect_part']}")
        add("")
        add("| rank | chunk id | document | part | score | kind | evidence |")
        add("|---|---|---|---|---|---|---|")
        for hit in result["hits"]:
            marker = "**yes**" if (hit["evidence"] and hit["part"] == spec["expect_part"]) else ("yes" if hit["evidence"] else "")
            add(f"| {hit['rank']} | {hit['id']} | {hit['document'][:40]} | {hit['part']} | {hit['score']:.3f} | {hit['kind']} | {marker} |")
        add("")
    add("## What this measures and what it does not")
    add("")
    add("* It measures the LEXICAL leg over `content_ltks`, which is exactly what Phase A rewrites.")
    add("* The dense leg is NOT measured here and cannot change: Phase A does not touch `q_*_vec`.")
    add("* The fused (hybrid) score is therefore expected to move only through its lexical term; the")
    add("  after-run repeats this exact script on the same index, so the two tables are comparable.")
    add("* `part` comes from the file name (or the header's designation), so a passage with neither shows `?`.")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--index", required=True)
    parser.add_argument("--host", default=os.environ.get("ES_HOST", "http://127.0.0.1:1200"))
    parser.add_argument("--user", default=os.environ.get("ES_USER", "elastic"))
    parser.add_argument("--password", default=os.environ.get("ES_PASSWORD", ""))
    parser.add_argument("--label", default="before")
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    auth = "Basic " + base64.b64encode(f"{args.user}:{args.password}".encode()).decode()

    results = [run_query(args, auth, spec) for spec in QUERIES]
    report = render(results).replace("BEFORE the Phase A canary", f"{args.label.upper()} the Phase A canary")
    path = pathlib.Path(args.report or f"retrieval_benchmark_{args.label}.md")
    path.write_text(report, encoding="utf-8")
    print(report.split("## ")[0])
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
