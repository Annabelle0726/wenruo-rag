"""LIVE acceptance against the DEPLOYED container's own server process.

Posts the original QGDW question and one non-QGDW sanity question to the running server's
OpenAI-compatible route and captures the answer, the reference and the retrieval health for each.
Run inside the deployed container so the serving process is the deployed image.
"""
import asyncio
import json
import os
import pathlib
import re
import sys

sys.path.insert(0, "/ragflow")

from common import settings

settings.init_settings()

import aiohttp
from common import settings as app_settings
from api.db.db_models import Dialog, User

BASE = "http://127.0.0.1:9380"
DIALOG_ID = os.environ.get("P12_DIALOG_ID", "29a6da60ba1f11f1be9555eabe501d5b")
QGDW = "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"
SANITY = "220kV 三芯海缆的主要结构有哪些？"


def mint_token():
    from itsdangerous.url_safe import URLSafeTimedSerializer as Serializer

    row = Dialog.get_or_none(Dialog.id == DIALOG_ID)
    owner = getattr(row, "tenant_id", None) or getattr(row, "created_by", None)
    user = User.get_or_none(User.id == owner) or User.select().first()
    return str(Serializer(secret_key=app_settings.get_secret_key()).dumps(str(user.access_token)))


async def ask(session, headers, question):
    body = {"question": question, "stream": True, "chat_id": DIALOG_ID}
    frames, buffer, status = [], "", None
    async with session.post(f"{BASE}/api/v1/chat/completions", json=body, headers=headers) as response:
        status = response.status
        async for chunk in response.content.iter_any():
            buffer += chunk.decode("utf-8", "replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                line = line[5:].strip()
                if line in ("[DONE]", ""):
                    continue
                try:
                    frames.append(json.loads(line))
                except Exception:  # noqa: BLE001
                    pass
    payloads = [f["data"] for f in frames if isinstance(f, dict) and isinstance(f.get("data"), dict)]
    terminal = next((p for p in reversed(payloads) if p.get("final")), {})
    answer = "".join(str(p.get("answer") or "") for p in payloads)
    reference = terminal.get("reference") or {}
    return {"status": status, "answer": answer,
            "reference_keys": sorted(reference) if isinstance(reference, dict) else None,
            "chunk_count": len(reference.get("chunks") or []) if isinstance(reference, dict) else None,
            "health": reference.get("retrieval_health") if isinstance(reference, dict) else None}


async def main():
    token = mint_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        qgdw = await ask(session, headers, QGDW)
        sanity = await ask(session, headers, SANITY)

    text = qgdw["answer"]
    three = sorted({int(v) for v in re.findall(r"3\s*[×x]\s*(\d{3,4})", text)})
    single = sorted({int(v) for v in re.findall(r"1\s*[×x]\s*(\d{3,4})", text)})
    out = {
        "qgdw": qgdw, "sanity": sanity,
        "three_core_values_in_answer": three,
        "single_core_values_in_answer": single,
        "three_core_range_ok": bool(three) and three[0] == 400 and three[-1] == 1600,
        "three_core_count_8": bool(re.search(r"(8\s*(种|个)?\s*(规格|截面)|共\s*8)", text)),
        "single_core_range_ok": bool(single) and single[0] == 400 and single[-1] == 2000,
        "single_core_count_10": bool(re.search(r"(10\s*(种|个)?\s*(规格|截面)|共\s*10)", text)),
    }
    pathlib.Path("/tmp/live_fusion_qa.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("=== QGDW ANSWER ===")
    print(text)
    print()
    print("three-core values:", three, " count8:", out["three_core_count_8"])
    print("single-core values:", single, " count10:", out["single_core_count_10"])
    print("qgdw status:", qgdw["status"], "chunks:", qgdw["chunk_count"], "health:", json.dumps(qgdw["health"], ensure_ascii=False))
    print()
    print("=== SANITY ANSWER (", SANITY, ") ===")
    print(sanity["answer"][:700])
    print("sanity status:", sanity["status"], "chunks:", sanity["chunk_count"], "health:", json.dumps(sanity["health"], ensure_ascii=False))


asyncio.run(main())
