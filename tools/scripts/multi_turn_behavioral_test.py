"""Multi-turn behavioural baseline (TEST ONLY - nothing is changed, tuned or fixed).

TEST TIER, declared because no assistant in the live index is bound to the canary knowledge
base (the owner assistant's `kb_ids` is empty), so a real Assistant end-to-end environment does
not exist for this KB:

    TIER = RETRIEVAL (deployed retrieve_multi_route) + LLM SYNTHESIS (tenant chat model)
           WITHOUT assistant configuration

Two consequences are recorded rather than hidden:
  * there is no assistant prompt/prologue/`refine_multiturn`, so the app-level "effective query"
    rewriting is NOT OBSERVABLE here and the multi-turn history is maintained by this harness;
  * `keyword` augmentation is OFF (it is an assistant setting), which is the frozen controlled
    configuration.

Configuration is the frozen one and is identical in every turn: threshold 0.2, vector weight 0.6,
routes_top_k 12, final_top_n 8, knn_top_k 1024, allow_dense_fallback True.

Labels are EXPLORATORY_JUDGMENT produced by deterministic heuristics over the observed answer and
context; they are explicitly NOT a Gold Set and every row says so.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import pathlib
import re
import sys

sys.path.insert(0, "/ragflow")

KB = "9463d93eb97511f1938f2592e9bc6fe4"
SESSIONS = {
    "A": {
        "target_parts": ["第2部分", "第1部分"],
        "turns": [
            "Q/GDW 73286.2-2026 是什么标准？",
            "这个标准适用于什么类型的电缆？",
            "那 220kV 单芯海底电缆的主要结构有哪些？",
            "导体、内衬层和铠装层分别有什么技术要求？",
            "这些要求都是这个专用技术规范自己规定的吗？",
            "如果不是，把通用技术规范里的要求也一起告诉我，并说明来源。",
        ],
    },
    "B": {
        "target_parts": ["第3部分", "第1部分"],
        "turns": [
            "220kV 三芯海底电缆一般有哪些主要结构？",
            "铠装层有什么要求？",
            "内衬层厚度呢？",
            "这个数值是在哪份规范里规定的？",
            "三芯专用规范里面没有吗？",
            "那你把专用规范和通用规范的要求区分开告诉我。",
        ],
    },
    "C": {
        "target_parts": ["第2部分", "第3部分", "第1部分"],
        "turns": [
            "220kV 单芯和三芯海底电缆的技术要求有什么区别？",
            "先只比较结构方面。",
            "哪些要求是它们共同的？",
            "哪些是单芯或三芯专用规范单独规定的？",
            "不要把投标人填写的空白参数表当成已经规定的参数。",
            "重新总结一次，并标明每条来自通用规范、单芯专用规范还是三芯专用规范。",
        ],
    },
}
CONTROL = [
    "220kV 单芯海底电缆的导体、内衬层、铠装层技术要求是什么？",
    "220kV 三芯海底电缆的内衬层厚度要求是什么？",
    "Q/GDW 73286 的通用规范与单芯/三芯专用规范分别规定什么？",
]
REFUSAL_MARKERS = ("未找到", "无法", "暂未", "没有找到", "未查到", "抱歉")
NOT_OBSERVABLE = "NOT_OBSERVABLE"
PARAMS = {"similarity_threshold": 0.2, "vector_similarity_weight": 0.6, "routes_top_k": 12, "final_top_n": 8, "knn_top_k": 1024, "max_sub_queries": 4, "allow_dense_fallback": True}


def part_of(name: str) -> str:
    for marker in ("第1部分", "第2部分", "第3部分"):
        if marker in name:
            return marker
    return "other-document"


def numbers(text: str) -> set:
    return {value for value in re.findall(r"\d+(?:\.\d+)?", str(text or "")) if len(value) >= 2}


def label(answer: str, context_parts: list, target_parts: list, previous_topic_terms: set) -> dict:
    """EXPLORATORY_JUDGMENT by deterministic heuristic - not a Gold Set, and labelled as such."""
    answer = str(answer or "")
    context_numbers = set()
    for part in context_parts:
        context_numbers |= numbers(part["text"])
    target_seen = [part for part in target_parts if part in context_parts[-1]["parts"]]
    fabricated = sorted(numbers(answer) - context_numbers - {"220", "73286"})
    return {
        "document_selection": "PASS" if target_seen else "FAIL",
        "answer_groundedness": "PASS" if (numbers(answer) & context_numbers) else ("UNCERTAIN" if answer.strip() else "FAIL"),
        "cross_document_behavior": ("PASS" if len(set(target_parts) & set(context_parts[-1]["parts"])) > 1 else "FAIL") if len(target_parts) > 1 and any("通用" in str(t) or "专用" in str(t) or "来源" in str(t) or "区分" in str(t) or "规定" in str(t) or "共同" in str(t) for t in [answer]) else "NOT_NEEDED",
        "conversation_continuity": "PASS" if (previous_topic_terms & numbers(answer) or previous_topic_terms & set(answer.split())) else "UNCERTAIN",
        "refusal": "UNNECESSARY" if any(marker in answer for marker in REFUSAL_MARKERS) else "NONE",
        "hallucination_suspicion": "YES" if fabricated else ("NO" if answer.strip() else "UNCERTAIN"),
        "fabricated_numbers": fabricated[:6] if fabricated else NOT_OBSERVABLE,
        "_provenance": "EXPLORATORY_JUDGMENT (deterministic heuristic; not a Gold Set)",
    }


async def main() -> int:
    from common import settings

    settings.init_settings()
    from rag.nlp import search as rag_search
    from rag.retrieval import retrieve_multi_route
    from api.db.joint_services.tenant_model_service import resolve_model_config
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from api.db.services.llm_service import LLMBundle
    from common.constants import LLMType
    from api.db import cable_defaults

    ok, kb = KnowledgebaseService.get_by_id(KB)
    if not ok:
        print(json.dumps({"error": "KB not found"}))
        return 1
    owner = str(getattr(kb, "tenant_id", "") or "")
    embd_mdl = LLMBundle(owner, resolve_model_config(owner, LLMType.EMBEDDING, kb.embd_id))
    chat_config = resolve_model_config(owner, LLMType.CHAT, None) if "model_ref" not in inspect.signature(resolve_model_config).parameters else None
    try:
        chat_mdl = LLMBundle(owner, resolve_model_config(owner, LLMType.CHAT, getattr(kb, "llm_id", None) or None))
    except Exception:  # noqa: BLE001 - the synthesis layer is optional at this tier
        chat_mdl = None
    dealer = rag_search.Dealer(settings.docStoreConn)
    accepted = set(inspect.signature(dealer.retrieval).parameters)
    params = {key: value for key, value in PARAMS.items() if key in inspect.signature(retrieve_multi_route).parameters}

    system_prompt = str(getattr(cable_defaults, "SYSTEM_PROMPT", "")) or "你是线缆行业标准助手，只依据给定资料回答。"

    report: dict = {
        "tier": "RETRIEVAL (deployed retrieve_multi_route) + LLM SYNTHESIS (tenant chat model) WITHOUT assistant configuration",
        "tier_caveats": ["no assistant prompt/prologue/refine_multiturn -> app-level effective query NOT OBSERVABLE", "keyword augmentation OFF (assistant setting)", "multi-turn history maintained by the harness"],
        "configuration": PARAMS,
        "kb_id": KB,
        "owner_tenant": owner,
        "embedding_model_id": getattr(kb, "embd_id", None),
        "sessions": {},
        "control": [],
    }

    async def one_turn(question: str, history: list, target_parts: list, previous_terms: set) -> dict:
        row: dict = {"user_query": question, "context_turns": len(history)}
        try:
            kbinfos = await retrieve_multi_route(retriever=dealer, question=question, tenant_ids=[owner], kb_ids=[KB], chat_mdl=chat_mdl, embd_mdl=embd_mdl, **params)
            chunks = kbinfos.get("chunks") or []
            row["retrieved_chunk_ids"] = [str(chunk.get("chunk_id") or "")[:16] for chunk in chunks]
            row["retrieved_documents"] = [str(chunk.get("docnm_kwd") or "")[:40] for chunk in chunks]
            row["retrieved_sections"] = [str(chunk.get("content_with_weight") or "").split("| 章节: ")[-1].split("]")[0].strip()[:24] if "| 章节: " in str(chunk.get("content_with_weight") or "") else NOT_OBSERVABLE for chunk in chunks]
            row["retrieved_parts"] = [part_of(str(chunk.get("docnm_kwd") or "")) for chunk in chunks]
            contexts = [{"text": str(chunk.get("content_with_weight") or ""), "parts": row["retrieved_parts"]} for chunk in chunks]
            row["final_context_chars"] = sum(len(item["text"]) for item in contexts)
            row["effective_query"] = question + "   [NOT_OBSERVABLE at app level; harness passes the raw question]"
        except Exception as exc:  # noqa: BLE001
            row["retrieval_error"] = f"{type(exc).__name__}: {exc}"
            contexts = []
        if chat_mdl is not None and contexts:
            knowledge = "\n\n------\n\n".join(item["text"] for item in contexts)[:12000]
            messages = [*history, {"role": "user", "content": question}]
            try:
                answer = await chat_mdl.async_chat(system_prompt.replace("{knowledge}", knowledge), messages)
                if isinstance(answer, tuple):
                    answer = answer[0]
                row["model_answer"] = str(answer)
            except Exception as exc:  # noqa: BLE001
                row["model_answer"] = f"NOT_OBSERVABLE ({type(exc).__name__}: {exc})"
        else:
            row["model_answer"] = NOT_OBSERVABLE
        row["labels"] = label(row.get("model_answer", ""), contexts, target_parts, previous_terms)
        return row

    for tag, spec in SESSIONS.items():
        history: list = []
        rows = []
        previous_terms: set = set()
        for index, question in enumerate(spec["turns"], 1):
            row = await one_turn(question, history, spec["target_parts"], previous_terms)
            row["round"] = index
            rows.append(row)
            if row.get("model_answer") and not str(row["model_answer"]).startswith("NOT_OBSERVABLE"):
                history = [*history, {"role": "user", "content": question}, {"role": "assistant", "content": str(row["model_answer"])[:1500]}]
            previous_terms |= numbers(question)
        report["sessions"][f"session_{tag}"] = {"target_parts": spec["target_parts"], "turns": rows}

    for question in CONTROL:
        row = await one_turn(question, [], ["第1部分", "第2部分", "第3部分"], set())
        row["round"] = 1
        report["control"].append({"user_query": question, **row})

    pathlib.Path("/tmp/multi_turn.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("BEHAVIOURAL_JSON_BEGIN")
    print(json.dumps(report, ensure_ascii=False))
    print("BEHAVIOURAL_JSON_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
