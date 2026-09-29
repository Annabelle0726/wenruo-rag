"""Read-only: bind to the persisted failed request (messages live in Conversation.message)."""
import json
import sys

sys.path.insert(0, "/ragflow")

from common import settings

settings.init_settings()

from api.db.db_models import Conversation, Dialog  # noqa: E402

CONV = "c737275ebae611f19c26b16ea36f75b8"
MSG = "18bb69bf-0e11-4bf2-9d1a-2b1966c98159"
ASSISTANT = "ccddcfdeba3a11f1a4910547a12ee1d1"

conv = Conversation.get_or_none(Conversation.id == CONV)
print("conversation found:", conv is not None)
if conv is not None:
    print("  dialog_id:", conv.dialog_id, " name:", conv.name, " user_id:", conv.user_id)
    msgs = conv.message if isinstance(conv.message, list) else json.loads(conv.message or "[]")
    print(f"  messages in conversation: {len(msgs)}")
    match = None
    for m in msgs:
        mid = str(m.get("id") or "")
        if mid == MSG or mid.startswith(MSG[:12]):
            match = m
            break
    if match is None:
        print("  !! message id not found inline; listing all ids:")
        for m in msgs:
            print("     ", m.get("id"), "| role=", m.get("role"), "|", str(m.get("content"))[:80])
    else:
        print("\n=== PERSISTED USER QUESTION (exact) ===")
        print(json.dumps(match.get("content"), ensure_ascii=False))
        print("\n  role:", match.get("role"), " id:", match.get("id"), " created_at:", match.get("created_at"))
        ref = match.get("reference")
        if ref:
            try:
                refj = ref if isinstance(ref, dict) else json.loads(ref)
                chunks = (refj or {}).get("chunks") or []
                print(f"  reference chunks: {len(chunks)}")
                print("  reference chunk ids:", [str(c.get('chunk_id'))[:16] for c in chunks])
            except Exception as exc:  # noqa: BLE001
                print("  reference parse:", type(exc).__name__)

print("\n=== assistant ===")
dlg = Dialog.get_or_none(Dialog.id == ASSISTANT)
if dlg is None:
    print("  NOT FOUND:", ASSISTANT)
else:
    keys = ("id", "name", "tenant_id", "kb_ids", "llm_id", "tenant_llm_id", "rerank_id",
            "similarity_threshold", "vector_similarity_weight", "top_n", "top_k",
            "rerank_candidates_count", "language", "status")
    for k in keys:
        print(f"  {k} = {getattr(dlg, k, None)}")
    pc = dlg.prompt_config or {}
    print("  prompt_config.quote =", pc.get("quote"))
    print("  prompt_config keys  =", sorted(pc))
    print("  meta_data_filter    =", json.dumps(getattr(dlg, "meta_data_filter", None), ensure_ascii=False))
