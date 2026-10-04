"""QA-004 terminology and granularity A/B (READ-ONLY).

E2 of the previous probe showed the decomposer's own design-life route

    标准对电缆附件（终端与接头）的设计使用寿命有何要求

returning 10 passages, NONE of which carries the design-life clause, while the corpus clause reads
``终端设计使用年限``. This probe isolates the two candidate causes:

T - TERMINOLOGY: the question says 设计使用寿命, the corpus says 设计使用年限
G - GRANULARITY: a composite route (终端 AND 接头 in one query) vs a narrowed one

Every query runs through the deployed ``Dealer.retrieval`` with the assistant's own parameters.
Nothing is written or changed.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys

sys.path.insert(0, "/ragflow")

KB_ID = "9463d93eb97511f1938f2592e9bc6fe4"
DIALOG_ID = "5c8c249eb8e411f180e20bf412cbc55e"

_TAG_RE = re.compile(r"<[^>]{0,300}?>")

#: label -> (query, what it varies)
PROBES: tuple[tuple[str, str, str], ...] = (
    ("decomposer_route_life", "标准对电缆附件（终端与接头）的设计使用寿命有何要求", "the route the deployed decomposer actually produced (term = 使用寿命, composite)"),
    ("term_swapped_annual", "标准对电缆附件（终端与接头）的设计使用年限有何要求", "T: same shape, corpus term 使用年限"),
    ("narrow_terminal_life", "标准对电缆附件终端的设计使用寿命有何要求", "G: narrowed to 终端, question term"),
    ("narrow_terminal_annual", "标准对电缆附件终端的设计使用年限有何要求", "T+G: narrowed to 终端, corpus term"),
    ("narrow_connector_life", "标准对电缆附件接头的设计使用寿命有何要求", "G: narrowed to 接头, question term"),
    ("narrow_connector_annual", "标准对电缆附件接头的设计使用年限有何要求", "T+G: narrowed to 接头, corpus term"),
    ("exact_clause", "终端设计使用年限", "the clause's own words"),
    ("term_only_life", "设计使用寿命", "T: question term alone"),
    ("term_only_annual", "设计使用年限", "T: corpus term alone"),
    ("original_composite", "标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求", "the benchmark question"),
)


def flat(text: str) -> str:
    return re.sub(r"\s+", "", _TAG_RE.sub("|", str(text or "")).lower())


def halves(chunk: dict) -> tuple[bool, bool]:
    text = flat(chunk.get("content_with_weight") or "")
    return ("设计使用年限" in text or "不少于30" in text), ("结构图纸" in text)


async def main() -> int:
    from common import settings

    settings.init_settings()
    from rag.nlp import rag_tokenizer
    from rag.retrieval.multi_route import resolve_routes_top_k
    from rag.retrieval.rerank import resolve_final_top_n
    from api.db.db_models import Dialog
    from api.db.joint_services.tenant_model_service import resolve_model_config
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from api.db.services.llm_service import LLMBundle
    from common.constants import LLMType

    rag_tokenizer.tokenizer.set_language("Chinese")
    ok, kb = KnowledgebaseService.get_by_id(KB_ID)
    tenant = str(kb.tenant_id)
    dialog = Dialog.get_or_none(Dialog.id == DIALOG_ID)
    embd_mdl = LLMBundle(tenant, resolve_model_config(tenant, LLMType.EMBEDDING, kb.embd_id))
    retriever = settings.retriever
    threshold = float(dialog.similarity_threshold)
    weight = float(dialog.vector_similarity_weight)
    candidates = int(getattr(dialog, "rerank_candidates_count", 30) or 30)
    page_size = resolve_routes_top_k(None)

    report: dict = {"window_per_route": page_size, "final_top_n": resolve_final_top_n(dialog.top_n), "probes": {}}

    # lexical view of the two competing terms, from the deployed tokenizer
    lex = {}
    for term in ("设计使用寿命", "设计使用年限", "终端设计使用年限"):
        _expr, keywords = retriever.qryr.question(term)
        lex[term] = list(keywords)
    report["lexical_terms"] = lex

    for label, query, varies in PROBES:
        try:
            result = await retriever.retrieval(
                query,
                embd_mdl,
                [tenant],
                [KB_ID],
                1,
                page_size,
                threshold,
                weight,
                aggs=True,
                highlight=False,
                rerank_candidates_count=candidates,
                allow_dense_fallback=True,
            )
            chunks = list(result.get("chunks") or [])
        except Exception as exc:  # noqa: BLE001
            report["probes"][label] = {"query": query, "varies": varies, "error": f"{type(exc).__name__}: {exc}"}
            continue
        life = [c for c in chunks if halves(c)[0]]
        struct = [c for c in chunks if halves(c)[1]]
        report["probes"][label] = {
            "query": query,
            "varies": varies,
            "returned": len(chunks),
            "design_life": len(life),
            "structure": len(struct),
            "design_life_ids": [str(c.get("chunk_id") or "")[:16] for c in life],
            "top8": [
                {
                    "id": str(c.get("chunk_id") or "")[:16],
                    "life": halves(c)[0],
                    "struct": halves(c)[1],
                    "similarity": round(float(c.get("similarity") or 0.0), 4),
                    "term": None if c.get("term_similarity") is None else round(float(c["term_similarity"]), 4),
                    "dense": None if c.get("vector_similarity") is None else round(float(c["vector_similarity"]), 4),
                    "doc": str(c.get("docnm_kwd") or "")[:26],
                }
                for c in chunks[:8]
            ],
        }

    with open("/tmp/qa004_terms.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)

    print("=== lexical terms produced by the deployed tokenizer ===")
    for term, kws in report["lexical_terms"].items():
        print(f"  {term}: {kws}")
    print("=== per-probe outcome (window = %d, threshold = %.2f) ===" % (page_size, threshold))
    for label, v in report["probes"].items():
        if "error" in v:
            print(f"  {label:24s} ERROR {v['error']}")
            continue
        print(f"  {label:24s} n={v['returned']:2d} design_life={v['design_life']} structure={v['structure']}  [{v['varies']}]")
        if v["design_life"]:
            print(f"      design-life chunks: {v['design_life_ids']}")
    print("=== term-similarity detail for the two life probes ===")
    for label in ("decomposer_route_life", "term_swapped_annual", "narrow_terminal_annual"):
        v = report["probes"].get(label)
        if not v or "error" in v:
            continue
        print(f"  {label}: {v['query']}")
        for row in v["top8"]:
            print(f"     {row['id']} life={int(row['life'])} struct={int(row['struct'])} sim={row['similarity']} term={row['term']} dense={row['dense']} {row['doc']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
