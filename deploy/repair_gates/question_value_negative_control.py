"""Negative control: the three semantics the repair targets, asserted against UNMODIFIED code.

Run in a container built from the deployed image with no fix mounted. Every assertion here MUST fail
on that code - if any of them passed, the repair would be fixing something that was not broken, and the
gate suite would be measuring nothing.
"""
import sys

sys.path.insert(0, "/ragflow")
import common.settings  # noqa: F401

from rag.retrieval.chunk_profile import carries_value
from rag.retrieval.decomposition import question_values

COMPOSITE = "根据 Q/GDW 73286.2-2026 与 Q/GDW 73286.3-2026 标准表 1 的规定，单芯与三芯交联聚乙烯绝缘电力电缆的导体标称截面覆盖范围及规格数量各是多少？"
HEADER = "[标准号: Q/GDW 73286.3 | 文档: 第3部分.pdf | 电压: 220kV | 芯数: 三芯]"
POOL = [{"chunk_id": f"c{i}", "content_with_weight": "800 mm² 的厚度要求是 1.5 mm" if i < 19 else "内衬层的一般要求"} for i in range(20)]

failures = []

values = question_values(COMPOSITE)
if values:
    failures.append(f"identity tokens are still admitted as values: {values}")

carried = carries_value({"chunk_id": "h", "content_with_weight": f"{HEADER} <table><tr><td>导体</td><td>铜</td></tr></table>"}, ("73286.3",))
if not carried:
    failures.append("the ingest preamble is no longer read as evidence (the fix is present)")

technical = question_values("800 mm² 的厚度是多少？", POOL)
if "800" in technical:
    failures.append("a common technical value is no longer discarded (the fix is present)")

print("NEGATIVE_CONTROL_FAILURES:", len(failures))
for line in failures:
    print("  -", line)
print("EXPECTED_ON_UNMODIFIED_CODE:", "all three present (4 failures listed => the gate detects the bug)")
