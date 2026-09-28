"""Two-arm gate runner: the SAME gates against the REJECTED repair and against this revision.

Arm A mounts the two product files as committed at the rejected revision (`git show HEAD:…`), arm B
mounts the working tree. The gate files themselves are never swapped: the whole point is that identical
tests are run against both, so a PASS on the revision means something.

Usage (inside the gate container, with `deploy/repair_gates` and both arms' files visible):
    python deploy/repair_gates/question_value_two_arm_run.py

It writes `question_value_two_arm_result.json` next to itself and prints one ASCII summary line per arm.
"""
import json
import pathlib
import re
import subprocess
import sys

#: pytest colourises its short summary even through a pipe in this image, which turns `PASSED x` into
#: `\x1b[32mPASSED\x1b[0m x` and silently defeats a prefix match. Both belt and braces: ask for no colour
#: and strip any escape that arrives anyway.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

GATE_DIR = pathlib.Path("/ragflow/deploy/repair_gates")
GATES = [
    "deploy/repair_gates/test_question_value_adversarial_gate.py",
    "deploy/repair_gates/test_question_value_class_gate.py",
    "deploy/repair_gates/test_question_value_feature_gates.py",
]
ARMS = {
    "A_rejected_repair": "/tmp/arm_a",
    "B_revision": "/tmp/arm_b",
}
PRODUCT_FILES = ("decomposition.py", "chunk_profile.py")


def run_arm(arm: str, source: str) -> dict:
    """Point `/ragflow/rag/retrieval/` at one arm's product files and run every gate."""
    for name in PRODUCT_FILES:
        candidate = pathlib.Path(source) / name
        target = pathlib.Path("/ragflow/rag/retrieval") / name
        target.write_bytes(candidate.read_bytes())

    report = {"source": source, "gates": {}, "outcomes": {}}
    for gate in GATES:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                gate,
                "-q",
                "--no-header",
                "--tb=no",
                "--color=no",
                "-p",
                "no:cacheprovider",
                "-rA",
            ],
            cwd="/ragflow",
            capture_output=True,
            text=True,
        )
        tail = [_ANSI_RE.sub("", line).rstrip() for line in completed.stdout.splitlines() if line.strip()]
        summary = tail[-1] if tail else ""
        report["gates"][gate] = {
            "exit_code": completed.returncode,
            "summary": summary,
            "failed": [line.split(" ")[1] for line in tail if line.startswith("FAILED ")],
            "errors": [line.split(" ")[1] for line in tail if line.startswith("ERROR ")],
        }
        for line in tail:
            if line.startswith("PASSED ") or line.startswith("FAILED ") or line.startswith("ERROR "):
                outcome, node = line.split(" ", 1)
                report["outcomes"][node.strip()] = outcome
    report["passed"] = sum(1 for value in report["outcomes"].values() if value == "PASSED")
    report["failed"] = sum(1 for value in report["outcomes"].values() if value == "FAILED")
    report["gate_files_failed"] = sum(1 for gate in report["gates"].values() if gate["exit_code"] != 0)
    return report


def main() -> int:
    result = {"arms": {}}
    for arm, source in ARMS.items():
        result["arms"][arm] = run_arm(arm, source)
        entry = result["arms"][arm]
        print(f"{arm}: passed={entry['passed']} failed={entry['failed']} gate_files_failed={entry['gate_files_failed']}")

    rejected = result["arms"]["A_rejected_repair"]
    revision = result["arms"]["B_revision"]
    result["verdict"] = {
        "rejected_arm_fails": rejected["failed"] > 0 or rejected["gate_files_failed"] > 0,
        "revision_arm_passes": revision["failed"] == 0 and revision["gate_files_failed"] == 0,
        "failing_on_rejected_but_passing_on_revision": sorted(
            node
            for node, outcome in rejected["outcomes"].items()
            if outcome == "FAILED" and revision["outcomes"].get(node) == "PASSED"
        ),
    }
    (GATE_DIR / "question_value_two_arm_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(
        "rejected_fails={rejected_arm_fails} revision_passes={revision_arm_passes} "
        "regressions_closed={count}".format(count=len(result["verdict"]["failing_on_rejected_but_passing_on_revision"]), **result["verdict"])
    )
    return 0 if result["verdict"]["revision_arm_passes"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
