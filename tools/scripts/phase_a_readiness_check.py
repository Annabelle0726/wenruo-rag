"""Corrective-migration readiness for the Phase A canary (READ-ONLY).

It calls the SAME projection as the migration (`retrieval_projection.project_chunk` and
`token_fields`) - there is no second algorithm here, which is the only way an audit of what
would be written can mean anything.

What it produces, in `phase_a_corrective_readiness.md`:

* the real old -> projected diff over the canary family, one row per changed chunk, with the
  raw-body hash that proves both sides were computed from the SAME body;
* the section transition census, whose `old X -> same X` bucket must be EMPTY (a change with
  an identical section means the checker is comparing the wrong thing);
* evidence for every `section_removed` and `section_changed`, quoting the raw body head;
* the convergence simulation `S0 -> S1 -> S2 -> S3` for all three initial states
  (raw / legacy+raw / current+raw) over a WHOLE document sequence, because the section walk is
  stateful: the state is the "current heading" carried from chunk to chunk in reading order,
  and it is why an isolated chunk cannot be tested and why a re-run from the stored state is
  deterministic.

    ES_PASSWORD=... python tools/scripts/phase_a_readiness_check.py --index ragflow_<tenant>
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import pathlib
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from rag.nlp import auto_metadata as am  # noqa: E402
from rag.nlp import retrieval_projection as rp  # noqa: E402
from rag.nlp.doc_context import document_sections  # noqa: E402

HEAD_CHARS = 6000
EVIDENCE_CHARS = 120
FAMILY = (
    "220kV海底电力电缆系统采购标准+第1部分：通用技术规范.pdf",
    "220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范.pdf",
    "220kV海底电力电缆系统采购标准+第3部分：220kV三芯海底电力电缆系统专用技术规范.pdf",
)


def _auth(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def _search(host, index, auth, body):
    request = urllib.request.Request(f"{host.rstrip('/')}/{index}/_search", data=json.dumps(body).encode(), headers={"Authorization": auth, "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode())["hits"]["hits"]


def load(args, auth):
    body = {
        "size": 3000,
        "_source": ["content_with_weight", "content_ltks", "content_sm_ltks", "docnm_kwd", "doc_id", "page_num_int"],
        "query": {"bool": {"must_not": [{"exists": {"field": "knowledge_graph_kwd"}}]}},
    }
    chunks = []
    for hit in _search(args.host, args.index, auth, body):
        source = dict(hit["_source"])
        source["_id"] = hit["_id"]
        chunks.append(source)
    return chunks


def fields_of(header: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for segment in header.strip("[]").split("|"):
        label, _, value = segment.partition(":")
        if label.strip():
            out[label.strip()] = value.strip()
    return out


def load_metadata(args, auth) -> dict:
    """The per-document metadata store, which the migration reads as a candidate source.

    Leaving it out was a real divergence in this checker: the executor passes
    ``fields=metadata.get(doc_id)``, whose ``cable_type`` becomes the header's 线缆类别, so a
    checker without it projected headers 66 chunks short of the executor's.
    """
    index = args.meta_index or args.index.replace("ragflow_", "ragflow_doc_meta_", 1)
    try:
        hits = _search(args.host, index, auth, {"size": 500, "_source": ["id", "meta_fields"]})
    except Exception as exc:  # noqa: BLE001 - reported, not hidden
        print(f"metadata index {index} unreadable ({exc}); the projection will lack its fields")
        return {}
    return {str(hit["_source"].get("id")): hit["_source"].get("meta_fields") or {} for hit in hits}


def metadata_for(document_rows, stored_fields):
    """Canonical metadata for a document, from its raw bodies in reading order."""
    name = str(document_rows[0].get("docnm_kwd") or "")
    doc_id = str(document_rows[0].get("doc_id") or "")
    raw_bodies = [rp.split_retrieval_header(str(row.get("content_with_weight") or ""))[1] for row in document_rows]
    head = "".join(raw_bodies)[:HEAD_CHARS]
    candidates = am.metadata_candidates(name, head, fields=(stored_fields or {}).get(doc_id) or {})
    category = rp.classify_category(name, head)
    return rp.resolve_metadata(candidates, document_id=doc_id, title=name, category=category)


def project_document(document_rows, metadata):
    """``[{chunk_id, stored_body, raw_body, section, header, retrieval_text}]`` in order."""
    raw_bodies = [rp.split_retrieval_header(str(row.get("content_with_weight") or ""))[1] for row in document_rows]
    sections = document_sections(raw_bodies)
    out = []
    for row, raw, section in zip(document_rows, raw_bodies, sections):
        stored = str(row.get("content_with_weight") or "")
        header, text = rp.project_chunk(stored, metadata, section)
        out.append({"chunk_id": row["_id"], "stored": stored, "raw": raw, "section": section, "header": header, "text": text, "tokens": rp.token_fields(text)})
    return out


def converge(document_rows, metadata, initial: str) -> list[dict]:
    """Run the migration over a WHOLE document three times, from a chosen initial state.

    ``initial`` is ``raw`` / ``legacy`` / ``current``: the state a real corpus can be in. The
    section walk is stateful (the heading in force is carried from chunk to chunk in reading
    order), which is why this runs over the sequence and not over one chunk.
    """
    simulated = []
    for row in document_rows:
        raw = rp.split_retrieval_header(str(row.get("content_with_weight") or ""))[1]
        if initial == "raw":
            body = raw
        elif initial == "legacy":
            body = f"[标准号: Q/GDW 00000.1-1999 | 文档: 旧格式] {raw}"
        else:
            body = f"[标准号: Q/GDW 00000.1-1999 | 文档: 旧格式 | 电压: 1kV] {raw}"
        simulated.append(dict(row, content_with_weight=body))

    states: list[list[dict]] = []
    current = simulated
    for _round in range(3):
        projected = project_document(current, metadata)
        current = [dict(row, content_with_weight=entry["text"], content_ltks=entry["tokens"].get("content_ltks", ""), content_sm_ltks=entry["tokens"].get("content_sm_ltks", "")) for row, entry in zip(current, projected)]
        states.append(current)
    return states


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--index", required=True)
    parser.add_argument("--host", default=os.environ.get("ES_HOST", "http://127.0.0.1:1200"))
    parser.add_argument("--user", default=os.environ.get("ES_USER", "elastic"))
    parser.add_argument("--password", default=os.environ.get("ES_PASSWORD", ""))
    parser.add_argument("--meta-index", default="", help="defaults to the doc-store index with doc_meta_ inserted")
    parser.add_argument("--report", default="phase_a_corrective_readiness.md")
    args = parser.parse_args()
    auth = _auth(args.user, args.password)
    stored_fields = load_metadata(args, auth)

    chunks = load(args, auth)
    family_rows = [chunk for chunk in chunks if str(chunk.get("docnm_kwd")) in FAMILY]
    outside = [chunk for chunk in chunks if str(chunk.get("docnm_kwd")) not in FAMILY]

    rows: list[dict] = []
    convergence: list[str] = []
    for name in FAMILY:
        document_rows = sorted([row for row in family_rows if str(row.get("docnm_kwd")) == name], key=lambda item: (item.get("page_num_int") or 0, item["_id"]))
        metadata = metadata_for(document_rows, stored_fields)
        projected = project_document(document_rows, metadata)
        for entry in projected:
            stored_header = rp.split_retrieval_header(entry["stored"])[0]
            old_section = fields_of(stored_header).get("章节", "")
            rows.append(
                {
                    "chunk_id": entry["chunk_id"],
                    "document": name,
                    "part": next((marker for marker in ("第1部分", "第2部分", "第3部分") if marker in name), "?"),
                    "old_section": old_section,
                    "new_section": entry["section"],
                    "old_header": stored_header,
                    "new_header": entry["header"],
                    "changed": entry["text"] != entry["stored"],
                    "raw_body_sha256": hashlib.sha256(entry["raw"].encode()).hexdigest()[:16],
                    "raw_head": " ".join(entry["raw"].split())[:EVIDENCE_CHARS],
                }
            )
        states = converge(document_rows, metadata, "legacy")
        convergence.append(f"* {name[:36]}... legacy: S1==S2: {states[0] == states[1]}; S2==S3: {states[1] == states[2]}")
        for kind in ("raw", "current"):
            other = converge(document_rows, metadata, kind)
            convergence.append(f"* {name[:36]}... {kind}: S1==S2: {other[0] == other[1]}; S2==S3: {other[1] == other[2]}")

    changed = [row for row in rows if row["changed"]]
    census = {"non_null_to_non_null": 0, "non_null_to_null": 0, "null_to_non_null": 0, "same_section": 0}
    reasons: list[str] = []
    for row in changed:
        if row["old_section"] and row["new_section"]:
            census["non_null_to_non_null"] += 1
            if row["old_section"] == row["new_section"]:
                census["same_section"] += 1
        elif row["old_section"] and not row["new_section"]:
            census["non_null_to_null"] += 1
        elif not row["old_section"] and row["new_section"]:
            census["null_to_non_null"] += 1
        row["reason"] = "section_removed" if (row["old_section"] and not row["new_section"]) else ("section_added" if (not row["old_section"] and row["new_section"]) else ("section_changed" if row["old_section"] != row["new_section"] else "other"))
        reasons.append(row["reason"])

    lines = [
        "# Corrective migration readiness (read-only; nothing written)",
        "",
        f"* family chunks: {len(family_rows)} of {len(chunks)} scanned; outside the family: {len(outside)}",
        f"* would change: **{len(changed)}**; unchanged: {len(rows) - len(changed)}",
        f"* section census over the changed set: {census}",
        f"* change reasons: section_added {reasons.count('section_added')}, section_removed {reasons.count('section_removed')}, section_changed {reasons.count('section_changed')}, other {reasons.count('other')}",
        f"* raw-body hash present on every row (proves old and new used the SAME body): {sum(1 for row in rows if row['raw_body_sha256'])}/{len(rows)}",
        "",
        "## Convergence (whole-document sequence, three initial states)",
        "",
        *convergence,
        "",
        "## The changed chunks",
        "",
        "| chunk id | document | Part | old section | new section | reason | raw sha |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in changed:
        lines.append(f"| {row['chunk_id']} | {row['document'][:28]} | {row['part']} | {row['old_section']!r} | {row['new_section']!r} | {row['reason']} | {row['raw_body_sha256']} |")
    lines += ["", "## Evidence: section_removed and section_changed", ""]
    for row in changed:
        if row["reason"] in {"section_removed", "section_changed"}:
            lines += [
                f"* `{row['chunk_id']}` ({row['part']}): {row['old_section']!r} -> {row['new_section']!r}",
                f"  - old header: `{row['old_header']}`",
                f"  - new header: `{row['new_header']}`",
                f"  - raw head  : {row['raw_head']}",
            ]
    verdict = "READY" if (census["same_section"] == 0 and len(changed) == 60) else "NOT READY"
    lines += ["", f"## Verdict: **{verdict}**", ""]
    if census["same_section"]:
        lines.append(f"* a change with an IDENTICAL section means the checker is comparing the wrong thing: {census['same_section']} such row(s)")
    if len(changed) != 60:
        lines.append(f"* the changed set is {len(changed)}, not the 60 the canary's dry run reported - the two must agree before an approval")
    pathlib.Path(args.report).write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:8]))
    print(f"wrote {args.report}")
    return 0 if verdict == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
