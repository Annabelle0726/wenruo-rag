"""Adjudicate the single GROUP_E failure: `attach_retrieval_health` returned only ['chunks'].

Three arms, run in the same context discipline as the acceptance driver:

  1. HARNESS REPRODUCTION - exactly what the driver does: obtain a session object produced inside an
     earlier `asyncio.run(...)` and then call `attach_retrieval_health` from the OUTER context, with no
     `begin_retrieval_health` issued in that outer context.
  2. SAME-CONTEXT CONTROL - issue `begin_retrieval_health` in the calling context, then attach.
  3. NO-SESSION CONTROL - attach with no session at all.

The product module is the image's own `rag.retrieval.health_bridge`; nothing is stubbed or patched.
Run it on BOTH the deployed base and the candidate: an identical outcome on both proves the driver
failure is not introduced by the nine-file overlay.
"""
import asyncio
import sys

sys.path.insert(0, "/ragflow")

from common import settings  # noqa: E402

settings.init_settings()

from rag.retrieval import health_bridge as hb  # noqa: E402

results = {}


def observe(label, value):
    results[label] = sorted(value)
    print(f"  {label}: {sorted(value)}", flush=True)


# --- 1. harness reproduction: session created inside asyncio.run, attach from the outer context --------
async def _inner():
    hb.begin_retrieval_health("inner")
    return hb.current_session()


inner_session = asyncio.run(_inner())
print(f"session object obtained from the inner context: {inner_session is not None}", flush=True)
print(f"current_session() in the OUTER context: {hb.current_session()!r}", flush=True)
observe("arm1_harness_reproduction", hb.attach_retrieval_health({"chunks": [{"id": "x"}]}))

# --- 2. same-context control: begin then attach in THIS context ---------------------------------------
hb.begin_retrieval_health("same-context")
print(f"current_session() after begin in THIS context: {hb.current_session() is not None}", flush=True)
observe("arm2_same_context_control", hb.attach_retrieval_health({"chunks": [{"id": "x"}]}))

# --- 3. no-session control: the contextvar is reset, so attach must pass the dict through -------------
hb.reset_retrieval_health() if hasattr(hb, "reset_retrieval_health") else None
print(f"current_session() after reset: {hb.current_session()!r}", flush=True)
observe("arm3_no_session_control", hb.attach_retrieval_health({"chunks": [{"id": "x"}]}))

print(flush=True)
arm1_ok = results["arm1_harness_reproduction"] == ["chunks"]
arm2_ok = results["arm2_same_context_control"] == ["chunks", "retrieval_health"]
arm3_ok = results["arm3_no_session_control"] == ["chunks"]
print(f"ARM1_REPRODUCES_DRIVER_LOSS = {arm1_ok}", flush=True)
print(f"ARM2_CONTRACT_HOLDS_IN_CONTEXT = {arm2_ok}", flush=True)
print(f"ARM3_PASSTHROUGH_WITHOUT_SESSION = {arm3_ok}", flush=True)
print(f"ATTACH_CONTRACT_HELD = {arm2_ok and arm3_ok}", flush=True)
print(f"DRIVER_FAILURE_IS_A_HARNESS_CONTEXTVAR_ARTIFACT = {arm1_ok and arm2_ok}", flush=True)
