"""Phase Candidate Integration - PART D end-to-end QA on the candidate's REAL runtime path.

Runs INSIDE a container created from the candidate image. Nothing is patched: the acceptance
measurements call the module the production entry point imports, exactly as the API service does.

It also fingerprints what it loaded, so "the production runtime actually traverses Phase 0 / 1.1 / 2"
is a recorded fact rather than an assumption.

    docker exec <candidate container> sh -c "cd /ragflow && python /tmp/candidate_e2e.py"
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import statistics as st
import sys
import time

sys.path.insert(0, "/ragflow")

KB_ID = "9463d93eb97511f1938f2592e9bc6fe4"
DIALOG_ID = "5c8c249eb8e411f180e20bf412cbc55e"
RUNS = int(os.environ.get("E2E_RUNS", "3"))
OUT = os.environ.get("E2E_OUT", "/tmp/candidate_e2e.json")

_TAG_RE = re.compile(r"<[^>]{0,300}?>")

LIFE_CLAUSE = "不少于30"
LIFE_FACT = "设计使用年限"
STRUCT_CLAUSE = "结构图纸"
STRUCT_FACT = "结构"

QUESTIONS: tuple[tuple[str, str, str], ...] = (
    ("QA001", "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？", "frozen"),
    ("QA002", "Q/GDW 73285-2026 标准体系由哪些部分构成？各自适用范围是什么？", "frozen"),
    ("QA003", "2026版标准相比2019旧版标准，主要进行了哪些重要修订？", "frozen"),
    ("QA004", "标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求", "frozen"),
    ("QA005", "110kV海缆系统的耐压试验标准（出厂与安装后）是如何规定的？", "frozen"),
    ("V1", "标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求？", "paraphrase"),
    ("V2", "电缆终端和接头的设计寿命、结构分别有什么要求？", "paraphrase"),
    ("V3", "终端与接头能使用多少年？结构上有什么规定？", "paraphrase"),
    ("V4", "电缆附件中的终端、接头，其使用年限和结构要求是什么？", "paraphrase"),
    ("V5", "标准对终端和接头的结构以及设计使用年限是怎样规定的？", "paraphrase"),
    ("V6", "终端、接头在寿命和结构方面有哪些技术要求？", "paraphrase"),
    ("G1", "户外终端和GIS终端的设计使用寿命和结构有什么规定？", "generalization"),
    ("G2", "工厂接头与修理接头的结构以及设计使用年限是怎样要求的？", "generalization"),
    ("G3", "110kV海缆单芯和三芯的终端、接头的使用年限和结构要求分别是什么？", "generalization"),
    ("G4", "电缆终端、电缆接头在结构和设计寿命方面有哪些技术要求？", "generalization"),
    ("G5", "标准对户外终端和电缆接头的设计使用年限、结构分别有什么规定？", "generalization"),
)


def flat(text: str) -> str:
    return re.sub(r"\s+", "", _TAG_RE.sub("|", str(text or "")).lower().replace("×", "x"))


def evidence(chunks) -> dict:
    texts = [flat(c.get("content_with_weight") or "") for c in chunks]
    return {
        "n": len(chunks),
        "life_fact": sum(1 for t in texts if LIFE_FACT in t),
        "life_clause": sum(1 for t in texts if LIFE_CLAUSE in t),
        "struct_fact": sum(1 for t in texts if STRUCT_FACT in t),
        "struct_clause": sum(1 for t in texts if STRUCT_CLAUSE in t),
        "docs": len({str(c.get("doc_id") or "") for c in chunks}),
        "dups": len(chunks) - len({str(c.get("chunk_id") or "") for c in chunks}),
    }


def fingerprint() -> dict:
    paths = (
        "rag/res/synonym.json",
        "rag/retrieval/domain_facts.py",
        "rag/retrieval/route_expansion.py",
        "rag/retrieval/context_reservation.py",
        "rag/retrieval/pipeline.py",
        "rag/retrieval/rerank.py",
    )
    out = {}
    for rel in paths:
        p = os.path.join("/ragflow", rel)
        try:
            out[rel] = hashlib.sha256(open(p, "rb").read()).hexdigest()
        except OSError as exc:
            out[rel] = f"MISSING ({type(exc).__name__})"
    return out


async def main() -> int:
    from common import settings

    settings.init_settings()

    import rag.retrieval.rerank as R
    from rag.retrieval import retrieve_multi_route
    from rag.prompts.generator import num_tokens_from_string, kb_prompt

    # The Phase 1.1 / Phase 2 modules exist only in the candidate. Importing them optionally lets
    # the SAME harness run against the production baseline, so before/after are directly comparable.
    try:
        import rag.retrieval.context_reservation as cr
        import rag.retrieval.domain_facts as df
        import rag.retrieval.route_expansion as rx
    except ModuleNotFoundError:
        cr = df = rx = None

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
    system_prompt = str((dialog.prompt_config or {}).get("system") or "")
    params = {
        "similarity_threshold": float(dialog.similarity_threshold),
        "vector_similarity_weight": float(dialog.vector_similarity_weight),
        "final_top_n": int(dialog.top_n),
        "knn_top_k": int(dialog.top_k),
        "rerank_candidates_count": int(getattr(dialog, "rerank_candidates_count", 30) or 30),
    }

    report: dict = {
        "runs": RUNS,
        "parameters": params,
        "fingerprint": fingerprint(),
        "module_paths": {
            "pipeline": sys.modules["rag.retrieval.pipeline"].__file__,
            "rerank": R.__file__,
            "route_expansion": getattr(rx, "__file__", "ABSENT"),
            "domain_facts": getattr(df, "__file__", "ABSENT"),
            "context_reservation": getattr(cr, "__file__", "ABSENT"),
        },
        # Phase 0 loaded?
        "phase0": {
            "synonym_entries": len(retriever.qryr.syn.dictionary or {}),
            "lookup_design_life_span": retriever.qryr.syn.lookup("设计使用寿命"),
            "lookup_design_life_span_short": retriever.qryr.syn.lookup("设计寿命"),
            "lookup_bare_life_span": retriever.qryr.syn.lookup("寿命"),
        },
        # Phase 2 wired into the production selection function?
        "phase2_wired": ("reserve_for_question" in R.rerank_chunks.__code__.co_names) if hasattr(R.rerank_chunks, "__code__") else None,
        "questions": {},
    }

    async def one(question):
        t0 = time.perf_counter()
        result = await retrieve_multi_route(
            retriever=retriever,
            question=question,
            chat_mdl=chat_mdl,
            embd_mdl=embd_mdl,
            rerank_mdl=rerank_mdl,
            tenant_ids=[tenant],
            kb_ids=[KB_ID],
            **params,
        )
        elapsed = time.perf_counter() - t0
        chunks = list(result.get("chunks") or [])
        row = evidence(chunks)
        row["elapsed_s"] = round(elapsed, 3)
        row["tokens"] = num_tokens_from_string("\n".join(str(c.get("content_with_weight") or "") for c in chunks))
        row["routes"] = sorted({r for c in chunks for r in (c.get("retrieval_routes") or [])})
        return row, chunks

    for name, question, role in QUESTIONS:
        facts = cr.required_fact_types(question) if cr else []
        if rx:
            added, trace = rx.supplemental_routes(question, existing_routes=(), budget=8)
            reason = trace.get("reason")
        else:
            added, reason = [], "baseline: no axis reader"
        entry: dict = {
            "question": question,
            "role": role,
            "fact_types": [f.key for f in facts],
            "expansion_reason": reason,
            "supplemental_routes": added,
            "runs": [],
        }
        for run_index in range(RUNS):
            try:
                row, chunks = await one(question)
            except Exception as exc:  # noqa: BLE001
                entry["runs"].append({"error": f"{type(exc).__name__}: {exc}"})
                continue
            if run_index == 0 and role in ("frozen", "paraphrase", "generalization"):
                try:
                    blocks = kb_prompt({"chunks": chunks}, 1000000)
                    ans = await chat_mdl.async_chat(
                        system_prompt.replace("{knowledge}", "\n------\n\n".join(blocks)),
                        [{"role": "user", "content": question}],
                    )
                    if isinstance(ans, tuple):
                        ans = ans[0]
                    t = flat(ans)
                    row["answer_facts"] = {
                        "design_life_years": ("不少于30" in t) or ("30年" in t),
                        "structure_drawings": "结构图纸" in t,
                    }
                except Exception as exc:  # noqa: BLE001
                    row["answer_facts"] = {"error": f"{type(exc).__name__}: {exc}"}
            entry["runs"].append(row)
        report["questions"][name] = entry
        print(f"done {name}", file=sys.stderr)

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)

    print("=== PART D: candidate runtime end-to-end ===")
    print("fingerprint:")
    for k, v in report["fingerprint"].items():
        print(f"   {k:42s} {v[:16]}")
    print("module paths:", json.dumps(report["module_paths"], ensure_ascii=False))
    print("phase0:", json.dumps(report["phase0"], ensure_ascii=False))
    print("phase2 wired into rerank_chunks:", report["phase2_wired"])
    print()
    hdr = f"{'q':8s} {'role':13s} {'ft':2s} {'sup':3s} {'life_cl':8s} {'struct_cl':9s} {'docs':6s} {'dup':4s} {'tokens':8s} {'lat':6s} exp"
    print(hdr)
    print("-" * len(hdr))
    for name, e in report["questions"].items():
        rows = [r for r in e["runs"] if "error" not in r]
        if not rows:
            print(f"{name:8s} {e['role']:13s} ERROR {e['runs'][0].get('error')}")
            continue
        lc = [r["life_clause"] for r in rows]
        sc = [r["struct_clause"] for r in rows]
        print(
            f"{name:8s} {e['role']:13s} {len(e['fact_types']):2d} {len(e['supplemental_routes']):3d} "
            f"{str(lc):8s} {str(sc):9s} {str(sorted({r['docs'] for r in rows})):6s} {sum(r['dups'] for r in rows):4d} "
            f"{str(sorted({r['tokens'] for r in rows})):8s} {st.median([r['elapsed_s'] for r in rows]):5.2f}s {e['expansion_reason']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
