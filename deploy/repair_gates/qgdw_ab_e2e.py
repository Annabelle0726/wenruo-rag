"""REAL end-to-end QGDW QA capture, identical for arm A (production) and arm B (candidate image).

Drives the production assistant's own `dialog_service.async_chat` with the frozen question: real
retrieval, real ordering/selection, real prompt, real answer model. The ONLY thing that differs between
the two arms is which image supplies `/ragflow/rag/retrieval/rerank.py`.

Read-write honesty: `async_chat` persists no conversation or message rows (its only `.insert(` is a list
insert and its only `.update(` is a langfuse tracing object), so no production row is created or changed.
Retrieval reads the live ES index; the answer model is called once per arm.

The driver never inspects a chunk id to decide anything - it dumps each final passage's OWN body text so
the evidence question ("does this passage hold the Table 1 nominal-section data?") is answered from
content, not from identity.
"""
import asyncio
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, "/ragflow")

from common import settings  # noqa: E402

settings.init_settings()

from api.db.db_models import Dialog  # noqa: E402
from api.db.services import dialog_service as ds  # noqa: E402
from rag.retrieval.chunk_profile import _body_text, is_table_chunk  # noqa: E402

DIALOG_ID = "29a6da60ba1f11f1be9555eabe501d5b"
QUESTION = "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/ab_arm.json")
LABEL = sys.argv[2] if len(sys.argv) > 2 else "arm"

#: Content probes. The answer the question asks for is a RANGE and a COUNT of conductor nominal
#: sections in Table 1, one per standard part. We look for the section data itself.
PROBES = ("导体", "标称截面", "800", "1200", "1600", "630", "1000")


def excerpt(body, limit=900):
    text = " ".join(body.split())
    return text[:limit]


def main():
    dialog = Dialog.get_or_none(Dialog.id == DIALOG_ID)
    assert dialog is not None, f"dialog {DIALOG_ID} not found"

    async def go():
        items = []
        async for item in ds.async_chat(dialog=dialog,
                                        messages=[{"role": "user", "content": QUESTION}],
                                        stream=False, quote=True):
            items.append(item)
        return items

    items = asyncio.run(go())
    final = items[-1] if items else {}
    reference = final.get("reference") or {}
    chunks = reference.get("chunks") or []
    health = reference.get("retrieval_health") if isinstance(reference, dict) else None
    answer = final.get("answer") or ""

    passages = []
    for chunk in chunks:
        body = _body_text(chunk)
        text = " ".join(body.split())
        passages.append({
            "chunk_id": chunk.get("chunk_id") or chunk.get("id"),
            "document": str(chunk.get("docnm_kwd") or chunk.get("document_name") or "")[:90],
            "is_table": bool(is_table_chunk(chunk)),
            "body_chars": len(body),
            "body_head": excerpt(text, 900),
            "probe_hits": [p for p in PROBES if p in text],
            "has_section_table": ("导体" in text and "标称截面" in text),
        })

    report = {
        "label": LABEL,
        "question": QUESTION,
        "question_sha256": hashlib.sha256(QUESTION.encode("utf-8")).hexdigest(),
        "rerank_sha256": hashlib.sha256(
            pathlib.Path("/ragflow/rag/retrieval/rerank.py").read_bytes()).hexdigest(),
        "answer": answer,
        "answer_length": len(answer),
        "retrieval_health": health,
        "reference_keys": sorted(reference) if isinstance(reference, dict) else None,
        "context_size": len(chunks),
        "context_tables": sum(1 for p in passages if p["is_table"]),
        "context_prose": sum(1 for p in passages if not p["is_table"]),
        "context_chunk_ids_in_order": [p["chunk_id"] for p in passages],
        "control_present": any(p["chunk_id"] == "b5aaf72bcd33d44a" for p in passages),
        "target_present": any(p["chunk_id"] == "d1d75672f2dbc333" for p in passages),
        "passages_with_section_table": [p["chunk_id"] for p in passages if p["has_section_table"]],
        "doc_aggs": reference.get("doc_aggs") if isinstance(reference, dict) else None,
        "passages": passages,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{LABEL}: answer_len={report['answer_length']} ctx={report['context_size']} "
          f"tables={report['context_tables']} prose={report['context_prose']} "
          f"control={report['control_present']} target={report['target_present']} "
          f"section_passages={report['passages_with_section_table']}")


main()
