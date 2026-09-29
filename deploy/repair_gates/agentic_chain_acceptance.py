"""NON-PERSISTENT end-to-end acceptance of the rerank reservation-contract repair.

Drives the REAL agentic entry point (``run_agentic_rag`` -> ``build_agentic_graph`` ->
... -> ``_compose_answer_from_evidence``) for the exact persisted request, and captures
every boundary the acceptance contract names:

  B1 route results
  B2 merged candidate pool
  B3 before select_context        (the ordered pool handed to select_context)
  B4 after  select_context
  B5 normalized Agentic return    (hybrid_search return / tools.kbinfos)
  B6 memory store                 (tools.kbinfos["memory"], filled by harness.memory.add)
  B7 compose evidence             (kb_prompt over the cite pool the composer numbers)
  B8 final model prompt           (system + history handed to the answer model)
  B9 final answer                 (think/answer split, then the citation post-processing)

Request binding is READ from the datastore (never assumed):
  conversation c737275ebae611f19c26b16ea36f75b8
  message      18bb69bf-0e11-4bf2-9d1a-2b1966c98159   (role=user)
  assistant    ccddcfdeba3a11f1a4910547a12ee1d1
The question is used verbatim. Nothing is persisted: this script never writes a
conversation, message or answer row; it only drives the in-process graph.

INSTRUMENTATION NOTE — why ``patch_everywhere``: the retrieval helpers are reached
through *both* module-attribute calls and direct ``from X import Y`` bindings
(``pipeline`` imports ``merge_route_hits`` / ``rerank_chunks`` by name, ``search``
imports ``retrieve_multi_route`` by name). Patching only the defining module leaves
those bound aliases untouched and silently observes nothing, so every binding of the
defining function object is replaced.

Output: $CHAIN_OUT/agentic_chain_acceptance.json (+ final_answer.txt, final_prompt.txt,
compose_evidence.txt, raw UTF-8).
"""
import asyncio
import json
import os
import pathlib
import sys
import time

sys.path.insert(0, "/ragflow")

from common import settings

settings.init_settings()

from api.db.db_models import Conversation, Dialog  # noqa: E402
from api.db.joint_services.tenant_model_service import (  # noqa: E402
    get_tenant_default_model_by_type,
    resolve_model_config,
)
from api.db.services.llm_service import LLMBundle  # noqa: E402
from common.constants import LLMType  # noqa: E402

CONV = "c737275ebae611f19c26b16ea36f75b8"
MSG = "18bb69bf-0e11-4bf2-9d1a-2b1966c98159"
ASSISTANT = "ccddcfdeba3a11f1a4910547a12ee1d1"
TARGET, CONTROL = "d1d75672f2dbc333", "b5aaf72bcd33d44a"

# Distinctive spec tokens: the TARGET chunk (Part 3 Table 1) is the only passage that
# enumerates three-core sizes; the CONTROL (Part 2 Table 1) enumerates single-core.
TARGET_MARKERS = ["3×400", "3×630", "3×1600"]
CONTROL_MARKERS = ["1×400", "1×2000"]

OUT = pathlib.Path(os.environ.get("CHAIN_OUT", "/out"))
OUT.mkdir(parents=True, exist_ok=True)

conv = Conversation.get_or_none(Conversation.id == CONV)
_conv_msgs = conv.message if isinstance(conv.message, list) else json.loads(conv.message or "[]")
_question_msg = next(m for m in _conv_msgs if str(m.get("id")) == MSG)
QUESTION = _question_msg["content"]
# Sanity arm only: an explicit override lets the SAME harness drive an ordinary,
# non-comparative question through the identical code path. Unset => bound request.
# B64 form is preferred: the console mangles CJK in transit, base64 does not.
_override = os.environ.get("CHAIN_QUESTION")
_b64 = os.environ.get("CHAIN_QUESTION_B64")
if _b64:
    import base64 as _b64mod

    _override = _b64mod.b64decode(_b64).decode("utf-8")
QUESTION_SOURCE = "persisted message " + MSG
if _override:
    QUESTION = _override
    QUESTION_SOURCE = ("CHAIN_QUESTION_B64 override" if _b64 else "CHAIN_QUESTION override")
dialog = Dialog.get_or_none(Dialog.id == ASSISTANT)

# The real caller (agentic_rag.RAGTools.rag) builds a SINGLE-message list from the
# effective question and calls ``run_agentic_rag(self, messages)`` with no gen_conf,
# so the replay passes exactly that — no conversation history, no model overrides.
MESSAGES = [{"role": "user", "content": QUESTION}]

B1, B2, B3, B4, B5 = {}, {}, {}, {}, {}
MEMORY, EVIDENCE, PROMPTS, PATCHED = {}, {}, [], {}
RERANK_CHUNKS, ROUTE_TEXTS, POLICY, RUNTIME, MERGE_META = {}, [], {}, {}, []
SEARCH_CALLS = {}


def ids_of(obj):
    out, chunks = [], None
    if isinstance(obj, dict):
        chunks = obj.get("chunks") or obj.get("hits")
    elif hasattr(obj, "chunks"):
        chunks = getattr(obj, "chunks")
    elif hasattr(obj, "ids"):
        return [str(i)[:16] for i in (obj.ids or [])]
    if isinstance(chunks, dict):
        chunks = chunks.get("hits")
    if isinstance(chunks, list):
        for c in chunks:
            if isinstance(c, dict):
                cid = c.get("chunk_id") or c.get("id") or c.get("_id")
                if cid:
                    out.append(str(cid)[:16])
    return out


def report(bucket, ids):
    ids = [i for i in ids if i]
    bucket.setdefault("calls", [])
    bucket["calls"].append({"n": len(ids),
                            "target": (ids.index(TARGET) + 1) if TARGET in ids else None,
                            "control": (ids.index(CONTROL) + 1) if CONTROL in ids else None,
                            "ids": ids if len(ids) <= 40 else ids[:40]})


def markers(text):
    text = text or ""
    return {"target_markers": {m: text.count(m) for m in TARGET_MARKERS},
            "control_markers": {m: text.count(m) for m in CONTROL_MARKERS},
            "target_present": any(text.count(m) for m in TARGET_MARKERS),
            "control_present": any(text.count(m) for m in CONTROL_MARKERS)}


def patch_everywhere(original, replacement, label):
    """Replace every binding of ``original`` in every loaded module.

    A direct ``from X import Y`` copies the function object into the importer's
    namespace, so patching only the defining module leaves live aliases behind.
    """
    n = 0
    for mod in list(sys.modules.values()):
        d = getattr(mod, "__dict__", None)
        if not isinstance(d, dict):
            continue
        for name, val in list(d.items()):
            if val is original:
                try:
                    setattr(mod, name, replacement)
                    n += 1
                except Exception:  # noqa: BLE001
                    pass
    PATCHED[label] = n
    return n


def policy_summary(policy):
    return {"compared_documents": sorted(policy.compared_documents),
            "max_document_share": policy.max_document_share,
            "max_table_share": policy.max_table_share,
            "min_prose": policy.min_prose,
            "table_penalty": policy.table_penalty,
            "question_values": sorted(policy.question_values)}


def instrument():
    from rag.advanced_rag.harness import memory as mem_mod
    from rag.advanced_rag.harness.tools import search as search_tool
    from rag.retrieval import multi_route as mr
    from rag.retrieval import pipeline as pipe
    from rag.retrieval import rerank as rr

    # B1 — every route's raw result.
    original_route = mr._retrieve_route

    async def route(*a, **k):
        res = await original_route(*a, **k)
        report(B1, ids_of(res))
        return res

    patch_everywhere(original_route, route, "multi_route._retrieve_route")

    # B2 — the merged candidate pool.
    original_merge = mr.merge_route_hits

    def merge(hits, existing=None, *a, **k):
        out = original_merge(hits, existing, *a, **k)
        MERGE_META.append({"existing_n": len(ids_of(existing)) if existing else 0,
                           "hits_n": len(ids_of({"chunks": list(hits)})) if hits else 0})
        report(B2, ids_of(out))
        return out

    patch_everywhere(original_merge, merge, "merge_route_hits")

    # B3 / B4 — the ordered pool handed to select_context, and what it returns.
    original_select = rr.select_context

    def select(ordered, top_n, policy):
        POLICY.clear()
        POLICY.update(policy_summary(policy))
        report(B3, [str(c.get("chunk_id"))[:16] for c in ordered])
        B3["top_n"] = top_n
        chosen = original_select(ordered, top_n, policy)
        report(B4, [str(c.get("chunk_id"))[:16] for c in chosen])
        return chosen

    patch_everywhere(original_select, select, "rerank.select_context")

    # Cross-check: the pool pipeline hands on after the rerank/cut stage.
    original_rerank_chunks = rr.rerank_chunks

    async def rerank_chunks(*a, **k):
        out = await original_rerank_chunks(*a, **k)
        RERANK_CHUNKS["calls"] = RERANK_CHUNKS.get("calls", 0) + 1
        RERANK_CHUNKS["rerank_mdl_present"] = a[0] is not None if a else None
        RERANK_CHUNKS["final_top_n"] = a[3] if len(a) > 3 else k.get("final_top_n")
        RERANK_CHUNKS["last_ids"] = [str(c.get("chunk_id"))[:16] for c in (out or [])]
        RERANK_CHUNKS["target_present"] = TARGET in RERANK_CHUNKS["last_ids"]
        RERANK_CHUNKS["control_present"] = CONTROL in RERANK_CHUNKS["last_ids"]
        return out

    patch_everywhere(original_rerank_chunks, rerank_chunks, "rerank.rerank_chunks")

    # B0 — the query text and settings the search tool actually hands to the pipeline.
    original_rmr = search_tool.retrieve_multi_route

    async def rmr(*a, **k):
        RUNTIME["formalized_query_text"] = k.get("question")
        RUNTIME["formalized_query_is_published"] = (k.get("question") == QUESTION)
        RUNTIME["rmr_kwargs"] = {
            kk: (str(kk_v)[:120] if not isinstance(kk_v, (int, float, bool, type(None))) else kk_v)
            for kk, kk_v in k.items()
            if kk in ("similarity_threshold", "vector_similarity_weight", "final_top_n",
                      "routes_top_k", "knn_top_k", "rerank_candidates_count", "doc_ids",
                      "kb_ids")}
        return await original_rmr(*a, **k)

    patch_everywhere(original_rmr, rmr, "search.retrieve_multi_route")

    # B5 — the normalized return of hybrid_search (what the rest of the harness sees).
    original_norm = search_tool._normalize

    def normalize(kb, tenant_ids, *a, **k):
        out = original_norm(kb, tenant_ids, *a, **k)
        if isinstance(out, dict):
            report(B5, [str(c.get("chunk_id"))[:16] for c in (out.get("chunks") or [])])
        return out

    patch_everywhere(original_norm, normalize, "search._normalize")

    # B6 — the memory store, snapshotted per memory.add() call.
    original_mem_add = mem_mod.add

    def mem_add(tools, chunks):
        out = original_mem_add(tools, chunks)
        mem = (getattr(tools, "kbinfos", None) or {}).get("memory") or []
        ids = [str(c.get("chunk_id"))[:16] for c in mem]
        MEMORY.setdefault("calls", []).append(
            {"n": len(ids), "target": (ids.index(TARGET) + 1) if TARGET in ids else None,
             "control": (ids.index(CONTROL) + 1) if CONTROL in ids else None})
        MEMORY["final_ids"] = ids
        MEMORY["target_present"] = TARGET in ids
        MEMORY["control_present"] = CONTROL in ids
        return out

    patch_everywhere(original_mem_add, mem_add, "memory.add")

    # B7 — the compose evidence exactly as rendered for the answer model.
    import rag.advanced_rag.agentic_rag_graph as G  # noqa: E402

    original_kb_prompt = G.kb_prompt

    def kb_prompt(kbinfos, budget):
        rendered = original_kb_prompt(kbinfos, budget)
        text = "\n".join(rendered) if isinstance(rendered, list) else str(rendered)
        chunks = kbinfos.get("chunks") or []
        ids = [str(c.get("chunk_id"))[:16] for c in chunks]
        EVIDENCE.update({"n_chunks": len(chunks), "ids": ids,
                         "target_present": TARGET in ids, "control_present": CONTROL in ids,
                         "rendered_chars": len(text), "budget": budget})
        EVIDENCE.update(markers(text))
        EVIDENCE["rendered_text"] = text
        return rendered

    patch_everywhere(original_kb_prompt, kb_prompt, "agentic_rag_graph.kb_prompt")

    # B7b — the cite-pool ids the composer numbered over.
    original_compose = G._compose_answer_from_evidence

    async def compose(state, tools, token_queue, answer_conf):
        res = await original_compose(state, tools, token_queue, answer_conf)
        ids = [str(i) for i in (getattr(tools, "_rag_cite_chunk_ids", None) or [])]
        EVIDENCE["cite_chunk_ids"] = ids
        EVIDENCE["cite_target"] = TARGET in ids
        EVIDENCE["cite_control"] = CONTROL in ids
        return res

    patch_everywhere(original_compose, compose, "agentic_rag_graph._compose_answer_from_evidence")

    # B8 — the exact system + history handed to the answer model.
    original_stream = LLMBundle.async_chat_streamly_delta

    def stream(self, system, history, gen_conf=None, **kw):
        rec = {"system": system if isinstance(system, str) else str(system),
               "history": [{"role": h.get("role"), "content": h.get("content")}
                           for h in (history or [])]}
        flat = rec["system"] + "\n" + "\n".join(h["content"] or "" for h in rec["history"])
        rec["chars"] = len(flat)
        rec["is_compose"] = ("Evidence:" in flat and "Question:" in flat)
        rec.update(markers(flat))
        PROMPTS.append(rec)
        return original_stream(self, system, history, gen_conf or {}, **kw)

    patch_everywhere(original_stream, stream, "LLMBundle.async_chat_streamly_delta")
    # The module sweep cannot reach a class attribute (classes are values in module
    # dicts, not names bound to the function), so bind the method explicitly.
    LLMBundle.async_chat_streamly_delta = stream

    # route texts as actually sent to ES
    store = settings.docStoreConn
    original_once = store._es_search_once

    def once(*a, **k):
        body = a[1] if len(a) > 1 else None
        if isinstance(body, dict):
            for m in ((body.get("query") or {}).get("bool", {}).get("must") or []):
                qs = (m or {}).get("query_string") or {}
                if qs.get("query"):
                    ROUTE_TEXTS.append(qs["query"][:120])
        return original_once(*a, **k)

    store._es_search_once = once
    PATCHED["docStoreConn._es_search_once"] = 1

    # Decisive attribution: which search entry points does the agentic graph actually
    # call? Counting them (rather than assuming) is what proves whether the boundary
    # under test is even on the executed path.
    def _counter(orig, name):
        async def _w(*a, **k):
            SEARCH_CALLS[name] = SEARCH_CALLS.get(name, 0) + 1
            return await orig(*a, **k)
        return _w

    for _fname in ("hybrid_search", "vector_search", "bm25_search", "metadata_search",
                   "grep_search", "structured_query", "list_chunks"):
        _orig = getattr(search_tool, _fname, None)
        if _orig is None or not asyncio.iscoroutinefunction(_orig):
            continue
        patch_everywhere(_orig, _counter(_orig, _fname), f"count:{_fname}")


async def main():
    instrument()

    from api.db.services.doc_metadata_service import DocMetadataService
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from common.metadata_utils import apply_meta_data_filter
    from rag.advanced_rag.agentic_rag import RAGTools
    from rag.advanced_rag.agentic_rag_graph import run_agentic_rag
    from rag.advanced_rag.harness.config import THINKING_MODES

    prompt_config = dialog.prompt_config or {}

    kbs = KnowledgebaseService.get_by_ids(dialog.kb_ids)
    embd_owner_tenant_id = kbs[0].tenant_id
    embd_mdl = LLMBundle(embd_owner_tenant_id,
                         resolve_model_config(embd_owner_tenant_id, LLMType.EMBEDDING, kbs[0].embd_id))
    chat_mdl = LLMBundle(dialog.tenant_id,
                         get_tenant_default_model_by_type(dialog.tenant_id, LLMType.CHAT))

    _mode_labels = list(THINKING_MODES.keys())
    try:
        _n = int(str(_question_msg.get("reasoning")).strip())
        thinking_mode = _mode_labels[_n - 1] if 1 <= _n <= len(_mode_labels) else "medium"
    except (TypeError, ValueError):
        thinking_mode = "medium"

    doc_scope = None
    if _question_msg.get("doc_ids"):
        doc_scope = [d for d in _question_msg["doc_ids"] if d]
    if dialog.meta_data_filter:
        doc_scope = await apply_meta_data_filter(
            dialog.meta_data_filter, None, QUESTION, chat_mdl, doc_scope,
            kb_ids=dialog.kb_ids,
            metas_loader=lambda: DocMetadataService.get_flatted_meta_by_kbs(dialog.kb_ids),
        )

    from api.db.services.dialog_service import _render_reasoning_system_prompt
    try:
        system_prompt = _render_reasoning_system_prompt(dialog, prompt_config, {})
    except Exception:  # noqa: BLE001
        system_prompt = prompt_config.get("system", "") or ""

    tools = RAGTools(
        [dialog.tenant_id],
        chat_mdl,
        embed_mdl=embd_mdl,
        kb_ids=list(dialog.kb_ids or []),
        web_search=None,
        meta_data_filter=dialog.meta_data_filter,
        doc_scope=doc_scope,
        empty_response=prompt_config.get("empty_response", ""),
        do_refer=False,
        thinking_mode=thinking_mode,
        text_attachments_content=None,
        system_prompt=system_prompt,
        similarity_threshold=dialog.similarity_threshold,
        vector_similarity_weight=dialog.vector_similarity_weight,
        top_n=dialog.top_n,
        rerank_candidates_count=dialog.rerank_candidates_count,
        top_k=dialog.top_k,
    )

    RUNTIME.update({
        "assistant": ASSISTANT, "assistant_name": dialog.name,
        "published_question": QUESTION, "question_len": len(QUESTION),
        "question_source": QUESTION_SOURCE,
        "messages_passed": MESSAGES, "reasoning_kwarg": _question_msg.get("reasoning"),
        "thinking_mode": thinking_mode,
        "rerank_id": getattr(dialog, "rerank_id", None) or None,
        "rerank_model": "absent" if not getattr(dialog, "rerank_id", None) else "present",
        "rerank_candidates_count": dialog.rerank_candidates_count,
        "final_top_n": dialog.top_n, "top_k": dialog.top_k,
        "similarity_threshold": dialog.similarity_threshold,
        "vector_similarity_weight": dialog.vector_similarity_weight,
        "kb_ids": list(dialog.kb_ids or []),
        "meta_data_filter": getattr(dialog, "meta_data_filter", None),
        "metadata_doc_scope": list(doc_scope or []) or None,
        "embed_mdl_present": embd_mdl is not None,
        "system_prompt_len": len(system_prompt or ""),
        "llm_setting": dialog.llm_setting or {},
    })

    t0 = time.time()
    tokens, logs = [], []
    # Exactly the real call: run_agentic_rag(self, messages) — no gen_conf override.
    async for tok in run_agentic_rag(tools, MESSAGES, max_loops=3):
        if isinstance(tok, str) and tok.startswith("[") and "]" in tok[:40]:
            logs.append(tok)
        else:
            tokens.append(tok if isinstance(tok, str) else str(tok))
    RUNTIME["elapsed_s"] = round(time.time() - t0, 1)
    RUNTIME["log_lines"] = len(logs)

    # De-interleave think vs answer exactly as the real path does, then apply the
    # same three post-processing steps RAGTools.rag applies to the answer stream.
    import re as _re

    from rag.advanced_rag.agentic_rag import (
        _expand_range_citation_markers,
        _repair_slot_citation_markers,
        _split_think_stream,
    )

    async def _replay():
        for _t in tokens:
            yield _t

    ANSWER, THINK = "", ""
    async for kind, delta in _split_think_stream(_replay()):
        if kind == "answer":
            ANSWER += delta
        else:
            THINK += delta
    RAW_ANSWER = ANSWER
    ANSWER = _re.sub(r"\(\**(ID:\d+)\**\)", r"[\1]", ANSWER)
    ANSWER = _repair_slot_citation_markers(
        ANSWER, getattr(tools, "_rag_slot_evidence", None) or {},
        getattr(tools, "_rag_cite_chunk_ids", None) or [])
    ANSWER = _expand_range_citation_markers(
        ANSWER, len(getattr(tools, "_rag_cite_chunk_ids", None) or []))
    RUNTIME["answer_postprocessed"] = ANSWER != RAW_ANSWER
    RUNTIME["think_chars"] = len(THINK)
    RUNTIME["slot_evidence_n"] = len(getattr(tools, "_rag_slot_evidence", None) or {})
    RUNTIME["verdict"] = (getattr(tools, "_rag_verdict", None) or {}).get("status") \
        if isinstance(getattr(tools, "_rag_verdict", None), dict) else None

    # The pool the harness ends with (union across every search the graph issued).
    pooled = (getattr(tools, "kbinfos", None) or {}).get("chunks") or []
    pool_ids = [str(c.get("chunk_id"))[:16] for c in pooled]
    post = {"n": len(pool_ids),
            "target": (pool_ids.index(TARGET) + 1) if TARGET in pool_ids else None,
            "control": (pool_ids.index(CONTROL) + 1) if CONTROL in pool_ids else None,
            "ids": pool_ids}

    compose_prompts = [p for p in PROMPTS if p["is_compose"]]
    last_compose = compose_prompts[-1] if compose_prompts else None

    out = {
        "runtime": RUNTIME, "policy": POLICY, "patched": PATCHED,
        "boundaries": {
            "B1_route_results": B1, "B2_merged_pool": B2, "B3_before_select_context": B3,
            "B4_after_select_context": B4, "B5_normalized_agentic_return": B5,
            "B6_memory": MEMORY,
            "B7_compose_evidence": {k: v for k, v in EVIDENCE.items() if k != "rendered_text"},
            "B8_final_prompt_summary": last_compose,
        },
        "rerank_chunks": RERANK_CHUNKS,
        "search_calls": SEARCH_CALLS,
        "merge_meta": MERGE_META,
        "post_run_pool": post,
        "route_texts": ROUTE_TEXTS,
        "llm_calls": len(PROMPTS),
        "logs": logs[-40:],
        "final_answer": ANSWER,
        "final_answer_markers": markers(ANSWER),
    }
    (OUT / "agentic_chain_acceptance.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "final_answer.txt").write_text(ANSWER, encoding="utf-8")
    (OUT / "final_prompt.txt").write_text(
        (last_compose["system"] + "\n\n===HISTORY===\n"
         + "\n".join(h["content"] or "" for h in last_compose["history"]))
        if last_compose else "", encoding="utf-8")
    (OUT / "compose_evidence.txt").write_text(EVIDENCE.get("rendered_text", ""), encoding="utf-8")

    # ASCII-only summary so the console never mangles or hides a result.
    print("RERANK CHAIN ACCEPTANCE")
    print("assistant        :", RUNTIME["assistant_name"], ASSISTANT)
    print("thinking_mode    :", thinking_mode, "| rerank_model:", RUNTIME["rerank_model"],
          "| embed_mdl:", RUNTIME["embed_mdl_present"])
    print("final_top_n      :", RUNTIME["final_top_n"], "| cands:", RUNTIME["rerank_candidates_count"],
          "| vsim_w:", RUNTIME["vector_similarity_weight"])
    print("query_is_exact   :", RUNTIME.get("formalized_query_is_published"))
    print("elapsed_s        :", RUNTIME["elapsed_s"], "| llm_calls:", len(PROMPTS))
    print("patched_bindings :", json.dumps(PATCHED))
    print("search_calls     :", json.dumps(SEARCH_CALLS))
    for name, b in out["boundaries"].items():
        if name == "B8_final_prompt_summary":
            if b:
                print(f"{name}: compose prompt chars={b['chars']} target_markers={b['target_markers']} "
                      f"control_markers={b['control_markers']}")
            continue
        if name == "B6_memory":
            print(f"{name}: calls={len(b.get('calls', []))} TARGET_present={b.get('target_present')} "
                  f"CONTROL_present={b.get('control_present')} memory_n={len(b.get('final_ids') or [])}")
            continue
        if name == "B7_compose_evidence":
            print(f"{name}: n_chunks={b.get('n_chunks')} cite_target={b.get('cite_target')} "
                  f"cite_control={b.get('cite_control')} target_present={b.get('target_present')} "
                  f"chars={b.get('rendered_chars')}")
            continue
        calls = b.get("calls", [])
        tgt = [c["target"] for c in calls if c["target"]]
        ctl = [c["control"] for c in calls if c["control"]]
        print(f"{name}: calls={len(calls)} TARGET_present={bool(tgt)} ranks={tgt[:8]} CONTROL ranks={ctl[:8]}")
        for n, c in enumerate(calls, 1):
            print(f"     call{n:2d} n={c['n']:3d} target={c['target']} control={c['control']}")
    print("rerank_chunks    :", json.dumps(RERANK_CHUNKS, ensure_ascii=False))
    print("post_run_pool    : n=%d target=%s control=%s" % (post["n"], post["target"], post["control"]))
    print("answer_markers   :", json.dumps(out["final_answer_markers"], ensure_ascii=False))
    print("answer_len       :", len(ANSWER))
    print("answer_head      :", ANSWER[:400].encode("unicode_escape").decode("ascii"))


try:
    asyncio.run(main())
except Exception as exc:  # noqa: BLE001
    import traceback
    (OUT / "chain_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
    print("CHAIN ACCEPTANCE FAILED:", type(exc).__name__, str(exc)[:300])
    raise
