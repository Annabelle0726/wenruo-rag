"""Read-only: run the EXACT agentic hybrid_search with the formalized query on the deployed image.

Captures the final chunk allocation, the raw ES ranks the routes returned, the merged/ordered pool (so
per-document ranks can be computed), and the selection, for the query the agentic layer actually sent.
Nothing is modified and no product code is changed; the wrappers only observe.
"""
import asyncio
import collections
import json
import pathlib
import sys

sys.path.insert(0, "/ragflow")

from common import settings

settings.init_settings()

from api.db.db_models import Dialog, Knowledgebase  # noqa: E402
from api.db.joint_services.tenant_model_service import get_tenant_default_model_by_type  # noqa: E402
from api.db.services.llm_service import LLMBundle  # noqa: E402
from common.constants import LLMType  # noqa: E402
from rag.advanced_rag.harness.tools.search import hybrid_search  # noqa: E402
from rag.retrieval import rerank as rr  # noqa: E402
from rag.utils.es_conn import ESConnection  # noqa: E402

FORMALIZED = ("根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围")
ORIGINAL = FORMALIZED + "及规格数量各是多少？"
DIALOG = "29a6da60ba1f11f1be9555eabe501d5b"
KB = "9463d93eb97511f1938f2592e9bc6fe4"
TARGET, CONTROL = "d1d75672f2dbc333", "b5aaf72bcd33d44a"
PART2, PART3 = "28668474ba1b11f1be9555eabe501d5b", "f18db09cba1211f18bee33eac9b39c66"

dialog = Dialog.get_or_none(Dialog.id == DIALOG)
kb = Knowledgebase.get_by_id(KB)


class Tools:
    """Minimal RAGTools surface: only the retrieval settings hybrid_search reads."""

    def __init__(self):
        self.kb_ids = [KB]
        self.sql_kbs = []
        self.search_cache = None
        self.tenant_ids = [kb.tenant_id]
        self.chat_mdl = LLMBundle(dialog.tenant_id, get_tenant_default_model_by_type(dialog.tenant_id, LLMType.CHAT))
        from api.db.joint_services.tenant_model_service import resolve_model_config
        self.embed_mdl = LLMBundle(dialog.tenant_id,
                                  resolve_model_config(dialog.tenant_id, LLMType.EMBEDDING, kb.embd_id))
        self.top_n = dialog.top_n
        self.top_k = dialog.top_k
        self.rerank_candidates_count = getattr(dialog, "rerank_candidates_count", 64)
        self.vector_similarity_weight = dialog.vector_similarity_weight
        self.similarity_threshold = dialog.similarity_threshold

    def scoped_doc_ids(self, doc_scope=None):
        """Mirror the metadata-resolved scope proven for this question: both standards."""
        return list(doc_scope) if doc_scope else [PART2, PART3]


WINDOWS = []
ORDERED = []
SELECTED = []


def instrument():
    store = settings.docStoreConn
    original_once = store._es_search_once

    def once(*args, **kwargs):
        body = args[1] if len(args) > 1 else None
        res = original_once(*args, **kwargs)
        ids = []
        try:
            ids = [h["_id"] for h in res["hits"]["hits"]]
        except Exception:  # noqa: BLE001
            pass
        WINDOWS.append({"size": (body or {}).get("size") if isinstance(body, dict) else None,
                        "n": len(ids), "target": (ids.index(TARGET) + 1) if TARGET in ids else None})
        return res

    store._es_search_once = once

    original_adjust = rr.apply_rank_adjustments

    def adjust(chunks, policy):
        out = original_adjust(chunks, policy)
        ORDERED.append({"ordered": [str(c.get("chunk_id"))[:16] for c in out],
                        "policy_compared": sorted(policy.compared_documents),
                        "max_document_share": policy.max_document_share,
                        "min_prose": policy.min_prose, "max_table_share": policy.max_table_share})
        return out

    rr.apply_rank_adjustments = adjust
    for mod in (sys.modules.get("rag.retrieval"),):
        if mod is not None and getattr(mod, "apply_rank_adjustments", None) is original_adjust:
            mod.apply_rank_adjustments = adjust

    original_select = rr.select_context

    def select(ordered, top_n, policy):
        chosen = original_select(ordered, top_n, policy)
        SELECTED.append([str(c.get("chunk_id"))[:16] for c in chosen])
        return chosen

    rr.select_context = select


async def main():
    instrument()
    tools = Tools()
    result = await hybrid_search(tools, FORMALIZED)
    chunks = result.get("chunks") or []
    by_doc = collections.Counter(str(c.get("docnm_kwd") or "")[-24:] for c in chunks)
    ids = [str(c.get("chunk_id"))[:16] for c in chunks]

    print("FORMALIZED_QUERY_TEXT:", FORMALIZED)
    print()
    print(f"final chunks: {len(chunks)}")
    print("allocation by document:")
    for doc, n in by_doc.items():
        print(f"   {n} x ...{doc}")
    print()
    print("final chunk ids in order:", ids)
    print()
    print("TARGET d1d75672f2dbc333 in final:", TARGET in ids, " at pos:", (ids.index(TARGET) + 1) if TARGET in ids else None)
    print("CONTROL b5aaf72bcd33d44a in final:", CONTROL in ids, " at pos:", (ids.index(CONTROL) + 1) if CONTROL in ids else None)

    print()
    print("=== raw ES windows (target rank) ===")
    for n, w in enumerate(WINDOWS, 1):
        print(f"   win{n:2d}: size={w['size']} returned={w['n']} target_rank={w['target']}")

    if ORDERED:
        o = ORDERED[0]
        ordered = o["ordered"]
        print()
        print(f"=== merged/ordered pool: n={len(ordered)} compared={[d[:8] for d in o['policy_compared']]} "
              f"max_document_share={o['max_document_share']} min_prose={o['min_prose']} "
              f"max_table_share={o['max_table_share']}")
        print("   target position in ordered pool:", (ordered.index(TARGET) + 1) if TARGET in ordered else None)
        print("   control position in ordered pool:", (ordered.index(CONTROL) + 1) if CONTROL in ordered else None)
        from rag.utils.es_conn import ESConnection as _E
        es = settings.docStoreConn.es
        docs = {}
        for cid in ordered:
            try:
                src = es.get(index="ragflow_" + kb.tenant_id, id=cid)["_source"]
            except Exception:  # noqa: BLE001
                continue
            docs[cid] = str(src.get("doc_id") or "")
        p3 = [c for c in ordered if docs.get(c) == PART3]
        p2 = [c for c in ordered if docs.get(c) == PART2]
        print(f"   Part 3 chunks in pool: {len(p3)}  Part 2: {len(p2)}")
        print("   Part 3's own ordering (position in pool):",
              [(n, c) for n, c in enumerate(p3[:12], 1)])
        print("   target's index WITHIN Part 3's ordering:",
              (p3.index(TARGET) + 1) if TARGET in p3 else "not in Part 3 list")

    print()
    print("=== selections ===")
    for n, s in enumerate(SELECTED, 1):
        print(f"   selection {n}: {len(s)} chunks -> {s}")


asyncio.run(main())
