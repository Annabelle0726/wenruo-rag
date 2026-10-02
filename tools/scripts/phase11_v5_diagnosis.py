"""Why does V5 still show 0/3 structure evidence? (READ-ONLY diagnosis.)

V5 ("标准对终端和接头的结构以及设计使用年限是怎样规定的？") now triggers with four supplemental
routes including "终端 结构" and "接头 结构", and its window route count rises 6 -> 8, yet the count
of passages carrying the structure-drawing clause stays 0. This probe asks whether the routes reach
structure CONTENT at all, and whether the specific clause is reachable by any route wording.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys

sys.path.insert(0, "/ragflow")
sys.path.insert(0, "/tmp/p1")

KB_ID = "9463d93eb97511f1938f2592e9bc6fe4"
DIALOG_ID = "5c8c249eb8e411f180e20bf412cbc55e"

_TAG_RE = re.compile(r"<[^>]{0,300}?>")

V5 = "标准对终端和接头的结构以及设计使用年限是怎样规定的？"

#: Route wordings to compare: what the rule emits, and narrower/alternative structure wordings.
ROUTES = (
    "标准对终端和接头的结构以及设计使用年限是怎样规定的？",
    "终端 结构",
    "接头 结构",
    "终端 结构图纸",
    "接头 结构图纸",
    "终端设计结构图纸",
    "结构图纸",
    "终端 设计使用年限",
    "接头 设计使用年限",
)


def flat(text: str) -> str:
    return re.sub(r"\s+", "", _TAG_RE.sub("|", str(text or "")).lower().replace("×", "x"))


async def main() -> int:
    from common import settings

    settings.init_settings()
    from rag.retrieval.multi_route import resolve_routes_top_k
    from rag.retrieval.rerank import resolve_final_top_n
    from api.db.db_models import Dialog
    from api.db.joint_services.tenant_model_service import resolve_model_config
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from api.db.services.llm_service import LLMBundle
    from common.constants import LLMType

    ok, kb = KnowledgebaseService.get_by_id(KB_ID)
    tenant = str(kb.tenant_id)
    dialog = Dialog.get_or_none(Dialog.id == DIALOG_ID)
    embd_mdl = LLMBundle(tenant, resolve_model_config(tenant, LLMType.EMBEDDING, kb.embd_id))
    retriever = settings.retriever
    page = resolve_routes_top_k(None)

    print("=== how many chunks carry 结构 vs the 结构图纸 clause? ===")
    print("   (corpus-wide, from the earlier measurement: 结构 116 chunks, 结构图纸 4 chunks)")

    print("\n=== what does each route retrieve? (window=%d, threshold=%.2f) ===" % (page, float(dialog.similarity_threshold)))
    for q in ROUTES:
        try:
            r = await retriever.retrieval(
                q, embd_mdl, [tenant], [KB_ID], 1, page,
                float(dialog.similarity_threshold), float(dialog.vector_similarity_weight),
                aggs=True, highlight=False,
                rerank_candidates_count=int(getattr(dialog, "rerank_candidates_count", 30) or 30),
                allow_dense_fallback=True,
            )
            chunks = list(r.get("chunks") or [])
        except Exception as exc:  # noqa: BLE001
            print(f"  {q!r}: ERROR {type(exc).__name__}: {exc}")
            continue
        n_struct = sum(1 for c in chunks if "结构" in flat(c.get("content_with_weight") or ""))
        n_draw = sum(1 for c in chunks if "结构图纸" in flat(c.get("content_with_weight") or ""))
        n_life = sum(1 for c in chunks if "设计使用年限" in flat(c.get("content_with_weight") or "") or "不少于30" in flat(c.get("content_with_weight") or ""))
        print(f"  {q!r:50s} n={len(chunks):2d}  结构={n_struct:2d}  结构图纸={n_draw}  life={n_life:2d}")

    print("\n=== is the 结构图纸 clause reachable at all, and from which documents? ===")
    r = await retriever.retrieval(
        "结构图纸", embd_mdl, [tenant], [KB_ID], 1, page,
        float(dialog.similarity_threshold), float(dialog.vector_similarity_weight),
        aggs=True, highlight=False,
        rerank_candidates_count=int(getattr(dialog, "rerank_candidates_count", 30) or 30),
        allow_dense_fallback=True,
    )
    for c in r.get("chunks") or []:
        body = c.get("content_with_weight") or ""
        if "结构图纸" in flat(body):
            desig = re.search(r"标准号[:：]\s*([A-Z0-9./\- ]+?)\s*[|\]]", body)
            print(f"   id={str(c.get('chunk_id'))[:16]} desig={(desig.group(1).strip() if desig else '?')} doc={str(c.get('docnm_kwd'))[:34]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

