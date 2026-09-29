"""Diagnostic: does the OpenAI-compatible route emit a reference at all, and on which frame?

Line-buffers the SSE stream properly (aiohttp yields arbitrary chunks, not lines) and prints the LAST
frames plus whether any frame carried a `reference` key. Read-only; one retrieval.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, "/ragflow")

from common import settings

settings.init_settings()

import aiohttp
from common import settings as app_settings
from api.db.db_models import Dialog, User

BASE = os.environ.get("P12_BASE_URL", "http://127.0.0.1:9380")
DIALOG_ID = os.environ.get("P12_DIALOG_ID", "")
QUESTION = "Q/GDW 73286.2-2026 表 1 中单芯电缆的导体标称截面有哪些规格？"


def mint_token():
    from itsdangerous.url_safe import URLSafeTimedSerializer as Serializer

    dialog_row = Dialog.get_or_none(Dialog.id == DIALOG_ID)
    owner_id = getattr(dialog_row, "tenant_id", None) or getattr(dialog_row, "created_by", None)
    user = User.get_or_none(User.id == owner_id) or User.select().first()
    serializer = Serializer(secret_key=app_settings.get_secret_key())
    return str(serializer.dumps(str(user.access_token)))


async def run(reference_flag):
    token = mint_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"model": "model", "messages": [{"role": "user", "content": QUESTION}],
            "stream": True, "extra_body": {"reference": reference_flag}}
    url = f"{BASE}/api/v1/openai/{DIALOG_ID}/chat/completions"

    frames, buffer = [], ""
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body, headers=headers) as response:
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
                        frames.append({"_unparsed": line[:160]})

    carriers = [i for i, f in enumerate(frames)
                if isinstance(f, dict)
                and isinstance(f.get("choices"), list) and f["choices"]
                and isinstance(f["choices"][0].get("delta"), dict)
                and "reference" in f["choices"][0]["delta"]]
    print(f"reference_flag={reference_flag} status={status} frames={len(frames)} reference_frames={carriers}")
    for index in carriers:
        ref = frames[index]["choices"][0]["delta"]["reference"]
        print(f"  frame[{index}] reference type={type(ref).__name__} "
              f"keys={sorted(ref) if isinstance(ref, dict) else None} "
              f"chunks={len(ref.get('chunks') or []) if isinstance(ref, dict) else None}")
    if not carriers:
        print("  no frame carried a reference; tail frames:")
        for index, frame in enumerate(frames[-3:], start=len(frames) - 3):
            print(f"  frame[{index}] {json.dumps(frame, ensure_ascii=False)[:220]}")


async def main():
    await run(True)
    await run(False)


if __name__ == "__main__":
    asyncio.run(main())
