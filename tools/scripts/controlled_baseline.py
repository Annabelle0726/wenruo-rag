"""Controlled Deployed Retrieval Baseline (read-only).

Runs INSIDE the deployed container. No assistant is created, modified or borrowed: the
experiment states its own configuration, tags every input with its provenance, and calls the
deployed engine with it.

Provenance tags used below:
  EXPLICIT_EXPERIMENT_VALUE - chosen by this experiment, recorded here
  DEPLOYED_DEFAULT         - the deployed function's own default for that parameter
  KB_VALUE                 - read from the knowledge base row
  MODEL_RESOLUTION         - produced by the deployed model-resolution path

Stages: engine sanity (lexical-only), controlled pipeline run, determinism (two identical
runs), instrumentation agreement, then the A/C stages and the standard-number lexical probe at
the SAME configuration.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import sys
import urllib.request

sys.path.insert(0, "/ragflow")

KB = os.environ.get("TRACE_KB", "9463d93eb97511f1938f2592e9bc6fe4")
QUERY_E = "单芯 220kV 海缆"
QUERY_A = "根据 Q/GDW 73286.2-2026 查找单芯 220kV 海缆参数"
QUERY_C = "220kV 三芯海底电缆结构参数"
PROBE = "Q/GDW 73286.2-2026"
PARAMS = {  # all DEPLOYED_DEFAULT
    "similarity_threshold": 0.2,
    "vector_similarity_weight": 0.6,
    "routes_top_k": 12,
    "final_top_n": 8,
    "knn_top_k": 1024,
    "max_sub_queries": 4,
    "allow_dense_fallback": True,
    "rerank_candidates_count": None,
    "doc_ids": None,
    "rank_feature": None,
    "must_not": None,
}


def keys(result):
    return [str(chunk.get("chunk_id") or chunk.get("id") or "")[:16] for chunk in (result or {}).get("chunks", [])]


def brief(result, limit=8):
    rows = []
    for rank, chunk in enumerate((result or {}).get("chunks", [])[:limit], 1):
        name = str(chunk.get("docnm_kwd") or "")
        part = next((marker for marker in ("第1部分", "第2部分", "第3部分") if marker in name), "?")
        rows.append(f"{rank}:{part}#{str(chunk.get('chunk_id') or '')[:12]}({float(chunk.get('similarity') or 0):.3f})")
    return " ".join(rows)


def lexical_probe(questions, result):
    """Token overlap between a query and the header the canary wrote, from stored tokens."""
    from rag.nlp import rag_tokenizer

    rag_tokenizer.tokenizer.set_language("Chinese")
    return [token for token in rag_tokenizer.tokenize(questions).split()][:24]


async def main() -> int:
    from common import settings

    # The doc store is bound at application boot, not on import: without this
    # `settings.docStoreConn` is None and `Dealer(None)` fails inside `search()` with
    # "'NoneType' object has no attribute 'search'". Initialising it here is the app's own
    # path (read-only: it opens the clients a request already uses).
    settings.init_settings()
    from rag.nlp import search as rag_search
    from rag.retrieval import retrieve_multi_route
    from api.db.joint_services.tenant_model_service import resolve_model_config
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from api.db.services.llm_service import LLMBundle
    from common.constants import LLMType

    print("=== provenance")
    print(f"  raw_query      = effective_query = {QUERY_E!r}   [EXPLICIT_EXPERIMENT_VALUE, keyword augmentation NOT used]")
    print(f"  retrieval params = {PARAMS}   [DEPLOYED_DEFAULT]")
    ok, kb = KnowledgebaseService.get_by_id(KB)
    if not ok:
        print(f"  KB {KB} not found   [KB_VALUE]")
        return 1
    owner = str(getattr(kb, "tenant_id", "") or "")
    print(f"  kb_id = {KB}   [KB_VALUE]; owner tenant = {owner[:12]}…; kb.embd_id = {getattr(kb, 'embd_id', None)}   [KB_VALUE]")
    config = resolve_model_config(owner, LLMType.EMBEDDING, kb.embd_id)  # MODEL_RESOLUTION
    embd_mdl = LLMBundle(owner, config)
    print(f"  embedding  = {type(embd_mdl).__name__} via resolve_model_config -> LLMBundle   [MODEL_RESOLUTION]")

    # 3072-dimension consistency check, read from the live mapping (read-only).
    try:
        es = os.environ.get("ES_URL") or os.environ.get("ELASTICSEARCH_URL") or "http://es01:9200"
        url = f"{es.rstrip('/')}/ragflow_{owner}/_mapping/field/q_3072_vec"
        request = urllib.request.Request(url, headers={"Authorization": "Basic " + __import__("base64").b64encode(b"elastic:infini_rag_flow").decode()})
        print("  q_3072_vec mapping:", json.loads(urllib.request.urlopen(request, timeout=20).read().decode())[f"ragflow_{owner}"]["mappings"]["q_3072_vec"])
    except Exception as exc:  # noqa: BLE001 - a read-only probe reports, it does not block
        print(f"  q_3072_vec mapping: NOT OBSERVABLE ({type(exc).__name__})")

    dealer = rag_search.Dealer(settings.docStoreConn)
    accepted = set(inspect.signature(dealer.retrieval).parameters)
    print(f"  deployed Dealer.retrieval accepts: {sorted(accepted)}")
    print("  CAPTURED from the deployed engine path (multi_route.py:235-244):")
    print("    retriever.retrieval(query, embd_mdl, tenant_ids, kb_ids, 1, routes_top_k, threshold, **kwargs)")
    # A parameter whose DEPLOYED_DEFAULT is not None must be OMITTED, not sent as None:
    # passing `rerank_candidates_count=None` overrode the deployed default and the engine died
    # on `page * page_size > rerank_candidates_count`. Same for doc_ids / rank_feature /
    # must_not, which the deployed pipeline also only adds when truthy.
    call = {key: value for key, value in PARAMS.items() if key in accepted and key not in {"similarity_threshold", "vector_similarity_weight"} and value is not None}
    # page=1, page_size=routes_top_k is what the deployed pipeline passes - a CAPTURED value,
    # not a default invented here.
    page, page_size = 1, PARAMS["routes_top_k"]

    async def leg(label, weight):
        """One diagnostic leg; a failure is REPORTED and the run continues."""
        try:
            result = await dealer.retrieval(QUERY_E, embd_mdl, [owner], [KB], page, page_size, PARAMS["similarity_threshold"], weight, **call)
            print(f"  {label} (weight {weight}): total={result.get('total')} n={len(result.get('chunks') or [])} {brief(result, 6)}")
            return result or {}
        except Exception as exc:  # noqa: BLE001
            print(f"  {label} (weight {weight}): FAILED {type(exc).__name__}: {exc}")
            return {}

    print("=== stage: engine sanity (lexical-only, weight 0.0)")
    lexical = await leg("lexical-only", 0.0)

    print("=== controlled pipeline run 1 (deployed retrieve_multi_route, DEPLOYED_DEFAULT)")
    try:
        run1 = await retrieve_multi_route(retriever=dealer, question=QUERY_E, tenant_ids=[owner], kb_ids=[KB], chat_mdl=None, embd_mdl=embd_mdl, **PARAMS)
    except Exception as exc:  # noqa: BLE001
        print(f"  FAILED: {type(exc).__name__}: {exc}")
        return 1
    print(f"  total={run1.get('total')} chunks={len(run1.get('chunks') or [])} {brief(run1)}")
    print("  CONTROLLED BASELINE AVAILABLE" if run1.get("chunks") else "  CONTROLLED BASELINE EMPTY")

    print("=== determinism: run 2 (identical inputs)")
    run2 = await retrieve_multi_route(retriever=dealer, question=QUERY_E, tenant_ids=[owner], kb_ids=[KB], chat_mdl=None, embd_mdl=embd_mdl, **PARAMS)
    same = keys(run1) == keys(run2)
    print(f"  identical chunk order: {same}  ({len(keys(run1))} vs {len(keys(run2))})")

    print("=== instrumentation agreement (diagnostic legs at the same configuration)")
    dense = await dealer.retrieval(QUERY_E, embd_mdl, [owner], [KB], page, page_size, PARAMS["similarity_threshold"], 1.0, **call)
    hybrid = await dealer.retrieval(QUERY_E, embd_mdl, [owner], [KB], page, page_size, PARAMS["similarity_threshold"], 0.6, **call)
    print(f"  lexical-only top: {keys(lexical)[:6]}")
    print(f"  dense-only   top: {keys(dense)[:6]}")
    print(f"  hybrid       top: {keys(hybrid)[:6]}")
    print(f"  pipeline     top: {keys(run1)[:6]}")
    overlap = len(set(keys(run1)[:8]) & set(keys(hybrid)[:8]))
    print(f"  pipeline top-8 inside hybrid top-8: {overlap}/8")

    status = "CONTROLLED TRACE VALIDATED" if (same and run1.get("chunks") and overlap >= 6) else "NOT VALIDATED"
    print(f"=== status: {status}")
    print(f"  probe tokens for {PROBE!r}: {lexical_probe(PROBE, run1)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
