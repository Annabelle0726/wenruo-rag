"""Non-persistent replay of the ORIGINAL Agentic retrieval flow, bound to the persisted request.

Request binding (read from the datastore, not assumed):
  conversation c737275ebae611f19c26b16ea36f75b8
  message      18bb69bf-0e11-4bf2-9d1a-2b1966c98159   (role=user)
  assistant    ccddcfdeba3a11f1a4910547a12ee1d1       ("海底test2")
The user question and every retrieval setting come from those rows. Nothing is shortened, substituted,
persisted or reconfigured; the wrappers only observe.

Boundaries captured:
  1 each route's raw Dealer result
  2 merged candidate pool before selection
  3 ordered/ranked pool before select_context
  4 output of select_context
  5 normalized hybrid_search return
"""
import asyncio
import json
import pathlib
import sys

sys.path.insert(0, "/ragflow")

from common import settings

settings.init_settings()

from api.db.db_models import Conversation, Dialog  # noqa: E402
from api.db.joint_services.tenant_model_service import get_tenant_default_model_by_type, resolve_model_config  # noqa: E402
from api.db.services.llm_service import LLMBundle  # noqa: E402
from common.constants import LLMType  # noqa: E402
from rag.advanced_rag.harness.tools import search as search_tool  # noqa: E402
from rag.retrieval import multi_route as mr  # noqa: E402
from rag.retrieval import rerank as rr  # noqa: E402

CONV = "c737275ebae611f19c26b16ea36f75b8"
MSG = "18bb69bf-0e11-4bf2-9d1a-2b1966c98159"
ASSISTANT = "ccddcfdeba3a11f1a4910547a12ee1d1"
TARGET, CONTROL = "d1d75672f2dbc333", "b5aaf72bcd33d44a"

conv = Conversation.get_or_none(Conversation.id == CONV)
messages = conv.message if isinstance(conv.message, list) else json.loads(conv.message or "[]")
QUESTION = next(m["content"] for m in messages if str(m.get("id")) == MSG)
dialog = Dialog.get_or_none(Dialog.id == ASSISTANT)

B1, B2, B3, B4, B5 = {}, {}, {}, {}, {}
ROUTE_TEXTS, POLICY, RUNTIME = [], {}, {}
RESOLVED_SCOPE = []


def ids_of(obj):
    out, chunks = [], None
    if isinstance(obj, dict):
        chunks = obj.get("chunks") or obj.get("hits")
    elif hasattr(obj, "chunks"):
        chunks = getattr(obj, "chunks")
    elif hasattr(obj, "ids"):
        return [str(i)[:16] for i in (obj.ids or [])]
    if isinstance(chunks, dict):
        chunks = chunks.get("hits")
    if isinstance(chunks, list):
        for c in chunks:
            if isinstance(c, dict):
                cid = c.get("chunk_id") or c.get("id") or c.get("_id")
                if cid:
                    out.append(str(cid)[:16])
    return out


def report(bucket, ids):
    ids = [i for i in ids if i]
    bucket.setdefault("calls", [])
    bucket["calls"].append({"n": len(ids),
                            "target": (ids.index(TARGET) + 1) if TARGET in ids else None,
                            "control": (ids.index(CONTROL) + 1) if CONTROL in ids else None,
                            "ids": ids if len(ids) <= 40 else ids[:40]})


def instrument():
    original_route = mr._retrieve_route

    async def route(*a, **k):
        res = await original_route(*a, **k)
        report(B1, ids_of(res))
        return res

    mr._retrieve_route = route

    original_merge = mr.merge_route_hits

    def merge(hits, existing=None, *a, **k):
        out = original_merge(hits, existing, *a, **k)
        report(B2, ids_of(out))
        return out

    mr.merge_route_hits = merge

    original_adjust = rr.apply_rank_adjustments

    def adjust(chunks, policy):
        POLICY.update({"compared_documents": sorted(policy.compared_documents),
                       "max_document_share": policy.max_document_share,
                       "max_table_share": policy.max_table_share,
                       "min_prose": policy.min_prose,
                       "table_penalty": policy.table_penalty,
                       "question_values": sorted(policy.question_values)})
        out = original_adjust(chunks, policy)
        report(B3, [str(c.get("chunk_id"))[:16] for c in out])
        return out

    rr.apply_rank_adjustments = adjust
    mod = sys.modules.get("rag.retrieval")
    if mod is not None and getattr(mod, "apply_rank_adjustments", None) is original_adjust:
        mod.apply_rank_adjustments = adjust

    original_select = rr.select_context

    def select(ordered, top_n, policy):
        chosen = original_select(ordered, top_n, policy)
        report(B4, [str(c.get("chunk_id"))[:16] for c in chosen])
        return chosen

    rr.select_context = select

    # route texts as actually sent to ES
    store = settings.docStoreConn
    original_once = store._es_search_once

    def once(*a, **k):
        body = a[1] if len(a) > 1 else None
        if isinstance(body, dict):
            for m in ((body.get("query") or {}).get("bool", {}).get("must") or []):
                qs = (m or {}).get("query_string") or {}
                if qs.get("query"):
                    ROUTE_TEXTS.append(qs["query"][:120])
        return original_once(*a, **k)

    store._es_search_once = once


class Tools:
    def __init__(self):
        self.kb_ids = list(dialog.kb_ids or [])
        self.sql_kbs = []
        self.search_cache = None
        self.tenant_ids = [dialog.tenant_id]
        self.chat_mdl = LLMBundle(dialog.tenant_id, get_tenant_default_model_by_type(dialog.tenant_id, LLMType.CHAT))
        # The real RAGTools carries an embedding model; without it `hybrid_search` forces
        # vector_similarity_weight=0 and the replay degrades to LEXICAL-ONLY retrieval, which changes the
        # ranking under test. Build the KB's own embedding model so the vector leg runs.
        from api.db.services.knowledgebase_service import KnowledgebaseService
        ok, kb = KnowledgebaseService.get_by_id(self.kb_ids[0])
        self.embed_mdl = LLMBundle(dialog.tenant_id,
                                   resolve_model_config(dialog.tenant_id, LLMType.EMBEDDING, kb.embd_id))
        self.top_n = dialog.top_n
        self.top_k = dialog.top_k
        self.rerank_candidates_count = getattr(dialog, "rerank_candidates_count", 30)
        self.vector_similarity_weight = dialog.vector_similarity_weight
        self.similarity_threshold = dialog.similarity_threshold

    def scoped_doc_ids(self, doc_scope=None):
        # The assistant carries meta_data_filter {"method":"auto"}; the real flow resolves the doc scope
        # from the question BEFORE retrieval. Apply that same resolved scope here.
        if doc_scope:
            return list(doc_scope)
        return list(RESOLVED_SCOPE) if RESOLVED_SCOPE else None


async def main():
    instrument()
    tools = Tools()
    RUNTIME["assistant"] = ASSISTANT
    RUNTIME["published_question"] = QUESTION
    RUNTIME["rerank_id"] = getattr(dialog, "rerank_id", None) or None
    RUNTIME["rerank_model"] = "absent" if not getattr(dialog, "rerank_id", None) else "present"
    RUNTIME["rerank_candidates_count"] = tools.rerank_candidates_count
    RUNTIME["final_top_n"] = tools.top_n
    RUNTIME["similarity_threshold"] = tools.similarity_threshold
    RUNTIME["vector_similarity_weight"] = tools.vector_similarity_weight
    RUNTIME["top_k"] = tools.top_k
    RUNTIME["kb_ids"] = tools.kb_ids
    RUNTIME["meta_data_filter"] = getattr(dialog, "meta_data_filter", None)

    from api.db.services.doc_metadata_service import DocMetadataService
    from rag.prompts.generator import gen_meta_filter
    from common.metadata_utils import apply_meta_data_filter
    metas = DocMetadataService.get_flatted_meta_by_kbs(tools.kb_ids)
    f = await gen_meta_filter(tools.chat_mdl, metas, QUESTION)
    RUNTIME["metadata_filter_conditions"] = f
    scope = await apply_meta_data_filter(getattr(dialog, "meta_data_filter", None), None, QUESTION,
                                         tools.chat_mdl, None, kb_ids=tools.kb_ids,
                                         metas_loader=lambda: metas)
    RESOLVED_SCOPE[:] = list(scope or [])
    RUNTIME["metadata_doc_scope"] = list(RESOLVED_SCOPE) or None

    # capture the query text the search tool actually hands to the retriever
    original_rmr = search_tool.retrieve_multi_route

    async def rmr(*a, **k):
        RUNTIME["formalized_query_text"] = k.get("question")
        RUNTIME["rmr_kwargs"] = {kk: (str(kk_v)[:80] if not isinstance(kk_v, (int, float, bool, type(None))) else kk_v)
                                 for kk, kk_v in k.items() if kk in
                                 ("similarity_threshold", "vector_similarity_weight", "final_top_n",
                                  "knn_top_k", "rerank_candidates_count")}
        return await original_rmr(*a, **k)

    search_tool.retrieve_multi_route = rmr

    result = await search_tool.hybrid_search(tools, QUESTION)
    report(B5, [str(c.get("chunk_id"))[:16] for c in (result.get("chunks") or [])])

    out = {"runtime": RUNTIME, "policy": POLICY,
           "boundaries": {"B1_route_results": B1, "B2_merged_pool": B2, "B3_ordered_pool": B3,
                          "B4_select_context": B4, "B5_normalized_return": B5},
           "route_texts": ROUTE_TEXTS,
           "final_allocation": [str(c.get("chunk_id"))[:16] for c in (result.get("chunks") or [])]}
    pathlib.Path("/tmp/agentic_bound_replay.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print("published question :", QUESTION)
    print("assistant          :", dialog.name, ASSISTANT)
    print("formalized query   :", RUNTIME.get("formalized_query_text"))
    print()
    for name, b in out["boundaries"].items():
        calls = b.get("calls", [])
        tgt = [c["target"] for c in calls if c["target"]]
        ctl = [c["control"] for c in calls if c["control"]]
        print(f"{name}: calls={len(calls)}  TARGET_present={bool(tgt)} ranks={tgt[:8]}  CONTROL ranks={ctl[:8]}")
        for n, c in enumerate(calls, 1):
            print(f"     call{n:2d} n={c['n']:3d} target={c['target']} control={c['control']}")
    print()
    print("policy:", json.dumps(POLICY, ensure_ascii=False))
    print("route texts:", json.dumps(sorted(set(ROUTE_TEXTS)), ensure_ascii=False)[:900])
    print("final allocation:", out["final_allocation"])


asyncio.run(main())
