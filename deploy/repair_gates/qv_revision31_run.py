"""Two-arm runner for Rev 3.1: the same gates against Revision 3 and against this revision.

Arm `rev3_global_cue` is `e211bea5c` (`/tmp/qv_rev3`, snapshotted before this window's first edit); arm
`rev31_clause_local` is this window. Identical gate files, never swapped.
"""
import json
import pathlib
import re
import subprocess
import sys

GATE_DIR = pathlib.Path("/ragflow/deploy/repair_gates")
OUT = GATE_DIR / "question_value_revision31_result.json"
GATES = [
    "deploy/repair_gates/test_qv_revision31_gate.py",
    "deploy/repair_gates/test_qv_revision31_mutation_arm.py",
]
ARMS = {
    "rev3_global_cue": "/tmp/qv_rev3",
    "rev31_clause_local": "/tmp/qv_rev31",
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
    result = {"purpose": "Numeric Rev 3.1: identical gates, revision 3 vs revision 3.1", "arms": {}}
    for arm, source in ARMS.items():
        result["arms"][arm] = run_arm(source)
        entry = result["arms"][arm]
        print(f"{arm}: passed={entry['passed']} failed={entry['failed']} gate_files_failed={entry['gate_files_failed']}")

    rev3 = result["arms"]["rev3_global_cue"]
    rev31 = result["arms"]["rev31_clause_local"]
    result["verdict"] = {
        "rev3_reproduces_the_kill_audit": rev3["failed"] > 0 or rev3["gate_files_failed"] > 0,
        "rev31_passes": rev31["failed"] == 0 and rev31["gate_files_failed"] == 0,
        "closed": sorted(
            node for node, outcome in rev3["outcomes"].items() if outcome == "FAILED" and rev31["outcomes"].get(node) == "PASSED"
        ),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        "rev3_reproduces={rev3_reproduces_the_kill_audit} rev31_passes={rev31_passes} closed={count}".format(
            count=len(result["verdict"]["closed"]), **result["verdict"]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
