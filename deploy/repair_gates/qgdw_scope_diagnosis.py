"""Read-only: does the assistant's metadata filter pin retrieval to the Part 2 document for this question?

Prints the dialog's meta_data_filter, runs the SAME `apply_meta_data_filter` the live path runs with the
live question, and lists the distinct route query strings captured from the live request with whether
each carried the doc scope.
"""
import asyncio
import json
import pathlib
import sys

sys.path.insert(0, "/ragflow")

from common import settings  # noqa: E402

settings.init_settings()

from api.db.db_models import Dialog  # noqa: E402
from api.db.services.dialog_service import apply_meta_data_filter  # noqa: E402
from api.db.services.doc_metadata_service import DocMetadataService  # noqa: E402
from api.db.joint_services.tenant_model_service import get_tenant_default_model_by_type  # noqa: E402
from api.db.services.llm_service import LLMBundle  # noqa: E402
from common.constants import LLMType  # noqa: E402

DIALOG_ID = "29a6da60ba1f11f1be9555eabe501d5b"
QUESTION = "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"
PART2, PART3 = "28668474ba1b11f1be9555eabe501d5b", "f18db09cba1211f18bee33eac9b39c66"

dialog = Dialog.get_or_none(Dialog.id == DIALOG_ID)
print("dialog.name                  :", dialog.name)
print("dialog.kb_ids                :", dialog.kb_ids)
print("dialog.meta_data_filter      :", json.dumps(getattr(dialog, "meta_data_filter", None), ensure_ascii=False))
print("dialog.similarity_threshold  :", dialog.similarity_threshold)
print("dialog.vector_sim_weight     :", dialog.vector_similarity_weight)
print("dialog.top_n / top_k         :", dialog.top_n, "/", dialog.top_k)
print("dialog.rerank_candidates_cnt :", getattr(dialog, "rerank_candidates_count", None))
print("prompt_config quote          :", (dialog.prompt_config or {}).get("quote"))

if getattr(dialog, "meta_data_filter", None):
    chat_cfg = get_tenant_default_model_by_type(dialog.tenant_id, LLMType.CHAT)
    chat_mdl = LLMBundle(dialog.tenant_id, chat_cfg)

    async def run():
        return await apply_meta_data_filter(
            dialog.meta_data_filter, None, QUESTION, chat_mdl, None,
            kb_ids=dialog.kb_ids,
            metas_loader=lambda: DocMetadataService.get_flatted_meta_by_kbs(dialog.kb_ids),
        )

    scoped = asyncio.run(run())
    print()
    print("apply_meta_data_filter(...) ->", scoped)
    print("  PART2 in scope:", PART2 in (scoped or []))
    print("  PART3 in scope:", PART3 in (scoped or []))
    print("  scope is Part2-only:", scoped == [PART2])

print()
print("=== distinct route query strings captured from the live request ===")
calls = json.loads(pathlib.Path("/tmp/route_queries.json").read_text(encoding="utf-8"))["calls"]
seen = {}
for c in calls:
    b = c.get("body") or {}
    bo = (b.get("query") or {}).get("bool") or {}
    qs = ""
    for m in (bo.get("must") or []):
        qs = ((m or {}).get("query_string") or {}).get("query", "") or qs
    docfilter = []
    for f in (bo.get("filter") or []):
        t = (f or {}).get("terms") or {}
        if "doc_id" in t:
            docfilter = t["doc_id"]
    key = qs[:90]
    rec = seen.setdefault(key, {"n": 0, "docfilter": docfilter, "boost": bo.get("boost"),
                                "size": b.get("size"), "knn_k": (b.get("knn") or {}).get("k")})
    rec["n"] += 1
for key, rec in seen.items():
    print(f"  x{rec['n']:2d} size={rec['size']} knn_k={rec['knn_k']} bool_boost={rec['boost']} "
          f"doc_filter={[d[:8] for d in rec['docfilter']]}")
    print(f"       {key}")
