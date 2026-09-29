"""Read-only trace of the AUTO metadata filter for the original QGDW question.

Captures, in order: the metadata dict handed to the filter model, the exact rendered prompt, the model's
JSON decision (repeated for determinism), the resolved metadata conditions, the matched document rows,
and the final doc_id scope. Also reports what happens with metadata filtering disabled - by calling the
function with no filter, which is a probe, not a configuration change.

No production config, index, weight or code is touched.
"""
import asyncio
import json
import pathlib
import sys

sys.path.insert(0, "/ragflow")

from common import settings  # noqa: E402

settings.init_settings()

from api.db.db_models import Dialog  # noqa: E402
from api.db.services.doc_metadata_service import DocMetadataService  # noqa: E402
from api.db.joint_services.tenant_model_service import get_tenant_default_model_by_type  # noqa: E402
from api.db.services.llm_service import LLMBundle  # noqa: E402
from common.constants import LLMType  # noqa: E402
from common.metadata_utils import apply_meta_data_filter, filter_doc_ids_by_metadata  # noqa: E402
from rag.prompts.generator import gen_meta_filter, PROMPT_JINJA_ENV, META_FILTER  # noqa: E402
import datetime  # noqa: E402

DIALOG_ID = "29a6da60ba1f11f1be9555eabe501d5b"
QUESTION = "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"
PART2, PART3 = "28668474ba1b11f1be9555eabe501d5b", "f18db09cba1211f18bee33eac9b39c66"
KB = "9463d93eb97511f1938f2592e9bc6fe4"

out = {}


def emit(key, value):
    out[key] = value


dialog = Dialog.get_or_none(Dialog.id == DIALOG_ID)
emit("meta_data_filter_config", getattr(dialog, "meta_data_filter", None))

metas = DocMetadataService.get_flatted_meta_by_kbs([KB])
emit("metadata_key_count", len(metas))
emit("metadata_keys", sorted(metas))

# Which metadata values each of the two documents is reachable through.
def docs_of(values):
    out_docs = set()
    if isinstance(values, dict):
        for value, ids in values.items():
            if isinstance(ids, (list, set, tuple)):
                out_docs |= {str(i) for i in ids}
            else:
                out_docs.add(str(ids))
    return out_docs


part2_meta, part3_meta, shared = {}, {}, {}
for key, values in metas.items():
    docs = docs_of(values)
    in2, in3 = PART2 in docs, PART3 in docs
    if in2 and in3:
        shared[key] = list(values.keys()) if isinstance(values, dict) else values
    elif in2:
        part2_meta[key] = list(values.keys()) if isinstance(values, dict) else values
    elif in3:
        part3_meta[key] = list(values.keys()) if isinstance(values, dict) else values

emit("metadata_keys_covering_BOTH_docs", shared)
emit("metadata_keys_only_PART2", part2_meta)
emit("metadata_keys_only_PART3", part3_meta)

# Which value of each key maps to which doc (the discriminator surface the model sees).
value_to_docs = {}
for key, values in metas.items():
    if not isinstance(values, dict):
        continue
    for value, ids in values.items():
        ids = [str(i) for i in ids] if isinstance(ids, (list, set, tuple)) else [str(ids)]
        if PART2 in ids or PART3 in ids:
            value_to_docs.setdefault(key, {})[str(value)] = {
                "part2": PART2 in ids, "part3": PART3 in ids, "doc_count": len(ids)}
emit("value_to_docs_for_our_two", value_to_docs)

# The exact prompt the filter model receives.
structure = {k: (list(v.keys()) if isinstance(v, dict) else v) for k, v in metas.items()}
prompt = PROMPT_JINJA_ENV.from_string(META_FILTER).render(
    current_date=datetime.datetime.today().strftime("%Y-%m-%d"),
    metadata_keys=json.dumps(structure), user_question=QUESTION, constraints=None)
pathlib.Path("/tmp/meta_filter_prompt.txt").write_text(prompt, encoding="utf-8")
emit("prompt_chars", len(prompt))
emit("prompt_metadata_keys_block", structure)

chat_cfg = get_tenant_default_model_by_type(dialog.tenant_id, LLMType.CHAT)
chat_mdl = LLMBundle(dialog.tenant_id, chat_cfg)


async def run():
    decisions, scopes = [], []
    for _ in range(3):
        filters = await gen_meta_filter(chat_mdl, metas, QUESTION)
        decisions.append(filters)
        resolved = filter_doc_ids_by_metadata([KB], filters.get("conditions", []), filters.get("logic", "and"),
                                              lambda: metas)
        scopes.append({"conditions": filters.get("conditions"), "logic": filters.get("logic", "and"),
                       "resolved": resolved,
                       "part2": PART2 in resolved, "part3": PART3 in resolved})
    final = await apply_meta_data_filter({"method": "auto"}, None, QUESTION, chat_mdl, None,
                                         kb_ids=[KB], metas_loader=lambda: metas)
    disabled = await apply_meta_data_filter(None, None, QUESTION, chat_mdl, None, kb_ids=[KB],
                                            metas_loader=lambda: metas)
    return decisions, scopes, final, disabled


decisions, scopes, final, disabled = asyncio.run(run())
emit("FILTER_MODEL_OUTPUT", decisions)
emit("resolution_per_call", scopes)
emit("final_scope_from_apply", final)
emit("filtering_disabled_result", disabled)

print(json.dumps(out, ensure_ascii=False, indent=1))
pathlib.Path("/tmp/meta_filter_trace.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
