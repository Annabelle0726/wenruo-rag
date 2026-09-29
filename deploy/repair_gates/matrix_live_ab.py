"""A/B/C matrix on the bound live Agentic request. READ-ONLY.

Runs the real low-mode graph with RERANK_PATH selecting the variant, then reports the
selection matrix for that variant. Occupancy comes from a replica of the variant's own
algorithm (dedup / budget flags, ORIGINAL stage order) that is validated by requiring its
final key list to EQUAL the variant's real select_context output.

    VARIANT=A RERANK_PATH=/tmp/v_rerank_A_base.py          python abc_matrix.py
    VARIANT=B RERANK_PATH=/tmp/v_rerank_B_dedup.py         python abc_matrix.py
    VARIANT=C RERANK_PATH=/tmp/v_rerank_C_dedup_budget.py  python abc_matrix.py
"""
import asyncio
import importlib.util
import json
import math
import os
import pathlib
import re
import sys

sys.path.insert(0, "/ragflow")

VARIANT = os.environ.get("VARIANT", "?")
_path = os.environ.get("RERANK_PATH")
if _path:
    import rag.retrieval as _pkg

    _spec = importlib.util.spec_from_file_location("rag.retrieval.rerank", _path)
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["rag.retrieval.rerank"] = _mod
    _spec.loader.exec_module(_mod)
    _pkg.rerank = _mod
    for _n in ("select_context", "apply_rank_adjustments", "ensure_route_coverage", "rerank_chunks"):
        if hasattr(_mod, _n):
            setattr(_pkg, _n, getattr(_mod, _n))

from common import settings  # noqa: E402

settings.init_settings()

from api.db.db_models import Conversation, Dialog  # noqa: E402
from api.db.joint_services.tenant_model_service import (  # noqa: E402
    get_tenant_default_model_by_type, resolve_model_config)
from api.db.services.llm_service import LLMBundle  # noqa: E402
from common.constants import LLMType  # noqa: E402
from rag.retrieval import rerank as rr  # noqa: E402

CONV = "c737275ebae611f19c26b16ea36f75b8"
MSG = "66ba96ca-7507-4a95-a4b7-02dd0eae7055"
ASSISTANT = "ccddcfdeba3a11f1a4910547a12ee1d1"
INDEX = "ragflow_a9e28731ab7011f19b833887d563fb04"
F8 = ["3\u00d7400", "3\u00d7500", "3\u00d7630", "3\u00d7800",
      "3\u00d71000", "3\u00d71200", "3\u00d71400", "3\u00d71600"]
F10 = ["1\u00d7400", "1\u00d7500", "1\u00d7630", "1\u00d7800", "1\u00d71000",
       "1\u00d71200", "1\u00d71400", "1\u00d71600", "1\u00d71800", "1\u00d72000"]

OUT = pathlib.Path(os.environ.get("ACC_OUT", "/out"))
OUT.mkdir(parents=True, exist_ok=True)

conv = Conversation.get_or_none(Conversation.id == CONV)
msgs = conv.message if isinstance(conv.message, list) else json.loads(conv.message or "[]")
QUESTION = next(m["content"] for m in msgs if str(m.get("id")) == MSG)
dialog = Dialog.get_or_none(Dialog.id == ASSISTANT)
CAPTURED, ROUTES = {}, []


def ck(c):
    return str(rr.chunk_key(c))


def text_of(c):
    for k in ("content_with_weight", "content", "content_ltks", "text"):
        v = c.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def flat(c):
    return " ".join(re.sub(r"<[^>]+>", " ", text_of(c)).split())


def has_family(t, toks):
    return all(tok in t or tok.replace("\u00d7", "x") in t for tok in toks)


def instrument():
    from rag.retrieval import multi_route as mr
    from rag.advanced_rag.harness.tools import search as search_tool

    if _path:  # rebind value-imported rerank names onto the variant under test
        for _m in list(sys.modules.values()):
            _d = getattr(_m, "__dict__", None)
            if not isinstance(_d, dict):
                continue
            for _nm in ("select_context", "apply_rank_adjustments", "ensure_route_coverage",
                        "rerank_chunks", "resolve_final_top_n", "dedupe_chunks",
                        "routes_of", "DEFAULT_FINAL_TOP_N"):
                _cur = _d.get(_nm)
                if _cur is None or getattr(_cur, "__module__", None) != "rag.retrieval.rerank":
                    continue
                if hasattr(_mod, _nm):
                    try:
                        setattr(_m, _nm, getattr(_mod, _nm))
                    except Exception:  # noqa: BLE001
                        pass

    orig_route = mr._retrieve_route

    async def route(*a, **k):
        res = await orig_route(*a, **k)
        try:
            ROUTES.append([ck(c) for c in (getattr(res, "chunks", []) or [])])
        except Exception:  # noqa: BLE001
            pass
        return res

    orig_select = rr.select_context

    def select(ordered, top_n, policy):
        chosen = orig_select(ordered, top_n, policy)
        CAPTURED.update({"ordered": list(ordered), "chosen": list(chosen),
                         "top_n": top_n, "policy": policy})
        return chosen

    orig_hs = search_tool.hybrid_search

    async def hybrid(*a, **k):
        res = await orig_hs(*a, **k)
        CAPTURED["normalized_return"] = list((res or {}).get("chunks") or [])
        return res

    import rag.advanced_rag.agentic_rag_graph as G
    orig_kb = G.kb_prompt

    def kb_prompt(kbinfos, budget):
        rendered = orig_kb(kbinfos, budget)
        CAPTURED["compose_pool"] = list(kbinfos.get("chunks") or [])
        return rendered

    for orig, repl in ((orig_route, route), (orig_select, select), (orig_hs, hybrid),
                       (orig_kb, kb_prompt)):
        for m in list(sys.modules.values()):
            d = getattr(m, "__dict__", None)
            if isinstance(d, dict):
                for nm, v in list(d.items()):
                    if v is orig:
                        try:
                            setattr(m, nm, repl)
                        except Exception:  # noqa: BLE001
                            pass

    orig_stream = LLMBundle.async_chat_streamly_delta

    def stream(self, system, history, gen_conf=None, **kw):
        flatp = (system or "") + "\n" + "\n".join((h.get("content") or "") for h in (history or []))
        if "Evidence:" in flatp and "Question:" in flatp:
            CAPTURED["model_prompt"] = flatp
        return orig_stream(self, system, history, gen_conf or {}, **kw)

    LLMBundle.async_chat_streamly_delta = stream


def simulate(ordered, top_n, policy, dedup, budget, unified=False):
    """The variant's own algorithm: stage order 1 routes -> 1b compared -> 2 prose -> fill.

    Returns the full final key list plus the per-stage occupancy, so it can be validated
    against the real cut instead of being trusted.
    """
    chosen, keys = [], set()
    table_count = [0]
    doc_counts, hollow_counts = {}, {}
    marks = {}
    table_cap = top_n if policy.max_table_share >= 1.0 else min(top_n, math.ceil(top_n * policy.max_table_share))
    doc_cap = 0 if policy.max_auxiliary_document_share >= 1.0 else max(1, min(top_n, math.ceil(top_n * policy.max_auxiliary_document_share)))
    every_cap = 0 if policy.max_document_share >= 1.0 else max(1, min(top_n, math.ceil(top_n * policy.max_document_share)))
    hollow_cap = max(1, min(top_n, math.ceil(top_n * rr.MAX_HOLLOW_TABLE_PER_DOCUMENT_SHARE)))
    limit = top_n - 1 if budget else top_n
    families = set()
    first_block = {}

    def doc_of(c):
        k = rr.document_key(c)
        return f"chunk:{ck(c)}" if not k else k

    def block_reason(c):
        if rr.is_table_chunk(c) and table_count[0] >= table_cap:
            return "table_cap"
        b = doc_of(c)
        n = doc_counts.get(b, 0)
        if every_cap and n >= every_cap:
            return "every_document_cap"
        if rr.is_hollow_table(c) and hollow_counts.get(b, 0) >= hollow_cap:
            return "hollow_table_per_document_cap"
        if doc_cap and not policy.is_core_document(c) and n >= doc_cap:
            return "auxiliary_document_cap"
        return None

    def take(c, stage, ignore_table_quota=False):
        key = ck(c)
        # the budget governs the RESERVATION stages only; the fill is bound by top_n alone
        if len(chosen) >= top_n or (stage[:1] in ("1", "2") and len(chosen) >= limit) or key in keys:
            return False
        why = block_reason(c)
        if why and not ignore_table_quota:
            first_block.setdefault(key, why)
            return False
        if ignore_table_quota:
            b = doc_of(c)
            n = doc_counts.get(b, 0)
            if (every_cap and n >= every_cap) or \
               (rr.is_hollow_table(c) and hollow_counts.get(b, 0) >= hollow_cap) or \
               (doc_cap and not policy.is_core_document(c) and n >= doc_cap):
                first_block.setdefault(key, "document_quota(ignore_table)")
                return False
        chosen.append(key)
        keys.add(key)
        b = doc_of(c)
        if rr.is_table_chunk(c):
            table_count[0] += 1
            if rr.is_hollow_table(c):
                hollow_counts[b] = hollow_counts.get(b, 0) + 1
        doc_counts[b] = doc_counts.get(b, 0) + 1
        marks[key] = stage
        return True

    def take_batch(c, stage, ignore_table_quota=False):
        if not take(c, stage, ignore_table_quota=ignore_table_quota):
            return False
        fam = rr.table_family_key(c)
        if fam is None or fam in families:
            return True
        families.add(fam)
        got = 1
        for sib in ordered:
            if got >= rr.MAX_TABLE_FAMILY_PARTS or len(chosen) >= top_n \
                    or (stage[:1] in ("1", "2") and len(chosen) >= limit):
                break
            if ck(sib) in keys or rr.table_family_key(sib) != fam:
                continue
            if take(sib, stage + "+family", ignore_table_quota=ignore_table_quota):
                got += 1
        return True

    # 1. one slot per route
    route_order = []
    for c in ordered:
        for r in rr.routes_of(c):
            if r not in route_order:
                route_order.append(r)
    if len(route_order) > 1:
        for r in route_order:
            for c in ordered:
                if r in rr.routes_of(c) and take_batch(c, "1_route"):
                    break
    after_step1 = len(chosen)

    # 1b. one slot per compared document
    compared_attempts = 0
    if policy.compared_documents:
        values = tuple(sorted(policy.question_values))
        reserved = set()
        for key in [rr.document_key(c) for c in ordered if policy.is_compared_document(c)]:
            if dedup:
                if key in reserved:
                    continue
                reserved.add(key)
            compared_attempts += 1
            cands = [c for c in ordered if rr.document_key(c) == key]
            if values:
                pairing = [c for c in cands if rr.paired_values(c, values)]
                cands = pairing or cands
            for c in cands:
                if take(c, "1b_compared_document"):
                    break
    after_step1b = len(chosen)

    # 2. prose floor
    prose_added = 0
    if policy.min_prose > 0:
        pt = sum(1 for c in ordered if ck(c) in keys and rr.is_prose_chunk(c))
        for c in ordered:
            if pt >= policy.min_prose or len(chosen) >= top_n:
                break
            if rr.is_prose_chunk(c) and take_batch(c, "2_prose_floor"):
                pt += 1
                prose_added += 1
    before_fill = len(chosen)

    def usage():
        by_doc = {}
        for k in keys:
            src = next((c for c in ordered if ck(c) == k), None)
            if src is None:
                continue
            by_doc[str(rr.document_key(src))] = by_doc.get(str(rr.document_key(src)), 0) + 1
        p2 = next((v for k, v in by_doc.items() if "28668474" in k), 0)
        p3 = next((v for k, v in by_doc.items() if "f18db09c" in k), 0)
        return {"part2": p2, "part3": p3, "tables": table_count[0]}

    usage_before = usage()

    # 3. the score fill.  Variant D replaces the deployed prose-first / table-second pair
    # with ONE score-ordered pass; A/B/C keep the deployed pair.
    if unified:
        table_only = table_cap < top_n and not any(not rr.is_table_chunk(c) for c in ordered)
        for c in ordered:
            if len(chosen) >= top_n:
                break
            take(c, "3_score_fill", ignore_table_quota=table_only and rr.is_table_chunk(c))
    elif table_cap < top_n:
        for c in ordered:
            if len(chosen) >= top_n:
                break
            if not rr.is_table_chunk(c):
                take(c, "3_nontable_fill")
        table_only = not any(not rr.is_table_chunk(c) for c in ordered)
        for c in ordered:
            if len(chosen) >= top_n:
                break
            take(c, "4_table_fill", ignore_table_quota=table_only and rr.is_table_chunk(c))
    else:
        for c in ordered:
            if len(chosen) >= top_n:
                break
            take(c, "3_score_fill")
    usage_after = usage()

    return {"final_keys": [ck(c) for c in ordered if ck(c) in keys],
            "after_step1": after_step1, "after_step1b": after_step1b,
            "compared_attempts": compared_attempts, "before_fill": before_fill,
            "fill_available": top_n - before_fill,
            "fill_added": len(chosen) - before_fill,
            "prose_added": prose_added, "unified_fill": unified,
            "usage_before_fill": usage_before, "usage_after_fill": usage_after,
            "limit": limit, "n_routes": len(route_order), "marks": marks,
            "first_block": first_block,
            "caps": {"table": table_cap, "aux_doc": doc_cap, "every_doc": every_cap,
                     "hollow": hollow_cap}}


async def main():
    instrument()
    from api.db.services.doc_metadata_service import DocMetadataService
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from rag.advanced_rag.agentic_rag import RAGTools
    from rag.advanced_rag.agentic_rag_graph import run_agentic_rag
    from common.metadata_utils import apply_meta_data_filter

    pc = dialog.prompt_config or {}
    kbs = KnowledgebaseService.get_by_ids(dialog.kb_ids)
    embd = LLMBundle(kbs[0].tenant_id, resolve_model_config(kbs[0].tenant_id, LLMType.EMBEDDING, kbs[0].embd_id))
    chat = LLMBundle(dialog.tenant_id, get_tenant_default_model_by_type(dialog.tenant_id, LLMType.CHAT))
    scope = None
    if dialog.meta_data_filter:
        scope = await apply_meta_data_filter(
            dialog.meta_data_filter, None, QUESTION, chat, None, kb_ids=dialog.kb_ids,
            metas_loader=lambda: DocMetadataService.get_flatted_meta_by_kbs(dialog.kb_ids))

    tools = RAGTools([dialog.tenant_id], chat, embed_mdl=embd, kb_ids=list(dialog.kb_ids or []),
                     web_search=None, meta_data_filter=dialog.meta_data_filter, doc_scope=scope,
                     empty_response=pc.get("empty_response", ""), do_refer=False,
                     thinking_mode="low", text_attachments_content=None, system_prompt="",
                     similarity_threshold=dialog.similarity_threshold,
                     vector_similarity_weight=dialog.vector_similarity_weight,
                     top_n=dialog.top_n, rerank_candidates_count=dialog.rerank_candidates_count,
                     top_k=dialog.top_k)

    tokens = []
    async for tok in run_agentic_rag(tools, [{"role": "user", "content": QUESTION}], max_loops=3):
        if not (isinstance(tok, str) and tok.startswith("[") and "]" in tok[:40]):
            tokens.append(tok)

    from rag.advanced_rag.agentic_rag import (
        _expand_range_citation_markers, _repair_slot_citation_markers, _split_think_stream)

    async def _replay():
        for t in tokens:
            yield t

    ANSWER = ""
    async for kind, delta in _split_think_stream(_replay()):
        if kind == "answer":
            ANSWER += delta
    ANSWER = re.sub(r"\(\**(ID:\d+)\**\)", r"[\1]", ANSWER)
    ANSWER = _repair_slot_citation_markers(
        ANSWER, getattr(tools, "_rag_slot_evidence", None) or {},
        getattr(tools, "_rag_cite_chunk_ids", None) or [])
    ANSWER = _expand_range_citation_markers(ANSWER, len(getattr(tools, "_rag_cite_chunk_ids", None) or []))

    ordered = CAPTURED["ordered"]
    chosen = CAPTURED["chosen"]
    policy = CAPTURED["policy"]
    top_n = CAPTURED["top_n"]
    dedup = VARIANT in ("B", "C", "D")
    budget = VARIANT in ("C", "D")
    sim = simulate(ordered, top_n, policy, dedup, budget, unified=(VARIANT == "D"))
    real_keys = [ck(c) for c in chosen]
    validated = sim["final_keys"] == real_keys

    carriers_ordered = [ck(c) for c in ordered if has_family(flat(c), F8)]
    carriers_selected = [ck(c) for c in chosen if has_family(flat(c), F8)]
    norm = CAPTURED.get("normalized_return") or []
    memory = (getattr(tools, "kbinfos", None) or {}).get("memory") or []
    compose = CAPTURED.get("compose_pool") or []
    prompt = CAPTURED.get("model_prompt") or ""

    cite = [str(i) for i in (getattr(tools, "_rag_cite_chunk_ids", None) or [])]
    markers = sorted({int(m) for m in re.findall(r"\[ID:\s*(\d+)\]", ANSWER)})
    ground = {"three": [], "one": [], "markers": markers}
    es = settings.docStoreConn.es
    for m in markers:
        if not (1 <= m <= len(cite)):
            continue
        try:
            src = es.get(index=INDEX, id=cite[m - 1])["_source"]
        except Exception:  # noqa: BLE001
            continue
        t = " ".join(re.sub(r"<[^>]+>", " ", str(src.get("content_with_weight") or "")).split())
        if has_family(t, F8):
            ground["three"].append(m)
        if has_family(t, F10):
            ground["one"].append(m)

    out = {
        "variant": VARIANT, "source": _path,
        "pool": {"ordered_n": len(ordered), "routes": len(ROUTES), "top_n": top_n},
        "sim_validated": validated, "sim": sim,
        "caps": sim["caps"], "policy": {"min_prose": policy.min_prose,
                                        "max_table_share": policy.max_table_share,
                                        "max_auxiliary_document_share": policy.max_auxiliary_document_share,
                                        "max_document_share": policy.max_document_share,
                                        "table_penalty": policy.table_penalty,
                                        "compared_documents": sorted(policy.compared_documents),
                                        "question_values": sorted(policy.question_values)},
        "final_window_n": len(chosen), "final_window_ids": real_keys,
        "carriers_in_ordered": carriers_ordered, "carriers_selected": carriers_selected,
        "carrier_in_normalized": [ck(c) for c in norm if has_family(flat(c), F8)],
        "carrier_in_memory": [ck(c) for c in memory if has_family(flat(c), F8)],
        "carrier_in_compose_pool": [ck(c) for c in compose if has_family(flat(c), F8)],
        "carrier_in_model_prompt": has_family(prompt, F8),
        "answer": ANSWER, "cite_ids": cite, "grounding": ground,
        "answer_has_8": bool(re.search(r"8\s*(种|个)", ANSWER)) and has_family(ANSWER, F8),
        "answer_has_10": bool(re.search(r"10\s*(种|个)", ANSWER)) and has_family(ANSWER, F10),
        "answer_denies_part3": bool(re.search(r"(没有出现|未检索到|知识库里|无法|建议您)", ANSWER)),
        "stage_attribution": {k: v for k, v in
                              ((s, [c for c, st in sim["marks"].items() if st == s]) for s in
                               ("1_route", "1_route+family", "1b_compared_document", "2_prose_floor",
                                "3_nontable_fill", "4_table_fill", "3_score_fill"))},
    }
    (OUT / f"matrix_{VARIANT}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / f"answer_{VARIANT}.txt").write_text(ANSWER, encoding="utf-8")

    print(f"===== VARIANT {VARIANT} :: {os.path.basename(_path or '')} =====")
    print("validated(sim==real)      :", validated)
    print("STEP1_SLOTS               :", sim["after_step1"])
    print("STEP1B_SLOTS              :", sim["after_step1b"] - sim["after_step1"],
          "(compared attempts: %d, dedup=%s)" % (sim["compared_attempts"], dedup))
    print("RESERVATION_TOTAL         :", sim["after_step1b"], "of limit", sim["limit"])
    print("PROSE_FLOOR_ADDITIONS     :", sim["prose_added"])
    print("SCORE_FILL_ADDITIONS      :", sim["fill_added"], "(unified fill: %s)" % sim["unified_fill"])
    print("DOC/TABLE BEFORE FILL     : part2=%s part3=%s tables=%s caps=%s"
          % (sim["usage_before_fill"]["part2"], sim["usage_before_fill"]["part3"],
             sim["usage_before_fill"]["tables"], sim["caps"]))
    print("DOC/TABLE AFTER FILL      : part2=%s part3=%s tables=%s"
          % (sim["usage_after_fill"]["part2"], sim["usage_after_fill"]["part3"],
             sim["usage_after_fill"]["tables"]))
    print("SCORE_FILL_AVAILABLE      :", sim["fill_available"])
    print("final window n            :", len(chosen))
    print("carriers in ordered       :", carriers_ordered)
    print("CARRIER SELECTED          :", carriers_selected)
    print("carrier normalized/memory :", out["carrier_in_normalized"], out["carrier_in_memory"])
    print("carrier compose/prompt    :", out["carrier_in_compose_pool"], out["carrier_in_model_prompt"])
    print("answer 8spec/10spec       :", out["answer_has_8"], out["answer_has_10"])
    print("answer denies part3       :", out["answer_denies_part3"])
    print("grounding three/one       :", ground["three"], ground["one"])
    if not validated:
        print("MISMATCH real:", real_keys)
        print("MISMATCH sim :", sim["final_keys"])


try:
    asyncio.run(main())
except Exception:
    import traceback
    (OUT / f"err_{VARIANT}.txt").write_text(traceback.format_exc(), encoding="utf-8")
    print("FAILED", VARIANT)
    raise
