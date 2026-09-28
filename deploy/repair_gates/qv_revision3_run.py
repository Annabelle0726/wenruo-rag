"""Two-arm runner for Numeric Rev 3: the same Rev-3 gates against Revision 2 and against this revision.

Arm `rev2_occurrence_model` is the revision Codex rejected on numeric grounds (`/tmp/qv_rev2`, snapshotted
before this window's first edit); arm `rev3_local_intent` is this window. The gate files are never swapped,
so the rev2 arm's failures are the reproduction and the rev3 arm's pass is evidence.

The mutation arm is run in both arms too. In the rev2 arm it fails at COLLECTION, because it asserts
against the original-offset API that revision does not have; that is reported rather than hidden.
"""
import json
import pathlib
import re
import subprocess
import sys

GATE_DIR = pathlib.Path("/ragflow/deploy/repair_gates")
OUT = GATE_DIR / "question_value_revision3_result.json"
GATES = [
    "deploy/repair_gates/test_qv_revision3_gate.py",
    "deploy/repair_gates/test_qv_revision3_mutation_arm.py",
]
ARMS = {
    "rev2_occurrence_model": "/tmp/qv_rev2",
    "rev3_local_intent": "/tmp/qv_rev3",
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
    result = {"purpose": "Numeric Rev 3: identical gates, revision 2 vs revision 3", "arms": {}}
    for arm, source in ARMS.items():
        result["arms"][arm] = run_arm(source)
        entry = result["arms"][arm]
        print(f"{arm}: passed={entry['passed']} failed={entry['failed']} gate_files_failed={entry['gate_files_failed']}")

    rev2 = result["arms"]["rev2_occurrence_model"]
    rev3 = result["arms"]["rev3_local_intent"]
    result["verdict"] = {
        "rev2_reproduces_the_numeric_reject": rev2["failed"] > 0 or rev2["gate_files_failed"] > 0,
        "rev3_passes": rev3["failed"] == 0 and rev3["gate_files_failed"] == 0,
        "closed": sorted(
            node for node, outcome in rev2["outcomes"].items() if outcome == "FAILED" and rev3["outcomes"].get(node) == "PASSED"
        ),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        "rev2_reproduces={rev2_reproduces_the_numeric_reject} rev3_passes={rev3_passes} closed={count}".format(
            count=len(result["verdict"]["closed"]), **result["verdict"]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
