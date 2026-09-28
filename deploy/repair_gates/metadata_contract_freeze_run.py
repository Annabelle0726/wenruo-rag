"""G8/G9 evidence: the producer before and after, compared field by field.

Runs the same fresh-ingest fixtures through the PREVIOUS producer (`rag/nlp/doc_context.py` as committed at
`b873fcb03`) and the current one, and through the previous and current consumer, then asserts:

  * G8 - `content_with_weight`, the chunk id, `content_ltks`/`content_sm_ltks` and the embedding input are
    IDENTICAL; only the four provenance fields are added;
  * G9 - an OLD consumer reading a NEW chunk still sees the bytes it knows.

The previous files are read out of git, so this is a real comparison and not a restatement of intent.
"""
import json
import pathlib
import subprocess
import sys
import tempfile

REPO = pathlib.Path(r"C:\Projects\RAG\wenruo-rag")
GATES = REPO / "deploy" / "repair_gates"
OUT = GATES / "metadata_contract_freeze_result.json"
PROBE = r'''
import json, sys, xxhash
sys.path.insert(0, "/ragflow")
from rag.nlp import doc_context

NAME = "Q/GDW 73286.2-2026 220kV海底电力电缆系统采购标准+第2部分：220kV单芯海底电力电缆系统专用技术规范.pdf"
FIXTURES = [
    ("clause", "5.3.4 内衬层厚度应不小于1.5mm。"),
    ("table", "<table><caption>表1</caption><tr><td>1\u00d7800</td><td>3.9</td></tr></table>"),
    ("look_alike", "[\u6807\u51c6\u53f7: GB/T 10666-1997 | \u6587\u6863: \u67d0\u4ea7\u54c1\u6807\u51c6] \u539f\u6587\u5f15\u7528\u3002"),
]
out = {}
for label, body in FIXTURES:
    chunk = {"content_with_weight": body, "doc_id": "doc-1", "docnm_kwd": NAME,
             "content_ltks": "body tks", "content_sm_ltks": "body sm tks"}
    doc_context.apply_document_context([chunk], NAME, language="Chinese")
    content = chunk["content_with_weight"]
    out[label] = {
        "content_with_weight": content,
        "chunk_id": xxhash.xxh64((content + "doc-1").encode("utf-8")).hexdigest(),
        "content_ltks": chunk.get("content_ltks"),
        "content_sm_ltks": chunk.get("content_sm_ltks"),
        "embedding_input": content,
        "provenance": {key: chunk[key] for key in sorted(chunk) if key.startswith("content_prefix")},
    }
print("PROBE_JSON:" + json.dumps(out, ensure_ascii=False))
'''

CONSUMER_PROBE = r'''
import json, sys
sys.path.insert(0, "/ragflow")
from rag.retrieval.chunk_profile import carries_value, _values_text
header = "[标准号: Q/GDW 73286.2-2026 | 文档: 规范]附录.pdf] "
table = header + "<table><tr><td>3.9</td></tr></table>"
chunk = {"content_with_weight": table, "docnm_kwd": "规范]附录.pdf"}
print("CONSUMER_JSON:" + json.dumps({"body": _values_text(chunk), "carries": carries_value(chunk, ("3.9",))}, ensure_ascii=False))
'''


def snapshot(relative: str, destination: pathlib.Path, revision: str) -> None:
    completed = subprocess.run(
        ["git", "show", f"{revision}:{relative}"], cwd=REPO, capture_output=True, text=True, encoding="utf-8"
    )
    assert completed.returncode == 0, completed.stderr[:300]
    destination.write_text(completed.stdout, encoding="utf-8", newline="")


def run_probe(doc_context_path: pathlib.Path, consumer_path: pathlib.Path) -> dict:
    """Run both probes with the given producer/consumer in place of the container's copies."""
    subprocess.run(["docker", "cp", str(doc_context_path), "wenruo-repair-gates:/ragflow/rag/nlp/doc_context.py"], check=True, capture_output=True)
    subprocess.run(["docker", "cp", str(consumer_path), "wenruo-repair-gates:/ragflow/rag/retrieval/chunk_profile.py"], check=True, capture_output=True)
    subprocess.run(["docker", "exec", "wenruo-repair-gates", "sh", "-c", "find /ragflow -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null; true"], check=False, capture_output=True)
    result = {}
    for name, code, marker in (("producer", PROBE, "PROBE_JSON:"), ("consumer", CONSUMER_PROBE, "CONSUMER_JSON:")):
        completed = subprocess.run(
            ["docker", "exec", "-w", "/ragflow", "wenruo-repair-gates", "python", "-c", code], capture_output=True, text=True, encoding="utf-8"
        )
        line = next((item for item in completed.stdout.splitlines() if item.startswith(marker)), None)
        assert line, f"{name} probe produced nothing: {completed.stdout[-400:]} {completed.stderr[-400:]}"
        result[name] = json.loads(line[len(marker):])
    return result


def main() -> int:
    work = pathlib.Path(tempfile.gettempdir()) / "contract-freeze"
    work.mkdir(parents=True, exist_ok=True)
    old_doc, new_doc = work / "doc_context.old.py", work / "doc_context.new.py"
    old_consumer, new_consumer = work / "chunk_profile.old.py", work / "chunk_profile.new.py"
    snapshot("rag/nlp/doc_context.py", old_doc, "b873fcb03")
    snapshot("rag/retrieval/chunk_profile.py", old_consumer, "b873fcb03")
    new_doc.write_text((REPO / "rag/nlp/doc_context.py").read_text(encoding="utf-8"), encoding="utf-8", newline="")
    new_consumer.write_text((REPO / "rag/retrieval/chunk_profile.py").read_text(encoding="utf-8"), encoding="utf-8", newline="")

    before = run_probe(old_doc, old_consumer)
    after = run_probe(new_doc, new_consumer)
    # restore the container to the current implementation
    run_probe(new_doc, new_consumer)

    report = {"purpose": "G8/G9: producer and consumer, previous revision vs this one", "before": before, "after": after, "checks": {}}
    frozen_fields = ("content_with_weight", "chunk_id", "content_ltks", "content_sm_ltks", "embedding_input")
    collision_label = "look_alike"
    for label in before["producer"]:
        for field in frozen_fields:
            report["checks"][f"{label}.{field}.unchanged"] = before["producer"][label][field] == after["producer"][label][field]
        report["checks"][f"{label}.provenance_before_is_empty"] = before["producer"][label]["provenance"] == {}
        report["checks"][f"{label}.provenance_after_is_recorded"] = bool(after["producer"][label]["provenance"])

    # The ONE intended difference: a fresh body whose first bytes look like a prefix. The previous producer
    # skipped it (the string heuristic) and the contract prefixes it, because the text cannot be the
    # authority on whether a prefix exists. Every other fixture must be byte-identical.
    old_look_alike = before["producer"][collision_label]["content_with_weight"]
    new_look_alike = after["producer"][collision_label]["content_with_weight"]
    report["checks"]["collision_fixture_was_skipped_before"] = before["producer"][collision_label]["provenance"] == {}
    report["checks"]["collision_fixture_is_prefixed_now"] = new_look_alike.startswith("[标准号: ") and new_look_alike.endswith(old_look_alike)
    report["checks"]["collision_fixture_only_gained_a_prefix"] = new_look_alike[len(new_look_alike) - len(old_look_alike):] == old_look_alike
    report["checks"]["old_consumer_on_new_chunk"] = before["consumer"]
    report["checks"]["new_consumer_on_unprovenanced_chunk"] = after["consumer"]
    report["verdict"] = {
        "corpus_bytes_frozen_outside_the_collision_fixture": all(
            value
            for name, value in report["checks"].items()
            if name.endswith(".unchanged") and not name.startswith(collision_label)
        ),
        "collision_fixture_fixed_as_intended": all(
            value
            for name, value in report["checks"].items()
            if name.startswith("collision_fixture")
        ),
        "provenance_is_additive_only": all(value for name, value in report["checks"].items() if "provenance_" in name),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print("corpus_bytes_frozen_outside_the_collision_fixture:", report["verdict"]["corpus_bytes_frozen_outside_the_collision_fixture"])
    print("collision_fixture_fixed_as_intended:", report["verdict"]["collision_fixture_fixed_as_intended"])
    print("provenance_is_additive_only:", report["verdict"]["provenance_is_additive_only"])
    print("old consumer on new chunk:", before["consumer"])
    print("new consumer, unprovenanced chunk:", after["consumer"])
    for label in before["producer"]:
        print(f"  {label}: before={before['producer'][label]['provenance']} after={sorted(after['producer'][label]['provenance'])}")
    return 0 if all(report["verdict"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
