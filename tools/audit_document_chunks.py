#
#  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
#  Modifications Copyright 2026 线缆工业智搜平台. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
"""Did this value land in a chunk at all? One command, run inside the server.

Every "the model cannot see row X of 表1" report splits into two very different
faults, and the stored chunks say which one it is:

* the row is in NO chunk - the PARSE lost it (the structure recogniser read the
  table as its head only, the layout model never called the region a table, the
  page was OCR'd as an image, or the line was dropped as a scrap). No retrieval
  change can reach a row that was never stored;
* the row IS in a chunk - the RETRIEVAL/answer path did not surface it. The report
  then names the chunk, its shape and its page, which is what the retrieval side
  needs.

Usage, inside the API/worker container (the repo root is the working directory):

    python tools/audit_document_chunks.py --doc-id <document_id> 1200 3.9 800
    python tools/audit_document_chunks.py --name 220kV单芯 --json > audit.json

``--name`` takes a file-name substring and audits every document that matches.
The doc-store query goes through the same connector and index the ingest writes to,
so it works for Elasticsearch, OpenSearch, Infinity, OceanBase and GaussDB alike.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Iterable, Sequence

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from rag.retrieval.chunk_profile import (  # noqa: E402
    DOC_TYPE_IMAGE,
    doc_type,
    is_image_chunk,
    is_table_chunk,
)

#: How much of a chunk is quoted in the report.
EXCERPT_CHARS = 220
#: Values a cable report usually asks about; overridden by the positional patterns.
DEFAULT_PATTERNS = ("表1", "1200", "800")


def chunk_body(chunk: dict) -> str:
    body = chunk.get("content_with_weight") or chunk.get("content") or chunk.get("content_without_weight") or ""
    return body if isinstance(body, str) else str(body)


def classify(chunk: dict) -> str:
    """What kind of stored passage this is, in the terms the parse decides it in.

    ``table-html`` / ``table-markdown`` matter: only Markdown is split with its header
    repeated by the older splitter, and HTML is split by ``split_html_table`` - a table
    that reached the store as neither is a table the recogniser did not emit.
    """
    body = chunk_body(chunk)
    lowered = body.lower()
    if "<table" in lowered or "<tr" in lowered:
        return "table-html"
    if is_table_chunk(chunk):
        return "table-markdown" if body.lstrip().startswith(("表", "Table", "|", "附")) or "| ---" in body else "table"
    if is_image_chunk(chunk) or doc_type(chunk) == DOC_TYPE_IMAGE:
        return "image"
    return "text"


def pages_of(chunk: dict) -> list[int]:
    """The page numbers a passage covers, 1-based, from the parser's own positions."""
    pages: list[int] = []
    for key in ("page_num_int",):
        value = chunk.get(key)
        if isinstance(value, (list, tuple)):
            pages.extend(int(page) + 1 for page in value if isinstance(page, (int, float)) and int(page) >= 0)
    for position in chunk.get("position_int") or []:
        if isinstance(position, (list, tuple)) and position:
            page = position[0]
            if isinstance(page, (int, float)) and int(page) > 0:
                pages.append(int(page))
    return sorted(set(pages))


def _excerpt(body: str, pattern: str) -> str:
    index = body.find(pattern)
    if index < 0:
        return " ".join(body[:EXCERPT_CHARS].split())
    start = max(0, index - EXCERPT_CHARS // 2)
    return " ".join(body[start : start + EXCERPT_CHARS].split())


def audit(chunks: Sequence[dict], patterns: Iterable[str] = DEFAULT_PATTERNS) -> dict:
    """Where each pattern occurs, and what shape the passages it occurs in have."""
    chunks = list(chunks)
    report: dict[str, Any] = {
        "chunks": len(chunks),
        "shapes": {},
        "page_range": [],
        "patterns": {},
    }
    shapes: dict[str, int] = {}
    pages: list[int] = []
    for chunk in chunks:
        shape = classify(chunk)
        shapes[shape] = shapes.get(shape, 0) + 1
        pages.extend(pages_of(chunk))
    report["shapes"] = dict(sorted(shapes.items()))
    report["page_range"] = [min(pages), max(pages)] if pages else []

    for pattern in patterns:
        hits = []
        for index, chunk in enumerate(chunks):
            body = chunk_body(chunk)
            if pattern not in body:
                continue
            hits.append(
                {
                    "index": index,
                    "shape": classify(chunk),
                    "pages": pages_of(chunk),
                    "chars": len(body),
                    "chunk_id": chunk.get("chunk_id") or chunk.get("id") or "",
                    "excerpt": _excerpt(body, pattern),
                }
            )
        report["patterns"][pattern] = hits
    return report


def render(report: dict) -> str:
    lines = [
        f"chunks: {report['chunks']}",
        f"shapes: {report['shapes'] or '{}'}",
        f"pages covered by chunks: {report['page_range'] or 'none'}",
    ]
    for pattern, hits in report["patterns"].items():
        if not hits:
            lines.append(f"  {pattern!r}: NOT FOUND in any chunk of this document")
            continue
        lines.append(f"  {pattern!r}: {len(hits)} chunk(s)")
        for hit in hits[:10]:
            lines.append(f"    #{hit['index']} {hit['shape']} page(s)={hit['pages']} {hit['chars']} chars :: {hit['excerpt']}")
        if len(hits) > 10:
            lines.append(f"    ... and {len(hits) - 10} more")
    return "\n".join(lines)


def verdict(report: dict, patterns: Sequence[str]) -> str:
    """The one line that decides which side of the pipeline to investigate."""
    missing = [pattern for pattern in patterns if not report["patterns"].get(pattern)]
    if missing and not report["chunks"]:
        return "VERDICT: this document has NO chunks at all - the parse stored nothing (check the task log)."
    if missing:
        return (
            f"VERDICT: {missing} are in NO chunk of this document - the PARSE lost them. "
            "Look for the '[Table] page(s) …' lines of that parse: a warning there names the page and the row count "
            "the rule-based reading found for the same region."
        )
    shapes = set()
    for pattern in patterns:
        for hit in report["patterns"].get(pattern, []):
            shapes.add(hit["shape"])
    return f"VERDICT: every pattern is stored ({sorted(shapes)}) - this is a RETRIEVAL/answer-side question, not a parse gap."


def _iter_documents(conn, index_name: str, *, doc_id: str, kb_ids: list[str], page_size: int = 1000):
    """Chunks of one document, in storage order, paged."""
    from common.doc_store.doc_store_base import OrderByExpr

    condition: dict[str, Any] = {"doc_id": doc_id}
    order_by = OrderByExpr()
    order_by.asc("doc_id")
    offset = 0
    while True:
        results = conn.search(
            select_fields=["*"],
            highlight_fields=[],
            condition=condition,
            match_expressions=[],
            order_by=order_by,
            offset=offset,
            limit=page_size,
            index_names=index_name,
            knowledgebase_ids=kb_ids,
        )
        rows = _rows_of(results)
        if not rows:
            return
        yield from rows
        if len(rows) < page_size:
            return
        offset += page_size


def _rows_of(results: Any) -> list[dict]:
    """Chunks out of whatever shape the connector returns (ES, DataFrame, list)."""
    if results is None:
        return []
    if isinstance(results, tuple) and len(results) == 2:
        results = results[0]
    if hasattr(results, "iterrows"):
        return [dict(row) for _, row in results.iterrows()]
    if hasattr(results, "get") and "hits" in results:
        return [dict(hit.get("_source", {})) for hit in results.get("hits", {}).get("hits", [])]
    if isinstance(results, list):
        rows = []
        for item in results:
            if isinstance(item, dict):
                rows.append(dict(item.get("_source", item)))
        return rows
    return []


def _resolve_documents(doc_id: str | None, name: str | None) -> list[dict]:
    from api.db.db_models import Knowledgebase
    from api.db.services.document_service import DocumentService

    query = DocumentService.model.select()
    if doc_id:
        query = query.where(DocumentService.model.id == doc_id)
    elif name:
        query = query.where(DocumentService.model.name.contains(name))
    else:
        raise SystemExit("give --doc-id or --name")
    documents = []
    for document in query.limit(50):
        kb = Knowledgebase.get_or_none(Knowledgebase.id == document.kb_id)
        if kb is None:
            continue
        documents.append({"id": document.id, "name": document.name, "kb_id": document.kb_id, "tenant_id": kb.tenant_id})
    return documents


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("patterns", nargs="*", default=list(DEFAULT_PATTERNS), help="values to look for in the stored chunks")
    parser.add_argument("--doc-id", help="document id")
    parser.add_argument("--name", help="file-name substring (audits every match)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    from common import settings
    from rag.nlp.search import index_name as index_name_of

    documents = _resolve_documents(args.doc_id, args.name)
    if not documents:
        print("no document matched; check --doc-id/--name")
        return 2

    conn = settings.docStoreConn
    reports = []
    for document in documents:
        index = index_name_of(document["tenant_id"])
        chunks = list(
            _iter_documents(
                conn,
                index,
                doc_id=document["id"],
                kb_ids=[document["kb_id"]],
            )
        )
        report = audit(chunks, args.patterns)
        report["document"] = {"id": document["id"], "name": document["name"], "kb_id": document["kb_id"], "index": index}
        report["verdict"] = verdict(report, args.patterns)
        reports.append(report)

    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2, default=str))
        return 0

    for report in reports:
        print(f"=== {report['document']['name']} ({report['document']['id']}) ===")
        print(f"index: {report['document']['index']}")
        print(render(report))
        print(report["verdict"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
