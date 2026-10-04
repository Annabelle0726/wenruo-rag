"""Where does the synonym's benefit stop? (READ-ONLY stage probe for terminology Phase 0.)

The synonym expands the QUERY only. It therefore reaches the two retrieval legs but NOT the
reranker, which scores the raw question string against the raw chunk text. This probe measures the
life/structure composition at each stage so the limit of a synonym-only change is explicit:

    route candidates (Dealer.retrieval, per route)
      -> merged pool (deployed merge_route_hits)
      -> after deployed rerank_chunks (reranker + select_context cut)

Run it twice, once with the alias channel empty and once loaded, and diff.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys

sys.path.insert(0, "/ragflow")

KB_ID = "9463d93eb97511f1938f2592e9bc6fe4"
DIALOG_ID = "5c8c249eb8e411f180e20bf412cbc55e"
LABEL = os.environ.get("SYN_LABEL", "run")

_TAG_RE = re.compile(r"<[^>]{0,300}?>")

ORIGINAL = "标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求"
ROUTES = (
    ("original_composite", ORIGINAL),
    ("life_route_as_decomposed", "标准对电缆附件（终端与接头）的设计使用寿命有何要求"),
    ("life_route_narrow_terminal", "标准对电缆附件终端的设计使用寿命有何要求"),
    ("structure_route", "标准对电缆附件（终端与接头）的结构有何要求"),
)


def flat(text: str) -> str:
    return re.sub(r"\s+", "", _TAG_RE.sub("|", str(text or "")).lower().replace("×", "x"))


def halves(chunk: dict) -> tuple[bool, bool]:
    t = flat(chunk.get("content_with_weight") or "")
    return ("设计使用年限" in t or "不少于30" in t), ("结构图纸" in t)


def tally(chunks) -> dict:
    chunks = list(chunks)
    life = [c for c in chunks if halves(c)[0]]
    struct = [c for c in chunks if halves(c)[1]]
    return {
        "n": len(chunks),
        "design_life": len(life),
        "structure": len(struct),
        "life_ids": [str(c.get("chunk_id") or "")[:16] for c in life],
        "ids": [str(c.get("chunk_id") or "")[:16] for c in chunks],
    }


async def main() -> int:
    from common import settings

    settings.init_settings()
    from rag.nlp import rag_tokenizer
    from rag.retrieval.multi_route import RouteResult, merge_route_hits, resolve_routes_top_k
    from rag.retrieval.rerank import rerank_chunks, resolve_final_top_n
    from api.db.db_models import Dialog
    from api.db.joint_services.tenant_model_service import resolve_model_config
    from api.db.services.dialog_service import resolve_rerank_mdl
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from api.db.services.llm_service import LLMBundle
    from common.constants import LLMType

    rag_tokenizer.tokenizer.set_language("Chinese")
    ok, kb = KnowledgebaseService.get_by_id(KB_ID)
    tenant = str(kb.tenant_id)
    dialog = Dialog.get_or_none(Dialog.id == DIALOG_ID)
    embd_mdl = LLMBundle(tenant, resolve_model_config(tenant, LLMType.EMBEDDING, kb.embd_id))
    rerank_mdl = resolve_rerank_mdl(tenant, dialog.rerank_id or "", dialog.tenant_rerank_id)
    retriever = settings.retriever
    threshold = float(dialog.similarity_threshold)
    weight = float(dialog.vector_similarity_weight)
    page_size = resolve_routes_top_k(None)
    top_n = resolve_final_top_n(dialog.top_n)
    candidates = int(getattr(dialog, "rerank_candidates_count", 30) or 30)

    report: dict = {
        "label": LABEL,
        "synonym_dict_size": len(retriever.qryr.syn.dictionary or {}),
        "lookup_life_term": retriever.qryr.syn.lookup("使用寿命"),
        "lookup_seacable": retriever.qryr.syn.lookup("海缆"),
        "routes": {},
    }

    route_chunks = {}
    for name, question in ROUTES:
        chunks = []
        try:
            r = await retriever.retrieval(
                question, embd_mdl, [tenant], [KB_ID], 1, page_size, threshold, weight,
                aggs=True, highlight=False, rerank_candidates_count=candidates,
                allow_dense_fallback=True,
            )
            chunks = list(r.get("chunks") or [])
        except Exception as exc:  # noqa: BLE001 - a probe reports, it does not hide
            report["routes"][name] = {"error": f"{type(exc).__name__}: {exc}"}
            route_chunks[name] = chunks
            continue
        route_chunks[name] = chunks
        report["routes"][name] = tally(chunks)

    hits = [RouteResult(query=q, chunks=route_chunks[n]) for n, q in ROUTES]
    merged = merge_route_hits(hits)
    pool = list(merged.get("chunks") or [])
    kept = await rerank_chunks(rerank_mdl, pool, ORIGINAL, top_n)
    report["merged_pool"] = tally(pool)
    report["after_rerank_cut"] = tally(kept)

    with open(f"/tmp/terminology_stages_{LABEL}.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)

    print(f"=== stages ({LABEL}) synonym_dict_size={report['synonym_dict_size']} "
          f"lookup(使用寿命)={report['lookup_life_term']} ===")
    for name, v in report["routes"].items():
        if "error" in v:
            print(f"  route {name:28s} ERROR {v['error']}")
        else:
            print(f"  route {name:28s} n={v['n']:2d} life={v['design_life']} struct={v['structure']} life_ids={v['life_ids']}")
    print(f"  merged pool                  n={report['merged_pool']['n']:2d} "
          f"life={report['merged_pool']['design_life']} struct={report['merged_pool']['structure']}")
    print(f"  after rerank+cut             n={report['after_rerank_cut']['n']:2d} "
          f"life={report['after_rerank_cut']['design_life']} struct={report['after_rerank_cut']['structure']} "
          f"life_ids={report['after_rerank_cut']['life_ids']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
