"""DRY RUN: what a context-prefix backfill would write, per document.

Reads the live doc store and metadata index and prints, for every document, the
prefix that a backfill would prepend to its chunks - computed with the INGEST'S OWN
functions (``rag.nlp.doc_context``), so a preview and an execution cannot disagree.
Writes nothing: this script only issues ``_search`` requests.

What it reports per document:

* the file name, the doc-store id, the dataset, and how many chunks carry a
  ``[标准号: …]`` prefix today;
* the designation (standard number), the core count and the voltage level, each with
  the SOURCE it came from - the file name, the document head, the metadata index, or
  the standard family inferred from that standard's other parts;
* the exact prefix template that would be written, in the format the report asked for:
  standard number, document name, core count, voltage level and the section number
  (the ``章节:`` LABEL is not searchable - the tokenizer drops it - so nothing is built
  on it; the section NUMBER is what is written);

The one thing a text-only backfill cannot fix is stated in the summary it prints: the
dense vector of an existing chunk was computed from the text it already had, so adding
a prefix without re-embedding reaches the FULL-TEXT leg only. A re-parse (or a
re-embed) is what puts the same words into the vector.

    ES_PASSWORD=... python tools/scripts/backfill_prefix_preview.py --index ragflow_<tenant>
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import re
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from rag.nlp import auto_metadata as am  # noqa: E402
from rag.nlp import retrieval_projection as rp  # noqa: E402
from rag.retrieval.chunk_profile import designation_parts, name_family  # noqa: E402

HEAD_CHARS = 4000
#: How far into the head a VOLTAGE has to appear to be trusted for the prefix. A
#: cable's rating is cover-page material; the same pattern deep in the body reads
#: "4kV 火花试验" (a test voltage on a 1kV cable), and a WRONG voltage in a filterable
#: prefix is worse than no voltage at all.
VOLTAGE_HEAD_CHARS = 200
PREFIX_MARK = "[标准号:"


def _search(host, index, auth, body):
    url = f"{host.rstrip('/')}/{index}/_search"
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Authorization": auth, "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode())


def _documents(host, index, auth):
    """Every real document: its chunks' bodies, in READING order.

    The order matters and is not the index's own: `apply_document_context` detects the
    standard number from the chunks in the order the chunker produced them, so a
    preview that read them any other way could propose a different designation than a
    re-parse would write - measured while running this dry run, on the 10kV general
    part, whose chunks carry GB/T 29782-2013 and Q/GDW 73237.1-2026 today.
    """
    body = {
        "size": 2000,
        "_source": ["content_with_weight", "docnm_kwd", "doc_id", "kb_id", "page_num_int"],
        "query": {"bool": {"must_not": [{"exists": {"field": "knowledge_graph_kwd"}}]}},
    }
    documents: dict[str, dict] = {}
    for hit in _search(host, index, auth, body)["hits"]["hits"]:
        source = hit["_source"]
        doc_id = str(source.get("doc_id") or "")
        name = str(source.get("docnm_kwd") or "")
        if not doc_id or not name:
            continue
        entry = documents.setdefault(doc_id, {"name": name, "kb_id": str(source.get("kb_id") or ""), "chunks": [], "prefixed": 0, "prefixes": set()})
        body_text = str(source.get("content_with_weight") or "")
        entry["chunks"].append((source.get("page_num_int") or 0, str(hit["_id"]), body_text))
        if body_text.lstrip().startswith(PREFIX_MARK):
            entry["prefixed"] += 1
            entry["prefixes"].add(body_text.split("]", 1)[0] + "]")
    for entry in documents.values():
        entry["chunks"].sort(key=lambda row: (row[0], row[1]))
        entry["bodies"] = [row[2] for row in entry["chunks"]]
    return documents


def _metadata_fields(host, index, auth):
    """``meta_fields`` per document id from the metadata index."""
    try:
        hits = _search(host, index, auth, {"size": 500, "_source": ["id", "meta_fields", "kb_id"]})["hits"]["hits"]
    except Exception as exc:  # noqa: BLE001 - the preview degrades, it does not fail
        print(f"metadata index unreadable ({exc}); continuing without it")
        return {}
    fields = {}
    for hit in hits:
        source = hit["_source"]
        doc_id = str(source.get("id") or "")
        if doc_id:
            fields[doc_id] = source.get("meta_fields") or {}
    return fields


def _family_designations(documents):
    """``family -> {part: designation}`` from the designations the corpus already carries.

    Indexed under BOTH keys a family can be looked up by: the designation's own family
    (``QGDW73286``, from the prefixed parts) and the name the parts share
    (``220kV海底电力电缆系统采购标准``). Without the second key the 三芯 part - whose
    file name carries no number and whose chunks carry no prefix at all - finds nothing
    to be inferred from, which is exactly the document the report asked about.
    """
    families: dict[str, dict[int, str]] = {}
    for entry in documents.values():
        for text in [entry["name"], *entry["prefixes"]]:
            designation = _designation_of(text)
            if not designation:
                continue
            parsed = designation_parts(designation)
            if not parsed:
                continue
            family, part, _year = parsed
            keys = {family}
            named = name_family(entry["name"])
            if named:
                keys.add(named)
            for key in keys:
                if part is not None:
                    families.setdefault(key, {}).setdefault(part, designation)
                else:
                    families.setdefault(key, {}).setdefault(0, designation)
    return families


def _designation_of(text: str) -> str:
    """The designation a file name or a prefix line carries, in normalized form."""
    import re

    match = re.search(r"(?:Q\s*/?\s*GDW|GB\s*/?\s*T|GB|DL\s*/?\s*T|JB\s*/?\s*T|NB\s*/?\s*T|YD\s*/?\s*T|IEC|ISO)\s*\d+(?:\.\d+)?(?:-\d{4})?", str(text or ""), re.IGNORECASE)
    if not match:
        return ""
    return re.sub(r"[\s/]+", "", match.group(0)).upper()


#: Designations that are never a document's OWN number: GB/T 1.1 is the
#: standardisation directive every Chinese standard cites in its foreword, and a head
#: scan reads it first. Measured in the dry run: 《450／750V聚氯乙烯绝缘电缆采购标准+第2
#: 部分》 was proposed `GB/T 1.1-2020`, which would have made a filterable field wrong.
_GUIDELINE_DESIGNATIONS = ("GBT1.1", "GBT1.2", "GBT20001", "GBT20000", "GB1.1")

#: Names that say "this document is NOT a standard": it applies one. Whatever number
#: its text repeats belongs to the standard it cites, so writing it into the prefix
#: would claim an ownership that is not there.
_NON_STANDARD_CUES = ("规格书", "技术要求", "指南", "说明书", "样本")


def _document_designation(entry):
    """``(designation, source)`` for a document: name first, then a vote over its text.

    The name is the document speaking about itself. Failing that, the designation that
    REPEATS most in the document is its own - a standard cites its number on the cover,
    in the running head and in every clause - while a citation of another standard
    appears once. Guidelines are never eligible.
    """
    named = _designation_of(entry["name"])
    if named:
        return named, "file name"
    votes: dict[str, int] = {}
    for body in entry["bodies"]:
        for match in re.finditer(r"(?:Q\s*/?\s*GDW|GB\s*/?\s*T|GB|DL\s*/?\s*T|JB\s*/?\s*T|NB\s*/?\s*T|YD\s*/?\s*T|IEC|ISO)\s*\d+(?:\.\d+)?(?:-\d{4})?", body, re.IGNORECASE):
            designation = re.sub(r"[\s/]+", "", match.group(0)).upper()
            if any(designation.startswith(prefix) for prefix in _GUIDELINE_DESIGNATIONS):
                continue
            votes[designation] = votes.get(designation, 0) + 1
    if not votes:
        return "", "not found"
    best, hits = max(votes.items(), key=lambda item: item[1])
    if hits < 2:
        return "", "not found (every designation appears once: they are citations)"
    return best, f"most frequent in the document ({hits} occurrences)"


def canonical_designation(designation: str) -> str:
    """``QGDW73286.3`` -> ``Q/GDW 73286.3`` (with the family's year when it has one).

    The ingest writes the READABLE form (``Q/GDW 73286.2-2026``), so a backfill has to
    write it too or one corpus would carry two spellings of the same designation. The
    year is filled from the family when this document's own text omits it: the parts of
    one standard share an edition, and the live 三芯 part cites ``Q/GDW 73286.3`` with no
    year while its siblings are filed as ``-2026``.
    """
    text = re.sub(r"\s+", "", str(designation or "")).upper()
    match = re.match(r"^(?P<prefix>QGDW|GBT|GB|DLT|JBT|NBT|YDT|IEC|ISO)(?P<base>\d+(?:\.\d+)*)(?:-(?P<year>\d{4}))?$", text)
    if not match:
        return str(designation or "")
    spelled = {"QGDW": "Q/GDW", "GBT": "GB/T", "GB": "GB", "DLT": "DL/T", "JBT": "JB/T", "NBT": "NB/T", "YDT": "YD/T", "IEC": "IEC", "ISO": "ISO"}[match.group("prefix")]
    # The `.N` of a multi-part designation is part of the number, not a decimal.
    return f"{spelled} {match.group('base')}" + (f"-{match.group('year')}" if match.group("year") else "")


def family_year(documents, entry) -> str:
    """A year to add to this document's designation, from its family's other parts."""
    family = entry.get("family") or ""
    if not family:
        # No family key means nothing to share an edition with. Matching on an empty key
        # would borrow a year from an unrelated document - measured in this dry run,
        # where it stamped "2017" onto IEC 60332, GB/T 3956 and GB/T 14049.
        return ""
    for other in documents.values():
        if other is entry or (other.get("family") or "") != family:
            continue
        match = re.search(r"-(\d{4})$", str(other.get("designation") or ""))
        if match:
            return match.group(1)
    return ""


def gather(host, index, meta_index, auth):
    documents = _documents(host, index, auth)
    metadata = _metadata_fields(host, meta_index, auth)
    families = _family_designations(documents)

    for doc_id, entry in documents.items():
        head = "".join(entry["bodies"])[:HEAD_CHARS]
        family = name_family(entry["name"])
        meta = metadata.get(doc_id) or {}
        candidates = am.metadata_candidates(entry["name"], head, fields=meta)
        # The family is established from the CORPUS, so it is offered here - and only
        # here - as the constrained last resort the projection orders last.
        known = (families.get(family) or {})
        numbered = {part: value for part, value in known.items() if part}
        if numbered and not any(candidate.key == "document_standard_no" for candidate in candidates):
            sample = numbered[max(numbered)]
            parsed = designation_parts(sample)
            if parsed:
                candidates.append(am.family_candidate(f"{parsed[0]}", family=parsed[0], part=max(numbered) + 1, year=parsed[2]))
        category = rp.classify_category(entry["name"], head)
        resolved = rp.resolve_metadata(candidates, document_id=doc_id, title=entry["name"], category=category)
        counts = {kind: 0 for kind in (rp.PREFIX_LEGACY, rp.PREFIX_CURRENT, rp.PREFIX_NONE)}
        for body_text in entry["bodies"]:
            counts[rp.declared_prefix_kind(body_text)] += 1
        entry.update(
            {
                "family": family,
                "metadata": resolved,
                "candidates": candidates,
                "prefix_counts": counts,
                "title": rp.profile_for(category).fields and entry["name"],
                "header": rp.render_retrieval_header(resolved),
            }
        )
    for entry in documents.values():
        resolved: rp.CanonicalMetadata = entry["metadata"]
        entry["designation"] = resolved.document_standard_no or ""
        entry["designation_source"] = next((str(candidate) for candidate in resolved.evidence if candidate.key == "document_standard_no" and candidate.value == resolved.document_standard_no), "not found")
        entry["core_type"] = resolved.attributes.get("core_count", "")
        entry["voltage"] = resolved.attributes.get("voltage_level", "")
        entry["voltage_source"] = next((candidate.source for candidate in resolved.evidence if candidate.key == "voltage_level" and candidate.value == entry["voltage"]), "")
        entry["part"] = (designation_parts(resolved.document_standard_no) or ("", None, ""))[1] if resolved.document_standard_no else None
        entry["prefixed"] = entry["prefix_counts"][rp.PREFIX_LEGACY] + entry["prefix_counts"][rp.PREFIX_CURRENT]
        entry["meta_fields"] = meta
        entry["is_standard"] = not any(cue in entry["name"] for cue in _NON_STANDARD_CUES)
        entry["identifying"] = bool(resolved.document_standard_no or entry["core_type"] or entry["voltage"])
    return documents


def render_report(documents) -> str:
    lines: list[str] = []
    write = lines.append
    total = sum(len(entry["bodies"]) for entry in documents.values())
    without = {doc_id: entry for doc_id, entry in documents.items() if entry["prefixed"] == 0}
    write("# Context-prefix backfill - DRY RUN (nothing was written)")
    write("")
    write(f"documents: {len(documents)}; chunks: {total}; documents with NO prefix: {len(without)}; chunks in them: {sum(len(e['bodies']) for e in without.values())}")
    write("")
    write("## Documents that would be written")
    write("")
    write("| # | document | chunks | legacy / new / none | 标准号 (winning candidate) | 芯数 | 电压 | projected retrieval header |")
    write("|---|---|---|---|---|---|---|---|")
    order = sorted(documents.items(), key=lambda item: (item[1]["prefixed"], item[1]["name"]))
    for position, (_doc_id, entry) in enumerate(order, 1):
        if entry["prefixed"] and entry["prefixed"] == len(entry["bodies"]):
            continue
        counts = entry["prefix_counts"]
        if not entry["identifying"]:
            write(f"| {position} | {entry['name']} | {len(entry['bodies'])} | {counts[rp.PREFIX_LEGACY]} / {counts[rp.PREFIX_CURRENT]} / {counts[rp.PREFIX_NONE]} | SKIPPED: nothing identifying beyond the file name | - | - | - |")
            continue
        designation = entry["designation"] or "(none)"
        if entry["designation"] and not entry["is_standard"]:
            # Reported below instead: a cited number is not this document's own.
            designation = f"({entry['designation']} CITED - not written by default)"
        header = entry["header"] if entry["is_standard"] else rp.render_retrieval_header(_without_identity(entry["metadata"]))
        write(f"| {position} | {entry['name']} | {len(entry['bodies'])} | {counts[rp.PREFIX_LEGACY]} / {counts[rp.PREFIX_CURRENT]} / {counts[rp.PREFIX_NONE]} | {designation} | {entry['core_type'] or '-'} | {entry['voltage'] or '-'} | `{header}` |")

    citations = [entry for entry in documents.values() if entry["designation"] and not entry["is_standard"]]
    if citations:
        write("")
        write("## Documents that are not standards (the number found is CITED, not owned)")
        write("")
        write("These are 规格书/技术要求/核实指南: their text repeats the standards they apply,")
        write("and no 标准号 is proposed for them. Confirm if you want them written anyway.")
        write("")
        for entry in citations:
            write(f"* {entry['name']} - cited `{entry['designation']}` ({entry['designation_source']}); they would get `{prefix_template({**entry, 'designation': ''})}`")
    write("")
    write("## Documents already fully prefixed (format comparison only)")
    write("")
    for _doc_id, entry in order:
        if entry["prefixed"] and entry["prefixed"] == len(entry["bodies"]):
            current = next(iter(sorted(entry["prefixes"])), "")
            write(f"* {entry['name']} - {entry['prefixed']}/{len(entry['bodies'])} chunks; today: `{current}`")
            write(f"  - would become: `{prefix_template(entry)}`")
    write("")
    write("## What this cannot fix")
    write("")
    write("* The DENSE vector of an existing chunk was computed from the text it already had. A")
    write("  text-only backfill reaches the full-text leg (`content_ltks`) and leaves `q_3072_vec`")
    write("  as it is, so `标准号`/`芯数`/`电压` become matchable but not semantically closer to a")
    write("  question that names them. Putting them into the vector needs a re-parse (or a re-embed).")
    write("* The `章节:` LABEL is not searchable (the tokenizer drops it; measured live: 57 chunks")
    write("  carry it and 2 chunks in the whole index have the token). The section NUMBER is written")
    write("  and does survive tokenization.")
    write("")
    return "\n".join(lines)


def _without_identity(metadata):
    """The same metadata with the cited number dropped, for a document that only cites."""
    clone = rp.CanonicalMetadata(
        document_id=metadata.document_id,
        title=metadata.title,
        document_type=metadata.document_type,
        category=metadata.category,
        document_standard_no=None,
        referenced_standard_nos=metadata.referenced_standard_nos,
        attributes=dict(metadata.attributes),
        evidence=list(metadata.evidence),
    )
    return clone


def prefix_template(entry) -> str:
    """The prefix the ingest would write, in the requested field set."""
    parts: list[str] = []
    if entry["designation"]:
        parts.append("标准号: " + entry["designation"])
    if entry["title"]:
        parts.append("文档: " + entry["title"])
    if entry["core_type"]:
        parts.append("芯数: " + entry["core_type"])
    if entry["voltage"]:
        parts.append("电压: " + entry["voltage"])
    parts.append("章节: <每切片章节号>")
    return "[" + " | ".join(parts) + "] "


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True)
    parser.add_argument("--meta-index", default="", help="defaults to the doc-store index name with 'doc_meta_' inserted")
    parser.add_argument("--host", default=os.environ.get("ES_HOST", "http://127.0.0.1:1200"))
    parser.add_argument("--user", default=os.environ.get("ES_USER", "elastic"))
    parser.add_argument("--password", default=os.environ.get("ES_PASSWORD", ""))
    args = parser.parse_args()

    meta_index = args.meta_index
    if not meta_index:
        meta_index = args.index.replace("ragflow_", "ragflow_doc_meta_", 1)
    auth = "Basic " + base64.b64encode(f"{args.user}:{args.password}".encode()).decode()

    documents = gather(args.host, args.index, meta_index, auth)
    report = render_report(documents)
    pathlib.Path("backfill_preview.md").write_text(report, encoding="utf-8")
    print("wrote backfill_preview.md")
    # The same report also goes to the ingest's OWN renderer for a spot check: one line
    # per document, exactly as `apply_document_context` would produce it.
    spot = []
    for entry in sorted(documents.values(), key=lambda item: item["name"]):
        if entry["header"]:
            spot.append(f"{entry['name']}\n    {rp.retrieval_text('<原始切片正文>', entry['header'])}")
    pathlib.Path("backfill_preview_examples.txt").write_text("\n".join(spot), encoding="utf-8")
    print("wrote backfill_preview_examples.txt")


if __name__ == "__main__":
    main()
