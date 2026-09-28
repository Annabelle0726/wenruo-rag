"""LIVE HTTP acceptance: the deployed server process itself, end to end.

The in-process acceptance proves the chain on the deployed image's code; this proves it through the
RUNNING server, which is the only way to see the P0-7 operator event land in the container's own log
stream (a `docker exec` process writes to its own stdout, not to PID 1's).

Mints a session token with the application's own serializer and posts a real chat-completion
request, then inspects the streamed payload the client receives.
"""
import asyncio
import json
import os
import pathlib
import sys

sys.path.insert(0, "/ragflow")

from common import settings

settings.init_settings()

import aiohttp
from common import settings as app_settings
from api.db.db_models import User

BASE = os.environ.get("P12_BASE_URL", "http://127.0.0.1:9380")
DIALOG_ID = os.environ.get("P12_DIALOG_ID", "")
QUESTION = "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"
OUT = pathlib.Path(os.environ.get("P12_HTTP_OUT", "/tmp/live_http_acceptance.json"))

USER_HEALTH_FIELDS = {"overall", "evidence_completeness", "degradation_reason"}
LEAK_MARKERS = ("AQ.Ab8RN6", "AIza", "api_key", "Authorization", "Bearer ", "generativelanguage", "Traceback", "RESOURCE_EXHAUSTED", "FAILED_PRECONDITION")


def mint_token():
    """The application's own serializer, exactly as `User.get_id()` mints a session token."""
    from itsdangerous.url_safe import URLSafeTimedSerializer as Serializer

    user = User.select().first()
    serializer = Serializer(secret_key=app_settings.get_secret_key())
    return str(serializer.dumps(str(user.access_token))), user.email


async def main():
    token, email = mint_token()
    headers = {"Authorization": token, "Content-Type": "application/json"}
    body = {"question": QUESTION, "stream": True}
    url = f"{BASE}/api/v1/chats/{DIALOG_ID}/completions"

    answers = []
    raw_lines = []
    status = None
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body, headers=headers) as response:
            status = response.status
            async for raw in response.content:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                if len(raw_lines) < 40:
                    raw_lines.append(line[:300])
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line in ("[DONE]", ""):
                    continue
                try:
                    answers.append(json.loads(line))
                except Exception:  # noqa: BLE001
                    answers.append({"_unparsed": line[:200]})

    payload = next((item for item in reversed(answers) if isinstance(item, dict) and item.get("data") is True), {})
    if not payload:
        payload = next((item for item in reversed(answers) if isinstance(item, dict) and item.get("reference")), {})
    reference = payload.get("reference") or {}
    chunks = reference.get("chunks") or []
    health = reference.get("retrieval_health")
    answer_text = "".join(str(item.get("answer") or "") for item in answers if isinstance(item, dict))
    serialized = json.dumps({"answer": answer_text, "reference": reference}, ensure_ascii=False)
    leaks = [marker for marker in LEAK_MARKERS if marker in serialized]

    report = {
        "purpose": "live HTTP acceptance through the deployed server process",
        "base_url": BASE,
        "http_status": status,
        "user_email": email,
        "stream_items": len(answers),
        "answer_length": len(answer_text),
        "answer_head": answer_text[:160],
        "reference_keys": sorted(reference.keys()),
        "chunk_count": len(chunks),
        "retrieval_health": health,
        "retrieval_health_field_set": sorted(health.keys()) if isinstance(health, dict) else None,
        "retrieval_health_occurrences": serialized.count('"retrieval_health"'),
        "leak_markers_found": leaks,
        "raw_stream_head": raw_lines[:12],
        "parsed_item_keys": sorted({key for item in answers if isinstance(item, dict) for key in item}),
    }
    report["checks"] = {
        "http_200": status == 200,
        "answer_returned": bool(answer_text.strip()),
        "reference_carries_chunks": len(chunks) > 0,
        "exactly_one_retrieval_health": serialized.count('"retrieval_health"') == 1,
        "health_overall_degraded": bool(health) and health.get("overall") == "degraded",
        "health_reason_present": bool(health) and bool(health.get("degradation_reason")),
        "user_dto_exposes_no_internals": bool(health) and set(health.keys()) == USER_HEALTH_FIELDS,
        "no_sensitive_leak": not leaks,
    }
    report["passed"] = all(report["checks"].values())
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("HTTP_ACCEPTANCE_BEGIN")
    print(json.dumps({k: report[k] for k in ("http_status", "checks", "retrieval_health", "chunk_count", "answer_length", "leak_markers_found", "passed")}, ensure_ascii=False, indent=1))
    print("HTTP_ACCEPTANCE_END")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
