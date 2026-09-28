"""Phase-0 RED probe for the quote-dependent retrieval_health loss.

Test-only. Drives the REAL `dialog_service.async_chat` so that its own nested `decorate_answer` closure
processes a controlled retrieval result; nothing here reimplements the branch. External dependencies are
stubbed permissively, and the entry-point kwargs are built from the real signature.

Prints the A-I matrix when the seam is reached, and the exact failure point when it is not.
"""
import asyncio
import inspect
import copy
import json
import os
import sys
import traceback

sys.path.insert(0, "/ragflow")

HEALTH = {
    "schema_version": "1.0",
    "overall": "degraded",
    "evidence_completeness": "partial",
    "degradation_reason": "EMBEDDING_UNAVAILABLE",
}
HEALTHY = {
    "schema_version": "1.0",
    "overall": "ok",
    "evidence_completeness": "complete",
    "degradation_reason": None,
}


class Permissive:
    """An attribute-tolerant stand-in: unknown attributes yield another permissive object."""

    def __init__(self, **kwargs):
        object.__setattr__(self, "_given", dict(kwargs))
        self.__dict__.update(kwargs)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return Permissive()

    def __call__(self, *args, **kwargs):
        return Permissive()

    def __bool__(self):
        return True

    def __iter__(self):
        return iter(())


def make_kbinfos(with_health=True, with_chunks=True, health=None):
    payload = {"chunks": [], "doc_aggs": [], "total": 1}
    if with_chunks:
        payload["chunks"] = [{"id": "x", "chunk_id": "x", "content_with_weight": "evidence text",
                              "content_ltks": "evidence text", "doc_id": "d1", "docnm_kwd": "n.pdf",
                              "vector": [0.0] * 8, "kb_id": "kb1"}]
        payload["doc_aggs"] = [{"doc_id": "d1", "doc_name": "n.pdf", "count": 1}]
    if with_health:
        payload["retrieval_health"] = dict(health or HEALTH)
    return payload


CONTROL = {"kbinfos": None}


def build_module_stubs(ds):
    """Patch only the imported symbols of the real module; the module's own code stays in charge."""
    import api.db.services.conversation_service as cs

    captured = {"kwargs": {}}

    class StubLLM:
        def __init__(self, *args, **kwargs):
            pass

        def __getattr__(self, name):
            def _call(*a, **k):
                # Feed any callback the real code hands us a deterministic answer, then stop.
                for value in list(a) + list(k.values()):
                    if callable(value):
                        try:
                            value("stub answer")  # decorate_answer style: single-arg
                        except TypeError:
                            try:
                                value("stub answer", True)
                            except TypeError:
                                pass
                        captured["callback_called"] = name
                return "stub answer"

            return _call

        async def chat_streamly(self, *a, **k):
            for value in list(a) + list(k.values()):
                if callable(value):
                    value("stub answer")
                    captured["callback_called"] = "chat_streamly"
            yield "stub answer"

        async def async_chat(self, *a, **k):
            """Non-streaming branch: `answer = await chat_mdl.async_chat(...)` then `decorate_answer(answer)`."""
            captured["callback_called"] = "async_chat"
            return "stub answer"

    return captured, StubLLM


async def _async_noop(*_a, **_k):
    """Neutralise a provider/ES-touching coroutine seam; it is not the behaviour under test."""
    return None


class StubRetriever:
    """The plain-deployment shape: no children config, and a model answer carrying no citation marker.

    `retrieval_by_children` is a passthrough and `insert_citations` finds nothing to cite, which is the
    degraded/no-citation case this gate is about. Citation formatting itself is covered elsewhere.
    """

    def retrieval_by_children(self, chunks, tenant_ids):
        return chunks

    def retrieval_by_toc(self, *_a, **_k):
        return None

    def insert_citations(self, answer, ltks, vectors, embd_mdl, **kwargs):
        return answer, []


async def drive(quote, kbinfos_payload):
    from api.db.services import dialog_service as ds
    import api.db.services.conversation_service as cs
    from unittest import mock

    captured, StubLLM = build_module_stubs(ds)
    CONTROL["kbinfos"] = kbinfos_payload

    async def fake_retrieve(*a, **k):
        # The real entry point is awaited by `async_chat`; hand back the exact payload object so the
        # probe can prove whether the product copies it or aliases the caller's dict.
        return CONTROL["kbinfos"]

    patches = []
    for target, value in (
        ("LLMBundle", StubLLM),
        ("DialogService", Permissive(query=lambda **kw: [Permissive(id="dlg", tenant_id="t1", kb_ids=["kb1"])])),
        ("KnowledgebaseService", Permissive(get_by_id=lambda *_a, **_k: (True, Permissive(id="kb1", embd_id="e1", tenant_id="t1")))),
        ("TenantService", Permissive(get_by_id=lambda *_a, **_k: (True, Permissive(tenancy_id="t1", llm_id="l1")))),
        ("Langfuse", Permissive()),
        ("FileService", Permissive()),
        ("DocMetadataService", Permissive()),
        ("TenantLangfuseService", Permissive()),
        ("RAGTools", Permissive()),
        # Model resolution and bundle construction are provider/DB seams, not the behaviour under test:
        # the probe drives the real `decorate_answer` and the real return statement.
        ("get_tenant_default_model_by_type", lambda *_a, **_k: {"llm_factory": "", "max_tokens": 8192, "model_type": "chat", "llm_name": "stub-chat"}),
        ("get_models", lambda *_a, **_k: (
            [Permissive(id="kb1", tenant_id="t1", embd_id="e1", parser_config={}, language="Chinese", name="kb1")],
            Permissive(encode_queries=lambda *_a, **_k: [[0.0] * 8]),
            None,
            StubLLM(),
            None,
        )),
        ("_hydrate_chunk_vectors", _async_noop),
    ):
        if hasattr(ds, target):
            patches.append(mock.patch.object(ds, target, value, create=True))

    # The retriever object itself: only its ES-touching children/TOC lookups are neutralised, the real
    # `kb_prompt` / citation-marker / recall-doc code below stays in charge.
    if hasattr(ds, "settings"):
        patches.append(mock.patch.object(ds.settings, "retriever", StubRetriever(), create=True))
        patches.append(mock.patch.object(ds.settings, "kg_retriever", StubRetriever(), create=True))

    # The retrieval entry point, by whichever name this module uses.
    for name in ("retrieve_multi_route", "retrieval", "retrieve"):
        if hasattr(ds, name):
            patches.append(mock.patch.object(ds, name, fake_retrieve, create=True))
    for module_name in ("pipeline", "pipeline_module", "retrieval_pipeline"):
        module = getattr(ds, module_name, None)
        if module is not None and hasattr(module, "retrieve_multi_route"):
            patches.append(mock.patch.object(module, "retrieve_multi_route", fake_retrieve))

    started = [p.start() for p in patches]
    try:
        kwargs = {}
        signature = inspect.signature(ds.async_chat)
        for name, parameter in signature.parameters.items():
            if name == "dialog":
                # The real first parameter: an attribute-tolerant stand-in carrying the fields the real
                # code reads. `prompt_config["quote"]` stays True so that the quote-OFF case is driven by
                # `kwargs["quote"]` alone, which is how the reviewed condition is written.
                kwargs[name] = Permissive(
                    id="dlg", dialog_id="dlg", tenant_id="t1", kb_ids=["kb1"],
                    llm_id=None, tenant_llm_id=None, rerank_id=None,
                    prompt_config={
                        "quote": True,
                        "system": "You are a helpful assistant. Answer from the context.\n\n{knowledge}",
                        # `knowledge` must be a declared parameter, otherwise the retrieval block is skipped
                        # and `kbinfos` stays the empty default - an unreachable-test artefact, not a result.
                        "parameters": [{"key": "knowledge", "optional": True}],
                        "empty_response": "",
                        "prologue": "",
                    },
                    vector_similarity_weight=0.3, similarity_threshold=0.0, top_n=6, top_k=1024,
                    parser_id=None, language="Chinese", message=[], reference=[], status="1", name="probe",
                )
            elif name == "messages":
                kwargs[name] = [{"role": "user", "content": "内衬层厚度是多少？"}]
            elif name in ("dialog_id", "chat_id"):
                kwargs[name] = "dlg"
            elif name in ("message", "question"):
                kwargs[name] = [{"role": "user", "content": "内衬层厚度是多少？"}] if name == "message" else "内衬层厚度是多少？"
            elif name == "stream":
                kwargs[name] = False
            elif name == "session_id":
                kwargs[name] = "s1"
            elif name == "quote":
                kwargs[name] = quote
            elif parameter.default is inspect.Parameter.empty:
                kwargs[name] = None
        # `async_chat(dialog, messages, stream=True, **kwargs)` has no named `quote` parameter, so the
        # per-caller quoting flag travels through **kwargs; without this the probe would silently test
        # quote=True in every case and the quote-OFF arm would be unreachable.
        kwargs["quote"] = quote
        CONTROL["kwargs"] = kwargs
        result = ds.async_chat(**kwargs)
        if inspect.isasyncgen(result):
            answers = []
            async for item in result:
                answers.append(item)
            return {"mode": "asyncgen", "items": answers, "captured": captured}
        if inspect.iscoroutine(result):
            return {"mode": "coroutine", "items": [await result], "captured": captured}
        return {"mode": type(result).__name__, "items": list(result) if hasattr(result, "__iter__") else [result], "captured": captured}
    finally:
        for patch in patches:
            patch.stop()


def observe(label, reference, source_health):
    health = reference.get("retrieval_health") if isinstance(reference, dict) else None
    print(json.dumps({
        "boundary": label,
        "type": type(reference).__name__,
        "keys": sorted(reference)[:12] if isinstance(reference, dict) else None,
        "len": len(reference) if hasattr(reference, "__len__") else None,
        "retrieval_health_present": health is not None,
        "equals_input": health == source_health if source_health is not None else None,
        "is_input_object": health is source_health,
    }, ensure_ascii=False), flush=True)


def run_case(label, quote, with_health=True, with_chunks=True, health=None):
    payload = make_kbinfos(with_health=with_health, with_chunks=with_chunks, health=health)
    source_health = payload.get("retrieval_health")
    source_health_snapshot = copy.deepcopy(source_health)
    print(f"\n--- {label} (quote={quote} health={'present' if with_health else 'absent'}) ---", flush=True)
    try:
        outcome = asyncio.run(drive(quote, payload))
    except BaseException as exc:  # noqa: BLE001
        traceback.print_exc()
        print(json.dumps({"case": label, "reached_decorate_answer": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), flush=True)
        return None
    answers = [item for item in outcome["items"] if isinstance(item, dict) and item.get("reference") is not None]
    reference = answers[-1]["reference"] if answers else None
    observe(label, reference, source_health)
    print(json.dumps({"case": label, "reached_decorate_answer": True, "mode": outcome["mode"],
                      "callback": outcome["captured"].get("callback_called"),
                      "kbinfos_health_after": payload.get("retrieval_health") == source_health}, ensure_ascii=False), flush=True)

    # Copy / aliasing contract, and the downstream serialization the client actually reads.
    # Snapshot BEFORE the mutation probe and before `structure_answer`, which edits the dict it is given
    # in place (it writes `reference["chunks"]`); the assertions are about what `async_chat` returned.
    ref_health = reference.get("retrieval_health") if isinstance(reference, dict) else None
    raw_keys = sorted(reference) if isinstance(reference, dict) else None
    health_snapshot = copy.deepcopy(ref_health)
    citation_content_present = bool(reference.get("chunks")) if isinstance(reference, dict) else None
    health_is_a_copy = (ref_health is not source_health) if source_health is not None else None
    print(json.dumps({"case": label, "aliasing": {
        "source_health_unchanged": payload.get("retrieval_health") == source_health_snapshot,
        "returned_equals_source_by_value": (health_snapshot == source_health) if source_health is not None else None,
        "returned_is_a_different_object": health_is_a_copy,
        "citation_content_present": citation_content_present,
    }}, ensure_ascii=False), flush=True)
    if isinstance(ref_health, dict):
        ref_health["MUTATION_PROBE"] = True
        mutation_isolated = payload.get("retrieval_health", {}).get("MUTATION_PROBE") is None
        print(json.dumps({"case": label, "aliasing": {
            "downstream_mutation_left_source_untouched": mutation_isolated,
        }}, ensure_ascii=False), flush=True)
    else:
        mutation_isolated = None
    downstream_visible, downstream_keys, downstream_type = None, None, None
    try:
        import api.db.services.conversation_service as cs

        ans = {"answer": "stub answer", "reference": reference if reference is not None else [], "final": True}
        structured = cs.structure_answer(None, ans, "m1", "s1")
        serialized = json.dumps(structured.get("reference"), ensure_ascii=False, default=str)
        downstream_type = type(structured.get("reference")).__name__
        downstream_keys = sorted(structured["reference"]) if isinstance(structured.get("reference"), dict) else None
        downstream_visible = "retrieval_health" in serialized
        print(json.dumps({"case": label, "downstream": {
            "reference_type": downstream_type,
            "keys": downstream_keys,
            "retrieval_health_visible": downstream_visible,
        }}, ensure_ascii=False), flush=True)
    except BaseException as exc:  # noqa: BLE001
        print(json.dumps({"case": label, "downstream_error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False), flush=True)

    RESULTS.append({
        "case": label,
        "quote": quote,
        "with_health": with_health,
        "with_chunks": with_chunks,
        "reference_type": type(reference).__name__,
        "reference_keys": raw_keys,
        "health_present": isinstance(ref_health, dict),
        "health_equals_source": (health_snapshot == source_health) if source_health is not None else None,
        "health_is_a_copy": health_is_a_copy,
        "source_untouched_by_downstream_mutation": mutation_isolated,
        "citation_content_present": citation_content_present,
        "downstream_health_visible": downstream_visible,
        "downstream_reference_keys": downstream_keys,
    })
    return reference


RESULTS = []


def verdict():
    """Turn the observed matrix into a pass/fail gate for the arm named by QUOTE_HEALTH_ARM.

    `red` asserts the defect is reproducible on the unrepaired source (health lost whenever the quote
    branch does not populate `refs`), `green` asserts authoritative health survives on every path and
    that nothing is invented when no authoritative health exists.
    """
    arm = os.environ.get("QUOTE_HEALTH_ARM", "green").strip().lower()
    failures = []
    seen = {record["case"]: record for record in RESULTS}
    expected_labels = [case for case, _quote, _kwargs in CASES]
    if len(seen) != len(expected_labels):
        failures.append(f"cases executed: observed={sorted(seen)} expected={sorted(expected_labels)}")

    for case in expected_labels:
        record = seen.get(case)
        if record is None:
            failures.append(f"{case}: not executed")
            continue
        # Citation behaviour must be identical in both arms.
        if record["with_chunks"] and record["quote"] and not record["citation_content_present"]:
            failures.append(f"{case}: quote=True dropped citation content")
        if record["with_chunks"] and not record["quote"] and record["citation_content_present"]:
            failures.append(f"{case}: quote=False exposed citation content")
        if record["with_health"]:
            # Authoritative retrieval health exists, so it must survive on every path - quoting on or
            # off, chunks or no chunks. These assertions describe the required behaviour, so the
            # unrepaired source fails them by construction and the repaired source must pass them.
            if record["health_present"] is not True:
                failures.append(f"{case}: authoritative retrieval_health did not survive")
                continue
            if record["health_equals_source"] is not True:
                failures.append(f"{case}: returned health differs from authoritative health")
            if record["health_is_a_copy"] is not True:
                failures.append(f"{case}: returned health is the caller's object")
            if record["source_untouched_by_downstream_mutation"] is not True:
                failures.append(f"{case}: source health aliased by the returned reference")
            if not record["quote"] and record["reference_keys"] != ["retrieval_health"]:
                failures.append(f"{case}: quote=False reference carries non-metadata keys {record['reference_keys']}")
            if record["downstream_health_visible"] is not True:
                failures.append(f"{case}: health not visible after structure_answer/serialization")
        else:
            if record["health_present"]:
                failures.append(f"{case}: invented retrieval_health with no authoritative health")
            if record["reference_type"] != ("dict" if record["quote"] and record["with_chunks"] else "list"):
                failures.append(f"{case}: reference shape changed without authoritative health: {record['reference_type']}")

    print(json.dumps({"arm": arm, "executed": len(RESULTS), "verdict": "PASS" if not failures else "FAIL",
                      "failures": failures}, ensure_ascii=False), flush=True)
    return 0 if not failures else 1


print("async_chat signature:", inspect.signature(__import__("api.db.services.dialog_service", fromlist=["x"]).async_chat), flush=True)
CASES = (
    ("A quote=True degraded+chunks", True, {}),
    ("B quote=False degraded+chunks", False, {}),
    ("C quote=True health absent", True, {"with_health": False}),
    ("D quote=False health absent", False, {"with_health": False}),
    ("E quote=True healthy", True, {"health": HEALTHY}),
    ("F quote=False healthy", False, {"health": HEALTHY}),
    ("G quote=True degraded zero chunks", True, {"with_chunks": False}),
    ("H quote=False degraded zero chunks", False, {"with_chunks": False}),
)
for label, quote, kwargs in CASES:
    run_case(label, quote, **kwargs)
print("\nPROBE COMPLETE", flush=True)
sys.exit(verdict())
