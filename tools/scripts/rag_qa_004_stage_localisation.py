"""QA-004 stage localisation (READ-ONLY follow-up).

The first diagnostic showed the composite question's window consistently holds 0 design-life
passages and 4 structure passages, while the same design-life evidence ranks 0.94-0.99 when asked
alone. This probe finds the stage that loses it, using only deployed functions and deployed
parameters:

E1 decomposition distribution   - is the LLM route list stable over more samples?
E2 per-route retrieval          - what does EACH route actually contribute, with production params?
E3 rerank determinism           - one fixed passage set re-scored synchronously, N times
E4 controlled recombination     - reproduce the deployed merge + rerank_cut over the routes'
                                  OWN candidates and count the halves at each stage, so the loss is
                                  attributed to recall, to the merge, or to the cut

Nothing is written; no parameter, model or code is changed.
"""

from __future__ import annotations

import asyncio
import collections
import datetime
import json
import os
import re
import sys

sys.path.insert(0, "/ragflow")

KB_ID = "9463d93eb97511f1938f2592e9bc6fe4"
DIALOG_ID = "5c8c249eb8e411f180e20bf412cbc55e"
ORIGINAL = "标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求"
N_DECOMPOSE = int(os.environ.get("N_DECOMPOSE", "12"))
N_MODEL = int(os.environ.get("N_MODEL", "3"))
JSON_OUT = "/tmp/qa004_stage.json"

_TAG_RE = re.compile(r"<[^>]{0,300}?>")


def flat(text: str) -> str:
    return re.sub(r"\s+", "", _TAG_RE.sub("|", str(text or "")).lower().replace("×", "x"))


def halves(chunk: dict) -> tuple[bool, bool]:
    text = flat(chunk.get("content_with_weight") or chunk.get("content") or "")
    return ("设计使用年限" in text or "不少于30" in text), ("结构图纸" in text)


def tally(chunks) -> dict:
    life = [c for c in chunks if halves(c)[0]]
    struct = [c for c in chunks if halves(c)[1]]
    return {"n": len(chunks), "design_life": len(life), "structure": len(struct), "both": bool(life) and bool(struct)}


def brief(chunks, limit=12) -> list[dict]:
    out = []
    for c in list(chunks)[:limit]:
        life, struct = halves(c)
        body = str(c.get("content_with_weight") or "")
        desig = re.search(r"标准号[:：]\s*([A-Z0-9./\- ]+?)\s*[|\]]", body)
        out.append(
            {
                "id": str(c.get("chunk_id") or "")[:16],
                "doc": str(c.get("docnm_kwd") or "")[:30],
                "designation": desig.group(1).strip() if desig else "",
                "design_life": life,
                "structure": struct,
                "rerank": None if c.get("rerank_score") is None else round(float(c["rerank_score"]), 4),
                "fused": None if c.get("fused_similarity") is None else round(float(c["fused_similarity"]), 4),
            }
        )
    return out


async def main() -> int:
    from common import settings

    settings.init_settings()
    from rag.nlp import rag_tokenizer
    from rag.retrieval import retrieve_multi_route
    from rag.retrieval.decomposition import decompose_question
    from rag.retrieval.multi_route import RouteResult, merge_route_hits, resolve_routes_top_k
    from rag.retrieval.rerank import resolve_final_top_n, rerank_chunks
    from api.db.db_models import Dialog
    from api.db.joint_services.tenant_model_service import get_tenant_default_model_by_type, resolve_model_config
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
    chat_mdl = LLMBundle(tenant, get_tenant_default_model_by_type(tenant, LLMType.CHAT))
    retriever = settings.retriever
    params = {
        "similarity_threshold": float(dialog.similarity_threshold),
        "vector_similarity_weight": float(dialog.vector_similarity_weight),
        "final_top_n": resolve_final_top_n(dialog.top_n),
        "knn_top_k": int(dialog.top_k),
        "rerank_candidates_count": int(getattr(dialog, "rerank_candidates_count", 30) or 30),
    }
    report: dict = {"captured_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "parameters": params}

    # ---- E1 decomposition distribution ---------------------------------------------------
    print("E1 decomposition distribution ...", file=sys.stderr)
    lists = []
    for _ in range(N_DECOMPOSE):
        try:
            routes = await decompose_question(chat_mdl, ORIGINAL, 4)
            lists.append([str(r) for r in routes])
        except Exception as exc:  # noqa: BLE001
            lists.append([f"ERROR {type(exc).__name__}: {exc}"])
    dist = collections.Counter(tuple(x) for x in lists)
    report["E1_decomposition"] = {
        "samples": len(lists),
        "distinct_lists": len(dist),
        "counts": [len(x) for x in lists],
        "distribution": [{"routes": list(k), "times": v} for k, v in dist.most_common()],
    }

    # ---- E2 per-route retrieval ----------------------------------------------------------
    print("E2 per-route retrieval ...", file=sys.stderr)
    routes_to_test = ["(original)", *lists[0]]
    per_route = {}
    route_outputs = {}
    for label in routes_to_test:
        question = ORIGINAL if label == "(original)" else label
        try:
            result = await retriever.retrieval(
                question,
                embd_mdl,
                [tenant],
                [KB_ID],
                1,
                resolve_routes_top_k(None),
                params["similarity_threshold"],
                params["vector_similarity_weight"],
                aggs=True,
                highlight=False,
                rerank_candidates_count=params["rerank_candidates_count"],
                allow_dense_fallback=True,
            )
            chunks = list(result.get("chunks") or [])
            route_outputs[label] = chunks
            per_route[label] = {**tally(chunks), "top": brief(chunks)}
        except Exception as exc:  # noqa: BLE001
            report.setdefault("errors", []).append(f"route {label!r}: {type(exc).__name__}: {exc}")
            route_outputs[label] = []
            per_route[label] = {"error": f"{type(exc).__name__}: {exc}"}
    report["E2_per_route"] = per_route

    # ---- E3 rerank determinism -----------------------------------------------------------
    print("E3 rerank determinism ...", file=sys.stderr)
    pool_docs = []
    pool_src = []
    for label, chunks in route_outputs.items():
        for c in chunks:
            pool_docs.append(str(c.get("content_with_weight") or ""))
            pool_src.append(c)
    runs = []
    if pool_docs and rerank_mdl is not None:
        for _ in range(N_MODEL):
            try:
                # ``similarity`` is synchronous and returns ``(scores, tokens)``.
                scores, _ = rerank_mdl.similarity(ORIGINAL, pool_docs)
                runs.append([round(float(s), 8) for s in scores])
            except Exception as exc:  # noqa: BLE001
                report.setdefault("errors", []).append(f"rerank: {type(exc).__name__}: {exc}")
    e3 = {"docs": len(pool_docs), "runs": len(runs)}
    if len(runs) > 1:
        e3["identical_all"] = all(r == runs[0] for r in runs)
        e3["max_abs_diff"] = max(max(abs(a - b) for a, b in zip(runs[0], r)) for r in runs[1:])
    report["E3_rerank"] = e3

    # ---- E4 controlled recombination -----------------------------------------------------
    # Reproduce the deployed merge + rerank + cut over the routes' OWN candidates, counting each
    # half at every stage. Route candidates come from the deployed retriever at deployed
    # parameters; only the assembly is done here, and it is labelled as a recombination.
    print("E4 controlled recombination ...", file=sys.stderr)
    hits = [RouteResult(query=label if label != "(original)" else ORIGINAL, chunks=chunks) for label, chunks in route_outputs.items()]
    merged = merge_route_hits(hits)
    pool = list(merged.get("chunks") or [])
    stage_pool = tally(pool)
    kept = await rerank_chunks(rerank_mdl, pool, ORIGINAL, params["final_top_n"])
    stage_kept = tally(kept)
    production = await retrieve_multi_route(
        retriever=retriever,
        question=ORIGINAL,
        chat_mdl=chat_mdl,
        embd_mdl=embd_mdl,
        rerank_mdl=rerank_mdl,
        tenant_ids=[tenant],
        kb_ids=[KB_ID],
        similarity_threshold=params["similarity_threshold"],
        vector_similarity_weight=params["vector_similarity_weight"],
        final_top_n=params["final_top_n"],
        knn_top_k=params["knn_top_k"],
        rerank_candidates_count=params["rerank_candidates_count"],
    )
    prod_chunks = list(production.get("chunks") or [])
    report["E4_recombination"] = {
        "routes_used": routes_to_test,
        "stage_1_route_candidates": {label: tally(chunks) for label, chunks in route_outputs.items()},
        "stage_2_merged_pool": stage_pool,
        "stage_3_after_rerank_cut": {**stage_kept, "top": brief(kept)},
        "stage_4_production_call": {**tally(prod_chunks), "top": brief(prod_chunks)},
    }
    stage1 = report["E4_recombination"]["stage_1_route_candidates"]
    sum1_life = sum(v.get("design_life", 0) for v in stage1.values())
    sum1_struct = sum(v.get("structure", 0) for v in stage1.values())
    report["E4_recombination"]["design_life_lost_at"] = (
        "route recall (no route returned a design-life passage)"
        if sum1_life == 0
        else "merge" if stage_pool["design_life"] == 0
        else "rerank+cut" if stage_kept["design_life"] == 0
        else "kept by the recombination"
    )
    report["E4_recombination"]["structure_lost_at"] = (
        "route recall (no route returned a structure passage)"
        if sum1_struct == 0
        else "merge" if stage_pool["structure"] == 0
        else "rerank+cut" if stage_kept["structure"] == 0
        else "kept by the recombination"
    )

    with open(JSON_OUT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)

    print("=== E1 decomposition ===")
    print(f"  samples={report['E1_decomposition']['samples']} distinct={report['E1_decomposition']['distinct_lists']} sizes={report['E1_decomposition']['counts']}")
    for d in report["E1_decomposition"]["distribution"]:
        print(f"  x{d['times']}: " + " | ".join(d["routes"]))
    print("=== E2 per-route contribution ===")
    for label, v in report["E2_per_route"].items():
        if "error" in v:
            print(f"  {label}: ERROR {v['error']}")
        else:
            print(f"  {label}: n={v['n']} design_life={v['design_life']} structure={v['structure']} both={v['both']}")
    print("=== E3 rerank determinism ===")
    print(" ", json.dumps(report["E3_rerank"], ensure_ascii=False))
    e4 = report["E4_recombination"]
    print("=== E4 controlled recombination ===")
    print(f"  merged pool: {e4['stage_2_merged_pool']}")
    print(f"  after rerank+cut: {e4['stage_3_after_rerank_cut']['n']} chunks, design_life={e4['stage_3_after_rerank_cut']['design_life']}, structure={e4['stage_3_after_rerank_cut']['structure']}")
    print(f"  production call: design_life={e4['stage_4_production_call']['design_life']}, structure={e4['stage_4_production_call']['structure']}")
    print(f"  DESIGN-LIFE LOST AT: {e4['design_life_lost_at']}")
    print(f"  STRUCTURE LOST AT:   {e4['structure_lost_at']}")
    for row in e4["stage_3_after_rerank_cut"]["top"]:
        print(f"    cut  {row['id']} life={int(row['design_life'])} struct={int(row['structure'])} rerank={row['rerank']} {row['doc'][:26]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
