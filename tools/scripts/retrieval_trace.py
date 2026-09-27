"""Query A/C end-to-end retrieval trace (read-only, one stage per leg).

Run INSIDE the API container, where the embedding model and the production retrieval code
live:

    docker exec <container> python /ragflow/tools/scripts/retrieval_trace.py

It separates the legs the production path fuses, without changing any parameter:

* lexical-only  -> ``vector_similarity_weight = 0.0``
* dense-only    -> ``vector_similarity_weight = 1.0``
* hybrid        -> the assistant's configured weight (0.3 by default)

and reports, for each query, the rank of the passages a human would call the answer. It
writes nothing: no index write, no model call beyond the embedding of the query text.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys

sys.path.insert(0, "/ragflow")

TENANT = os.environ.get("TRACE_TENANT", "a9e28731ab7011f19b833887d563fb04")
KB = os.environ.get("TRACE_KB", "9463d93eb97511f1938f2592e9bc6fe4")
PAGE_SIZE = 50

QUERIES = (
    ("A", "根据 Q/GDW 73286.2-2026 查找单芯 220kV 海缆参数"),
    ("C", "220kV 三芯海底电缆结构参数"),
    ("A0", "Q/GDW 73286.2-2026"),
)
#: Passages a human would accept, by the text they must contain and the part they are in.
TARGETS = (("标称截面", "第2部分"), ("1×800", "第2部分"), ("3×400", "第3部分"), ("接头规格", "第2部分"))


def part_of(chunk) -> str:
    name = str(chunk.get("docnm_kwd") or "")
    for marker in ("第1部分", "第2部分", "第3部分"):
        if marker in name:
            return marker
    return "?"


async def embed(text: str):
    from api.db.joint_services.tenant_model_service import get_tenant_default_model_by_type
    from api.db.services.llm_service import LLMBundle
    from common.constants import LLMType

    config = get_tenant_default_model_by_type(TENANT, LLMType.EMBEDDING)
    if not config:
        raise SystemExit("no embedding model configured for the tenant")
    bundle = LLMBundle(TENANT, LLMType.EMBEDDING, config)
    return bundle


async def run_leg(question: str, weight: float, embd_mdl):
    from rag.nlp import search as rag_search

    dealer = rag_search.Dealer()
    result = await dealer.retrieval(
        question,
        embd_mdl,
        [TENANT],
        [KB],
        page=1,
        page_size=PAGE_SIZE,
        similarity_threshold=0.0,
        vector_similarity_weight=weight,
        top=1024,
    )
    return result


def describe(result):
    rows = []
    for rank, chunk in enumerate(result.get("chunks") or [], 1):
        body = str(chunk.get("content_with_weight") or "")
        rows.append(
            {
                "rank": rank,
                "id": str(chunk.get("chunk_id") or chunk.get("id") or "")[:16],
                "part": part_of(chunk),
                "score": round(float(chunk.get("similarity") or 0.0), 4),
                "section": (body.split("| 章节: ", 1)[1].split("]")[0].strip() if "| 章节: " in body else ""),
                "document": str(chunk.get("docnm_kwd") or "")[:30],
            }
        )
    return rows


def target_ranks(rows):
    found = {}
    for phrase, part in TARGETS:
        hit = next((row for row in rows if part in row["part"] and phrase in row["document"]), None)
        found[f"{phrase}@{part}"] = hit["rank"] if hit else None
    return found


async def main() -> int:
    embd_mdl = await embed("x")
    report: dict = {"tenant": TENANT, "kb": KB, "page_size": PAGE_SIZE, "queries": {}}
    for tag, question in QUERIES:
        entry = {"question": question, "legs": {}}
        for label, weight in (("lexical_only", 0.0), ("dense_only", 1.0), ("hybrid", 0.3)):
            try:
                result = await run_leg(question, weight, embd_mdl)
                rows = describe(result)
                entry["legs"][label] = {"weight": weight, "returned": len(rows), "top10": rows[:10], "top50_ids": [row["id"] for row in rows]}
            except Exception as exc:  # noqa: BLE001 - a trace must record the failure, not hide it
                entry["legs"][label] = {"weight": weight, "error": f"{type(exc).__name__}: {exc}"}
        report["queries"][tag] = entry
    print(json.dumps(report, ensure_ascii=False))
    for tag, entry in report["queries"].items():
        print(f"=== {tag}: {entry['question']}")
        for label, leg in entry["legs"].items():
            if "error" in leg:
                print(f"  {label}: ERROR {leg['error']}")
                continue
            top = ", ".join(f"{row['part']}#{row['id']}({row['score']})" for row in leg["top10"][:5])
            print(f"  {label}: {leg['returned']} returned; top5: {top}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
