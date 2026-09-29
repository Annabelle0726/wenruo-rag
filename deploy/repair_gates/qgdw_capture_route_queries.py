"""Capture the EXACT ES query bodies the live routes issue for the original question. Read-only.

Wraps the doc store's single ES round trip (`_es_search_once`) and records every request body plus the
response, so each route's real query can be replayed afterwards with a larger window and explained for
the two authoritative chunks. The wrapper only observes; nothing about the query is changed.

`async_chat` is driven once (real retrieval, real answer model). No datastore write.
"""
import asyncio
import json
import pathlib
import sys

sys.path.insert(0, "/ragflow")

from common import settings  # noqa: E402

settings.init_settings()

from api.db.db_models import Dialog  # noqa: E402
from api.db.services import dialog_service as ds  # noqa: E402

DIALOG_ID = "29a6da60ba1f11f1be9555eabe501d5b"
QUESTION = "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"
TARGET, CONTROL = "d1d75672f2dbc333", "b5aaf72bcd33d44a"
OUT = pathlib.Path("/tmp/route_queries.json")

CALLS = []


def main():
    dialog = Dialog.get_or_none(Dialog.id == DIALOG_ID)
    store = settings.docStoreConn
    original = store._es_search_once

    def capture(*args, **kwargs):
        body = args[1] if len(args) > 1 else kwargs.get("body") or kwargs.get("query")
        result = original(*args, **kwargs)
        hits = []
        try:
            hits = [{"id": h.get("_id"), "score": h.get("_score")} for h in result["hits"]["hits"]]
        except Exception:  # noqa: BLE001
            pass
        CALLS.append({"index": args[0] if args else None, "body": body, "returned": len(hits),
                      "ranks": {h["id"]: n for n, h in enumerate(hits, 1)},
                      "scores": {h["id"]: h["score"] for h in hits},
                      "target_rank": next((n for n, h in enumerate(hits, 1) if h["id"] == TARGET), None),
                      "control_rank": next((n for n, h in enumerate(hits, 1) if h["id"] == CONTROL), None)})
        return result

    store._es_search_once = capture

    async def go():
        items = []
        async for item in ds.async_chat(dialog=dialog,
                                        messages=[{"role": "user", "content": QUESTION}],
                                        stream=False, quote=True):
            items.append(item)
        return items

    asyncio.run(go())
    OUT.write_text(json.dumps({"calls": CALLS}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"captured {len(CALLS)} ES calls")
    for n, c in enumerate(CALLS, 1):
        b = c["body"] or {}
        kinds = []
        if isinstance(b, dict):
            q = b.get("query") or {}
            if isinstance(q, dict):
                kinds += list(q.keys())
            if "knn" in b:
                kinds.append("knn")
            if "aggs" in b:
                kinds.append("aggs")
        print(f"  call{n:2d}: returned={c['returned']:3d} target={c['target_rank']} "
              f"control={c['control_rank']} size={b.get('size') if isinstance(b, dict) else None} "
              f"kinds={sorted(set(kinds))}")


main()
