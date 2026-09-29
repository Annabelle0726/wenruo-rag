"""Acceptance for the metadata repair - ONE live run of the exact question.

Captures, in a single pass:
  A. the auto metadata filter's model decision and the resolved scope;
  B. whether both doc_ids appear in the live route filters (lexical + knn);
  C. every ES call body with the TARGET/CONTROL rank in it (raw window);
  D. the final answer and the final context.
Read-only apart from the already-performed metadata repair; async_chat persists no conversation rows.
"""
import asyncio
import json
import pathlib
import sys

sys.path.insert(0, "/ragflow")

from common import settings  # noqa: E402

settings.init_settings()

from api.db.db_models import Dialog, Knowledgebase  # noqa: E402
from api.db.services import dialog_service as ds  # noqa: E402
from api.db.joint_services.tenant_model_service import get_tenant_default_model_by_type  # noqa: E402
from api.db.services.llm_service import LLMBundle  # noqa: E402
from api.db.services.doc_metadata_service import DocMetadataService  # noqa: E402
from common.constants import LLMType  # noqa: E402
from common.metadata_utils import apply_meta_data_filter, filter_doc_ids_by_metadata  # noqa: E402
from rag.prompts.generator import gen_meta_filter  # noqa: E402
from rag.retrieval.chunk_profile import _body_text, is_table_chunk  # noqa: E402

DIALOG_ID = "29a6da60ba1f11f1be9555eabe501d5b"
QUESTION = "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"
TARGET, CONTROL = "d1d75672f2dbc333", "b5aaf72bcd33d44a"
PART2, PART3 = "28668474ba1b11f1be9555eabe501d5b", "f18db09cba1211f18bee33eac9b39c66"
KB = "9463d93eb97511f1938f2592e9bc6fe4"

out = {}
dialog = Dialog.get_or_none(Dialog.id == DIALOG_ID)
kb = Knowledgebase.get_by_id(KB)
metas = DocMetadataService.get_flatted_meta_by_kbs([KB])
chat_mdl = LLMBundle(dialog.tenant_id, get_tenant_default_model_by_type(dialog.tenant_id, LLMType.CHAT))

# ---- A: filter decision + resolved scope ---------------------------------------------------------
filters = asyncio.run(gen_meta_filter(chat_mdl, metas, QUESTION))
resolved = filter_doc_ids_by_metadata([KB], filters.get("conditions", []), filters.get("logic", "and"), lambda: metas)
final_scope = asyncio.run(apply_meta_data_filter({"method": "auto"}, None, QUESTION, chat_mdl, None,
                                                 kb_ids=[KB], metas_loader=lambda: metas))
out["A_model_decision"] = filters
out["A_resolved_scope"] = resolved
out["A_scope_has_part2"] = PART2 in (resolved or [])
out["A_scope_has_part3"] = PART3 in (resolved or [])
out["A_final_scope"] = final_scope
out["A_metadata_standard_no_values"] = metas.get("standard_no")
out["A_metadata_year_values"] = metas.get("year")

# ---- B/C: the live route filters and the raw windows ---------------------------------------------
CALLS = []
store = settings.docStoreConn
original = store._es_search_once


def capture(*args, **kwargs):
    body = args[1] if len(args) > 1 else None
    result = original(*args, **kwargs)
    hits = []
    try:
        hits = [h["_id"] for h in result["hits"]["hits"]]
    except Exception:  # noqa: BLE001
        pass
    docfilters = []
    if isinstance(body, dict):
        for site in (body.get("query"), (body.get("knn") or {}).get("filter")):
            node = site.get("bool") if isinstance(site, dict) and "bool" in site else site
            if isinstance(node, dict):
                for f in node.get("filter") or []:
                    t = (f or {}).get("terms") or {}
                    if "doc_id" in t:
                        docfilters.append(list(t["doc_id"]))
    CALLS.append({"returned": len(hits), "size": body.get("size") if isinstance(body, dict) else None,
                  "doc_filters": docfilters,
                  "target_rank": (hits.index(TARGET) + 1) if TARGET in hits else None,
                  "control_rank": (hits.index(CONTROL) + 1) if CONTROL in hits else None})
    return result


store._es_search_once = capture

ITEMS = []


async def go():
    async for item in ds.async_chat(dialog=dialog, messages=[{"role": "user", "content": QUESTION}],
                                    stream=False, quote=True):
        ITEMS.append(item)


asyncio.run(go())
final = ITEMS[-1] if ITEMS else {}
reference = final.get("reference") or {}
chunks = reference.get("chunks") or []

scoped_calls = [c for c in CALLS if c["doc_filters"]]
out["B_calls_total"] = len(CALLS)
out["B_calls_with_doc_filter"] = len(scoped_calls)
out["B_distinct_doc_filter_sets"] = sorted({tuple(sorted(x)) for c in scoped_calls for x in c["doc_filters"]})
out["B_filters_contain_part2"] = any(PART2 in x for c in scoped_calls for x in c["doc_filters"])
out["B_filters_contain_part3"] = any(PART3 in x for c in scoped_calls for x in c["doc_filters"])
out["C_target_raw_ranks"] = [c["target_rank"] for c in CALLS]
out["C_control_raw_ranks"] = [c["control_rank"] for c in CALLS]
out["C_target_in_any_window"] = any(c["target_rank"] for c in CALLS)
out["C_target_in_top30"] = any(c["target_rank"] and c["target_rank"] <= 30 for c in CALLS)

out["D_answer"] = final.get("answer") or ""
out["D_answer_length"] = len(out["D_answer"])
out["D_context_size"] = len(chunks)
out["D_context"] = [{"chunk_id": c.get("chunk_id") or c.get("id"),
                     "is_table": bool(is_table_chunk(c)),
                     "document": str(c.get("docnm_kwd") or "")[:70],
                     "body_head": " ".join(_body_text(c).split())[:300]} for c in chunks]
out["D_context_tables"] = sum(1 for c in out["D_context"] if c["is_table"])
out["D_health"] = reference.get("retrieval_health")

print(json.dumps(out, ensure_ascii=False, indent=1))
pathlib.Path("/tmp/metadata_acceptance.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
