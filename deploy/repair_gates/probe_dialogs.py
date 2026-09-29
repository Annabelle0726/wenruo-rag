import importlib.util
import json
import sys

sys.path.insert(0, "/ragflow")

print("=== playwright ===")
spec = importlib.util.find_spec("playwright")
print("playwright module:", spec.origin if spec else "ABSENT")

print("=== assistants bound to KBs ===")
from common import settings  # noqa: E402

settings.init_settings()
from api.db.db_models import Dialog  # noqa: E402

TENANT = "a9e28731ab7011f19b833887d563fb04"
rows = []
for row in Dialog.select().where((Dialog.tenant_id == TENANT) & (Dialog.kb_ids.is_null(False))).dicts():
    rows.append({"id": row.get("id"), "name": row.get("name"), "kb_ids": row.get("kb_ids"),
                 "quote": (row.get("prompt_config") or {}).get("quote") if isinstance(row.get("prompt_config"), dict) else None,
                 "status": row.get("status")})
print(json.dumps(rows, ensure_ascii=False, indent=1)[:1800])
