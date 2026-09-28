"""Durable record: the kill-audit counterexamples across PARENT, Revision 3 and Revision 3.1.

The audit asked for the parent-vs-Rev3 regression on R6 to be recorded explicitly. This runs the same six
questions through three code versions and writes the comparison, so the movement is on the record rather
than asserted in prose.

PARENT is the deployed production build, whose QV layer predates every revision in this chain
(`/tmp/qv_parent`, copied out of the image `my-wenruorag:repair-798288f8` with nothing mounted).
"""
import json
import pathlib
import subprocess
import sys

GATE_DIR = pathlib.Path("/ragflow/deploy/repair_gates")
OUT = GATE_DIR / "question_value_revision31_parent_regression.json"
VERSIONS = {
    "PARENT": "/tmp/qv_parent",
    "REV3": "/tmp/qv_rev3",
    "REV31": "/tmp/qv_rev31",
}
PRODUCT_FILES = ("decomposition.py", "chunk_profile.py")
PROBE = r'''
import json, sys
sys.path.insert(0, "/ragflow")
from rag.retrieval.decomposition import question_values
CASES = {
 "R1": "\u6839\u636e 2026\u7248\uff0c\u53e6\u4e00\u4efd\u89c4\u8303\u7684\u7248\u672c\u662f2025\u7248\u5417\uff1f",
 "R2": "\u6211\u4eec\u57fa\u4e8eAB123CD\u7684800mm\u00b2\u6570\u636e\uff0c\u5f85\u9009\u578b\u53f7\u4e3aEF456GH\u5417\uff1f",
 "R3": "\u6309\u71672026\u7248\u548c2025\u7248\u6838\u5bf9800mm\u00b2\u7535\u7f06\uff0c\u5f85\u5ba1\u6587\u4ef6\u7684\u7248\u672c\u662f2024\u7248\u5417\uff1f",
 "R4": "Q/GDW 73286.2-2026\u89c4\u5b9a800mm\u00b2\u7535\u7f06\uff1b\u5f85\u5ba1\u6587\u4ef6\u7684\u6807\u51c6\u53f7\u662f\u591a\u5c11\uff1f",
 "R5": "\u5df2\u77e5\u578b\u53f7\u4e3aAB123CD\uff0c\u539a\u5ea6\u5e94\u53d61.8\u8fd8\u662f2.0mm\uff1f",
 "R6": "\u4f9d\u636e\u662f2026\u7248\u8fd8\u662f2025\u7248\uff0c\u5141\u8bb8\u539a\u5ea6\u4e3a1.8mm\u5417\uff1f",
}
print(json.dumps({name: question_values(q) for name, q in CASES.items()}, ensure_ascii=False))
'''


def run_version(source: str) -> dict:
    for name in PRODUCT_FILES:
        pathlib.Path("/ragflow/rag/retrieval", name).write_bytes((pathlib.Path(source) / name).read_bytes())
    completed = subprocess.run([sys.executable, "-c", PROBE], cwd="/ragflow", capture_output=True, text=True)
    line = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else "{}"
    return json.loads(line)


result = {"purpose": "kill-audit counterexamples across PARENT / Revision 3 / Revision 3.1", "versions": {}}
for version, source in VERSIONS.items():
    if not pathlib.Path(source).exists():
        result["versions"][version] = {"missing": source}
        continue
    result["versions"][version] = run_version(source)

result["r6_movement"] = {
    version: values.get("R6") for version, values in result["versions"].items() if isinstance(values, dict)
}
OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
for version, values in result["versions"].items():
    print(version, values)
print("R6:", result["r6_movement"])
