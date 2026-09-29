"""A/C six-stage retrieval trace under the FROZEN controlled configuration (read-only).

Same configuration as the validated Query E baseline: all DEPLOYED_DEFAULT parameters, the
same KB, owner tenant, embedding model, deployed code and ES index. No query-specific
override anywhere in this file.

Stages, each instrumented through the deployed code:
  0 query representation (deployed tokenizer)
  1 lexical-only candidates  (weight 0.0)
  2 dense-only candidates    (weight 1.0)
  3 production-equivalent hybrid (weight 0.6)
  4 reranker                 (NOT ACTIVE when the deployed call passes no rerank model)
  5 rank adjustments         (deployed rag.retrieval.rerank helpers)
  6 final selected context   (deployed select_context, final_top_n=8)

Relevance grades are PROPOSED by cheap deterministic signals and labelled as such; the raw
body snippet is printed for every row so a human can overrule them.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys

sys.path.insert(0, "/ragflow")

KB = os.environ.get("TRACE_KB", "9463d93eb97511f1938f2592e9bc6fe4")
QUERIES = {
    "A": "根据 Q/GDW 73286.2-2026 查找单芯 220kV 海缆参数",
    "C": "220kV 三芯海底电缆结构参数",
}
STANDARD_NO = "Q/GDW 73286.2-2026"
WEIGHT, THRESHOLD, PAGE_SIZE = 0.6, 0.2, 50
NOT_ACTIVE = "NOT ACTIVE"


def part_of(chunk) -> str:
    name = str(chunk.get("docnm_kwd") or "")
    for marker in ("第1部分", "第2部分", "第3部分"):
        if marker in name:
            return marker
    return "other-document"


def blank_template(chunk) -> bool:
    from rag.nlp.retrieval_projection import blank_template_evidence

    return bool(blank_template_evidence(chunk))


def proposed_grade(chunk) -> int:
    """A PROPOSED grade from deterministic signals - a human overrules it from the snippet."""
    body = str(chunk.get("content_with_weight") or "")
    if part_of(chunk) == "other-document":
        return 0
    if blank_template(chunk):
        return 1
    if any(cue in body for cue in ("应不小于", "应不大于", "不应", "应符合", "不小于", "按表")):
        return 3
    if "标准参数值" in body or "对应1×" in body or "对应3×" in body:
        return 2
    return 1


def evidence_type(chunk) -> str:
    body = str(chunk.get("content_with_weight") or "")
    part = part_of(chunk)
    if part == "other-document":
        return "other_standard"
    if blank_template(chunk):
        return "blank_response_template"
    if "<table" in body or "标准参数值" in body or "对应1×" in body:
        return "parameter_table"
    if any(cue in body for cue in ("应不小于", "应不大于", "不应", "应符合")):
        return "normative_requirement"
    if str(chunk.get("doc_type_kwd") or "") == "text" and len(body) < 400:
        return "document_identity/context"
    return "other"


def row(rank, chunk) -> dict:
    body = str(chunk.get("content_with_weight") or "")
    return {
        "rank": rank,
        "id": str(chunk.get("chunk_id") or chunk.get("id") or "")[:16],
        "part": part_of(chunk),
        "grade": proposed_grade(chunk),
        "type": evidence_type(chunk),
        "score": round(float(chunk.get("similarity") or 0.0), 4),
        "snippet": " ".join(body.split())[:70],
    }


def distribution(rows) -> dict:
    counts = {"第1部分": 0, "第2部分": 0, "第3部分": 0, "other-document": 0}
    for item in rows:
        counts[item["part"]] = counts.get(item["part"], 0) + 1
    return counts


async def main() -> int:
    from common import settings

    settings.init_settings()
    from rag.nlp import rag_tokenizer
    from rag.nlp import search as rag_search
    from api.db.joint_services.tenant_model_service import resolve_model_config
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from api.db.services.llm_service import LLMBundle
    from common.constants import LLMType

    ok, kb = KnowledgebaseService.get_by_id(KB)
    if not ok:
        print(f"KB {KB} not found")
        return 1
    owner = str(getattr(kb, "tenant_id", "") or "")
    embd_mdl = LLMBundle(owner, resolve_model_config(owner, LLMType.EMBEDDING, kb.embd_id))
    dealer = rag_search.Dealer(settings.docStoreConn)
    accepted = set(inspect.signature(dealer.retrieval).parameters)
    kwargs = {key: value for key, value in (("knn_top_k", 1024), ("allow_dense_fallback", True)) if key in accepted}

    out: list[str] = []
    add = out.append
    add("# A/C stage trace under the frozen controlled configuration\n")
    add(f"* KB `{KB}` (owner tenant `{owner[:12]}…`), embedding `{getattr(kb, 'embd_id', None)}` via resolve_model_config -> LLMBundle")
    add(f"* params: threshold {THRESHOLD}, vector_weight {WEIGHT}, page_size {PAGE_SIZE} (Top 50), knn_top_k 1024, allow_dense_fallback True, keyword augmentation OFF")
    add("* reranker: NOT ACTIVE (these calls pass no rerank model, exactly as the deployed pipeline does by default)\n")

    rag_tokenizer.tokenizer.set_language("Chinese")
    probe_tokens = rag_tokenizer.tokenize(STANDARD_NO).split()
    add(f"## Standard-number probe `{STANDARD_NO}`\n")
    add(f"* query tokens: `{probe_tokens}`")

    for tag, question in QUERIES.items():
        qtokens = rag_tokenizer.tokenize(question).split()
        add(f"\n## Query {tag}: `{question}`\n")
        add(f"* query tokens ({len(qtokens)}): `{qtokens[:30]}`")

        legs = {}
        for label, weight in (("lexical", 0.0), ("dense", 1.0), ("hybrid", WEIGHT)):
            try:
                result = await dealer.retrieval(question, embd_mdl, [owner], [KB], 1, PAGE_SIZE, THRESHOLD, weight, **kwargs)
                legs[label] = [row(rank, chunk) for rank, chunk in enumerate(result.get("chunks") or [], 1)]
            except Exception as exc:  # noqa: BLE001
                add(f"* {label} leg FAILED: {type(exc).__name__}: {exc}")
                legs[label] = []

        for label in ("lexical", "dense", "hybrid"):
            rows = legs[label]
            add(f"\n### Stage {label} Top 50 -> family distribution {distribution(rows)}")
            for limit, name in ((5, "Top5"), (10, "Top10"), (50, "Top50")):
                counts = distribution(rows[:limit])
                add(f"  * {name}: Part2={counts['第2部分']} Part3={counts['第3部分']} Part1={counts['第1部分']} other={counts['other-document']}")
            best = next((item for item in rows if item["part"] == ("第2部分" if tag == "A" else "第3部分")), None)
            add(f"  * highest-ranked {'Part 2' if tag == 'A' else 'Part 3'} chunk: {best['id'] if best else 'ABSENT FROM TOP 50'} (rank {best['rank'] if best else '-'}, score {best['score'] if best else '-'})")

        add("\n### Stage 3 Top 10 detail (hybrid, production-equivalent)")
        add("| rank | chunk | part | score | grade | type | snippet |")
        add("|---|---|---|---|---|---|---|")
        for item in legs["hybrid"][:10]:
            add(f"| {item['rank']} | {item['id']} | {item['part']} | {item['score']} | {item['grade']} | {item['type']} | {item['snippet']} |")

        # Stages 5 and 6 through the deployed helpers, on the hybrid candidate pool.
        try:
            from rag.retrieval import rerank as deployed_rerank

            pool = [dict(chunk) for chunk in (await dealer.retrieval(question, embd_mdl, [owner], [KB], 1, PAGE_SIZE, THRESHOLD, WEIGHT, **kwargs)).get("chunks", [])]
            policy = deployed_rerank.DiversityPolicy.for_question(question, pool)
            ordered = deployed_rerank.apply_rank_adjustments(pool, policy)
            selected = deployed_rerank.select_context(ordered, 8, policy)
            add("\n### Stage 5 rank adjustments -> Stage 6 select_context (window 8)")
            add(f"* pool {len(pool)} -> adjusted order top5: {[str(c.get('chunk_id'))[:12] for c in ordered[:5]]}")
            add(f"* selected {len(selected)}: {[str(c.get('chunk_id'))[:12] for c in selected]}")
            add(f"* selected family distribution: {distribution([row(rank, c) for rank, c in enumerate(selected, 1)])}")
            moved = []
            before = {item["id"]: item["rank"] for item in legs["hybrid"]}
            for rank, chunk in enumerate(ordered, 1):
                cid = str(chunk.get("chunk_id") or "")[:16]
                if cid in before and before[cid] != rank:
                    moved.append(f"{cid}: {before[cid]} -> {rank}")
            add(f"* candidates whose rank changed at stage 5: {moved or 'none'}")
            add(f"* blank templates inside the selected context: {sum(1 for c in selected if blank_template(c))}")
        except Exception as exc:  # noqa: BLE001
            add(f"* stages 5/6 FAILED: {type(exc).__name__}: {exc}")

    path = "/tmp/ac_trace.md"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(out) + "\n")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
