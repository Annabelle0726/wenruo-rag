"""LIVE quote-true / quote-false matrix through the deployed server process.

Uses the chatbot completion route, which is the live route that forwards an explicit per-request
quoting flag to the retrieval answer path:

    if "quote" not in req: req["quote"] = False       # bot_api.chatbot_completions
    ...  iframe_completion(dialog_id, tenant_id=tenant_id, **req)   # -> dialog_service.async_chat

`dialog_service.async_chat` gates citations on `prompt_config["quote"] and kwargs["quote"]`, so sending
`quote` true/false exercises the two live arms. Both arms must still deliver `retrieval_health`
(the quote-health repair); citations must be present on quote=True and must stay suppressed on
quote=False. Secrets are never printed - the payload is scanned and only booleans are reported.

A dict-shaped reference (SDK/web envelope) and a list-shaped reference (OpenAI route) are both handled.
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
from api.db.db_models import Dialog, User

BASE = os.environ.get("P12_BASE_URL", "http://127.0.0.1:9380")
DIALOG_ID = os.environ.get("P12_DIALOG_ID", "")
QUESTION = "Q/GDW 73286.2-2026 表 1 中单芯电缆的导体标称截面有哪些规格？"
OUT = pathlib.Path(os.environ.get("P12_QUOTE_OUT", "/tmp/live_quote_matrix.json"))

USER_HEALTH_FIELDS = {"overall", "evidence_completeness", "degradation_reason"}
LEAK_MARKERS = ("AQ.Ab8RN6", "AIza", "api_key", "Authorization", "Bearer ", "generativelanguage",
                "Traceback", "RESOURCE_EXHAUSTED", "FAILED_PRECONDITION", "location is not supported")


def mint_token():
    from itsdangerous.url_safe import URLSafeTimedSerializer as Serializer

    dialog_row = Dialog.get_or_none(Dialog.id == DIALOG_ID)
    owner_id = getattr(dialog_row, "tenant_id", None) or getattr(dialog_row, "created_by", None)
    user = User.get_or_none(User.id == owner_id) or User.select().first()
    serializer = Serializer(secret_key=app_settings.get_secret_key())
    return str(serializer.dumps(str(user.access_token))), user.email


async def ask(session, headers, quote_flag):
    body = {"question": QUESTION, "stream": True, "quote": quote_flag}
    url = f"{BASE}/api/v1/chatbots/{DIALOG_ID}/completions"

    frames, buffer, status, raw_lines = [], "", None, []
    async with session.post(url, json=body, headers=headers) as response:
        status = response.status
        async for chunk in response.content.iter_any():
            buffer += chunk.decode("utf-8", "replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                if len(raw_lines) < 4:
                    raw_lines.append(line[:220])
                if line.startswith("data:"):
                    line = line[5:].strip()
                if line in ("[DONE]", ""):
                    continue
                try:
                    frames.append(json.loads(line))
                except Exception:  # noqa: BLE001
                    frames.append({"_unparsed": line[:200]})

    # Tolerant of the RAGFlow envelope (`data.{answer,reference,final}`) and the OpenAI shape.
    payloads = []
    for item in frames:
        if not isinstance(item, dict):
            continue
        if isinstance(item.get("data"), dict):
            payloads.append(item["data"])
        elif isinstance(item.get("choices"), list) and item["choices"]:
            choice = item["choices"][0]
            payloads.append(choice.get("delta") or choice.get("message") or {})

    terminal = next((p for p in reversed(payloads) if p.get("final")), None)
    if terminal is None:
        terminal = next((p for p in reversed(payloads) if p.get("reference") is not None), {})
    reference = terminal.get("reference")
    answer = "".join(str(p.get("answer") or p.get("content") or "") for p in payloads)
    serialized = json.dumps({"answer": answer, "reference": reference}, ensure_ascii=False)

    if isinstance(reference, dict):
        health = reference.get("retrieval_health")
        chunks, doc_aggs = reference.get("chunks"), reference.get("doc_aggs")
        keys = sorted(reference)
    elif isinstance(reference, list):
        health, doc_aggs = None, None
        chunks, keys = reference, None
    else:
        health = chunks = doc_aggs = keys = None

    return {
        "quote_flag": quote_flag,
        "http_status": status,
        "answer_length": len(answer),
        "reference_type": type(reference).__name__,
        "reference_keys": keys,
        "chunk_count": len(chunks) if isinstance(chunks, list) else 0,
        "doc_agg_count": len(doc_aggs) if isinstance(doc_aggs, list) else 0,
        "retrieval_health": health,
        "retrieval_health_occurrences": serialized.count('"retrieval_health"'),
        "leak_markers_found": [m for m in LEAK_MARKERS if m in serialized],
        "raw_head": raw_lines[:3],
    }


async def main():
    token, email = mint_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        on = await ask(session, headers, True)
        off = await ask(session, headers, False)

    checks = {
        "quote_true_http_200": on["http_status"] == 200,
        "quote_true_answer": on["answer_length"] > 0,
        "quote_true_health_present": isinstance(on["retrieval_health"], dict),
        "quote_true_health_dto_exact": isinstance(on["retrieval_health"], dict) and set(on["retrieval_health"]) == USER_HEALTH_FIELDS,
        "quote_true_citations_present": on["chunk_count"] > 0 and on["doc_agg_count"] > 0,
        "quote_true_exactly_one_health": on["retrieval_health_occurrences"] == 1,
        "quote_false_http_200": off["http_status"] == 200,
        "quote_false_answer": off["answer_length"] > 0,
        "quote_false_health_present": isinstance(off["retrieval_health"], dict),
        "quote_false_health_dto_exact": isinstance(off["retrieval_health"], dict) and set(off["retrieval_health"]) == USER_HEALTH_FIELDS,
        "quote_false_reference_is_health_only": off["reference_keys"] == ["retrieval_health"],
        "quote_false_no_chunks": off["chunk_count"] == 0,
        "quote_false_no_doc_aggs": off["doc_agg_count"] == 0,
        "quote_false_exactly_one_health": off["retrieval_health_occurrences"] == 1,
        "no_sensitive_leak": not on["leak_markers_found"] and not off["leak_markers_found"],
    }
    report = {"base_url": BASE, "route": f"/api/v1/chatbots/{DIALOG_ID}/completions",
              "user_email": email, "question": QUESTION,
              "quote_true": on, "quote_false": off, "checks": checks, "passed": all(checks.values())}
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("QUOTE_MATRIX_BEGIN")
    print(json.dumps({"checks": checks, "passed": report["passed"],
                      "quote_true": {k: on[k] for k in ("reference_keys", "chunk_count", "doc_agg_count", "retrieval_health", "answer_length")},
                      "quote_false": {k: off[k] for k in ("reference_keys", "chunk_count", "doc_agg_count", "retrieval_health", "answer_length")}},
                     ensure_ascii=False, indent=1))
    print("QUOTE_MATRIX_END")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
