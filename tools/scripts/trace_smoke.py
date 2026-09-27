"""Query E smoke test: does calling the DEPLOYED production entry reproduce production?

Plan A: call the deployed `retrieve_multi_route` and let the deployed code resolve its own
models (`resolve_model_config` -> `LLMBundle`), so nothing here re-implements model
resolution. The signature is INSPECTED at runtime rather than assumed, because the container
runs a revision this working tree does not have.

The comparison is against the deployed `Dealer.retrieval` called with the production weight:
if the two disagree, my diagnostic construction is wrong and the trace must not proceed.

Read-only: no index write, no MySQL write. The only model call is the embedding of the query
text, which is what a normal chat request does.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import sys

sys.path.insert(0, "/ragflow")

TENANT = os.environ.get("TRACE_TENANT", "a9e28731ab7011f19b833887d563fb04")
KB = os.environ.get("TRACE_KB", "9463d93eb97511f1938f2592e9bc6fe4")
QUESTION = "单芯 220kV 海缆"


def ids(result):
    return [str(chunk.get("chunk_id") or chunk.get("id") or "")[:20] for chunk in (result or {}).get("chunks", [])]


async def main() -> int:
    print("=== deployed signature of retrieve_multi_route")
    from rag.retrieval import pipeline as deployed_pipeline

    print("   ", inspect.signature(deployed_pipeline.retrieve_multi_route))

    print("=== deployed model resolution")
    from api.db.joint_services.tenant_model_service import resolve_model_config
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from api.db.services.llm_service import LLMBundle
    from common.constants import LLMType

    ok, kb = KnowledgebaseService.get_by_id(KB)
    if not ok:
        print(f"    knowledge base {KB} not found")
        return 1
    # The DEPLOYED path resolves the embedding from the KB's own model id:
    # `resolve_model_config(embd_owner_tenant_id, LLMType.EMBEDDING, kbs[0].embd_id)`. Passing
    # the KB id here instead was my error and produced "TenantModel id=9463d93e… not found".
    owner = str(getattr(kb, "tenant_id", TENANT) or TENANT)
    print(f"    kb.embd_id = {getattr(kb, 'embd_id', None)!r} (owner tenant {owner[:8]}…)")
    config = resolve_model_config(owner, LLMType.EMBEDDING, kb.embd_id)
    print("    resolve_model_config ->", type(config).__name__, str(config)[:60])
    embd_mdl = LLMBundle(owner, config)
    print("    LLMBundle ->", type(embd_mdl).__name__)

    print("=== production entry (deployed retrieve_multi_route)")
    from common import settings

    accepted = inspect.signature(deployed_pipeline.retrieve_multi_route).parameters
    kwargs = {
        # The deployed Dealer takes the doc store as its one argument; the deployed
        # `dialog_service` builds it the same way.
        "retriever": __import__("rag.nlp.search", fromlist=["Dealer"]).Dealer(settings.docStoreConn),
        "question": QUESTION,
        "tenant_ids": [TENANT],
        "kb_ids": [KB],
        "embd_mdl": embd_mdl,
        "similarity_threshold": 0.2,
        "final_top_n": 12,
    }
    kwargs = {key: value for key, value in kwargs.items() if key in accepted or key == "retriever"}
    try:
        production = await deployed_pipeline.retrieve_multi_route(**kwargs)
    except Exception as exc:  # noqa: BLE001 - the smoke test reports, it does not hide
        print(f"    PRODUCTION ENTRY FAILED: {type(exc).__name__}: {exc}")
        return 1
    production_ids = ids(production)
    print(f"    returned {len(production_ids)}; top10: {production_ids[:10]}")

    print("=== diagnostic path (deployed Dealer.retrieval, production weight)")
    from rag.nlp import search as rag_search

    dealer = rag_search.Dealer(settings.docStoreConn)
    diagnostic = await dealer.retrieval(QUESTION, embd_mdl, [TENANT], [KB], page=1, page_size=12, similarity_threshold=0.2, vector_similarity_weight=0.3, top=1024)
    diagnostic_ids = ids(diagnostic)
    print(f"    returned {len(diagnostic_ids)}; top10: {diagnostic_ids[:10]}")

    overlap = [chunk for chunk in diagnostic_ids[:10] if chunk in production_ids]
    print("=== comparison")
    print(f"    overlap of the diagnostic top-10 inside the production set: {len(overlap)}/10")
    print(f"    identical top-10 order: {diagnostic_ids[:10] == production_ids[:10]}")
    print("    production ids not in diagnostic top-10:", [chunk for chunk in production_ids[:12] if chunk not in diagnostic_ids][:6])
    payload = {"production_top10": production_ids[:10], "diagnostic_top10": diagnostic_ids[:10], "overlap": len(overlap)}
    print("SMOKE_JSON " + json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
