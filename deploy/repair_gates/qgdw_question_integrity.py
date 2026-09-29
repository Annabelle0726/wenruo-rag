"""Integrity check: was the frozen INCIDENT question delivered to the container byte-exactly?

Compares the staged question file against the question recorded in the attribution artifact. If the
PowerShell/python round-trip mangled it, the predicate check must be re-run from the artifact bytes.
"""
import hashlib
import json
import pathlib
import os

artifact = json.loads(pathlib.Path("deploy/repair_gates/attribution_matrix_result.json").read_text(encoding="utf-8"))
expected = artifact["queries"][0]["question"]

staged = pathlib.Path(os.environ["TEMP"]) / "incident_question.json"
raw = staged.read_bytes()
text = raw.decode("utf-8-sig").strip()

print("expected chars:", len(expected))
print("staged   chars:", len(text))
print("expected sha256:", hashlib.sha256(expected.encode("utf-8")).hexdigest())
print("staged   sha256:", hashlib.sha256(text.encode("utf-8")).hexdigest())
print("IDENTICAL:", text == expected)
print("staged file bytes:", len(raw), "starts with BOM:", raw[:3] == b"\xef\xbb\xbf")
if text != expected:
    print("expected repr head:", repr(expected[:60]))
    print("staged   repr head:", repr(text[:60]))
