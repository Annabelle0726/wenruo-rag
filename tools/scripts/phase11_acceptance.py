"""Phase 1.1 acceptance suite (READ-ONLY, no image built, nothing deployed).

Runs the acceptance set twice on the SAME deployed stack (index, embedding, reranker, assistant
parameters):

    BEFORE  the deployed entry point, exactly as production runs it today
    AFTER   the DEPLOYED pipeline.py with the Phase-1 hunks applied, loaded as a standalone module,
            with the generalized axis reader injected under its real dotted name

Both sides therefore execute the real production route assembly; the only difference is the
deterministic supplemental routes. The deployed tree is never modified.

    P11_LABEL=acc P11_RUNS=3 python /tmp/phase11_acceptance.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import statistics as st
import sys
import time

sys.path.insert(0, "/ragflow")
sys.path.insert(0, "/tmp/p1cand")

KB_ID = "9463d93eb97511f1938f2592e9bc6fe4"
DIALOG_ID = "5c8c249eb8e411f180e20bf412cbc55e"
LABEL = os.environ.get("P11_LABEL", "acc")
RUNS = int(os.environ.get("P11_RUNS", "3"))
ROUTE_BUDGET = 8

_TAG_RE = re.compile(r"<[^>]{0,300}?>")

#: The acceptance set: six paraphrases of one question, three single-axis negatives, and the four
#: frozen benchmark questions that must not regress.
SUITE: tuple[tuple[str, str, str], ...] = (
    ("V1", "标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求？", "paraphrase"),
    ("V2", "电缆终端和接头的设计寿命、结构分别有什么要求？", "paraphrase"),
    ("V3", "终端与接头能使用多少年？结构上有什么规定？", "paraphrase"),
    ("V4", "电缆附件中的终端、接头，其使用年限和结构要求是什么？", "paraphrase"),
    ("V5", "标准对终端和接头的结构以及设计使用年限是怎样规定的？", "paraphrase"),
    ("V6", "终端、接头在寿命和结构方面有哪些技术要求？", "paraphrase"),
    ("N1_single_entity", "海缆的设计使用寿命是多少？", "negative"),
    ("N2_single_fact", "终端结构有什么要求？", "negative"),
    ("N3_one_axis", "终端和接头有哪些类型？", "negative"),
    ("QA001", "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？", "frozen"),
    ("QA002", "Q/GDW 73285-2026 标准体系由哪些部分构成？各自适用范围是什么？", "frozen"),
    ("QA003", "2026版标准相比2019旧版标准，主要进行了哪些重要修订？", "frozen"),
    ("QA005", "110kV海缆系统的耐压试验标准（出厂与安装后）是如何规定的？", "frozen"),
)

LIFE_NEEDLES = ("设计使用年限", "不少于30")
STRUCT_NEEDLES = ("结构图纸",)
STRUCT_TOPIC = ("户外终端", "gis终端", "油浸终端", "预制直通接头", "绝缘接头")

#: A route is malformed when it carries question scaffolding instead of a noun phrase. Checked on
#: every emitted route, per run.
_RESIDUE_RE = re.compile(r"有|是|什么|怎样|怎么|如何|哪些|多少|分别|以及|能|可以|要求|规定|方面$|技术")


def flat(text: str) -> str:
    return re.sub(r"\s+", "", _TAG_RE.sub("|", str(text or "")).lower().replace("×", "x"))


def halves(c: dict) -> tuple[bool, bool]:
    t = flat(c.get("content_with_weight") or "")
    return any(n in t for n in LIFE_NEEDLES), any(n in t for n in STRUCT_NEEDLES)


def facts(text: str) -> dict:
    t = flat(text)
    return {
        "design_life_years": ("不少于30" in t) or ("30年" in t),
        "structure_drawings": "结构图纸" in t,
        "structure_topics": sum(1 for n in STRUCT_TOPIC if n in t),
    }


async def main() -> int:
    from common import settings

    settings.init_settings()

    # Inject the Phase-1.1 modules under their real dotted names, so the candidate's import line is
    # the one that would ship and no production file is touched.
    for name, path in (
        ("rag.retrieval.domain_facts", "/tmp/p1/domain_facts.py"),
        ("rag.retrieval.route_expansion", "/tmp/p1/route_expansion.py"),
    ):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)

    candidate = None
    if os.path.exists("/tmp/p1cand/pipeline.py"):
        cspec = importlib.util.spec_from_file_location("p11_candidate_pipeline", "/tmp/p1cand/pipeline.py")
        candidate = importlib.util.module_from_spec(cspec)
        cspec.loader.exec_module(candidate)

    from rag.retrieval import retrieve_multi_route as deployed_entry
    from rag.retrieval.route_expansion import entity_fact_routes, supplemental_routes

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
    params = {
        "similarity_threshold": float(dialog.similarity_threshold),
        "vector_similarity_weight": float(dialog.vector_similarity_weight),
        "final_top_n": int(dialog.top_n),
        "knn_top_k": int(dialog.top_k),
        "rerank_candidates_count": int(getattr(dialog, "rerank_candidates_count", 30) or 30),
    }

    async def run(entry, question, name, side):
        out = []
        for _ in range(RUNS):
            t0 = time.perf_counter()
            try:
                result = await entry(
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
                out.append({"error": f"{type(exc).__name__}: {exc}"})
                continue
            elapsed = time.perf_counter() - t0
            chunks = list(result.get("chunks") or [])
            ids = [str(c.get("chunk_id") or "") for c in chunks]
            life = [c for c in chunks if halves(c)[0]]
            struct = [c for c in chunks if halves(c)[1]]
            routes = sorted({r for c in chunks for r in (c.get("retrieval_routes") or [])})
            out.append(
                {
                    "elapsed_s": round(elapsed, 3),
                    "returned": len(chunks),
                    "design_life": len(life),
                    "structure": len(struct),
                    "both_halves": bool(life) and bool(struct),
                    "duplicate_chunks": len(ids) - len(set(ids)),
                    "distinct_documents": len({str(c.get("doc_id") or "") for c in chunks}),
                    "route_count_in_window": len(routes),
                }
            )
        return out

    report: dict = {
        "label": LABEL,
        "runs": RUNS,
        "candidate_module": getattr(candidate, "__file__", None),
        "parameters": params,
        "questions": {},
    }

    for name, question, role in SUITE:
        produced, trace = entity_fact_routes(question)
        added, strace = supplemental_routes(question, existing_routes=(), budget=ROUTE_BUDGET)
        malformed = [r for r in produced if _RESIDUE_RE.search(r.split(" ", 1)[-1])]
        entry: dict = {
            "question": question,
            "role": role,
            "axes": {
                "entities": strace.get("entities"),
                "fact_types": strace.get("fact_types"),
                "source": strace.get("entity_source"),
                "reason": strace.get("reason"),
                "profile": strace.get("profile"),
            },
            "supplemental_routes": added,
            "supplemental_count": len(added),
            "malformed_routes": malformed,
            "before": await run(deployed_entry, question, name, "before"),
        }
        if candidate is not None:
            entry["after"] = await run(candidate.retrieve_multi_route, question, name, "after")
        report["questions"][name] = entry
        print(f"done {name}", file=sys.stderr)

    with open(f"/tmp/p11_{LABEL}.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)

    print(f"=== Phase 1.1 acceptance ({LABEL}) candidate={report['candidate_module']} ===")
    print(f"{'q':18s} {'role':10s} {'sup':>3s} {'mal':>3s} {'life b->a':18s} {'struct b->a':16s} {'both a':6s} {'lat b->a':14s} {'win b->a'}")
    print("-" * 116)
    for name, e in report["questions"].items():
        b = [x for x in e["before"] if "error" not in x]
        a = [x for x in e.get("after", []) if "error" not in x]
        if not b or not a:
            print(f"{name:18s} {e['role']:10s} ERROR b={e['before'][:1]} a={e.get('after',[])[:1]}")
            continue
        lb = [x["design_life"] for x in b]
        la = [x["design_life"] for x in a]
        sb = [x["structure"] for x in b]
        sa = [x["structure"] for x in a]
        both = sum(1 for x in a if x["both_halves"])
        latb = st.median([x["elapsed_s"] for x in b])
        lata = st.median([x["elapsed_s"] for x in a])
        wb = sorted({x["route_count_in_window"] for x in b})
        wa = sorted({x["route_count_in_window"] for x in a})
        dup = sum(x["duplicate_chunks"] for x in a)
        print(
            f"{name:18s} {e['role']:10s} {e['supplemental_count']:3d} {len(e['malformed_routes']):3d} "
            f"{str(lb)+' -> '+str(la):18s} {str(sb)+' -> '+str(sa):16s} {both}/{len(a)}    {latb:4.2f}->{lata:4.2f}s   {wb}->{wa} dup={dup}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
