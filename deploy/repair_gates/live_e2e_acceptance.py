"""LIVE end-to-end acceptance through the real answer path.

Runs the production answer flow (`dialog_service.async_chat`) for the incident question on the
deployed candidate and inspects the payload a real client receives. This is the leg that a
retrieval-only probe cannot cover:

* the answer layer consumes degraded chunks, which is where the absent `vector: None` used to raise
  inside `insert_citations` as soon as the provider recovered between retrieval and citations;
* the response `reference` is what the P0-6 notice is computed from, so counting
  `retrieval_health` in it is the notice's real input;
* the P0-7 operator event must still be exactly one line for the turn;
* nothing sensitive may appear in the response or in the log.

Read-only for ES/MySQL/Redis. One answer is generated, which is the point of the check.
"""
import asyncio
import json
import logging
import os
import pathlib
import sys

sys.path.insert(0, "/ragflow")

from common import settings

settings.init_settings()

from api.db.db_models import Dialog
from api.db.services.dialog_service import async_chat

OUT = pathlib.Path(os.environ.get("P12_E2E_OUT", "/tmp/live_e2e_acceptance.json"))
DIALOG_ID = os.environ.get("P12_DIALOG_ID", "")
QUESTION = "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"

OPERATOR_MARKER = "[RetrievalHealth]"
#: Markers of a real leak INTO A CLIENT RESPONSE: credentials, the provider endpoint, a provider
#: error body, a stack trace. Deliberately NOT `content_with_weight` - that is the retrieved passage
#: text and it is the response's whole purpose. In the P0-7 OPERATOR LOG the same marker is a
#: legitimate leak check, because a log line must not carry chunk content; in an API response it is
#: not a leak at all.
LEAK_MARKERS = ("AQ.Ab8RN6", "AIza", "api_key", "api-key", "Authorization", "Bearer ", "generativelanguage", "Traceback", "File \"", "RESOURCE_EXHAUSTED", "FAILED_PRECONDITION")
#: The user-facing DTO's exact field set. Internals must not reach a client: the leg map and the
#: per-leg reasons belong to the P0-7 operator event, not to the response.
USER_HEALTH_FIELDS = {"overall", "evidence_completeness", "degradation_reason"}

operator_lines = []


class OperatorCapture(logging.Handler):
    def emit(self, record):
        message = record.getMessage()
        if message.startswith(OPERATOR_MARKER):
            operator_lines.append(message)


async def main():
    capture = OperatorCapture()
    logging.getLogger("rag.retrieval.health_producers").addHandler(capture)
    logging.getLogger("rag.retrieval.health_producers").setLevel(logging.INFO)

    dialog_row = Dialog.get_or_none(Dialog.id == DIALOG_ID)
    if dialog_row is None:
        print(json.dumps({"error": "dialog not found", "dialog_id": DIALOG_ID}), file=sys.stderr)
        return 1
    messages = [{"role": "user", "content": QUESTION}]

    operator_lines.clear()
    answers = []
    error = None
    try:
        async for chunk in async_chat(dialog_row, messages, stream=True):
            answers.append(chunk)
    except BaseException as exc:  # noqa: BLE001
        error = "%s: %s" % (type(exc).__name__, exc)

    final = answers[-1] if answers else {}
    if isinstance(final, dict) and final.get("final"):
        payload = final
    else:
        payload = next((item for item in reversed(answers) if isinstance(item, dict) and "answer" in item), {})

    # A streaming turn delivers the answer as DELTAS: the terminal chunk carries an empty `answer`
    # and the full reference, so the text has to be concatenated rather than read off the last item.
    answer_text = "".join(str(item.get("answer") or "") for item in answers if isinstance(item, dict))
    if not answer_text.strip():
        answer_text = str(payload.get("answer") or "")

    reference = payload.get("reference") or {}
    chunks = reference.get("chunks") or []
    health = reference.get("retrieval_health")
    events = []
    for line in operator_lines:
        try:
            events.append(json.loads(line[len(OPERATOR_MARKER):].strip()))
        except Exception:  # noqa: BLE001
            events.append({"_parse_error": True})

    serialized = json.dumps({"answer": payload.get("answer"), "reference": reference}, ensure_ascii=False)
    leaks = [marker for marker in LEAK_MARKERS if marker in serialized]

    report = {
        "purpose": "live end-to-end acceptance through the real answer path",
        "image": os.environ.get("P12_IMAGE", "unknown"),
        "dialog_id": DIALOG_ID,
        "question": QUESTION,
        "error": error,
        "stream_items": len(answers),
        "answer_length": len(answer_text),
        "answer_head": answer_text[:200],
        "reference_keys": sorted(reference.keys()),
        "chunk_count": len(chunks),
        "retrieval_health_present": health is not None,
        "retrieval_health": health,
        "retrieval_health_field_set": sorted(health.keys()) if isinstance(health, dict) else None,
        "retrieval_health_occurrences_in_payload": serialized.count('"retrieval_health"'),
        "chunk_has_vector_key_with_none": sum(1 for chunk in chunks if "vector" in chunk and chunk.get("vector") is None),
        "chunk_has_score_provenance": sum(1 for chunk in chunks if chunk.get("score_provenance")),
        "operator_event_count": len(events),
        "operator_events": events,
        "leak_markers_found": leaks,
    }
    report["checks"] = {
        "no_exception_on_the_answer_path": error is None,
        "reference_carries_chunks": len(chunks) > 0,
        "exactly_one_retrieval_health_in_the_payload": serialized.count('"retrieval_health"') == 1,
        "health_overall_degraded": bool(health) and health.get("overall") == "degraded",
        "health_reason_present": bool(health) and bool(health.get("degradation_reason")),
        "user_dto_exposes_no_internals": bool(health) and set(health.keys()) == USER_HEALTH_FIELDS,
        "operator_event_exactly_once": len(events) == 1,
        "operator_event_carries_the_leg_facts": bool(events) and (events[0].get("legs") or {}).get("dense") == "failed" and (events[0].get("legs") or {}).get("lexical") == "success",
        "operator_event_matches_the_user_dto": bool(events) and bool(health) and events[0].get("overall") == health.get("overall") and events[0].get("reason") == health.get("degradation_reason"),
        "no_sensitive_leak_in_the_response": not leaks,
    }
    report["answer_produced"] = bool(answer_text.strip())
    report["passed"] = all(report["checks"].values())

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("E2E_ACCEPTANCE_BEGIN")
    print(json.dumps({k: report[k] for k in ("checks", "retrieval_health", "operator_event_count", "leak_markers_found", "chunk_count", "answer_length", "passed")}, ensure_ascii=False, indent=1))
    print("E2E_ACCEPTANCE_END")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
