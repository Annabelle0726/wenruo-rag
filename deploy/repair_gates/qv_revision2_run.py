"""Two-arm runner for QV Revision 2: the SAME gates against the previous revision and this one.

Arm `rev1_semantic_boundary` is the revision the second Codex audit REJECTED (its product files were
snapshotted before this window edited anything, because that revision exists only as uncommitted work).
Arm `rev2_occurrence_model` is this window's implementation. The gate files are never swapped, so a PASS
in the rev2 arm is evidence and the rev1 arm's failures are the reproduction.

Both the behavioural gate and the occurrence gate are run; the occurrence gate is expected to fail at
COLLECTION in the rev1 arm, because the revision it is run against has no per-occurrence record at all -
which is the audit's finding, not an accident of the harness.
"""
import json
import pathlib
import re
import subprocess
import sys

GATE_DIR = pathlib.Path("/ragflow/deploy/repair_gates")
OUT = GATE_DIR / "question_value_revision2_result.json"
GATES = [
    "deploy/repair_gates/test_qv_revision2_gate.py",
    "deploy/repair_gates/test_qv_revision2_occurrence_gate.py",
]
ARMS = {
    "rev1_semantic_boundary": "/tmp/qv_rev1",
    "rev2_occurrence_model": "/tmp/qv_rev2",
}
PRODUCT_FILES = ("decomposition.py", "chunk_profile.py")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def run_arm(source: str) -> dict:
    for name in PRODUCT_FILES:
        pathlib.Path("/ragflow/rag/retrieval", name).write_bytes((pathlib.Path(source) / name).read_bytes())

    report = {"source": source, "gates": {}, "outcomes": {}}
    for gate in GATES:
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", gate, "-q", "--no-header", "--tb=no", "--color=no", "-p", "no:cacheprovider", "-rA"],
            cwd="/ragflow",
            capture_output=True,
            text=True,
        )
        lines = [_ANSI_RE.sub("", line).rstrip() for line in completed.stdout.splitlines() if line.strip()]
        report["gates"][gate] = {
            "exit_code": completed.returncode,
            "summary": lines[-1] if lines else "",
            "failed": [line.split(" ")[1] for line in lines if line.startswith("FAILED ")],
            "collection_error": any(line.startswith("ERROR ") for line in lines),
        }
        for line in lines:
            if line.startswith(("PASSED ", "FAILED ")):
                outcome, node = line.split(" ", 1)
                report["outcomes"][node.strip()] = outcome
    report["passed"] = sum(1 for value in report["outcomes"].values() if value == "PASSED")
    report["failed"] = sum(1 for value in report["outcomes"].values() if value == "FAILED")
    report["gate_files_failed"] = sum(1 for gate in report["gates"].values() if gate["exit_code"] != 0)
    return report


def main() -> int:
    result = {"purpose": "QV Revision 2: identical gates, previous revision vs this one", "arms": {}}
    for arm, source in ARMS.items():
        result["arms"][arm] = run_arm(source)
        entry = result["arms"][arm]
        print(f"{arm}: passed={entry['passed']} failed={entry['failed']} gate_files_failed={entry['gate_files_failed']}")

    rev1 = result["arms"]["rev1_semantic_boundary"]
    rev2 = result["arms"]["rev2_occurrence_model"]
    result["verdict"] = {
        "rev1_reproduces_the_reject": rev1["failed"] > 0 or rev1["gate_files_failed"] > 0,
        "rev2_passes": rev2["failed"] == 0 and rev2["gate_files_failed"] == 0,
        "closed_regressions": sorted(
            node for node, outcome in rev1["outcomes"].items() if outcome == "FAILED" and rev2["outcomes"].get(node) == "PASSED"
        ),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        "rev1_reproduces={rev1_reproduces_the_reject} rev2_passes={rev2_passes} closed={count}".format(
            count=len(result["verdict"]["closed_regressions"]), **result["verdict"]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
