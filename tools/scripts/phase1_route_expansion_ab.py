"""Phase 1 controlled validation: deterministic supplemental routes (READ-ONLY, no deploy).

The deployed image does not contain the Phase-1 rule, so the change cannot be exercised by simply
calling the entry point. It is exercised instead by pinning the LLM channel: the deployed pipeline
asks ``decompose_question`` for sub-queries, and this harness supplies that channel with a stub
whose answer is FIXED. Before and after then differ by exactly one thing - whether the
deterministic supplemental routes are present - which is what a controlled design comparison needs.

Modes, per query:

    PRODUCTION_ASIS  the real chat model, exactly as production runs today (documents the status quo)
    CTRL_BEFORE      stub = the frozen LLM route set only
    CTRL_AFTER       stub = the same frozen LLM route set PLUS the deterministic supplemental routes
    AFTER_NO_LLM     stub = no LLM routes at all, supplemental routes only (LLM channel dead)

``max_sub_queries`` is raised to the route budget in EVERY controlled mode, so the sub-query cap is
never the variable being measured; PRODUCTION_ASIS keeps the deployed default.

Nothing is written and no production file is touched.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, "/ragflow")
# The Phase-1 rule itself, delivered as a control-path module (NOT deployed).
sys.path.insert(0, "/tmp/p1")
sys.path.insert(0, "/tmp")

KB_ID = "9463d93eb97511f1938f2592e9bc6fe4"
DIALOG_ID = "5c8c249eb8e411f180e20bf412cbc55e"
LABEL = os.environ.get("P1_LABEL", "run")
RUNS = int(os.environ.get("P1_RUNS", "3"))
#: Optional filters so a correction can be re-measured without repeating the whole matrix.
ONLY_QUERIES = [x for x in os.environ.get("P1_ONLY", "").split(",") if x]
ONLY_MODES = [x for x in os.environ.get("P1_MODES", "").split(",") if x]
JSON_OUT = f"/tmp/p1_{LABEL}.json"
ROUTE_BUDGET = 16

_TAG_RE = re.compile(r"<[^>]{0,300}?>")

#: The two LLM outputs this question was OBSERVED to produce on this build. The 2-route form is the
#: one that loses the design life; the 4-route form is the one that finds it.
LLM_ROUTES_2 = (
    "标准对电缆附件（终端与接头）的设计使用寿命有何要求",
    "标准对电缆附件（终端与接头）的结构有何要求",
)
LLM_ROUTES_4 = (
    "标准对电缆附件接头的结构有何要求？",
    "标准对电缆附件接头的设计使用寿命有何要求？",
    "标准对电缆附件终端的结构有何要求？",
    "标准对电缆附件终端的设计使用寿命有何要求？",
)

QA004 = "标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求"
QA004_LIFE = "标准对电缆附件终端和接头的设计使用寿命有何要求"

CONTROLS: tuple[tuple[str, str], ...] = (
    ("QA004_exact", QA004),
    ("QA004_narrow_life", QA004_LIFE),
    ("QA001", "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"),
    ("QA002", "Q/GDW 73285-2026 标准体系由哪些部分构成？各自适用范围是什么？"),
    ("QA003", "2026版标准相比2019旧版标准，主要进行了哪些重要修订？"),
    ("QA005", "110kV海缆系统的耐压试验系统（出厂与安装后）是如何规定的？".replace("试验系统", "试验标准")),
)

LIFE_NEEDLES = ("设计使用年限", "不少于30")
STRUCT_NEEDLES = ("结构图纸",)
STRUCT_TOPIC = ("户外终端", "gis终端", "油浸终端", "预制直通接头", "绝缘接头")


def flat(text: str) -> str:
    return re.sub(r"\s+", "", _TAG_RE.sub("|", str(text or "")).lower().replace("×", "x"))


def halves(chunk: dict) -> tuple[bool, bool]:
    t = flat(chunk.get("content_with_weight") or "")
    return any(n in t for n in LIFE_NEEDLES), any(n in t for n in STRUCT_NEEDLES)


def facts(text: str) -> dict:
    t = flat(text)
    return {
        "design_life_years": ("不少于30" in t) or ("30年" in t),
        "structure_drawings": "结构图纸" in t,
        "structure_topics": sum(1 for n in STRUCT_TOPIC if n in t),
    }


class StubChat:
    """A chat model that returns a FIXED decomposition payload.

    ``gen_json`` needs ``llm_name`` (cache key), ``max_length``, and an async ``async_chat`` whose
    first argument is the system prompt. The name is deliberately unique per mode so the real LLM
    cache can neither serve nor be polluted by these calls.
    """

    def __init__(self, name: str, routes):
        self.llm_name = name
        self.max_length = 8192
        self._routes = list(routes)

    async def async_chat(self, system_prompt, messages, gen_conf=None, **kwargs):  # noqa: ARG002
        return json.dumps({"sub_queries": self._routes}, ensure_ascii=False)


async def main() -> int:
    from common import settings

    settings.init_settings()
    from rag.nlp import rag_tokenizer
    from rag.retrieval import retrieve_multi_route
    from rag.retrieval.decomposition import decompose_question
    from rag.retrieval.rerank import resolve_final_top_n
    try:
        # Working tree / a future image: the rule lives in the package.
        from rag.retrieval.route_expansion import supplemental_routes
    except ModuleNotFoundError:
        # Today's image does not contain the Phase-1 rule, so it is supplied as a control-path
        # module on /tmp/p1. Same file, byte-identical, imported against the DEPLOYED rag tree.
        from route_expansion import supplemental_routes
    from api.db.db_models import Dialog
    from api.db.joint_services.tenant_model_service import get_tenant_default_model_by_type, resolve_model_config
    from api.db.services.dialog_service import resolve_rerank_mdl
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from api.db.services.llm_service import LLMBundle
    from api.db import cable_defaults
    from common.constants import LLMType

    rag_tokenizer.tokenizer.set_language("Chinese")
    ok, kb = KnowledgebaseService.get_by_id(KB_ID)
    tenant = str(kb.tenant_id)
    dialog = Dialog.get_or_none(Dialog.id == DIALOG_ID)
    embd_mdl = LLMBundle(tenant, resolve_model_config(tenant, LLMType.EMBEDDING, kb.embd_id))
    rerank_mdl = resolve_rerank_mdl(tenant, dialog.rerank_id or "", dialog.tenant_rerank_id)
    real_chat = LLMBundle(tenant, get_tenant_default_model_by_type(tenant, LLMType.CHAT))
    retriever = settings.retriever
    prompt_config = dialog.prompt_config or {}
    system_prompt = str(prompt_config.get("system") or getattr(cable_defaults, "SYSTEM_PROMPT", "") or "")
    max_tokens = (get_tenant_default_model_by_type(tenant, LLMType.CHAT) or {}).get("max_tokens") or 8192
    slo = {
        "similarity_threshold": float(dialog.similarity_threshold),
        "vector_similarity_weight": float(dialog.vector_similarity_weight),
        "final_top_n": resolve_final_top_n(dialog.top_n),
        "knn_top_k": int(dialog.top_k),
        "rerank_candidates_count": int(getattr(dialog, "rerank_candidates_count", 30) or 30),
    }

    report: dict = {
        "label": LABEL,
        "runs_per_mode": RUNS,
        "parameters": slo,
        "route_budget": ROUTE_BUDGET,
        "expansion_audit": {},
        "queries": {},
    }

    # ---- the rule's decision per query, computed once, in-process ------------------------
    for name, question in CONTROLS:
        added, trace = supplemental_routes(question, existing_routes=(), budget=ROUTE_BUDGET)
        report["expansion_audit"][name] = {
            "entities": trace.get("entities"),
            "fact_types": trace.get("fact_types"),
            "profile": trace.get("profile"),
            "reason": trace.get("reason"),
            "added": added,
        }

    async def one_call(question, chat_mdl, max_sub_queries):
        t0 = time.perf_counter()
        result = await retrieve_multi_route(
            retriever=retriever,
            question=question,
            chat_mdl=chat_mdl,
            embd_mdl=embd_mdl,
            rerank_mdl=rerank_mdl,
            tenant_ids=[tenant],
            kb_ids=[KB_ID],
            max_sub_queries=max_sub_queries,
            **slo,
        )
        elapsed = time.perf_counter() - t0
        chunks = list(result.get("chunks") or [])
        ids = [str(c.get("chunk_id") or "") for c in chunks]
        life = [c for c in chunks if halves(c)[0]]
        struct = [c for c in chunks if halves(c)[1]]
        routes = sorted({r for c in chunks for r in (c.get("retrieval_routes") or [])})
        return {
            "elapsed_s": round(elapsed, 3),
            "returned": len(chunks),
            "total": result.get("total"),
            "ids": [i[:16] for i in ids],
            "design_life": len(life),
            "structure": len(struct),
            "both_halves": bool(life) and bool(struct),
            "duplicate_chunks": len(ids) - len(set(ids)),
            "distinct_documents": len({str(c.get("doc_id") or "") for c in chunks}),
            "context_chars": sum(len(str(c.get("content_with_weight") or "")) for c in chunks),
            "routes_in_window": routes,
            "route_count_in_window": len(routes),
        }, chunks

    async def answer_from(chunks, question):
        if not chunks:
            return None, None
        from rag.prompts.generator import kb_prompt

        blocks = kb_prompt({"chunks": chunks}, max_tokens)
        ctx = "\n\n------\n\n".join(blocks)
        try:
            ans = await real_chat.async_chat(system_prompt.replace("{knowledge}", "\n------\n" + ctx), [{"role": "user", "content": question}])
            if isinstance(ans, tuple):
                ans = ans[0]
            ans = str(ans)
        except Exception as exc:  # noqa: BLE001
            return None, f"{type(exc).__name__}: {exc}"
        return ans, None

    for name, question in CONTROLS:
        if ONLY_QUERIES and name not in ONLY_QUERIES:
            continue
        entry: dict = {"question": question, "modes": {}}
        # frozen LLM route sets
        asis_routes = await decompose_question(real_chat, question, 4)
        if name == "QA004_exact":
            sets = {
                "CTRL_BEFORE": list(LLM_ROUTES_2),
                "CTRL_AFTER": list(LLM_ROUTES_2),
                "CTRL_AFTER_llm4": list(LLM_ROUTES_4),
                "CTRL_BEFORE_llm4": list(LLM_ROUTES_4),
                "AFTER_NO_LLM": [],
            }
        else:
            sets = {"CTRL_BEFORE": list(asis_routes), "CTRL_AFTER": list(asis_routes)}
        entry["llm_routes_observed_asis"] = list(asis_routes)
        entry["llm_route_count_asis"] = len(asis_routes)

        for mode, base in sets.items():
            if ONLY_MODES and mode not in ONLY_MODES:
                continue
            added, trace = supplemental_routes(question, existing_routes=base, budget=ROUTE_BUDGET)
            # A supplemental-route mode is any mode whose point is to ADD them. Keying this off
            # `CTRL_AFTER` alone silently gave AFTER_NO_LLM an empty supplemental set, so that mode
            # measured "no routes at all" instead of "supplemental routes alone".
            wants_supplemental = mode.startswith("CTRL_AFTER") or mode.startswith("AFTER")
            payload = list(base) + (added if wants_supplemental else [])
            mode_entry: dict = {
                "llm_routes": list(base),
                "supplemental_routes": added if wants_supplemental else [],
                "merged_route_set": payload,
                "expansion": trace,
                "runs": [],
            }
            stub = StubChat(f"phase1-{LABEL}-{name}-{mode}", payload)
            for run_index in range(RUNS):
                try:
                    stats, chunks = await one_call(question, stub, ROUTE_BUDGET)
                    # Answer only the first run of each mode: the retrieval statistics are what need
                    # repetition, and every extra answer is a full generation round trip.
                    if run_index == 0:
                        ans, err = await answer_from(chunks, question)
                        stats["answer_error"] = err
                        stats["answer_facts"] = facts(ans or "")
                        stats["answer_text"] = (ans or "")[:4000]
                        stats["answer_sha"] = hashlib.sha256((ans or "").encode()).hexdigest()[:12]
                    mode_entry["runs"].append(stats)
                except Exception as exc:  # noqa: BLE001
                    mode_entry["runs"].append({"error": f"{type(exc).__name__}: {exc}"})
            entry["modes"][mode] = mode_entry

        # status quo, untouched, with the real model and the deployed default cap
        asis: dict = {"runs": []}
        for run_index in range(RUNS):
            try:
                stats, chunks = await one_call(question, real_chat, 4)
                if run_index == 0:
                    ans, err = await answer_from(chunks, question)
                    stats["answer_error"] = err
                    stats["answer_facts"] = facts(ans or "")
                asis["runs"].append(stats)
            except Exception as exc:  # noqa: BLE001
                asis["runs"].append({"error": f"{type(exc).__name__}: {exc}"})
        entry["modes"]["PRODUCTION_ASIS"] = asis
        report["queries"][name] = entry
        print(f"done {name}", file=sys.stderr)

    with open(JSON_OUT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)

    print(f"=== Phase 1 controlled A/B ({LABEL}) ===")
    for name, e in report["queries"].items():
        a = report["expansion_audit"][name]
        print(f"\n-- {name}: entities={a['entities']} fact_types={a['fact_types']} profile={a['profile']} reason={a['reason']}")
        if a["added"]:
            print(f"   supplemental routes: {a['added']}")
        print(f"   LLM routes as-is ({e['llm_route_count_asis']}): {e['llm_routes_observed_asis']}")
        for mode, m in e["modes"].items():
            ok_runs = [r for r in m["runs"] if "error" not in r]
            if not ok_runs:
                print(f"   {mode:16s} ALL ERRORS: {m['runs'][0].get('error')}")
                continue
            life = [r["design_life"] for r in ok_runs]
            both = sum(1 for r in ok_runs if r["both_halves"])
            lat = [r["elapsed_s"] for r in ok_runs]
            rc = [r["route_count_in_window"] for r in ok_runs]
            dup = [r["duplicate_chunks"] for r in ok_runs]
            doc = [r["distinct_documents"] for r in ok_runs]
            af = [r.get("answer_facts") for r in ok_runs if r.get("answer_facts")]
            # PRODUCTION_ASIS has no fixed route set to report; it ran the real decomposition.
            mr = len(m["merged_route_set"]) if "merged_route_set" in m else "asis"
            print(f"   {mode:16s} routes_used={mr} life={life} both={both}/{len(ok_runs)} "
                  f"lat={lat} window_routes={rc} dup={dup} docs={doc}")
            print(f"   {'':16s} answer_facts={af}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
