"""One-run binding trace for the original QGDW question on CURRENT production code/config.

Wraps every pipeline boundary the retrieval path actually resolves, records where the pinned TARGET
(`d1d75672f2dbc333`, Part 3 three-core Table 1) and the CONTROL (`b5aaf72bcd33d44a`, Part 2 single-core
Table 1) are present, and captures the FULL final context bodies plus the exact `kb_prompt` model
context after token budgeting.

Every wrapper DELEGATES to the original and only observes - no logic, ordering, threshold or parameter is
changed. Read-only against the datastores; `async_chat` persists no conversation rows.
"""
import asyncio
import hashlib
import inspect
import json
import pathlib
import sys

sys.path.insert(0, "/ragflow")

from common import settings  # noqa: E402

settings.init_settings()

from api.db.db_models import Dialog  # noqa: E402
from api.db.services import dialog_service as ds  # noqa: E402
from rag.nlp import search as rag_search  # noqa: E402
from rag.retrieval import multi_route as mr  # noqa: E402
from rag.retrieval import rerank as rr  # noqa: E402
from rag.retrieval.chunk_profile import _body_text, is_table_chunk  # noqa: E402

DIALOG_ID = "29a6da60ba1f11f1be9555eabe501d5b"
QUESTION = "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"
TARGET, CONTROL = "d1d75672f2dbc333", "b5aaf72bcd33d44a"
OUT = pathlib.Path("/tmp/binding_trace.json")

STAGES = []
KB_PROMPT = {}
FINAL_KBINFOS = {}
RETRIEVAL_REQUEST = {}


def ids_of(obj, depth=0):
    """Best-effort id extraction across the shapes the boundaries return.

    Handles the elasticsearch-py `ObjectApiResponse` the doc-store search returns (a dict-like with
    `hits.hits[]._id`), which is what the raw candidate window looks like.
    """
    if depth > 3 or obj is None:
        return []
    # ES response / any mapping with hits.hits
    try:
        hits = obj.get("hits") if hasattr(obj, "get") else None
    except Exception:  # noqa: BLE001
        hits = None
    if isinstance(hits, dict) and isinstance(hits.get("hits"), list):
        return [str(h.get("_id") or (h.get("_source") or {}).get("chunk_id") or "")[:16] for h in hits["hits"]]
    if isinstance(obj, (list, tuple)):
        out = []
        for item in obj:
            if isinstance(item, dict):
                cid = item.get("chunk_id") or item.get("id") or item.get("_id")
                if cid:
                    out.append(str(cid)[:16])
        return out
    if isinstance(obj, dict):
        for key in ("chunks", "hits", "ids", "documents"):
            if key in obj:
                got = ids_of(obj[key], depth + 1)
                if got:
                    return got
        cid = obj.get("chunk_id") or obj.get("id") or obj.get("_id")
        return [str(cid)[:16]] if cid else []
    for attr in ("ids", "chunks"):
        got = ids_of(getattr(obj, attr, None), depth + 1)
        if got:
            return got
    return []


def record(stage, ids):
    ids = [i for i in ids if i]
    STAGES.append({
        "stage": stage,
        "count": len(ids),
        "target_rank": (ids.index(TARGET) + 1) if TARGET in ids else None,
        "control_rank": (ids.index(CONTROL) + 1) if CONTROL in ids else None,
    })


def patch(module, name, wrapper):
    original = getattr(module, name)
    setattr(module, name, wrapper)
    for other in (ds, mr, rr, rag_search):
        if getattr(other, name, None) is original:
            setattr(other, name, wrapper)
    return original


def wrap(stage, original, extractor=ids_of):
    def wrapper(*args, **kwargs):
        result = original(*args, **kwargs)
        if inspect.isawaitable(result):
            async def go():
                resolved = await result
                try:
                    record(stage, extractor(resolved))
                except Exception as exc:  # noqa: BLE001
                    record(stage, [f"<extract-error {type(exc).__name__}>"])
                return resolved
            return go()
        record(stage, extractor(result))
        return result
    return wrapper


def main():
    dialog = Dialog.get_or_none(Dialog.id == DIALOG_ID)
    es_shapes = []

    def es_wrapper(original):
        def wrapper(*args, **kwargs):
            result = original(*args, **kwargs)
            if inspect.isawaitable(result):
                async def go():
                    resolved = await result
                    ids = ids_of(resolved)
                    es_shapes.append({"shape": type(resolved).__name__, "len": len(resolved) if hasattr(resolved, "__len__") else None,
                                      "extracted": len(ids), "repr": repr(resolved)[:200]})
                    record("S1_raw_ES_window", ids)
                    return resolved
                return go()
            ids = ids_of(result)
            es_shapes.append({"shape": type(result).__name__, "len": len(result) if hasattr(result, "__len__") else None,
                              "extracted": len(ids), "repr": repr(result)[:200]})
            record("S1_raw_ES_window", ids)
            return result
        return wrapper

    # S1 raw ES window(s) issued by the retrieval path
    patch(settings.docStoreConn.__class__, "search", es_wrapper(settings.docStoreConn.__class__.search))
    # S2 the SearchResult Dealer.search returns (its own `.ids`, in ES rank order)
    patch(rag_search.Dealer, "search", wrap("S2_dealer_search", rag_search.Dealer.search,
                                            lambda r: ids_of(getattr(r, "ids", None)) or ids_of(r)))
    # S3 route page returned by Dealer.retrieval
    patch(rag_search.Dealer, "retrieval", wrap("S3_route_page", rag_search.Dealer.retrieval))
    # S4 what each route contributes
    patch(mr, "_retrieve_route", wrap("S4_route_result", mr._retrieve_route))
    # S5 merged pool
    patch(mr, "merge_route_hits", wrap("S5_merged_pool", mr.merge_route_hits))
    # S6 ranking adjustment
    patch(rr, "apply_rank_adjustments", wrap("S6_rank_adjustment", rr.apply_rank_adjustments))
    # S7 rerank / cut
    patch(rr, "rerank_chunks", wrap("S7_rerank_cut", rr.rerank_chunks))
    # S8 explicit selection
    patch(rr, "select_context", wrap("S8_context_selection", rr.select_context))
    # S9 the kbinfos the model is actually given
    original_rmr = ds.retrieve_multi_route

    async def rmr_wrapper(*args, **kwargs):
        RETRIEVAL_REQUEST.update({
            "question_argument": kwargs.get("question"),
            "similarity_threshold": kwargs.get("similarity_threshold"),
            "vector_similarity_weight": kwargs.get("vector_similarity_weight"),
            "final_top_n": kwargs.get("final_top_n"),
            "knn_top_k": kwargs.get("knn_top_k"),
            "rerank_candidates_count": kwargs.get("rerank_candidates_count"),
            "kb_ids": kwargs.get("kb_ids"),
            "rerank_mdl_present": kwargs.get("rerank_mdl") is not None,
            "embd_mdl_present": kwargs.get("embd_mdl") is not None,
        })
        result = await original_rmr(*args, **kwargs)
        record("S9_final_reference", ids_of(result))
        return result

    patch(ds, "retrieve_multi_route", rmr_wrapper)

    original_kb_prompt = ds.kb_prompt

    def kb_prompt_wrapper(kbinfos, max_tokens, *a, **k):
        raw = original_kb_prompt(kbinfos, max_tokens, *a, **k)
        # kb_prompt returns a LIST of evidence blocks; normalise for hashing and probing.
        text = "\n".join(str(block) for block in raw) if isinstance(raw, (list, tuple)) else str(raw)
        KB_PROMPT["block_count"] = len(raw) if isinstance(raw, (list, tuple)) else 1
        KB_PROMPT["chars"] = len(text)
        KB_PROMPT["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        KB_PROMPT["blocks"] = text.count("[ID:")
        KB_PROMPT["has_3x400"] = "3×400" in text or "3x400" in text
        KB_PROMPT["has_1x400"] = "1×400" in text or "1x400" in text
        KB_PROMPT["mentions_73286_3"] = "73286.3" in text
        KB_PROMPT["mentions_part3"] = "第3部分" in text
        KB_PROMPT["mentions_三芯"] = "三芯" in text
        KB_PROMPT["head"] = " ".join(text.split())[:400]
        return raw

    ds.kb_prompt = kb_prompt_wrapper

    async def go():
        items = []
        async for item in ds.async_chat(dialog=dialog,
                                        messages=[{"role": "user", "content": QUESTION}],
                                        stream=False, quote=True):
            items.append(item)
        return items

    items = asyncio.run(go())
    final = items[-1] if items else {}
    reference = final.get("reference") or {}
    chunks = reference.get("chunks") or []
    FINAL_KBINFOS["answer"] = final.get("answer") or ""
    FINAL_KBINFOS["answer_length"] = len(FINAL_KBINFOS["answer"])
    FINAL_KBINFOS["context_size"] = len(chunks)
    FINAL_KBINFOS["chunks"] = []
    for c in chunks:
        body = _body_text(c)
        FINAL_KBINFOS["chunks"].append({
            "chunk_id": c.get("chunk_id") or c.get("id"),
            "document": str(c.get("docnm_kwd") or "")[:80],
            "is_table": bool(is_table_chunk(c)),
            "content_chars": len(str(c.get("content_with_weight") or "")),
            "body_chars": len(body),
            "content_sha256": hashlib.sha256(str(c.get("content_with_weight") or "").encode("utf-8")).hexdigest(),
            "body_full": " ".join(body.split()),
        })
    FINAL_KBINFOS["health"] = reference.get("retrieval_health")
    FINAL_KBINFOS["stage_trace"] = STAGES
    FINAL_KBINFOS["kb_prompt"] = KB_PROMPT
    FINAL_KBINFOS["es_shapes"] = es_shapes
    FINAL_KBINFOS["retrieval_request"] = RETRIEVAL_REQUEST

    OUT.write_text(json.dumps(FINAL_KBINFOS, ensure_ascii=False, indent=1), encoding="utf-8")
    print("STAGE TRACE (target / control ranks):")
    for s in STAGES:
        print(f"  {s['stage']:26s} n={s['count']:4d} target={s['target_rank']} control={s['control_rank']}")
    print(f"  kb_prompt: chars={KB_PROMPT.get('chars')} blocks={KB_PROMPT.get('blocks')} "
          f"3x400={KB_PROMPT.get('has_3x400')} 1x400={KB_PROMPT.get('has_1x400')} "
          f"73286.3={KB_PROMPT.get('mentions_73286_3')}")
    print(f"  final context: {FINAL_KBINFOS['context_size']} chunks; answer {FINAL_KBINFOS['answer_length']} chars")


main()
