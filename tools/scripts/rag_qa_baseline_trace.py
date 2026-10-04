"""RAG QA baseline trace for the frozen benchmark (READ-ONLY).

Produces ``docs/evaluation/rag_qa_baseline_fullbuild.md`` in the format the benchmark asks for,
from the **deployed** retrieval path, without touching production code.

Run INSIDE the deployed container, copied in byte-exactly (the image has no bind mount of this
repository, and rebuilding it is out of scope):

    docker cp tools/scripts/rag_qa_baseline_trace.py wenruo-rag-cpu:/tmp/rag_qa_baseline_trace.py
    docker exec wenruo-rag-cpu sh -c "cd /ragflow && python /tmp/rag_qa_baseline_trace.py > /tmp/qa_baseline.md 2> /tmp/qa_baseline.err"
    docker cp wenruo-rag-cpu:/tmp/qa_baseline.md docs/evaluation/rag_qa_baseline_fullbuild.md

Do NOT pipe this file into `python -` on stdin: the container decodes piped bytes as GBK, which
corrupts every Chinese literal in it (tried; it fails with `SyntaxError: unterminated string
literal` while a small ASCII-only test passes, so the trap is not obvious). Verify the copy with
`sha256sum` on both sides instead.

Re-score an existing capture without re-running it (no retrieval, no model call, no database), so
a corrected evidence probe can be applied to a run that must stay frozen:

    docker exec wenruo-rag-cpu sh -c "cd /ragflow && TRACE_RENDER_FROM=/tmp/rag_qa_baseline_trace.json python /tmp/rag_qa_baseline_trace.py"

What it does NOT do: no index write, no MySQL write, no Docker build, no deploy, no assistant
created or modified. It reads the assistant row that already owns the benchmark knowledge base
and calls the deployed entry point with that row's own values.

WHAT IS DIAGNOSTIC AND WHAT IS NOT
=================================

The trace has three evidence classes and each line of the report says which one it is:

``PRODUCTION``
    Recorded from a single call to the deployed entry point
    ``rag.retrieval.retrieve_multi_route`` with exactly the parameters the owning assistant
    passes. This is what the deployed version actually does.

``CONTROLLED_VARIANT``
    A leg-isolated call to the deployed ``Dealer.retrieval`` at a weight this script chose
    (0.0 = lexical only, 1.0 = dense only). The deployed doc store fuses the two legs
    SERVER-SIDE inside one Elasticsearch request, so the production call cannot report its
    lexical and dense candidate sets separately - the only way to observe them is to ask
    again with the other leg switched off. These rows are labelled as variants, never as
    production output.

``NOT_OBSERVABLE``
    A signal the deployed code does not emit at all. These are listed in the report's coverage
    table together with the hook that would have to be added, so the gap is recorded rather
    than silently filled with a guess.

Read-only provenance: the storage clients are opened by ``settings.init_settings()``, which is
the application's own boot path; the only model calls are the query embedding, the reranker on
the retrieved window, and the answer generation.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import pathlib
import re
import sys

# The container's application root; PYTHONPATH already points here in the image, but an
# explicit path keeps the script runnable under a bare `python -`.
sys.path.insert(0, "/ragflow")

# ---------------------------------------------------------------------------
# Configuration (environment overrides, deployed values as defaults)
# ---------------------------------------------------------------------------

KB_ID = os.environ.get("TRACE_KB", "9463d93eb97511f1938f2592e9bc6fe4")
#: The assistant whose values the trace reproduces. Every assistant bound to this knowledge
#: base carries the same retrieval settings; this one is chosen because its
#: ``meta_data_filter`` is ``{}`` (no metadata-derived document scope), which makes the
#: retrieval call fully determined by values that can be read back from the row.
DIALOG_ID = os.environ.get("TRACE_DIALOG", "5c8c249eb8e411f180e20bf412cbc55e")
IMAGE = os.environ.get("BASELINE_IMAGE", "my-wenruorag:fullbuild-6892b3c33")
DIGEST = os.environ.get("BASELINE_DIGEST", "sha256:18711d10f0353a9f37d25611bd81030bd6c6af0f00f764ddf0132b5ad3f7d123")
SOURCE_REVISION = os.environ.get("BASELINE_REVISION", "6892b3c3370835286d6431d274d13cfb217f1b9d")
JSON_OUT = os.environ.get("TRACE_JSON", "/tmp/rag_qa_baseline_trace.json")

#: Deployed code whose bytes this trace was taken from. Hashing them makes the trace
#: self-verifying: a rerun on a different image produces a different fingerprint.
FINGERPRINT_PATHS = (
    "rag/retrieval/pipeline.py",
    "rag/retrieval/multi_route.py",
    "rag/retrieval/rerank.py",
    "rag/retrieval/planner.py",
    "rag/retrieval/query_router.py",
    "rag/nlp/search.py",
    "rag/utils/es_conn.py",
)

# ---------------------------------------------------------------------------
# The frozen benchmark (docs/evaluation/rag_qa_benchmark_v0.1.md, commit 7a63b6f57)
# ---------------------------------------------------------------------------

QAS: tuple[dict, ...] = (
    {
        "id": "QA-001",
        "question": "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？",
        "evidence": ["Q/GDW 73286.2-2026 表 1", "Q/GDW 73286.3-2026 表 1"],
        "category": "table retrieval; exact numeric retrieval",
        "facts": (
            ("单芯 覆盖下界 1×400 mm²", ("1×400", "400mm²", "400 mm²")),
            ("单芯 覆盖上界 1×2000 mm²", ("1×2000", "2000mm²", "2000 mm²")),
            ("单芯 规格数量 = 10（表中枚举计数，仅对上下文）", {"count_re": r"1[x*](\d{3,4})", "expect": 10}),
            ("三芯 覆盖下界 3×400 mm²", ("3×400", "400mm²", "400 mm²")),
            ("三芯 覆盖上界 3×1600 mm²", ("3×1600", "1600mm²", "1600 mm²")),
            ("三芯 规格数量 = 8（表中枚举计数，仅对上下文）", {"count_re": r"3[x*](\d{3,4})", "expect": 8}),
        ),
    },
    {
        "id": "QA-002",
        "question": "Q/GDW 73285-2026 标准体系由哪些部分构成？各自适用范围是什么？",
        "evidence": ["Part 1 通用技术规范", "Part 2 单芯专用技术规范", "Part 3 三芯专用技术规范"],
        "category": "document hierarchy; cross-document reasoning",
        "facts": (
            ("Part 1 通用技术规范", ("通用技术规范",)),
            ("Part 2 单芯专用技术规范", ("单芯海底电力电缆系统专用技术规范", "单芯专用技术规范")),
            ("Part 3 三芯专用技术规范", ("三芯海底电力电缆系统专用技术规范", "三芯专用技术规范")),
        ),
    },
    {
        "id": "QA-003",
        "question": "2026版标准相比2019旧版标准，主要进行了哪些重要修订？",
        "evidence": ["2026 版前言的修订说明", "2019 旧版对照"],
        "category": "version comparison; change detection",
        "facts": (
            ("更改导体结构名称", ("导体结构名称", "导体结构")),
            ("删除绝缘平均厚度要求", ("绝缘平均厚度",)),
        ),
    },
    {
        "id": "QA-004",
        "question": "标准对电缆附件（终端与接头）的设计使用寿命与结构有何要求？",
        "evidence": ["终端设计使用年限参数", "附件结构资料要求"],
        "category": "mixed retrieval; missing evidence detection",
        "facts": (
            ("终端设计使用年限不少于30年", ("不少于30", "30年")),
            ("户外终端", ("户外终端",)),
            ("GIS终端", ("gis终端",)),
            ("油浸终端", ("油浸终端",)),
            ("预制直通接头", ("预制直通接头",)),
            ("绝缘接头", ("绝缘接头",)),
        ),
    },
    {
        "id": "QA-005",
        "question": "110kV海缆系统的耐压试验标准（出厂与安装后）是如何规定的？",
        "evidence": ["110kV 出厂耐压试验", "110kV 安装后耐压试验"],
        "category": "parameter retrieval; engineering specification",
        "facts": (
            ("[benchmark] 出厂 160kV（绝对电压）", ("160kv",)),
            ("[benchmark] 出厂 30min", ("30min", "30分钟")),
            ("[benchmark] 安装后 128kV（绝对电压）", ("128kv",)),
            ("[benchmark] 安装后 60min", ("60min", "1小时", "1h")),
            ("[corpus] 出厂以 U₀ 倍数表述：2.5U₀", ("2.5u₀", "2.5u0", "2.5u")),
            ("[corpus] 安装后以 U₀ 倍数表述：2U₀", ("2u₀", "2u0", "2u")),
            ("[corpus] 安装后替代方案：64kV", ("64kv",)),
        ),
    },
)

#: The eight signals the benchmark asks the trace to expose. ``class`` is which evidence class
#: can actually produce each one on the deployed version, and ``note`` says why or what hook
#: would be needed.
COVERAGE: tuple[dict, ...] = (
    {
        "signal": "effective query",
        "cls": "PRODUCTION",
        "note": "retrieve_multi_route's `question` argument. The owning assistant has keyword/refine_multiturn/cross_languages all OFF, so it equals the user question; the raw preprocessor output is logged (dialog_service.py:940) but not returned.",
    },
    {
        "signal": "keyword extraction (app level)",
        "cls": "NOT_OBSERVABLE",
        "note": "rag.prompts.generator.keyword_extraction is an LLM call whose result is concatenated onto the question (dialog_service.py:874); nothing records it. OFF for this assistant, so it does not affect this baseline. hook: record the preprocessor output with the turn.",
    },
    {
        "signal": "keyword extraction (retrieval level)",
        "cls": "CONTROLLED_VARIANT",
        "note": "reproduced offline from the deployed tokenizer via `Dealer.qryr.question(effective_query)` -> (lexical query string, keyword list); no deployed call returns this value.",
    },
    {
        "signal": "lexical candidates",
        "cls": "CONTROLLED_VARIANT",
        "note": "the doc store fuses both legs server-side in ONE request (es_conn.search: weighted_sum of query_string + kNN), so the production call has no lexical-only candidate set. Observed by re-asking at vector_similarity_weight=0.0. hook: a per-leg candidate list returned by the doc store.",
    },
    {
        "signal": "dense candidates",
        "cls": "CONTROLLED_VARIANT",
        "note": "same fusion; observed by re-asking at vector_similarity_weight=1.0. hook: same as above.",
    },
    {
        "signal": "hybrid ranking",
        "cls": "PRODUCTION",
        "note": "per returned chunk: `similarity` (fused/reranked), `term_similarity` (lexical), `vector_similarity` (dense) and `score_provenance{score_kind, mode, selection_score, lexical_selection_score, dense_score, configured_threshold, effective_vector_weight}`. Only the returned window is exposed: the pre-cut ranked pool is not.",
    },
    {
        "signal": "final top N",
        "cls": "PRODUCTION",
        "note": "the returned `chunks` list (dialog.top_n=12) plus `total`/`doc_aggs`. The cut diagnostics (pool size, prose/table mix, quota shortfall) are logged by rag/retrieval/rerank.py `_select` but NOT returned as data. hook: return the cut diagnostics with the result.",
    },
    {
        "signal": "document metadata",
        "cls": "PRODUCTION",
        "note": "per chunk: `docnm_kwd`, `doc_id`, `kb_id`, `doc_type_kwd`, positions/page, the injected `[标准号: ... | 文档: ... | 章节: ...]` prefix and its `content_prefix_*` provenance fields.",
    },
    {
        "signal": "chunk content",
        "cls": "PRODUCTION",
        "note": "per chunk: `content_with_weight` (markup preserved) and `content_ltks` (the indexed token stream the lexical leg scores against).",
    },
    {
        "signal": "route plan (effective sub-queries)",
        "cls": "PRODUCTION",
        "note": "each returned chunk carries `retrieval_routes` / `route_hits`, so the routes that reached the window are recoverable from the result itself. In the deployed (pre-planner) revision the route list is produced by `decompose_question()` at rag/retrieval/pipeline.py:280 and is not returned as data; there is no compiled plan or plan_hash in this image. hook: return the route plan with the result.",
    },
    {
        "signal": "leg health / degradation",
        "cls": "PRODUCTION",
        "note": "`retrieval_health` (execution, evidence state, answer action) attached by attach_retrieval_health, plus `route_execution` when a route failed or ran LEXICAL_DEGRADED.",
    },
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def code_fingerprint() -> dict:
    """sha256 of the deployed retrieval modules - proves which bytes produced the trace."""
    out = {}
    for rel in FINGERPRINT_PATHS:
        path = pathlib.Path("/ragflow") / rel
        try:
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        except FileNotFoundError:
            out[rel] = "ABSENT"
        except OSError as exc:
            out[rel] = f"UNREADABLE ({type(exc).__name__})"
    combined = hashlib.sha256("".join(sorted(out.values())).encode()).hexdigest()[:16]
    return {"modules": out, "combined": combined}


#: Verified at capture time by hashing the deployed files against the repository's own git
#: blobs. The image tag does NOT name the revision that is running, so the baseline records the
#: deployed layout explicitly instead of trusting the tag.
DEPLOYED_SOURCE_FACTS = (
    "the image tag `fullbuild-6892b3c33` does NOT identify the code that ran: `rag/retrieval/pipeline.py` in the image is the PRE-PLANNER revision (git blob `da38414bd59b`, last present in commit `138a1a79a`, 2026-09-29) and it routes via `decompose_question()`",
    "`rag/retrieval/planner.py` does not exist in the image; at revision `6892b3c33` and at HEAD it does, and `pipeline.py` there is the newer planner version (`compile_retrieval_plan`)",
    "`rag/retrieval/__init__.py` also differs from HEAD (HEAD's re-exports the planner symbols)",
    "byte-identical to HEAD: `rag/nlp/search.py`, `rag/retrieval/multi_route.py`, `rag/retrieval/rerank.py`, `rag/retrieval/query_router.py`, `rag/retrieval/health.py`, `rag/retrieval/health_bridge.py`, `rag/retrieval/health_producers.py`, `rag/retrieval/decomposition.py`, `rag/retrieval/chunk_profile.py`, `rag/nlp/query.py`, `rag/prompts/generator.py`, `rag/utils/es_conn.py`, `rag/app/tag.py`, `api/db/services/dialog_service.py`, `api/db/cable_defaults.py`, `api/db/db_models.py`",
    "the per-file digests below identify the running code directly, so this capture stands on its own regardless of the tag",
)


_TAG_RE = re.compile(r"<[^>]{0,300}?>")


def flat(text: str) -> str:
    """Comparison form: no markup, no whitespace, unified multiplication sign and case.

    Retrieved passages are HTML (`<td>终端设计使用年限</td><td>年</td><td>不少于30 </td>`), so a
    naive substring search over the raw text reports a false MISS for every fact that a table
    splits across cells. Tags are replaced by a separator (not by nothing) before comparison:
    deleting them outright would concatenate adjacent cells and make `3×400` + `3×500` read as
    the single value `3×4003×500`, which corrupts any value count taken over the text.
    """
    text = _TAG_RE.sub("|", str(text or ""))
    for entity, char in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"')):
        text = text.replace(entity, char)
    text = text.lower()
    text = text.replace("×", "x").replace("＊", "*").replace("－", "-")
    return re.sub(r"\s+", "", text)


def fact_probe(facts, *texts) -> list[dict]:
    """EXPLORATORY_JUDGMENT: is each frozen expected fact supported by the given texts?

    Deterministic matching over the flattened text. Two spec shapes:

    * ``(label, (needle, ...))`` - the fact is present when ANY needle is a substring. Anything
      beyond "any spelling of the same figures" in one needle list would overstate the probe.
    * ``(label, {"count_re": r, "expect": n})`` - the fact is a NUMBER OF DISTINCT VALUES the
      passage enumerates (e.g. the ten nominal cross-sections a table lists). A cross-section
      count is not a string in any document, so substring matching cannot answer it and the
      enumeration is counted instead.

    It answers "is the evidence in front of the model", which is the question a retrieval
    baseline is asked; it is NOT a Gold Set and it does not judge whether an answer is correct.
    """
    joined = [flat(text) for text in texts]
    rows = []
    for label, spec in facts:
        if isinstance(spec, dict):
            pattern = re.compile(spec["count_re"])
            observed = {m for text in joined for m in pattern.findall(text)}
            expect = int(spec["expect"])
            rows.append(
                {
                    "fact": label,
                    "kind": "count",
                    "observed": len(observed),
                    "expected": expect,
                    "present": len(observed) == expect,
                    "examples": sorted(observed)[:14],
                }
            )
            continue
        needle_list = list(spec)
        hit = [i for i, text in enumerate(joined) if any(flat(n) in text for n in needle_list)]
        rows.append({"fact": label, "kind": "substring", "needles": needle_list, "matched_in": hit, "present": bool(hit)})
    return rows


def designation_of(chunk: dict) -> str:
    """The standard designation a passage belongs to (from its injected prefix or name)."""
    body = str(chunk.get("content_with_weight") or "")
    found = re.search(r"标准号[:：]\s*([A-Z0-9./\- ]+?)\s*[|\]]", body)
    if found:
        return found.group(1).strip()
    return str(chunk.get("docnm_kwd") or "")[:48]


#: A standard designation as it appears inside the benchmark's `Expected evidence` strings,
#: with the year stripped: `Q/GDW 73286.2-2026` -> `73286.2`. The injected prefix omits the
#: year, and the 2026 texts also quote their 2019 predecessors, so matching the year would
#: report a false miss on the right passage and a false hit on an old revision.
_DESIGNATION_RE = re.compile(r"(\d{5}(?:\.\d+)?)")
#: A table / clause marker the passage has to carry: `表 1`, `表1`, `5.2 表 3`.
_TABLE_RE = re.compile(r"表\s*(\d+)")


def evidence_needles(item: str) -> list[str]:
    """The two things an expected-evidence string actually asks for, as matchable needles.

    Returns ``["designation:<n>", "table:<n>"]`` (a designation, a table marker, or both). The
    benchmark mixes both kinds: `Q/GDW 73286.2-2026 表 1` names a document AND a table in it.
    """
    needles = [f"designation:{m}" for m in _DESIGNATION_RE.findall(item)]
    needles += [f"table:{m}" for m in _TABLE_RE.findall(item)]
    return needles


def evidence_probe(item: str, chunks: list[dict]) -> dict:
    """Which returned passage satisfies an expected-evidence string, and on which needle.

    A needle matches inside a passage's own flattened text - designation, file name, section
    header and body together - which is where a reader would look for it.
    """
    needles = evidence_needles(item)
    if not needles:
        return {
            "needles": [],
            "verdict": "NOT_MATCHABLE (prose-only expected evidence, not a designation or a table marker) - the expected-facts probe below carries the assessment for this QA",
        }
    found: dict[str, str] = {}
    for needle, kind in ((n, n.split(":", 1)[0]) for n in needles):
        want = needle.split(":", 1)[1]
        for chunk in chunks:
            haystack = flat(" ".join((chunk["designation"], chunk["document"], chunk["section"], chunk["content"])))
            if kind == "designation" and want in haystack:
                found[needle] = f"rank {chunk['rank']} ({chunk['designation']})"
                break
            if kind == "table" and f"表{want}" in haystack:
                found[needle] = f"rank {chunk['rank']} ({chunk['designation']})"
                break
    missing = [n for n in needles if n not in found]
    verdict = "RETRIEVED: " + "; ".join(f"{n} -> {where}" for n, where in found.items())
    if missing:
        verdict += ("; " if found else "") + "NOT_RETRIEVED: " + ", ".join(missing)
    return {"needles": needles, "found": found, "missing": missing, "verdict": verdict}


def section_of(chunk: dict) -> str:
    body = str(chunk.get("content_with_weight") or "")
    if "章节:" in body:
        return body.split("章节:", 1)[1].split("]")[0].strip()[:60]
    return ""


def part_of(chunk: dict) -> str:
    """Which part of a standard series the passage is from, by its file name."""
    name = str(chunk.get("docnm_kwd") or "")
    found = re.search(r"第\s*([0-9])\s*部分", name)
    return f"Part {found.group(1)}" if found else "?"


def one_line(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def cell(text: str, limit: int = 60) -> str:
    """A markdown table cell: no pipe can escape into a new column, and no newline into a row."""
    return one_line(text, limit).replace("|", "\\|")


def describe(chunk: dict, rank: int) -> dict:
    """The production-observable fields of one returned passage."""
    provenance = chunk.get("score_provenance") or {}
    routes = chunk.get("retrieval_routes") or []
    return {
        "rank": rank,
        "chunk_id": str(chunk.get("chunk_id") or chunk.get("id") or ""),
        "document": str(chunk.get("docnm_kwd") or ""),
        "designation": designation_of(chunk),
        "part": part_of(chunk),
        "section": section_of(chunk),
        "similarity": round(float(chunk.get("similarity") or 0.0), 4),
        "rerank_score": None if chunk.get("rerank_score") is None else round(float(chunk["rerank_score"]), 4),
        "fused_similarity": None if chunk.get("fused_similarity") is None else round(float(chunk["fused_similarity"]), 4),
        "term_similarity": None if chunk.get("term_similarity") is None else round(float(chunk["term_similarity"]), 4),
        "vector_similarity": None if chunk.get("vector_similarity") is None else round(float(chunk["vector_similarity"]), 4),
        "score_kind": provenance.get("score_kind"),
        "mode": provenance.get("mode"),
        "lexical_selection_score": None if provenance.get("lexical_selection_score") is None else round(float(provenance["lexical_selection_score"]), 4),
        "dense_score": None if provenance.get("dense_score") is None else round(float(provenance["dense_score"]), 4),
        "routes": list(routes) if isinstance(routes, list) else [],
        "route_hits": int(chunk.get("route_hits") or 0),
        "chars": len(str(chunk.get("content_with_weight") or "")),
        "content": str(chunk.get("content_with_weight") or ""),
    }


def ids_of(result) -> list[str]:
    return [str(c.get("chunk_id") or c.get("id") or "") for c in (result or {}).get("chunks") or []]


#: Fields the doc store returns that are not worth carrying into a report: `vector` is the
#: chunk's own embedding (3072 floats per passage) and `content_ltks` the indexed token stream,
#: which for six documents is many megabytes of noise.
def slim(chunk: dict) -> dict:
    """The retrieved passage without its embedding, so a report can quote it verbatim."""
    return {k: v for k, v in chunk.items() if k not in {"vector", "content_ltks"}}


def health_view(health):
    """`retrieval_health` in a JSON-safe shape, whatever the deployed class looks like."""
    if health is None or isinstance(health, (dict, str)):
        return health
    for name in ("api_view", "to_dict"):
        method = getattr(health, name, None)
        if callable(method):
            try:
                return method()
            except Exception:  # noqa: BLE001 - reporting must not break the trace
                continue
    return str(health)


# ---------------------------------------------------------------------------
# Deployed call wrappers
# ---------------------------------------------------------------------------


async def call_production(question, *, retriever, embd_mdl, rerank_mdl, chat_mdl, tenant, kb_ids, params, kbs):
    """ONE call to the deployed entry point, with the assistant row's own values."""
    from rag.retrieval import retrieve_multi_route
    from rag.app.tag import label_question

    accepted = set(inspect.signature(retrieve_multi_route).parameters)
    kwargs = {
        "retriever": retriever,
        "question": question,
        "chat_mdl": chat_mdl,
        "embd_mdl": embd_mdl,
        "rerank_mdl": rerank_mdl,
        "tenant_ids": [tenant],
        "kb_ids": kb_ids,
        "similarity_threshold": params["similarity_threshold"],
        "vector_similarity_weight": params["vector_similarity_weight"],
        "final_top_n": params["final_top_n"],
        "knn_top_k": params["knn_top_k"],
        "rerank_candidates_count": params["rerank_candidates_count"],
        "doc_ids": params["doc_ids"],
        "rank_feature": label_question(question, kbs),
    }
    dropped = sorted(k for k in kwargs if k not in accepted and k != "retriever")
    sent = {k: v for k, v in kwargs.items() if k in accepted or k == "retriever"}
    return await retrieve_multi_route(**sent), dropped, {k: v for k, v in sent.items() if k != "retriever"}


async def call_variant(question, *, retriever, embd_mdl, tenant, kb_ids, params, weight):
    """A CONTROLLED_VARIANT leg: the deployed Dealer.retrieval with one leg switched off.

    ``weight`` 0.0 keeps the lexical leg only, 1.0 the dense leg only. The candidate window is
    the per-route window the production pipeline uses, and the threshold is the assistant's
    own, so the variant differs from production in exactly one value.
    """
    return await retriever.retrieval(
        question,
        embd_mdl,
        [tenant],
        kb_ids,
        1,
        params["routes_top_k"],
        params["similarity_threshold"],
        weight,
        aggs=True,
        highlight=False,
        rerank_candidates_count=params["rerank_candidates_count"],
        allow_dense_fallback=True,
    )


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------


def render_parameters(observed: dict) -> list[str]:
    rows = [
        ("embedding model", observed["embedding"]),
        ("rerank", observed["rerank"]),
        ("top k (knn_top_k)", observed["knn_top_k"]),
        ("final_top_n (dialog.top_n)", observed["final_top_n"]),
        ("similarity_threshold", observed["similarity_threshold"]),
        ("vector_similarity_weight", observed["vector_similarity_weight"]),
        ("routes_top_k (per-route recall window)", "pipeline default 12, adapted in memory per question by rag/retrieval/query_router.route_question; not a dialog column (the log shows it raised to 20 for QA-001)"),
        ("rerank_candidates_count", observed["rerank_candidates_count"]),
        ("scored window", "`similarity` is the RERANKER score: rag/retrieval/rerank.py:759 overwrites the fused score and preserves it in `fused_similarity`. `term_similarity` / `vector_similarity` are the retrieval legs' scores from `score_provenance`"),
        ("similarity_threshold effect", "0.55 is above the whole candidate pool, so `_retrieve_route` retried at RECALL_FLOOR=0.2 (rag/retrieval/multi_route.py:303) for every route of every QA above; the window is carried by the rescue path, not by the configured threshold"),
        ("max_sub_queries", "pipeline default 4"),
        ("allow_dense_fallback", "pipeline default True"),
        ("metadata scope (doc_ids)", "None - the assistant's meta_data_filter is {} so no document scope is derived"),
        ("rank_feature", observed["rank_feature"]),
        ("keyword augmentation", "OFF (dialog.prompt_config['keyword'] = false)"),
        ("refine_multiturn", "OFF (dialog.prompt_config['refine_multiturn'] = false)"),
        ("cross_languages", "not configured"),
        ("knowledge base", f"{observed['kb_id']} ({observed['kb_docs']} documents, {observed['kb_chunks']} chunks)"),
        ("assistant (dialog)", f"{observed['dialog_id']} - {observed['dialog_name']!r}"),
        ("tenant", observed["tenant"]),
        ("answer model", observed["chat_model"]),
    ]
    return [f"- {label}: {value}" for label, value in rows]


def render_qa(qa: dict, record: dict) -> list[str]:
    """One QA block in exactly the requested section order.

    The evidence probes are recomputed here from the stored context and answer rather than read
    back from the record, so re-rendering a captured trace with a corrected probe cannot silently
    keep the old verdicts.
    """
    out: list[str] = [f"## {qa['id']}", ""]
    out.append(f"Question: {qa['question']}")
    out.append("")

    prod = record.get("production") or {}
    chunks = prod.get("chunks") or []
    context_text = (record.get("context") or {}).get("text") or ""
    answer = record.get("answer")
    in_context = fact_probe(qa["facts"], context_text) if context_text else []
    # Count specs describe what a table ENUMERATES, which only the context can answer: a prose
    # answer states "共 10 种规格" instead of listing the ten values, so probing the answer for a
    # value count would report a false miss on a correct answer.
    answer_facts = [(label, spec) for label, spec in qa["facts"] if not isinstance(spec, dict)]
    in_answer = fact_probe(answer_facts, answer) if answer is not None else []

    # --- Evidence retrieved -------------------------------------------------
    out.append("Evidence retrieved:")
    out.append("")
    out.append(f"- benchmark expects: {'; '.join(qa['evidence'])}")
    out.append(f"- category: {qa['category']}")
    if record.get("error"):
        out.append(f"- **retrieval error: {record['error']}**")
    else:
        covered = sorted({c["designation"] for c in chunks})
        out.append(f"- production returned {len(chunks)} passage(s) (total reported: {prod.get('total')}) from: {', '.join(covered) if covered else 'none'}")
        routes = sorted({r for c in chunks for r in c["routes"]})
        out.append(f"- compiled route(s) that reached the window ({len(routes)}): " + ("; ".join(one_line(r, 90) for r in routes) if routes else "none"))
        for name, probe in (record.get("evidence_match") or {}).items():
            out.append(f"- expected evidence `{name}`: {probe.get('verdict')}")
        leg = record.get("legs") or {}
        for label in ("lexical_only", "dense_only", "configured_weight"):
            entry = leg.get(label)
            if not entry:
                continue
            if entry.get("error"):
                out.append(f"- CONTROLLED_VARIANT {label}: ERROR {entry['error']}")
            else:
                out.append(f"- CONTROLLED_VARIANT {label} (vector_similarity_weight={entry['weight']}): {entry['returned']} passage(s), top ids {' '.join(i[:12] for i in entry['ids'][:5])}")
        keywords = record.get("retrieval_keywords") or {}
        out.append(f"- retrieval-level keyword extraction (`Dealer.qryr.question`): {len(keywords.get('keywords') or [])} term(s) {keywords.get('keywords')}")
    out.append("")

    # --- Top chunks ---------------------------------------------------------
    out.append("Top chunks:")
    out.append("")
    if not chunks:
        out.append("- NONE")
    else:
        out.append("| # | chunk id | designation | part | doc | section | rerank | fused | term | dense | kind | routes |")
        out.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for c in chunks:
            def num(value):
                return "-" if value is None else format(value, ".4f")

            out.append(
                f"| {c['rank']} | `{c['chunk_id'][:16]}` | {cell(c['designation'], 30)} | {cell(c['part'], 8)} | {cell(c['document'], 34)} | "
                f"{cell(c['section'], 26) or '-'} | {num(c.get('rerank_score', c.get('similarity')))} | {num(c.get('fused_similarity'))} | "
                f"{num(c['term_similarity'])} | {num(c['vector_similarity'])} | "
                f"{cell(c['score_kind'], 12) or '-'} | {len(c['routes'])} |"
            )
        out.append("")
        out.append("`rerank` is the score that ordered this window (`chunk['similarity']` after `rerank_chunks`); `fused` is the retrieval-side hybrid score it replaced, kept in `fused_similarity`; `term` / `dense` are the two retrieval legs. `kind` is `score_provenance.score_kind`, which still says `hybrid` after the reranker has overwritten the score.")
        out.append("")

    # --- Final context ------------------------------------------------------
    out.append("Final context:")
    out.append("")
    context = record.get("context") or {}
    if record.get("error"):
        out.append("- NOT AVAILABLE (retrieval failed)")
    else:
        out.append(f"- passages handed to the answer model: {context.get('blocks', 0)} of {len(chunks)} retrieved; {context.get('chars', 0)} characters")
        out.append(f"- designations in the window: {', '.join(context.get('designations') or []) or 'none'}")
        if context.get("truncated"):
            out.append("- **the token budget dropped passage(s) from the prompt** (rag.prompts.generator.kb_prompt)")
        out.append(f"- prompt template: `{context.get('prompt_source', 'unknown')}` with `{{knowledge}}` filled; answer budget {context.get('max_tokens')} tokens")
    out.append("")

    # --- Answer -------------------------------------------------------------
    out.append("Answer:")
    out.append("")
    answer = record.get("answer")
    if answer is None:
        out.append(f"- NOT_OBSERVABLE ({record.get('answer_error') or 'no answer model'})")
    else:
        out.append("```")
        out.append(str(answer).strip())
        out.append("```")
    out.append("")

    # --- Assessment ---------------------------------------------------------
    out.append("Assessment:")
    out.append("")
    out.append("- provenance: EXPLORATORY_JUDGMENT (deterministic evidence probe; NOT a Gold Set)")
    if in_context:
        present = sum(1 for f in in_context if f["present"])
        out.append(f"- expected facts supported by the final context: {present}/{len(in_context)}")
        for f in in_context:
            if f.get("kind") == "count":
                out.append(f"  - {'YES' if f['present'] else 'NO '} {f['fact']}: enumerated {f['observed']} distinct value(s), expected {f['expected']} [{', '.join(f['examples'])}]")
            else:
                out.append(f"  - {'YES' if f['present'] else 'NO '} {f['fact']}")
        if in_answer and answer is not None:
            grounded = sum(1 for f in in_answer if f["present"])
            out.append(f"- expected facts stated in the answer: {grounded}/{len(in_answer)}")
            stated = {f["fact"]: f["present"] for f in in_answer}
            missed = [f["fact"] for f in in_context if f.get("kind") != "count" and f["present"] and not stated.get(f["fact"], False)]
            unsupported = [f["fact"] for f in in_answer if f["present"] and not next((c["present"] for c in in_context if c["fact"] == f["fact"]), False)]
            if missed:
                out.append(f"- evidence was in context but not stated: {', '.join(missed)}")
            if unsupported:
                out.append(f"- **stated in the answer without a matching string in the retrieved context** (a probe verdict, not a grounding verdict: table markup or a derived count can put a fact in front of the model without the literal string): {', '.join(unsupported)}")
            if not missed and not unsupported:
                out.append("- every expected fact that reached the context is stated, and no stated fact lacks a match in the context")
    if record.get("retrieval_health"):
        out.append(f"- retrieval health: `{json.dumps(record['retrieval_health'], ensure_ascii=False)}`")
    for note in record.get("notes") or []:
        out.append(f"- {note}")
    out.append("")
    return out


def render(header: dict, records: list[dict]) -> str:
    out: list[str] = ["# Baseline", ""]
    out.append(f"Image: {header['image']}")
    out.append(f"Digest: {header['digest']}")
    out.append("")
    out.append(f"- captured at: {header['captured_at']} (UTC), inside container `{header['container']}`")
    out.append(f"- revision the image tag names: {header['revision']}")
    out.append("- deployed source, verified against the repository's git blobs:")
    for fact in header.get("deployed_source") or DEPLOYED_SOURCE_FACTS:
        out.append(f"  - {fact}")
    out.append(f"- deployed-code fingerprint (sha256, first 16): {header['fingerprint']['combined']}")
    for rel, value in header["fingerprint"]["modules"].items():
        out.append(f"  - {rel}: {value}")
    out.append("")
    out.append("Parameters:")
    out.append("")
    out.extend(render_parameters(header["observed"]))
    out.append("")

    out.append("## Trace coverage on this build")
    out.append("")
    out.append("| required signal | evidence class | note |")
    out.append("|---|---|---|")
    for row in COVERAGE:
        out.append(f"| {cell(row['signal'], 40)} | {row['cls']} | {cell(row['note'], 600)} |")
    out.append("")
    out.append("`PRODUCTION` = recorded from the deployed entry point; `CONTROLLED_VARIANT` = a leg-isolated call this script made, labelled where it appears; `NOT_OBSERVABLE` = the deployed code emits nothing for it.")
    out.append("")

    for qa, record in zip(QAS, records):
        out.extend(render_qa(qa, record))
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:
    import datetime

    # ---- re-render mode -------------------------------------------------------------------
    # Re-score and re-render an ALREADY CAPTURED run from its JSON sibling. No retrieval, no
    # model call, no database: the stored context and answer are the only inputs. This exists so
    # a corrected evidence probe can be applied to a capture without re-running it (a re-run
    # would re-invoke the decomposition model and could produce a different baseline).
    render_from = os.environ.get("TRACE_RENDER_FROM", "").strip()
    if render_from:
        payload = json.loads(pathlib.Path(render_from).read_text(encoding="utf-8"))
        header = payload["header"]
        header["deployed_source"] = list(DEPLOYED_SOURCE_FACTS)
        header["fingerprint"] = code_fingerprint()
        print(render(header, payload["records"]))
        return 0

    from common import settings

    settings.init_settings()
    from rag.nlp import rag_tokenizer
    from rag.prompts.generator import kb_prompt
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
        print(f"knowledge base {KB_ID} not found", file=sys.stderr)
        return 1
    tenant = str(getattr(kb, "tenant_id", "") or "")

    dialog = Dialog.get_or_none(Dialog.id == DIALOG_ID)
    if dialog is None:
        print(f"assistant {DIALOG_ID} not found", file=sys.stderr)
        return 1
    if KB_ID not in (dialog.kb_ids or []):
        print(f"assistant {DIALOG_ID} is not bound to {KB_ID}", file=sys.stderr)
        return 1

    # Models resolved exactly as dialog_service.get_models does.
    embd_mdl = LLMBundle(tenant, resolve_model_config(tenant, LLMType.EMBEDDING, kb.embd_id))
    rerank_mdl = resolve_rerank_mdl(tenant, dialog.rerank_id or "", dialog.tenant_rerank_id)
    chat_config = resolve_model_config(tenant, LLMType.CHAT, dialog.llm_id) if getattr(dialog, "llm_id", "") else get_tenant_default_model_by_type(tenant, LLMType.CHAT)
    try:
        chat_mdl = LLMBundle(tenant, chat_config)
    except Exception as exc:  # noqa: BLE001 - the answer layer is reported as unavailable, not hidden
        chat_mdl = None
        print(f"answer model unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)

    retriever = settings.retriever
    kbs = [kb]
    prompt_config = dialog.prompt_config or {}
    params = {
        "similarity_threshold": float(dialog.similarity_threshold),
        "vector_similarity_weight": float(dialog.vector_similarity_weight),
        "final_top_n": resolve_final_top_n(dialog.top_n),
        "knn_top_k": int(dialog.top_k),
        "rerank_candidates_count": int(getattr(dialog, "rerank_candidates_count", 30) or 30),
        "routes_top_k": resolve_routes_top_k(None),
        "doc_ids": None,  # meta_data_filter {} -> no derived document scope
    }
    max_tokens = (chat_config or {}).get("max_tokens") or 8192

    observed = {
        "kb_id": KB_ID,
        "kb_docs": int(getattr(kb, "doc_num", 0) or 0),
        "kb_chunks": int(getattr(kb, "chunk_num", 0) or 0),
        "tenant": tenant,
        "dialog_id": DIALOG_ID,
        "dialog_name": str(getattr(dialog, "name", "") or ""),
        "embedding": f"{kb.embd_id} via resolve_model_config -> LLMBundle({type(embd_mdl).__name__})",
        "rerank": ("NONE - reranking skipped, fused hybrid order used" if rerank_mdl is None else f"workspace default reranker (dialog.rerank_id is empty) -> {type(rerank_mdl).__name__}"),
        "chat_model": (getattr(chat_config, "get", lambda *_: None)("llm_name") or (chat_config or {}).get("model_name") or "NOT_OBSERVABLE") if chat_config else "NONE",
        **{k: params[k] for k in ("similarity_threshold", "vector_similarity_weight", "final_top_n", "knn_top_k", "rerank_candidates_count")},
        "rank_feature": "label_question() - None unless the knowledge base configures tag_kb_ids (recorded per QA)",
    }

    records: list[dict] = []
    for qa in QAS:
        question = qa["question"]
        record: dict = {"question": question, "notes": []}

        # Retrieval-level keyword extraction, reproduced from the deployed tokenizer.
        # ``qryr.question`` returns (MatchTextExpr, keywords): the lexical expression the
        # document store is asked for, plus the keyword list it was built from.
        try:
            lexical_query, keywords = retriever.qryr.question(question)
            record["retrieval_keywords"] = {
                "lexical_matching_text": one_line(getattr(lexical_query, "matching_text", "") or "", 600),
                "lexical_fields": list(getattr(lexical_query, "fields", []) or []),
                "keywords": list(keywords or []),
                "note": "CONTROLLED_VARIANT: recomputed offline from the deployed tokenizer; no deployed call returns this value",
            }
        except Exception as exc:  # noqa: BLE001
            record["retrieval_keywords"] = {"error": f"{type(exc).__name__}: {exc}"}

        try:
            result, dropped, sent = await call_production(
                question,
                retriever=retriever,
                embd_mdl=embd_mdl,
                rerank_mdl=rerank_mdl,
                chat_mdl=chat_mdl,
                tenant=tenant,
                kb_ids=[KB_ID],
                params=params,
                kbs=kbs,
            )
            if dropped:
                record["notes"].append(f"the deployed signature does not accept {dropped}; not sent")
            if sent.get("rank_feature") is None:
                record["notes"].append("rank_feature resolved to None (no tag_kb_ids on this knowledge base)")
            chunks = [describe(c, i) for i, c in enumerate(result.get("chunks") or [], 1)]
            record["production"] = {
                "total": result.get("total"),
                "retrieval_mode": result.get("retrieval_mode", "HYBRID"),
                "chunks": chunks,
                "raw": [slim(c) for c in result.get("chunks") or []],
                "doc_aggs": result.get("doc_aggs") or [],
                "generic_fallback": result.get("generic_fallback"),
            }
            if result.get("retrieval_mode") == "LEXICAL_DEGRADED":
                record["notes"].append("PRODUCTION ran LEXICAL_DEGRADED: the dense leg was unavailable, so `vector_similarity` is absent and ranking is lexical")
            if result.get("route_execution"):
                failed = [r for r in result["route_execution"] if r.get("failed")]
                if failed:
                    record["notes"].append(f"{len(failed)} route(s) failed: {[r['query'][:60] for r in failed]}")
            if result.get("generic_fallback"):
                record["notes"].append(f"cross-part fallback fired: {json.dumps(result['generic_fallback'], ensure_ascii=False)}")
            # Retrieval health: the deployed shape may be a dataclass or a dict.
            health = result.get("retrieval_health")
            if health is not None:
                record["retrieval_health"] = health_view(health)

            # Evidence match against the benchmark's own expected-evidence strings.
            record["evidence_match"] = {item: evidence_probe(item, chunks) for item in qa["evidence"]}
        except Exception as exc:  # noqa: BLE001 - a trace records the failure, it does not hide it
            record["error"] = f"{type(exc).__name__}: {exc}"
            record["production"] = {"chunks": []}

        # CONTROLLED_VARIANT legs: one value changed, everything else the assistant's own.
        record["legs"] = {}
        for label, weight in (("lexical_only", 0.0), ("dense_only", 1.0), ("configured_weight", params["vector_similarity_weight"])):
            try:
                variant = await call_variant(question, retriever=retriever, embd_mdl=embd_mdl, tenant=tenant, kb_ids=[KB_ID], params=params, weight=weight)
                rows = ids_of(variant)
                record["legs"][label] = {
                    "weight": weight,
                    "returned": len(rows),
                    "ids": rows,
                    "mode": variant.get("retrieval_mode", "HYBRID"),
                    "top": [
                        {"rank": i, "id": (c.get("chunk_id") or "")[:16], "designation": designation_of(c), "similarity": round(float(c.get("similarity") or 0.0), 4)}
                        for i, c in enumerate((variant.get("chunks") or [])[:10], 1)
                    ],
                }
            except Exception as exc:  # noqa: BLE001
                record["legs"][label] = {"weight": weight, "error": f"{type(exc).__name__}: {exc}"}
        prod_ids = ids_of({"chunks": (record["production"].get("chunks") or [])})
        hybrid = record["legs"].get("configured_weight") or {}
        if prod_ids and hybrid.get("ids"):
            overlap = len(set(prod_ids) & set(hybrid["ids"][: len(prod_ids)]))
            record["notes"].append(f"production window overlap with the same-weight Dealer.retrieval leg: {overlap}/{len(prod_ids)} (the two differ by route count and by the reranker)")

        # Final context: the production prompt builder, verbatim, over the retrieved chunks.
        chunks = record["production"].get("chunks") or []
        raw = record["production"].get("raw") or []
        blocks = []
        if raw:
            try:
                blocks = kb_prompt({"chunks": raw}, max_tokens)
            except Exception as exc:  # noqa: BLE001
                record["notes"].append(f"kb_prompt failed: {type(exc).__name__}: {exc}")
        context_text = "\n\n------\n\n".join(blocks)
        record["context"] = {
            "blocks": len(blocks),
            "chars": len(context_text),
            "max_tokens": max_tokens,
            "prompt_source": "dialog.prompt_config['system']" if prompt_config.get("system") else "cable_defaults.SYSTEM_PROMPT",
            "truncated": bool(blocks) and len(blocks) < len(chunks),
            "designations": sorted({c["designation"] for c in chunks}),
            "text": context_text,
        }
        record["facts_in_context"] = fact_probe(qa["facts"], context_text)

        # Answer: the assistant's OWN system prompt, with {knowledge} filled the way
        # dialog_service fills it (the row's prompt wins; cable_defaults is only the fallback).
        if chat_mdl is not None:
            system = str(prompt_config.get("system") or getattr(cable_defaults, "SYSTEM_PROMPT", "") or "")
            record["notes"].append("answer prompt: dialog.prompt_config['system']" if prompt_config.get("system") else "answer prompt: cable_defaults.SYSTEM_PROMPT (the row carries no system prompt)")
            date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            try:
                rendered = system.replace("{knowledge}", "\n------\n" + context_text if context_text else " ").replace("{date}", date)
                answer = await chat_mdl.async_chat(rendered, [{"role": "user", "content": question}])
                if isinstance(answer, tuple):
                    answer = answer[0]
                record["answer"] = str(answer)
                record["facts_in_answer"] = fact_probe(qa["facts"], record["answer"])
            except Exception as exc:  # noqa: BLE001
                record["answer"] = None
                record["answer_error"] = f"{type(exc).__name__}: {exc}"
        else:
            record["answer"] = None
            record["answer_error"] = "no chat model resolved for this tenant"

        records.append(record)

    header = {
        "image": IMAGE,
        "digest": DIGEST,
        "revision": SOURCE_REVISION,
        "container": os.environ.get("HOSTNAME", "unknown"),
        "captured_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fingerprint": code_fingerprint(),
        "deployed_source": list(DEPLOYED_SOURCE_FACTS),
        "observed": observed,
    }

    report = render(header, records)
    try:
        pathlib.Path(JSON_OUT).write_text(json.dumps({"header": header, "records": records}, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as exc:
        print(f"JSON dump failed: {exc}", file=sys.stderr)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
