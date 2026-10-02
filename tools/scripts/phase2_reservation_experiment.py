"""Phase 2 controlled experiment: multi-fact context coverage (READ-ONLY, nothing deployed).

PART A  stage localisation - for each fact type, per-route candidates, merged-pool rank, rerank
        score, final-context rank, and which required evidence was in the pool but cut. Every
        required evidence item is attributed to RECALL_MISS, RERANK_DROP or CONTEXT_CUT_DROP.
PART C  controlled comparison of four strategies on the same questions:
          A current      the deployed cut, unchanged
          B fact         reserve 1 highest-evidence passage per fact type
          C route        reserve 1 best passage per supplemental route
          D topn16       the deployed cut with a 16-slot window (CONTROL ONLY, not a proposal)

The comparison swaps the cut IN PROCESS by replacing ``rag.retrieval.rerank.select_context``, so the
rest of the call - index, embedding, reranker, route assembly, health - is the deployed production
path. No production file is modified and nothing is written.

    P2_LABEL=exp P2_RUNS=3 python /tmp/phase2_reservation_experiment.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import statistics as st
import sys
import time

sys.path.insert(0, "/ragflow")
sys.path.insert(0, "/tmp/p11")

LABEL = os.environ.get("P2_LABEL", "exp")
RUNS = int(os.environ.get("P2_RUNS", "3"))
KB_ID = "9463d93eb97511f1938f2592e9bc6fe4"
DIALOG_ID = "5c8c249eb8e411f180e20bf412cbc55e"

_TAG_RE = re.compile(r"<[^>]{0,300}?>")

LIFE_CLAUSE = "不少于30"
LIFE_FACT = "设计使用年限"
STRUCT_CLAUSE = "结构图纸"
STRUCT_FACT = "结构"

QUESTIONS: tuple[tuple[str, str, str], ...] = (
    ("V1", "标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求？", "v"),
    ("V2", "电缆终端和接头的设计寿命、结构分别有什么要求？", "v"),
    ("V3", "终端与接头能使用多少年？结构上有什么规定？", "v"),
    ("V4", "电缆附件中的终端、接头，其使用年限和结构要求是什么？", "v"),
    ("V5", "标准对终端和接头的结构以及设计使用年限是怎样规定的？", "v"),
    ("V6", "终端、接头在寿命和结构方面有哪些技术要求？", "v"),
    ("QA001", "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？", "frozen"),
    ("QA002", "Q/GDW 73285-2026 标准体系由哪些部分构成？各自适用范围是什么？", "frozen"),
    ("QA003", "2026版标准相比2019旧版标准，主要进行了哪些重要修订？", "frozen"),
    ("QA005", "110kV海缆系统的耐压试验标准（出厂与安装后）是如何规定的？", "frozen"),
    ("N1_single_entity", "海缆的设计使用寿命是多少？", "negative"),
    ("N2_single_fact", "终端结构有什么要求？", "negative"),
    ("N3_one_axis", "终端和接头有哪些类型？", "negative"),
    # PART E generalization: same two fact types, deliberately different entity pairs, enumerators
    # and phrasings, so the mechanism is tested as a coverage rule rather than as one question.
    ("G1", "户外终端和GIS终端的设计使用寿命和结构有什么规定？", "generalization"),
    ("G2", "工厂接头与修理接头的结构以及设计使用年限是怎样要求的？", "generalization"),
    ("G3", "110kV海缆单芯和三芯的终端、接头的使用年限和结构要求分别是什么？", "generalization"),
    ("G4", "电缆终端、电缆接头在结构和设计寿命方面有哪些技术要求？", "generalization"),
    ("G5", "标准对户外终端和电缆接头的设计使用年限、结构分别有什么规定？", "generalization"),
)

STRATEGIES = ("current", "fact", "route", "topn16")


async def main() -> int:
    from common import settings

    settings.init_settings()

    # Phase-1.1 modules, injected under their real dotted names (the deployed image does not have
    # them); the Phase-2 reservation module likewise.
    for name, path in (
        ("rag.retrieval.domain_facts", "/tmp/p11/domain_facts.py"),
        ("rag.retrieval.route_expansion", "/tmp/p11/route_expansion.py"),
        ("rag.retrieval.context_reservation", "/tmp/p11/context_reservation.py"),
    ):
        import importlib.util

        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)

    import rag.retrieval.rerank as R
    from rag.retrieval import retrieve_multi_route
    from rag.retrieval.domain_facts import FACT_TYPES, resolve_domain
    from rag.retrieval.context_reservation import (
        chunk_key,
        fact_evidence,
        flat,
        score_of,
        select_with_reservation,
    )
    from rag.retrieval.route_expansion import supplemental_routes
    from rag.prompts.generator import num_tokens_from_string, kb_prompt

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
    max_tokens = 1000000
    params = {
        "similarity_threshold": float(dialog.similarity_threshold),
        "vector_similarity_weight": float(dialog.vector_similarity_weight),
        "final_top_n": int(dialog.top_n),
        "knn_top_k": int(dialog.top_k),
        "rerank_candidates_count": int(getattr(dialog, "rerank_candidates_count", 30) or 30),
    }

    original_select = R.select_context
    capture: dict = {}

    def make_select(strategy: str, facts, routes):
        def _select(ordered, top_n, policy=None):
            policy = policy if policy is not None else R.DiversityPolicy()
            base = original_select(ordered, top_n, policy)
            # The pool and the deployed selection are captured for EVERY strategy, so the stage
            # attribution of the control run is available too.
            capture.setdefault("ordered", list(ordered))
            capture.setdefault("base", list(base))
            if strategy == "current":
                return base
            if strategy == "topn16":
                selected = original_select(ordered, 16, policy)
                capture.setdefault("selected", list(selected))
                return selected
            selected = select_with_reservation(
                ordered, top_n, base, strategy=strategy, facts=facts, routes=routes
            )
            capture.setdefault("selected", list(selected))
            return selected

        return _select

    def facts_for(question: str):
        category, mentioned = resolve_domain(question)
        if not category:
            return [], []
        by_key = {f.key: f for f in FACT_TYPES.get(category, ())}
        return [by_key[m["key"]] for m in mentioned if m["key"] in by_key], category

    def evidence_counts(chunks):
        texts = [flat(c.get("content_with_weight") or "") for c in chunks]
        return {
            "n": len(chunks),
            "life_fact": sum(1 for t in texts if LIFE_FACT in t),
            "life_clause": sum(1 for t in texts if LIFE_CLAUSE in t),
            "struct_fact": sum(1 for t in texts if STRUCT_FACT in t),
            "struct_clause": sum(1 for t in texts if STRUCT_CLAUSE in t),
            "docs": len({str(c.get("doc_id") or "") for c in chunks}),
            "dups": len(chunks) - len({chunk_key(c) for c in chunks}),
            "mean_score": round(st.mean([score_of(c) for c in chunks]), 4) if chunks else 0.0,
            "chars": sum(len(str(c.get("content_with_weight") or "")) for c in chunks),
            "tokens": num_tokens_from_string("\n".join(str(c.get("content_with_weight") or "") for c in chunks)),
        }

    report: dict = {
        "label": LABEL,
        "runs": RUNS,
        "parameters": params,
        "questions": {},
    }

    for name, question, role in QUESTIONS:
        facts, category = facts_for(question)
        added, trace = supplemental_routes(question, existing_routes=(), budget=8)
        entry: dict = {
            "question": question,
            "role": role,
            "category": category,
            "fact_types": [f.key for f in facts],
            "supplemental_routes": added,
            "expansion_reason": trace.get("reason"),
            "strategies": {},
        }

        for strategy in STRATEGIES:
            capture.clear()
            R.select_context = make_select(strategy, facts, added)
            stats = []
            for run_index in range(RUNS):
                t0 = time.perf_counter()
                try:
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
                except Exception as exc:  # noqa: BLE001
                    stats.append({"error": f"{type(exc).__name__}: {exc}"})
                    continue
                elapsed = time.perf_counter() - t0
                chunks = list(result.get("chunks") or [])
                row = evidence_counts(chunks)
                row["elapsed_s"] = round(elapsed, 3)
                if run_index == 0:
                    # Answers are generated only where they inform the decision: the composite
                    # questions, and only for the deployed cut and the proposed reservation.
                    if role in ("v", "generalization") and strategy in ("current", "fact"):
                        row["answer_facts"] = await answer_facts(chat_mdl, chunks, question, system_prompt, kb_prompt, max_tokens, flat)
                    if capture:
                        row["stage"] = localise(capture, facts, fact_evidence, score_of, chunk_key, flat)
                stats.append(row)
            entry["strategies"][strategy] = stats
            print(f"done {name}/{strategy}", file=sys.stderr)

        R.select_context = original_select
        report["questions"][name] = entry

    with open(f"/tmp/p2_{LABEL}.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)

    print(f"=== Phase 2 controlled comparison ({LABEL}) ===")
    hdr = f"{'q':18s} {'role':12s} {'f':2s} {'strategy':9s} {'life_cl':8s} {'struct_cl':9s} {'docs':5s} {'dup':4s} {'meanScore':9s} {'tok':6s} {'lat':7s}"
    print(hdr)
    print("-" * len(hdr))
    for name, e in report["questions"].items():
        for strategy in STRATEGIES:
            rows = [r for r in e["strategies"][strategy] if "error" not in r]
            if not rows:
                print(f"{name:18s} {e['role']:12s} {len(e['fact_types']):2d} {strategy:9s} ERROR")
                continue
            lc = [r["life_clause"] for r in rows]
            sc = [r["struct_clause"] for r in rows]
            docs = sorted({r["docs"] for r in rows})
            dup = sum(r["dups"] for r in rows)
            ms = round(st.mean([r["mean_score"] for r in rows]), 3)
            tok = sorted({r["tokens"] for r in rows})
            lat = round(st.median([r["elapsed_s"] for r in rows]), 2)
            print(f"{name:18s} {e['role']:12s} {len(e['fact_types']):2d} {strategy:9s} {str(lc):8s} {str(sc):9s} {str(docs):5s} {dup:4d} {ms:9.3f} {str(tok):6s} {lat:7.2f}")
    return 0


async def answer_facts(chat_mdl, chunks, question, system_prompt, kb_prompt, max_tokens, flat):
    if not chunks or not system_prompt:
        return None
    try:
        blocks = kb_prompt({"chunks": chunks}, max_tokens)
        ctx = "\n\n------\n\n".join(blocks)
        ans = await chat_mdl.async_chat(system_prompt.replace("{knowledge}", "\n------\n" + ctx), [{"role": "user", "content": question}])
        if isinstance(ans, tuple):
            ans = ans[0]
        text = flat(ans)
        return {
            "design_life_years": ("不少于30" in text) or ("30年" in text),
            "structure_drawings": "结构图纸" in text,
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def localise(capture, facts, fact_evidence, score_of, chunk_key, flat):
    """PART A: attribute every required evidence item to a stage."""
    ordered = capture.get("ordered") or []
    base = capture.get("base") or []
    selected = capture.get("selected") or []

    def best_evidence(pool, cue):
        hits = [c for c in pool if cue in flat(c.get("content_with_weight") or "")]
        if not hits:
            return None
        hits.sort(key=score_of, reverse=True)
        return hits[0]

    out: dict = {"pool_size": len(ordered), "pure_topn_size": len(base), "window_size": len(selected)}
    # A pure score-ordered cut, to separate "the reranker ranked it too low" from "the selection
    # dropped it".
    pure = {chunk_key(c) for c in ordered[: len(base)]}
    for label, cue in (("life_clause", LIFE_CLAUSE), ("structure_clause", STRUCT_CLAUSE)):
        pool_hit = best_evidence(ordered, cue)
        if pool_hit is None:
            out[label] = {"verdict": "RECALL_MISS", "detail": "no passage in the merged pool carries this clause"}
            continue
        key = chunk_key(pool_hit)
        rank = next((i + 1 for i, c in enumerate(ordered) if chunk_key(c) == key), None)
        in_window = any(chunk_key(c) == key for c in selected)
        if in_window:
            out[label] = {"verdict": "PRESENT", "rank": rank, "score": round(score_of(pool_hit), 4)}
        elif key in pure:
            out[label] = {
                "verdict": "CONTEXT_CUT_DROP",
                "rank": rank,
                "score": round(score_of(pool_hit), 4),
                "detail": "in the pool and inside a pure top-N cut, excluded by the selection",
            }
        else:
            out[label] = {
                "verdict": "RERANK_DROP",
                "rank": rank,
                "score": round(score_of(pool_hit), 4),
                "detail": "in the pool but ranked below the cut boundary by score",
            }
    out["per_fact"] = {
        f.key: {
            "pool_evidence": sum(1 for c in ordered if fact_evidence(c, f) > 0),
            "base_evidence": sum(1 for c in base if fact_evidence(c, f) > 0),
            "window_evidence": sum(1 for c in selected if fact_evidence(c, f) > 0),
        }
        for f in facts
    }
    return out


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
