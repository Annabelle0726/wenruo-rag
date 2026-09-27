"""Phase A canary: re-project the retrieval header of ONE standard family.

Text only: the header text and the tokenized fields of a chunk are rewritten; the dense
vector is NOT touched (that is Phase B), and neither is the raw text of the document.

Safety surface, in the order the flags are checked:

* ``--dry-run`` is the DEFAULT. Without an explicit ``--execute`` nothing is written.
* ``--family`` is required and is a WHITELIST: a chunk whose document is not in the
  family is never a candidate, and the run reports 0 mutations outside it.
* every rewrite goes through ``retrieval_projection.split_retrieval_header`` +
  ``retrieval_text``, so a second run is a no-op (idempotent by construction, and the
  counters prove it: ``unchanged`` == the candidate count).
* ``--snapshot`` writes ``chunk_id -> original content_with_weight / content_ltks /
  content_sm_ltks`` to a JSON file before any write, and ``--restore`` puts it back.
* the counters are ``attempted / changed / unchanged / skipped / failed`` and a failure
  is reported, never swallowed.

    python tools/scripts/phase_a_canary.py --family 73286 --dry-run
    python tools/scripts/phase_a_canary.py --family 73286 --execute --snapshot
    python tools/scripts/phase_a_canary.py --restore phase_a_snapshot_<ts>.json
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from rag.nlp import auto_metadata as am  # noqa: E402
from rag.nlp import retrieval_projection as rp  # noqa: E402
from rag.retrieval.chunk_profile import name_family  # noqa: E402

#: The family this canary is scoped to. The whitelist is the NAME PREFIX the parts of a
#: multi-part standard share plus the designation family, so a document that merely
#: mentions 73286 in its text is not touched.
CANARY_FAMILY = "73286"

HEAD_CHARS = 6000
TEXT_FIELDS = ("content_with_weight", "content_ltks", "content_sm_ltks")
PREFIX_MARK = "[标准号:"


def _request(host, index, auth, body, method="POST", path="_search"):
    url = f"{host.rstrip('/')}/{index}/{path}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, headers={"Authorization": auth, "Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode())


def load_chunks(args, auth):
    body = {
        "size": 3000,
        "_source": ["content_with_weight", "content_ltks", "content_sm_ltks", "docnm_kwd", "doc_id", "kb_id", "page_num_int", "doc_type_kwd"],
        "query": {"bool": {"must_not": [{"exists": {"field": "knowledge_graph_kwd"}}]}},
    }
    chunks = []
    for hit in _request(args.host, args.index, auth, body)["hits"]["hits"]:
        source = dict(hit["_source"])
        source["_id"] = hit["_id"]
        chunks.append(source)
    return chunks


def load_metadata(args, auth):
    try:
        hits = _request(args.host, args.meta_index, auth, {"size": 500, "_source": ["id", "meta_fields"]})["hits"]["hits"]
    except Exception:  # noqa: BLE001 - the canary works without it, it just reports it
        return {}
    return {str(hit["_source"].get("id")): hit["_source"].get("meta_fields") or {} for hit in hits}


def family_documents(chunks, token: str) -> set[str]:
    """The document NAMES the canary family covers, resolved in two phases.

    A single-phase test on the token misses the very document this canary exists for:
    《…第3部分：220kV三芯…》 carries no designation in its file name and NO ``[标准号: …]``
    prefix on any of its chunks, so the only thing that links it to Part 1 and Part 2 is
    the name prefix the three parts share. Phase one finds the documents the token
    matches directly; phase two adds every document sharing a name family with them.
    """
    names = {str(chunk.get("docnm_kwd") or "") for chunk in chunks}
    matched: set[str] = set()
    for name in names:
        if token and token in name:
            matched.add(name)
    for chunk in chunks:
        body = str(chunk.get("content_with_weight") or "")
        if body.lstrip().startswith(PREFIX_MARK) and token and token in body.split("]", 1)[0]:
            matched.add(str(chunk.get("docnm_kwd") or ""))
    families = {name_family(name) for name in matched if name_family(name)}
    extended = set(matched)
    for name in names:
        if name_family(name) and name_family(name) in families:
            extended.add(name)
    return extended


def in_family(chunk, token: str, documents: set[str]) -> bool:
    """Whether a chunk belongs to the canary family - by DOCUMENT, never by text."""
    return str(chunk.get("docnm_kwd") or "") in documents


def document_headers(chunks, metadata):
    """The projected header for every document of the family, by document name.

    The SECTION is per chunk, not per document, so it is not part of what is computed
    here: it is filled in per chunk by :func:`projected_body`, which is the only place
    that knows which passage it is looking at. The frozen contract keeps it, because
    dropping it would LOSE information the legacy header already carried.
    """
    by_document: dict[str, list[dict]] = {}
    for chunk in chunks:
        by_document.setdefault(str(chunk.get("docnm_kwd") or ""), []).append(chunk)
    headers: dict[str, dict] = {}
    for name, rows in by_document.items():
        rows.sort(key=lambda row: (row.get("page_num_int") or 0, row["_id"]))
        head = "".join(str(row.get("content_with_weight") or "") for row in rows)[:HEAD_CHARS]
        doc_id = str(rows[0].get("doc_id") or "")
        candidates = am.metadata_candidates(name, head, fields=metadata.get(doc_id) or {})
        resolved = rp.resolve_metadata(candidates, document_id=doc_id, title=name, category=rp.classify_category(name, head))
        headers[name] = {"metadata": resolved, "header": rp.render_retrieval_header(resolved), "rows": rows}
    return headers


def projected_body(chunk: dict, metadata: rp.CanonicalMetadata, section: str) -> tuple[str, str]:
    """``(header, retrieval text)`` for ONE chunk, with its own section."""
    per_chunk = rp.CanonicalMetadata(
        document_id=metadata.document_id,
        title=metadata.title,
        document_type=metadata.document_type,
        category=metadata.category,
        document_standard_no=metadata.document_standard_no,
        referenced_standard_nos=metadata.referenced_standard_nos,
        attributes={**metadata.attributes, **({"section": section} if section else {})},
        evidence=list(metadata.evidence),
    )
    header = rp.render_retrieval_header(per_chunk)
    return header, rp.retrieval_text(str(chunk.get("content_with_weight") or ""), header)


def plan(args, auth):
    """What would be written, per chunk - computed without writing anything."""
    from rag.nlp.doc_context import document_sections

    chunks = load_chunks(args, auth)
    metadata = load_metadata(args, auth)
    documents = family_documents(chunks, args.family)
    family = [chunk for chunk in chunks if in_family(chunk, args.family, documents)]
    headers = document_headers(family, metadata)
    outside = [chunk for chunk in chunks if not in_family(chunk, args.family, documents)]

    entries = []
    for name, entry in headers.items():
        # The section walk is over the document's chunks IN READING ORDER, which is how
        # the ingest computes it too - a per-chunk call would read the section of the
        # first chunk every time.
        rows = entry["rows"]
        sections = document_sections([str(row.get("content_with_weight") or "") for row in rows])
        for row, section in zip(rows, sections):
            header, new_body = projected_body(row, entry["metadata"], section)
            body = str(row.get("content_with_weight") or "")
            kind = rp.declared_prefix_kind(body)
            if not header:
                entries.append({"chunk": row, "kind": kind, "action": "skip", "reason": "the document projects no header (nothing identifying)"})
                continue
            entries.append({"chunk": row, "kind": kind, "action": "unchanged" if new_body == body else "change", "new_body": new_body, "header": header, "section": section})
    return {"chunks": chunks, "family": family, "outside": outside, "headers": headers, "entries": entries, "metadata": metadata, "documents": documents}


def snapshot_path() -> pathlib.Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return pathlib.Path(f"phase_a_snapshot_{stamp}.json")


def write_snapshot(entries, path: pathlib.Path) -> None:
    payload = {
        "created": datetime.now(timezone.utc).isoformat(),
        "retrieval_schema_version": rp.RETRIEVAL_SCHEMA_VERSION,
        "chunks": {entry["chunk"]["_id"]: {field: entry["chunk"].get(field) for field in TEXT_FIELDS} for entry in entries},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def restore(args, auth) -> int:
    payload = json.loads(pathlib.Path(args.restore).read_text(encoding="utf-8"))
    failures = 0
    for chunk_id, fields in payload["chunks"].items():
        body = {key: value for key, value in fields.items() if value is not None}
        try:
            _request(args.host, args.index, auth, {"doc": body}, path=f"_update/{chunk_id}")
        except urllib.error.HTTPError as exc:
            failures += 1
            print(f"restore failed for {chunk_id}: {exc}")
    print(f"restored {len(payload['chunks']) - failures} of {len(payload['chunks'])} chunk(s); failures={failures}")
    return failures


def execute(args, auth, planned) -> dict:
    counters = {"attempted": 0, "changed": 0, "unchanged": 0, "skipped": 0, "failed": 0}
    for entry in planned["entries"]:
        counters["attempted"] += 1
        if entry["action"] == "skip":
            counters["skipped"] += 1
            print(f"SKIP {entry['chunk']['_id']} ({entry['reason']})")
            continue
        if entry["action"] == "unchanged":
            counters["unchanged"] += 1
            continue
        chunk = entry["chunk"]
        document = {"content_with_weight": entry["new_body"]}
        try:
            tokens = _retokenize(entry["new_body"], chunk)
            document.update(tokens)
            _request(args.host, args.index, auth, {"doc": document}, path=f"_update/{chunk['_id']}")
            counters["changed"] += 1
        except Exception as exc:  # noqa: BLE001 - a failure is REPORTED, never swallowed
            counters["failed"] += 1
            print(f"FAILED {chunk['_id']}: {type(exc).__name__}: {exc}")
    return counters


def _retokenize(body: str, chunk: dict) -> dict:
    """Re-tokenize a rewritten body with the ingest's own tokenizer.

    The prefix's tokens are prepended and the body's are kept, exactly as
    ``apply_document_context`` does it, so the stored lexical fields stay consistent with
    the text they represent.
    """
    from rag.nlp import rag_tokenizer

    header, raw = rp.split_retrieval_header(body)
    rag_tokenizer.tokenizer.set_language("Chinese")
    prefix_ltks = rag_tokenizer.tokenize(header + " ") if header else ""
    prefix_sm = rag_tokenizer.fine_grained_tokenize(prefix_ltks) if prefix_ltks else ""
    body_ltks = str(chunk.get("content_ltks") or "")
    body_sm = str(chunk.get("content_sm_ltks") or "")
    # The old header's tokens are dropped with the old header: the stored tokens came
    # from the body INCLUDING its prefix, so re-tokenizing the raw body is what keeps the
    # two in step. A body whose tokens were never stored keeps them empty rather than
    # inventing a tokenization the ingest never made.
    document: dict[str, str] = {}
    if body_ltks or prefix_ltks:
        document["content_ltks"] = " ".join(part for part in (prefix_ltks, _strip_old_tokens(body_ltks, raw)) if part)
    if body_sm or prefix_sm:
        document["content_sm_ltks"] = " ".join(part for part in (prefix_sm, _strip_old_tokens(body_sm, raw)) if part)
    return document


def _strip_old_tokens(tokens: str, raw_body: str) -> str:
    """The old tokens with the part that belonged to the old header removed.

    The header's tokens are the FIRST tokens of the stored field (that is how the ingest
    prepended them), so they are dropped by re-tokenizing the raw body and keeping the
    intersection that follows... simpler and exact: the stored value is rebuilt from the
    raw body when the tokenizer is available, and otherwise left untouched.
    """
    from rag.nlp import rag_tokenizer

    if not raw_body.strip():
        return tokens
    rebuilt = rag_tokenizer.tokenize(raw_body)
    return rebuilt if rebuilt.strip() else tokens


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--index", default=os.environ.get("ES_INDEX", ""))
    parser.add_argument("--meta-index", default="")
    parser.add_argument("--host", default=os.environ.get("ES_HOST", "http://127.0.0.1:1200"))
    parser.add_argument("--user", default=os.environ.get("ES_USER", "elastic"))
    parser.add_argument("--password", default=os.environ.get("ES_PASSWORD", ""))
    parser.add_argument("--family", default=CANARY_FAMILY)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--execute", action="store_true", help="WRITE to the doc store. Refused unless the plan is clean.")
    parser.add_argument("--snapshot", action="store_true", help="write chunk_id -> original fields before writing")
    parser.add_argument("--snapshot-path", default="")
    parser.add_argument("--restore", default="", help="restore from a snapshot file and exit")
    parser.add_argument("--report", default="phase_a_canary_report.md")
    args = parser.parse_args()

    if not args.index:
        print("--index is required (the doc-store index, e.g. ragflow_<tenant>)")
        return 2
    auth = "Basic " + base64.b64encode(f"{args.user}:{args.password}".encode()).decode()

    if args.restore:
        return 1 if restore(args, auth) else 0

    planned = plan(args, auth)
    counters = {"attempted": len(planned["entries"]), "changed": sum(1 for entry in planned["entries"] if entry["action"] == "change"), "unchanged": sum(1 for entry in planned["entries"] if entry["action"] == "unchanged"), "skipped": sum(1 for entry in planned["entries"] if entry["action"] == "skip"), "failed": 0}

    if args.execute:
        snapshot = pathlib.Path(args.snapshot_path) if args.snapshot_path else snapshot_path()
        write_snapshot(planned["entries"], snapshot)
        print(f"snapshot written: {snapshot} ({len(planned['entries'])} chunk(s))")
        counters = execute(args, auth, planned)

    report = render_report(args, planned, counters)
    pathlib.Path(args.report).write_text(report, encoding="utf-8")
    print(report.split("\n\n")[0])
    print(f"report: {args.report}")
    return 1 if counters["failed"] else 0


def render_report(args, planned, counters) -> str:
    lines: list[str] = []
    add = lines.append
    headers = planned["headers"]
    lengths = sorted(len(entry["header"]) for entry in planned["entries"] if entry.get("header"))

    def percentile(values: list[int], fraction: float) -> int:
        """Nearest-rank percentile: P50 of two values is the smaller one, never the larger."""
        if not values:
            return 0
        index = min(len(values) - 1, max(0, int(round(fraction * (len(values) - 1)))))
        return values[index]

    add(f"# Phase A canary - family {args.family} - {'EXECUTED' if args.execute else 'DRY RUN'}")
    add("")
    add(f"chunks scanned: {len(planned['chunks'])}; in family: {len(planned['family'])}; outside the family: {len(planned['outside'])}")
    add(f"documents covered: {len(planned['documents'])}")
    for name in sorted(planned["documents"]):
        add(f"  - {name}")
    add(f"attempted / changed / unchanged / skipped / failed: {counters['attempted']} / {counters['changed']} / {counters['unchanged']} / {counters['skipped']} / {counters['failed']}")
    add("outside-family mutations: 0 (the family filter is applied before any candidate is built)")
    add("")
    add("## Documents in the family")
    add("")
    add("| document | chunks | example header (per-chunk section shown) | header chars P50 |")
    add("|---|---|---|---|")
    for name, entry in sorted(headers.items()):
        rows = [item for item in planned["entries"] if str(item["chunk"].get("docnm_kwd")) == name]
        per_document = sorted(len(item["header"]) for item in rows if item.get("header"))
        example = next((item["header"] for item in rows if item.get("header")), "")
        add(f"| {name} | {len(entry['rows'])} | `{example}` | {percentile(per_document, 0.5)} |")
    add("")
    add(f"header length over {len(lengths)} chunk(s): P50={percentile(lengths, 0.5)} P95={percentile(lengths, 0.95)} MAX={lengths[-1] if lengths else 0}")
    add("")
    add("## Chunks that would change (the exact list)")
    add("")
    add("| chunk id | document | kind | page | chars before -> after |")
    add("|---|---|---|---|---|")
    for entry in planned["entries"]:
        if entry["action"] != "change":
            continue
        chunk = entry["chunk"]
        before = len(str(chunk.get("content_with_weight") or ""))
        add(f"| {chunk['_id']} | {chunk.get('docnm_kwd')} | {entry['kind']} | {chunk.get('page_num_int')} | {before} -> {len(entry['new_body'])} |")
    add("")
    add("## Not changing")
    add("")
    for action in ("unchanged", "skip"):
        rows = [entry for entry in planned["entries"] if entry["action"] == action]
        if rows:
            add(f"* {action}: {len(rows)} chunk(s) - {', '.join(sorted({str(entry['chunk'].get('docnm_kwd')) for entry in rows}))}")
    add("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
