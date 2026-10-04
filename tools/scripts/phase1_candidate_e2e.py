"""Run the isolated retrieval candidate end to end (READ-ONLY, no image build).

The candidate is the DEPLOYED pipeline.py with the three Phase-1 hunks applied, loaded as a
standalone module so the deployed tree is never modified. The Phase-1 rule is injected into the
deployed package namespace under its real name, so the candidate's import line is byte-identical to
the one that would ship.

Everything else - index, embedding model, reranker, assistant parameters - is the deployed one, so
the route assembly under test is the real production code path.

    P1CAND_LABEL=cand python /tmp/phase1_candidate_e2e.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import sys
import time

sys.path.insert(0, "/ragflow")
sys.path.insert(0, "/tmp/p1cand")

KB_ID = "9463d93eb97511f1938f2592e9bc6fe4"
DIALOG_ID = "5c8c249eb8e411f180e20bf412cbc55e"
LABEL = os.environ.get("P1CAND_LABEL", "cand")
RUNS = int(os.environ.get("P1CAND_RUNS", "3"))

_TAG_RE = re.compile(r"<[^>]{0,300}?>")

QA: tuple[tuple[str, str], ...] = (
    ("QA004_exact", "标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求"),
    ("QA004_v2", "电缆终端和接头的设计寿命、结构分别有什么要求？"),
    ("QA004_v3", "终端与接头能使用多少年？结构上有什么规定？"),
    ("QA004_v4", "电缆附件中的终端、接头，其使用年限和结构要求是什么？"),
    ("QA004_v5", "标准对终端和接头的结构以及设计使用年限是怎样规定的？"),
    ("QA004_v6", "终端、接头在寿命和结构方面有哪些技术要求？"),
    ("QA001", "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"),
    ("QA002", "Q/GDW 73285-2026 标准体系由哪些部分构成？各自适用范围是什么？"),
    ("QA003", "2026版标准相比2019旧版标准，主要进行了哪些重要修订？"),
    ("QA005", "110kV海缆系统的耐压试验标准（出厂与安装后）是如何规定的？"),
    ("N1_single_entity", "海缆的设计使用寿命是多少？"),
    ("N2_single_fact", "终端结构有什么要求？"),
    ("N3_one_axis", "终端和接头有哪些类型？"),
)


def flat(text: str) -> str:
    return re.sub(r"\s+", "", _TAG_RE.sub("|", str(text or "")).lower().replace("×", "x"))


def halves(c: dict) -> tuple[bool, bool]:
    t = flat(c.get("content_with_weight") or "")
    return ("设计使用年限" in t or "不少于30" in t), ("结构图纸" in t)


async def main() -> int:
    from common import settings

    settings.init_settings()

    # Inject the Phase-1 rule under its real dotted name so the candidate's import line is the real
    # one and no production file is touched.
    spec = importlib.util.spec_from_file_location("rag.retrieval.route_expansion", "/tmp/p1/route_expansion.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["rag.retrieval.route_expansion"] = module
    spec.loader.exec_module(module)

    # Load the candidate pipeline (deployed pipeline.py + the 3 hunks).
    cspec = importlib.util.spec_from_file_location("phase1_candidate_pipeline", "/tmp/p1cand/pipeline.py")
    candidate = importlib.util.module_from_spec(cspec)
    cspec.loader.exec_module(candidate)

    from api.db.db_models import Dialog
    from api.db.joint_services.tenant_model_service import get_tenant_default_model_by_type, resolve_model_config
    from api.db.services.dialog_service import resolve_rerank_mdl
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from api.db.services.llm_service import LLMBundle
    from common.constants import LLMType

    ok, kb = KnowledgebaseService.get_by_id(KB_ID)
    tenant = str(kb.tenant_id)
    dialog = Dialog.get_or_none(Dialog.id == DIALOG_ID)
    embd_mdl = LLMBundle(tenant, resolve_model_config(tenant, LLMType.EMBEDDING, kb.embd_id))
    rerank_mdl = resolve_rerank_mdl(tenant, dialog.rerank_id or "", dialog.tenant_rerank_id)
    chat_mdl = LLMBundle(tenant, get_tenant_default_model_by_type(tenant, LLMType.CHAT))
    retriever = settings.retriever

    report: dict = {
        "label": LABEL,
        "candidate_module": candidate.__file__,
        "candidate_route_budget": getattr(candidate, "ROUTE_BUDGET", None),
        "candidate_expansion_is_ours": getattr(candidate, "supplemental_routes", None) is module.supplemental_routes,
        "runs": RUNS,
        "queries": {},
    }
    params = {
        "similarity_threshold": float(dialog.similarity_threshold),
        "vector_similarity_weight": float(dialog.vector_similarity_weight),
        "final_top_n": (lambda v: v)(int(dialog.top_n)),
        "knn_top_k": int(dialog.top_k),
        "rerank_candidates_count": int(getattr(dialog, "rerank_candidates_count", 30) or 30),
    }
    report["parameters"] = params

    for name, question in QA:
        entry: dict = {"question": question, "runs": []}
        added, trace = module.supplemental_routes(question, existing_routes=(), budget=candidate.ROUTE_BUDGET)
        entry["expansion"] = {
            "entities": trace.get("entities"),
            "fact_types": trace.get("fact_types"),
            "reason": trace.get("reason"),
            "added": added,
        }
        for run_index in range(RUNS):
            t0 = time.perf_counter()
            try:
                result = await candidate.retrieve_multi_route(
                    retriever=retriever,
                    question=question,
                    chat_mdl=chat_mdl,
                    embd_mdl=embd_mdl,
                    rerank_mdl=rerank_mdl,
                    tenant_ids=[tenant],
                    kb_ids=[KB_ID],
                    **params,
                )
            except Exception as exc:  # noqa: BLE001
                entry["runs"].append({"error": f"{type(exc).__name__}: {exc}"})
                continue
            elapsed = time.perf_counter() - t0
            chunks = list(result.get("chunks") or [])
            ids = [str(c.get("chunk_id") or "") for c in chunks]
            life = [c for c in chunks if halves(c)[0]]
            struct = [c for c in chunks if halves(c)[1]]
            routes = sorted({r for c in chunks for r in (c.get("retrieval_routes") or [])})
            entry["runs"].append(
                {
                    "elapsed_s": round(elapsed, 3),
                    "returned": len(chunks),
                    "design_life": len(life),
                    "structure": len(struct),
                    "both_halves": bool(life) and bool(struct),
                    "duplicate_chunks": len(ids) - len(set(ids)),
                    "distinct_documents": len({str(c.get("doc_id") or "") for c in chunks}),
                    "context_chars": sum(len(str(c.get("content_with_weight") or "")) for c in chunks),
                    "route_count_in_window": len(routes),
                }
            )
        report["queries"][name] = entry
        print(f"done {name}", file=sys.stderr)

    with open(f"/tmp/p1cand_{LABEL}.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)

    print(f"=== isolated candidate e2e ({LABEL}) ===")
    print(f"  candidate module: {report['candidate_module']}")
    print(f"  ROUTE_BUDGET={report['candidate_route_budget']}  route_expansion is Phase-1 rule: {report['candidate_expansion_is_ours']}")
    import statistics as st

    for name, e in report["queries"].items():
        ok_runs = [r for r in e["runs"] if "error" not in r]
        if not ok_runs:
            print(f"  {name:18s} ERRORS {e['runs'][0].get('error')}")
            continue
        life = [r["design_life"] for r in ok_runs]
        struct = [r["structure"] for r in ok_runs]
        both = sum(1 for r in ok_runs if r["both_halves"])
        lat = st.median([r["elapsed_s"] for r in ok_runs])
        rc = sorted({r["route_count_in_window"] for r in ok_runs})
        dup = sum(r["duplicate_chunks"] for r in ok_runs)
        ex = e["expansion"]
        print(f"  {name:18s} exp={ex['reason']:24s} added={len(ex['added'])} life={life} struct={struct} both={both}/{len(ok_runs)} lat_med={lat:.2f}s winroutes={rc} dup={dup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
