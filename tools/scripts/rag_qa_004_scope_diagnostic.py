"""QA-004 instability diagnostic (READ-ONLY): which layer is unstable?

Question under investigation:

    标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求

Two runs of it were observed to answer differently (one kept the 30-year design life, the other
returned detailed structure instead and lost the design life). This script measures each layer
that could produce that, one at a time, using the deployed code and no changes to it:

P1 embedding determinism        - same question embedded N times, compare vectors
P2 decomposition stability      - same question -> route list, N times (the deployed pipeline asks
                                  the chat model for sub-queries; the routes ARE delegated)
P3 retrieval stability          - N full production calls, compare window id-sets, order, and how
                                  many "design life" vs "structure" passages each window holds
P4 rerank determinism           - one fixed set of 12 passages re-scored N times
P5 controlled scope variants    - the question under original / 110kV / 220kV / design-life-only /
                                  structure-only phrasings, N times each
P6 generation stability         - the SAME frozen context answered N times (isolates text
                                  generation from everything above)

Nothing is written to any index or row, no parameter is changed, no model is swapped, and no
production file is touched. Run it the same way as the baseline tool (docker cp; do NOT pipe the
source over stdin - the container decodes stdin as GBK and corrupts the Chinese literals):

    docker cp tools/scripts/rag_qa_004_scope_diagnostic.py wenruo-rag-cpu:/tmp/
    docker exec wenruo-rag-cpu sh -c "cd /ragflow && python /tmp/rag_qa_004_scope_diagnostic.py > /tmp/qa004.md 2> /tmp/qa004.err"
    docker cp wenruo-rag-cpu:/tmp/qa004.md docs/evaluation/rag_qa_004_instability.md
"""

from __future__ import annotations

import asyncio
import collections
import datetime
import hashlib
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, "/ragflow")

KB_ID = os.environ.get("TRACE_KB", "9463d93eb97511f1938f2592e9bc6fe4")
DIALOG_ID = os.environ.get("TRACE_DIALOG", "5c8c249eb8e411f180e20bf412cbc55e")
JSON_OUT = os.environ.get("TRACE_JSON", "/tmp/qa004_diagnostic.json")

#: How many times to repeat each measurement. Kept small because every production run costs one
#: decomposition call, one hybrid retrieval per route, and one rerank call.
N_RETRIEVAL = int(os.environ.get("N_RETRIEVAL", "5"))
N_DECOMPOSE = int(os.environ.get("N_DECOMPOSE", "6"))
N_MODEL = int(os.environ.get("N_MODEL", "3"))
N_VARIANT = int(os.environ.get("N_VARIANT", "3"))

ORIGINAL = "标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求"

#: Controlled phrasings. The first three vary ONLY the voltage scope; the last two ask one half
#: of the question each, which is what tells a recall problem from a ranking problem.
VARIANTS: tuple[tuple[str, str], ...] = (
    ("original", ORIGINAL),
    ("110kV_scoped", "Q/GDW 73285-2026（110kV）标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求"),
    ("220kV_scoped", "Q/GDW 73286-2026（220kV）标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求"),
    ("design_life_only", "标准对电缆附件终端和接头的设计使用年限有何要求"),
    ("structure_only", "标准对电缆附件终端和接头的结构图纸资料有什么要求"),
)

#: A passage counts as carrying one half of the answer when it holds the clause itself.
LIFETIME_MARKERS = ("设计使用年限", "不少于30")
STRUCTURE_MARKERS = ("结构图纸",)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]{0,300}?>")


def flat(text: str) -> str:
    """Comparison form: tags become separators, whitespace removed, case folded."""
    text = _TAG_RE.sub("|", str(text or ""))
    text = text.lower().replace("×", "x")
    return re.sub(r"\s+", "", text)


def classify(chunk: dict) -> dict:
    """Which half of the answer a passage carries, and where it comes from."""
    text = flat(chunk.get("content_with_weight") or chunk.get("content") or "")
    body = str(chunk.get("content_with_weight") or chunk.get("content") or "")
    found = re.search(r"标准号[:：]\s*([A-Z0-9./\- ]+?)\s*[|\]]", body)
    section = re.search(r"章节[:：]\s*([^|\]]+)", body)
    return {
        "id": str(chunk.get("chunk_id") or chunk.get("id") or ""),
        "doc": str(chunk.get("docnm_kwd") or ""),
        "doc_id": str(chunk.get("doc_id") or ""),
        "designation": found.group(1).strip() if found else "",
        "section": section.group(1).strip() if section else "",
        "voltage": ("220kV" if "220kv" in flat(chunk.get("docnm_kwd") or "") else "110kV" if "110kv" in flat(chunk.get("docnm_kwd") or "") else "?"),
        "chars": len(body),
        "content": body,
        "page": (chunk.get("positions") or [[None]])[0][0] if chunk.get("positions") else None,
        "lifetime": any(m in text for m in LIFETIME_MARKERS),
        "structure": any(m in text for m in STRUCTURE_MARKERS),
        "rerank_score": None if chunk.get("rerank_score") is None else round(float(chunk["rerank_score"]), 6),
        "fused_similarity": None if chunk.get("fused_similarity") is None else round(float(chunk["fused_similarity"]), 6),
        "score_kind": (chunk.get("score_provenance") or {}).get("score_kind"),
        "routes": list(chunk.get("retrieval_routes") or []),
        "route_hits": int(chunk.get("route_hits") or 0),
        "prefix": bool(chunk.get("content_prefix_kind_kwd")),
    }


def window_facts(rows: list[dict]) -> dict:
    return {
        "n": len(rows),
        "ids": [r["id"] for r in rows],
        "lifetime_chunks": sum(1 for r in rows if r["lifetime"]),
        "structure_chunks": sum(1 for r in rows if r["structure"]),
        "both_halves": (any(r["lifetime"] for r in rows) and any(r["structure"] for r in rows)),
        "voltage_mix": dict(collections.Counter(r["voltage"] for r in rows)),
        "docs": sorted({r["doc"][:46] for r in rows}),
        "designations": sorted({r["designation"] or "(no prefix)" for r in rows}),
        "routes_reached": sorted({q for r in rows for q in r["routes"]}),
    }


def jaccard(a, b) -> float:
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if (sa | sb) else 1.0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


async def main() -> int:
    from common import settings

    settings.init_settings()
    from rag.nlp import rag_tokenizer
    from rag.prompts.generator import kb_prompt
    from rag.retrieval import retrieve_multi_route
    from rag.retrieval.decomposition import decompose_question
    from rag.retrieval.rerank import resolve_final_top_n
    from rag.retrieval.multi_route import resolve_routes_top_k
    from api.db.db_models import Dialog
    from api.db.joint_services.tenant_model_service import get_tenant_default_model_by_type, resolve_model_config
    from api.db.services.dialog_service import resolve_rerank_mdl
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from api.db.services.llm_service import LLMBundle
    from api.db import cable_defaults
    from common.constants import LLMType

    rag_tokenizer.tokenizer.set_language("Chinese")

    ok, kb = KnowledgebaseService.get_by_id(KB_ID)
    if not ok:
        print(f"KB {KB_ID} not found", file=sys.stderr)
        return 1
    tenant = str(kb.tenant_id)
    dialog = Dialog.get_or_none(Dialog.id == DIALOG_ID)
    if dialog is None:
        print(f"dialog {DIALOG_ID} not found", file=sys.stderr)
        return 1

    embd_mdl = LLMBundle(tenant, resolve_model_config(tenant, LLMType.EMBEDDING, kb.embd_id))
    rerank_mdl = resolve_rerank_mdl(tenant, dialog.rerank_id or "", dialog.tenant_rerank_id)
    chat_config = get_tenant_default_model_by_type(tenant, LLMType.CHAT)
    chat_mdl = LLMBundle(tenant, chat_config)
    retriever = settings.retriever
    prompt_config = dialog.prompt_config or {}
    params = {
        "similarity_threshold": float(dialog.similarity_threshold),
        "vector_similarity_weight": float(dialog.vector_similarity_weight),
        "final_top_n": resolve_final_top_n(dialog.top_n),
        "knn_top_k": int(dialog.top_k),
        "rerank_candidates_count": int(getattr(dialog, "rerank_candidates_count", 30) or 30),
    }
    max_tokens = (chat_config or {}).get("max_tokens") or 8192
    report: dict = {
        "captured_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "question": ORIGINAL,
        "kb_id": KB_ID,
        "dialog_id": DIALOG_ID,
        "parameters": params,
        "threshold": {"uses_configured_threshold": None},
        "phases": {},
    }

    async def production(question: str) -> dict:
        result = await retrieve_multi_route(
            retriever=retriever,
            question=question,
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
        rows = [classify(c) for c in (result.get("chunks") or [])]
        return {"rows": rows, "facts": window_facts(rows), "total": result.get("total"), "mode": result.get("retrieval_mode", "HYBRID")}

    # ---- P1 embedding determinism --------------------------------------------------------
    print("P1 embedding determinism ...", file=sys.stderr)
    vecs = []
    for _ in range(N_MODEL):
        try:
            # ``LLMBundle.encode_queries`` is synchronous, takes ONE string, and returns
            # ``(embedding, used_tokens)``; the network call is pushed off the event loop.
            def _embed():
                result = embd_mdl.encode_queries(ORIGINAL)
                vector = result[0] if isinstance(result, tuple) else result
                return [round(float(x), 9) for x in vector]

            vecs.append(await asyncio.to_thread(_embed))
        except Exception as exc:  # noqa: BLE001
            vecs.append(None)
            report["phases"].setdefault("errors", []).append(f"embed: {type(exc).__name__}: {exc}")
    good = [v for v in vecs if v]
    emb_stats = {"runs": len(vecs), "dims": [len(v) for v in good]}
    if len(good) > 1:
        emb_stats["identical_all"] = all(v == good[0] for v in good)
        emb_stats["max_abs_diff"] = max(max(abs(a - b) for a, b in zip(good[0], v)) for v in good[1:])
    report["phases"]["P1_embedding"] = emb_stats

    # ---- P2 decomposition stability ------------------------------------------------------
    print("P2 decomposition stability ...", file=sys.stderr)
    decomps = []
    for i in range(N_DECOMPOSE):
        try:
            decomposition = await decompose_question(chat_mdl, ORIGINAL, 4)
            routes = list(getattr(decomposition, "sub_queries", decomposition) or [])
            decomps.append([str(r) for r in routes])
        except Exception as exc:  # noqa: BLE001
            decomps.append([])
            report["phases"].setdefault("errors", []).append(f"decompose: {type(exc).__name__}: {exc}")
    counts = collections.Counter(len(d) for d in decomps)
    distinct = collections.Counter(tuple(d) for d in decomps)
    report["phases"]["P2_decomposition"] = {
        "runs": decomps,
        "sub_query_counts": dict(counts),
        "distinct_route_lists": len(distinct),
        "stable_route_list": len(distinct) == 1,
        "most_common": [" | ".join(k) for k, _ in distinct.most_common(3)],
    }

    # ---- P3 retrieval stability -----------------------------------------------------------
    print(f"P3 retrieval stability ({N_RETRIEVAL} runs) ...", file=sys.stderr)
    runs = []
    for i in range(N_RETRIEVAL):
        runs.append(await production(ORIGINAL))
    pair_j = []
    for a in range(len(runs)):
        for b in range(a + 1, len(runs)):
            pair_j.append(jaccard(runs[a]["facts"]["ids"], runs[b]["facts"]["ids"]))
    order_same = len({tuple(r["facts"]["ids"]) for r in runs}) == 1
    report["phases"]["P3_retrieval"] = {
        "runs": [r["facts"] for r in runs],
        "windows_recorded": len(runs),
        "distinct_windows": len({tuple(r["facts"]["ids"]) for r in runs}),
        "order_identical_all_runs": order_same,
        "pairwise_jaccard_min": round(min(pair_j), 4) if pair_j else None,
        "pairwise_jaccard_mean": round(sum(pair_j) / len(pair_j), 4) if pair_j else None,
        "both_halves_runs": sum(1 for r in runs if r["facts"]["both_halves"]),
        "lifetime_counts": [r["facts"]["lifetime_chunks"] for r in runs],
        "structure_counts": [r["facts"]["structure_chunks"] for r in runs],
        "route_sets": [r["facts"]["routes_reached"] for r in runs],
        "route_set_stability": len({tuple(sorted(r["facts"]["routes_reached"])) for r in runs}),
    }

    # ---- P4 rerank determinism on a FIXED candidate set -----------------------------------
    print("P4 rerank determinism ...", file=sys.stderr)
    base_rows = runs[0]["rows"] if runs else []
    docs = [str(c.get("content_with_weight") or "") for c in base_rows]
    rerank_runs = []
    if docs and rerank_mdl is not None:
        for _ in range(N_MODEL):
            try:
                scores, _ = await rerank_mdl.similarity(ORIGINAL, docs)
                rerank_runs.append([round(float(s), 6) for s in scores])
            except Exception as exc:  # noqa: BLE001
                report["phases"].setdefault("errors", []).append(f"rerank: {type(exc).__name__}: {exc}")
    rr = {"runs": len(rerank_runs), "docs": len(docs)}
    if len(rerank_runs) > 1:
        rr["identical_all"] = all(r == rerank_runs[0] for r in rerank_runs)
        rr["max_abs_diff"] = max(max(abs(a - b) for a, b in zip(rerank_runs[0], r)) for r in rerank_runs[1:])
        rr["per_run_top3_ids"] = [
            [base_rows[i]["id"][:16] for i in sorted(range(len(r)), key=lambda k: -r[k])[:3]] for r in rerank_runs
        ]
        rr["top3_order_stable"] = len({tuple(x) for x in rr["per_run_top3_ids"]}) == 1
    report["phases"]["P4_rerank"] = rr

    # ---- P5 controlled scope variants -----------------------------------------------------
    print(f"P5 controlled variants ({len(VARIANTS)} x {N_VARIANT} runs) ...", file=sys.stderr)
    variants = {}
    for name, question in VARIANTS:
        rs = []
        for _ in range(N_VARIANT):
            rs.append(await production(question))
        pj = []
        for a in range(len(rs)):
            for b in range(a + 1, len(rs)):
                pj.append(jaccard(rs[a]["facts"]["ids"], rs[b]["facts"]["ids"]))
        variants[name] = {
            "question": question,
            "runs": [r["facts"] for r in rs],
            "both_halves_runs": sum(1 for r in rs if r["facts"]["both_halves"]),
            "lifetime_counts": [r["facts"]["lifetime_chunks"] for r in rs],
            "structure_counts": [r["facts"]["structure_chunks"] for r in rs],
            "distinct_windows": len({tuple(r["facts"]["ids"]) for r in rs}),
            "pairwise_jaccard_mean": round(sum(pj) / len(pj), 4) if pj else None,
            "voltage_mix": [r["facts"]["voltage_mix"] for r in rs],
            "docs": sorted({d for r in rs for d in r["facts"]["docs"]}),
            "first_rows": rs[0]["rows"],
            "context_chars": None,
            "answer": None,
        }
    report["phases"]["P5_variants"] = variants

    # ---- P6 generation stability ---------------------------------------------------------
    # (a) three answers from ONE frozen context: isolates text generation from retrieval
    print("P6 generation stability ...", file=sys.stderr)
    frozen_rows = runs[0]["rows"] if runs else []
    system = str(prompt_config.get("system") or getattr(cable_defaults, "SYSTEM_PROMPT", "") or "")
    date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    frozen_context = ""
    if frozen_rows:
        blocks = kb_prompt(
            {"chunks": [{"chunk_id": r["id"], "docnm_kwd": r["doc"], "content_with_weight": r["content"]} for r in frozen_rows]},
            max_tokens,
        )
        frozen_context = "\n\n------\n\n".join(blocks)
    frozen_answers = []
    for _ in range(N_MODEL):
        try:
            ans = await chat_mdl.async_chat(
                system.replace("{knowledge}", "\n------\n" + frozen_context).replace("{date}", date),
                [{"role": "user", "content": ORIGINAL}],
            )
            frozen_answers.append(str(ans[0] if isinstance(ans, tuple) else ans))
        except Exception as exc:  # noqa: BLE001
            frozen_answers.append(f"ERROR {type(exc).__name__}: {exc}")
    report["phases"]["P6_generation"] = {
        "frozen_window_ids": [r["id"] for r in frozen_rows],
        "frozen_context_chars": len(frozen_context),
        "answers": frozen_answers,
        "identical_answers": len(set(frozen_answers)) == 1,
        "distinct_answers": len(set(frozen_answers)),
        "mentions_design_life": [bool(re.search(r"30\s*年|设计使用年限", a)) for a in frozen_answers],
        "mentions_structure": [bool(re.search(r"结构图纸|结构", a)) for a in frozen_answers],
    }

    # (b) one answer per variant, from that variant's own context
    for name, entry in variants.items():
        rows = entry["first_rows"]
        if not rows:
            continue
        blocks = kb_prompt(
            {"chunks": [{"chunk_id": r["id"], "docnm_kwd": r["doc"], "content_with_weight": r["content"]} for r in rows]},
            max_tokens,
        )
        ctx = "\n\n------\n\n".join(blocks)
        entry["context_chars"] = len(ctx)
        try:
            ans = await chat_mdl.async_chat(
                system.replace("{knowledge}", "\n------\n" + ctx).replace("{date}", date),
                [{"role": "user", "content": entry["question"]}],
            )
            entry["answer"] = str(ans[0] if isinstance(ans, tuple) else ans)
        except Exception as exc:  # noqa: BLE001
            entry["answer"] = f"ERROR {type(exc).__name__}: {exc}"

    pathlib.Path(JSON_OUT).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(render(report))
    return 0


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def render(r: dict) -> str:
    p = r["phases"]
    out: list[str] = ["# QA-004 instability diagnostic (read-only)", ""]
    out.append(f"- question: {r['question']}")
    out.append(f"- captured at: {r['captured_at']} (UTC)")
    out.append(f"- knowledge base: {r['kb_id']}; assistant: {r['dialog_id']}")
    out.append(f"- parameters (unchanged, read from the assistant row): {json.dumps(r['parameters'], ensure_ascii=False)}")
    out.append("")
    if p.get("errors"):
        out.append("## Errors encountered (reported, not hidden)")
        out.append("")
        for e in p["errors"]:
            out.append(f"- {e}")
        out.append("")

    out.append("## P1 embedding determinism")
    out.append("")
    e = p["P1_embedding"]
    out.append(f"- runs: {e['runs']}; dims: {e.get('dims')}")
    out.append(f"- byte-identical across runs: **{e.get('identical_all')}**; max |Δ| component: {e.get('max_abs_diff')}")
    out.append("")

    out.append("## P2 decomposition stability (the deployed pipeline asks the chat model for sub-queries)")
    out.append("")
    d = p["P2_decomposition"]
    out.append(f"- sub-query counts across {len(d['runs'])} runs: {d['sub_query_counts']}")
    out.append(f"- distinct route lists: **{d['distinct_route_lists']}** (stable: {d['stable_route_list']})")
    out.append("")
    for i, run in enumerate(d["runs"], 1):
        out.append(f"  - run {i}: " + " | ".join(run))
    out.append("")

    out.append("## P3 retrieval stability (identical question, repeated production calls)")
    out.append("")
    t = p["P3_retrieval"]
    out.append(f"- runs: {t['windows_recorded']}; distinct windows: **{t['distinct_windows']}**; identical order in all runs: **{t['order_identical_all_runs']}**")
    out.append(f"- pairwise window Jaccard: mean **{t['pairwise_jaccard_mean']}**, min {t['pairwise_jaccard_min']}")
    out.append(f"- runs whose window held BOTH halves (design life AND structure): **{t['both_halves_runs']}/{t['windows_recorded']}**")
    out.append(f"- design-life passages per run: {t['lifetime_counts']}")
    out.append(f"- structure passages per run: {t['structure_counts']}")
    out.append(f"- distinct route-sets reaching the window: {t['route_set_stability']}")
    out.append("")
    out.append("| run | n | design-life | structure | both | voltage mix | docs (110/220) |")
    out.append("|---|---|---|---|---|---|---|")
    for i, run in enumerate(t["runs"], 1):
        out.append(f"| {i} | {run['n']} | {run['lifetime_chunks']} | {run['structure_chunks']} | {run['both_halves']} | {json.dumps(run['voltage_mix'])} | {len(run['docs'])} |")
    out.append("")

    out.append("## P4 rerank determinism (one fixed set of passages, re-scored)")
    out.append("")
    rr = p["P4_rerank"]
    out.append(f"- passages re-scored: {rr.get('docs')}; runs: {rr.get('runs')}")
    out.append(f"- identical scores across runs: **{rr.get('identical_all')}**; max |Δ|: {rr.get('max_abs_diff')}")
    out.append(f"- top-3 order stable: {rr.get('top3_order_stable')}; per-run top-3: {rr.get('per_run_top3_ids')}")
    out.append("")

    out.append("## P5 controlled scope variants")
    out.append("")
    for name, v in p["P5_variants"].items():
        out.append(f"### {name}")
        out.append("")
        out.append(f"- question: {v['question']}")
        out.append(f"- runs: {len(v['runs'])}; distinct windows: {v['distinct_windows']}; mean pairwise Jaccard: {v['pairwise_jaccard_mean']}")
        out.append(f"- runs holding BOTH halves: **{v['both_halves_runs']}/{len(v['runs'])}**")
        out.append(f"- design-life passages per run: {v['lifetime_counts']}")
        out.append(f"- structure passages per run: {v['structure_counts']}")
        out.append(f"- voltage mix per run: {json.dumps(v['voltage_mix'], ensure_ascii=False)}")
        out.append(f"- documents touched: {'; '.join(x[:44] for x in v['docs'])}")
        out.append("")
        out.append("| # | chunk id | voltage | designation | section | page | design-life | structure | rerank | fused | routes |")
        out.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for i, row in enumerate(v["first_rows"], 1):
            out.append(
                f"| {i} | `{row['id'][:16]}` | {row['voltage']} | {row['designation'] or '(no prefix)'} | "
                f"{row['section'] or '-'} | {row['page']} | {'Y' if row['lifetime'] else ''} | {'Y' if row['structure'] else ''} | "
                f"{row['rerank_score']} | {row['fused_similarity']} | {len(row['routes'])} |"
            )
        out.append("")
        if v.get("answer"):
            out.append(f"context: {v['context_chars']} chars")
            out.append("")
            out.append("```")
            out.append(v["answer"].strip())
            out.append("```")
            out.append("")

    out.append("## P6 generation stability (one FROZEN context, answered repeatedly)")
    out.append("")
    g = p["P6_generation"]
    out.append(f"- frozen window: {len(g['frozen_window_ids'])} passages, {g['frozen_context_chars']} chars")
    out.append(f"- distinct answers from that one context: **{g['distinct_answers']}** (identical: {g['identical_answers']})")
    out.append(f"- mentions design life per answer: {g['mentions_design_life']}")
    out.append(f"- mentions structure per answer: {g['mentions_structure']}")
    out.append("")
    for i, a in enumerate(g["answers"], 1):
        out.append(f"### frozen-context answer {i}")
        out.append("")
        out.append("```")
        out.append(a.strip())
        out.append("```")
        out.append("")
    out.append(f"_sha256 of each frozen-context answer: {[hashlib.sha256(a.encode()).hexdigest()[:12] for a in g['answers']]}_")
    out.append("")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
