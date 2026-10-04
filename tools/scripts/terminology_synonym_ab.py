"""Terminology synonym coverage - before/after A/B on the DEPLOYED retrieval path (READ-ONLY).

Runs a fixed query set through the deployed ``retrieve_multi_route`` with the assistant's own
parameters, and reports per query: the passages returned, how many carry the design-life clause,
how many carry the structure clause, and the raw keyword list the deployed tokenizer produced.

It changes nothing itself. The synonym table is toggled OUTSIDE this script through the channel
the deployed loader already reads (Redis ``kevin_synonyms``), which is how Phase 0 is verified
without rebuilding the image:

    before : redis has no kevin_synonyms  -> dictionary empty (today's behaviour)
    after  : redis has kevin_synonyms     -> same JSON as rag/res/synonym.json

Run inside the container (docker cp, never stdin - the container decodes stdin as GBK):

    docker cp tools/scripts/terminology_synonym_ab.py wenruo-rag-cpu:/tmp/
    docker exec wenruo-rag-cpu sh -c "cd /ragflow && SYN_LABEL=before python /tmp/terminology_synonym_ab.py > /tmp/ab_before.json 2>/dev/null"
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys

sys.path.insert(0, "/ragflow")

KB_ID = "9463d93eb97511f1938f2592e9bc6fe4"
DIALOG_ID = "5c8c249eb8e411f180e20bf412cbc55e"
LABEL = os.environ.get("SYN_LABEL", "run")
JSON_OUT = os.environ.get("SYN_OUT", f"/tmp/terminology_ab_{LABEL}.json")

_TAG_RE = re.compile(r"<[^>]{0,300}?>")

#: Queries the mapping SHOULD change, and queries it must NOT disturb.
QUERIES: tuple[tuple[str, str, str], ...] = (
    # --- target: the QA-004 question and its already-working twin -------------------------
    ("QA004_user_term", "标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求", "target"),
    ("QA004_std_term", "标准对电缆附件（终端与接头）的设计使用年限与结构有何要求", "target-control"),
    ("QA004_life_only", "标准对电缆附件终端和接头的设计使用寿命有何要求", "target"),
    ("QA004_struct_only", "标准对电缆附件终端和接头的结构图纸资料有什么要求", "target-control"),
    # --- regression controls: the other frozen benchmark questions ------------------------
    ("QA001", "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？", "control"),
    ("QA002", "Q/GDW 73285-2026 标准体系由哪些部分构成？各自适用范围是什么？", "control"),
    ("QA003", "2026版标准相比2019旧版标准，主要进行了哪些重要修订？", "control"),
    ("QA005", "110kV海缆系统的耐压试验标准（出厂与安装后）是如何规定的？", "control"),
    # --- mapping-specific probes ----------------------------------------------------------
    ("MAP_seacable", "海缆的铅套厚度有什么要求", "probe"),
    ("MAP_xlpe", "XLPE绝缘海底电缆的导体屏蔽有什么要求", "probe"),
    ("MAP_connector", "电缆接头的结构图纸有哪些要求", "probe"),
    # --- must be untouched: no mapped key occurs in these ---------------------------------
    ("UNC_armour", "220kV海底电力电缆的铠装层有什么要求", "control"),
    ("UNC_pumping", "抽水蓄能电站工程500kV电力电缆的采购要求", "control"),
    ("UNC_numeric", "110kV海缆出厂耐压试验的电压和持续时间是多少", "control"),
)


def flat(text: str) -> str:
    return re.sub(r"\s+", "", _TAG_RE.sub("|", str(text or "")).lower().replace("×", "x"))


def halves(chunk: dict) -> tuple[bool, bool]:
    text = flat(chunk.get("content_with_weight") or "")
    return ("设计使用年限" in text or "不少于30" in text), ("结构图纸" in text)


async def main() -> int:
    from common import settings

    settings.init_settings()
    from rag.nlp import rag_tokenizer
    from rag.retrieval import retrieve_multi_route
    from rag.retrieval.rerank import resolve_final_top_n
    from api.db.db_models import Dialog
    from api.db.joint_services.tenant_model_service import resolve_model_config
    from api.db.services.dialog_service import resolve_rerank_mdl
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from api.db.services.llm_service import LLMBundle
    from common.constants import LLMType

    rag_tokenizer.tokenizer.set_language("Chinese")
    ok, kb = KnowledgebaseService.get_by_id(KB_ID)
    tenant = str(kb.tenant_id)
    dialog = Dialog.get_or_none(Dialog.id == DIALOG_ID)
    embd_mdl = LLMBundle(tenant, resolve_model_config(tenant, LLMType.EMBEDDING, kb.embd_id))
    # The deployed path reranks with the workspace default (the assistant binds none).
    rerank_mdl = resolve_rerank_mdl(tenant, dialog.rerank_id or "", dialog.tenant_rerank_id)
    retriever = settings.retriever
    params = {
        "similarity_threshold": float(dialog.similarity_threshold),
        "vector_similarity_weight": float(dialog.vector_similarity_weight),
        "final_top_n": resolve_final_top_n(dialog.top_n),
        "knn_top_k": int(dialog.top_k),
        "rerank_candidates_count": int(getattr(dialog, "rerank_candidates_count", 30) or 30),
    }

    # ---- prove which synonym state this run actually ran with ---------------------------
    syn = retriever.qryr.syn
    probes = {}
    for key in ("设计使用寿命", "使用寿命", "电缆接头", "海缆", "海底电缆", "xlpe", "寿命", "年限"):
        probes[key] = syn.lookup(key)
    state = {
        "label": LABEL,
        "dictionary_size": len(syn.dictionary or {}),
        "dictionary_keys": list((syn.dictionary or {}).keys()),
        "redis_attached": syn.redis is not None,
        "lookups": probes,
    }

    report: dict = {"state": state, "parameters": params, "queries": {}}
    for name, question, role in QUERIES:
        entry: dict = {"question": question, "role": role}
        try:
            _expr, keywords = retriever.qryr.question(question)
            entry["keywords"] = list(keywords or [])
            result = await retrieve_multi_route(
                retriever=retriever,
                question=question,
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
            chunks = list(result.get("chunks") or [])
            life = [c for c in chunks if halves(c)[0]]
            struct = [c for c in chunks if halves(c)[1]]
            entry.update(
                {
                    "returned": len(chunks),
                    "total": result.get("total"),
                    "design_life": len(life),
                    "structure": len(struct),
                    "ids": [str(c.get("chunk_id") or "")[:16] for c in chunks],
                    "life_ids": [str(c.get("chunk_id") or "")[:16] for c in life],
                    "structure_ids": [str(c.get("chunk_id") or "")[:16] for c in struct],
                    "context_chars": sum(len(str(c.get("content_with_weight") or "")) for c in chunks),
                }
            )
        except Exception as exc:  # noqa: BLE001 - a probe reports, it does not hide
            entry["error"] = f"{type(exc).__name__}: {exc}"
        report["queries"][name] = entry

    with open(JSON_OUT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)

    print(f"=== synonym state ({LABEL}) ===")
    print(f"  dictionary_size={state['dictionary_size']} redis={state['redis_attached']}")
    for k, v in probes.items():
        print(f"    lookup {k} -> {v}")
    print(f"=== queries ({LABEL}) ===")
    for name, e in report["queries"].items():
        if "error" in e:
            print(f"  {name:18s} [{e['role']:14s}] ERROR {e['error']}")
            continue
        print(f"  {name:18s} [{e['role']:14s}] n={e['returned']:2d} life={e['design_life']} struct={e['structure']} chars={e['context_chars']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
