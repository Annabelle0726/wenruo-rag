"""Step 1: bind the authoritative three-core chunk to the CURRENT index. Read-only.

Fetches the pinned chunk by id from the live production index (a direct document GET, not a query),
verifies its document identity, extracts the Table 1 conductor nominal-section values from its OWN
content, hashes the full content, and compares against any captured corpus snapshot.
"""
import hashlib
import json
import pathlib
import re
import sys

sys.path.insert(0, "/ragflow")

from common import settings  # noqa: E402

settings.init_settings()

INDEX = "ragflow_a9e28731ab7011f19b833887d563fb04"
TARGET = "d1d75672f2dbc333"
CONTROL = "b5aaf72bcd33d44a"
SNAPSHOTS = ("/tmp/corpus_p12.json", "/tmp/corpus_codex.json")

es = settings.docStoreConn.es
out = {}


def fetch(cid):
    try:
        return es.get(index=INDEX, id=cid)["_source"]
    except Exception as exc:  # noqa: BLE001
        return {"__error__": f"{type(exc).__name__}: {exc}"}


target = fetch(TARGET)
out["target_exists"] = "__error__" not in target

if not out["target_exists"]:
    out["TARGET_ERROR"] = target["__error__"]
else:
    content = str(target.get("content_with_weight") or "")
    out["doc_id"] = target.get("doc_id")
    out["docnm_kwd"] = str(target.get("docnm_kwd") or "")
    out["doc_type_kwd"] = target.get("doc_type_kwd")
    out["content_chars"] = len(content)
    out["content_sha256"] = hashlib.sha256(content.encode("utf-8")).hexdigest()
    out["kb_id"] = target.get("kb_id")
    out["available_int"] = target.get("available_int")

    # Does the document identity say Q/GDW 73286.3 (Part 3, three-core)?
    name = out["docnm_kwd"]
    out["is_part3_document"] = ("73286.3" in name) or ("第3部分" in name) or ("第 3 部分" in name)
    out["is_part2_document"] = ("73286.2" in name) or ("第2部分" in name)
    out["part3_markers_in_content"] = [m for m in ("73286.3", "第3部分", "三芯", "第 3 部分") if m in content]

    # Table 1 caption + conductor nominal-section enumeration, taken from the chunk's own text.
    body = re.sub(r"<[^>]+>", " ", content)
    body = " ".join(body.split())
    out["t1_caption"] = bool(re.search(r"表\s*1", body))
    out["body_chars"] = len(body)
    out["body_head"] = body[:600]

    # Nominal-section values: the "1xNNN" / "NNN mm2" family near 标称截面/导体.
    sections = re.findall(r"1\s*[×x]\s*(\d{3,4})", body)
    sections += re.findall(r"(\d{3,4})\s*mm2", body)
    ordered = []
    for s in sections:
        if s not in ordered:
            ordered.append(s)
    nums = sorted({int(s) for s in ordered})
    out["section_values_found"] = nums
    out["section_count"] = len(nums)
    out["section_min_max"] = [min(nums), max(nums)] if nums else None

control = fetch(CONTROL)
out["control_exists"] = "__error__" not in control
if out["control_exists"]:
    cc = str(control.get("content_with_weight") or "")
    out["control_docnm_kwd"] = str(control.get("docnm_kwd") or "")
    out["control_content_sha256"] = hashlib.sha256(cc.encode("utf-8")).hexdigest()
    out["control_content_chars"] = len(cc)

# Corpus snapshot comparison
out["snapshot_comparison"] = {}
for path in SNAPSHOTS:
    p = pathlib.Path(path)
    if not p.exists():
        out["snapshot_comparison"][path] = "absent"
        continue
    try:
        snap = json.loads(p.read_text(encoding="utf-8-sig"))
        hits = snap.get("hits") or []
        match = next((h for h in hits if h.get("_id") == TARGET), None)
        if match is None:
            out["snapshot_comparison"][path] = f"target not present (hits={len(hits)})"
        else:
            sc = str((match.get("_source") or {}).get("content_with_weight") or "")
            out["snapshot_comparison"][path] = {
                "found": True,
                "content_chars": len(sc),
                "content_sha256": hashlib.sha256(sc.encode("utf-8")).hexdigest(),
                "same_as_current": hashlib.sha256(sc.encode("utf-8")).hexdigest() == out.get("content_sha256"),
            }
    except Exception as exc:  # noqa: BLE001
        out["snapshot_comparison"][path] = f"{type(exc).__name__}: {exc}"

print(json.dumps(out, ensure_ascii=False, indent=1))
pathlib.Path("/tmp/step1_binding.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
