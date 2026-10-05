#
#  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
#  Modifications Copyright 2026 线缆工业智搜平台. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
"""Automatic metadata tagging for the ingestion pipeline.

A cable corpus is filed by document, not by field: the standard number, the voltage
level, the cable type and the document type are all IN the document (cover page,
running header, file name), but nothing extracts them into ``meta_fields``. The
consequences are measurable on this stack: the document list shows ``0 fields``, and
an assistant whose metadata matching is on (``meta_data_filter = {"method": "auto"}``)
has nothing to match against - the matcher is handed an empty key set and every
question is answered from the whole corpus.

This module fills that gap in two steps, cheapest first:

1. **A regex fast path over the file name and the first
   :data:`REGEX_SCAN_CHARS` characters** - zero tokens. It covers the four fields a
   cable document always carries: ``standard_no``, ``voltage_level``, ``doc_type``,
   ``year``.
2. **One low-token LLM call** on the first :data:`LLM_SCAN_CHARS` characters,
   used only when the fast path found fewer than :data:`MIN_CORE_FIELDS` of the two
   identifying fields (:data:`CORE_FIELDS`). Its system prompt demands a bare JSON
   object with a fixed key set, and it also fills ``cable_type``, which a regex
   cannot guess for an arbitrary corpus.

Neither step may ever fail the ingest: :func:`auto_tag` catches everything, logs a
warning and returns whatever the fast path had. A document that yields no metadata
is exactly as retrievable as it was before this module existed.

Where this runs: in ``rag/svr/task_executor.py::build_chunks``, after the parser has
produced the chunk texts and AFTER
:func:`rag.nlp.doc_context.apply_document_context` has bound the document's own
standard number into them - so the ``standard_no`` FIELD and the ``[标准号: …]``
prefix every chunk carries cannot disagree - and before the embedding stage and the
vector write, which are the irreversible ones. The result is persisted to the
document's metadata (the doc-meta index the ``auto`` filter pushes down on, and the
same store the document list counts fields from).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from rag.nlp.doc_context import detect_standard_id

_LOG = logging.getLogger(__name__)

#: The fields this module produces, in the order the LLM is asked for them.
METADATA_FIELDS = ("standard_no", "voltage_level", "core_type", "cable_type", "doc_type", "year")

#: The two fields that identify a cable document. The LLM fallback fires when the
#: fast path finds fewer than :data:`MIN_CORE_FIELDS` of them: a document carrying
#: neither its standard number nor its voltage level is the one worth a call.
CORE_FIELDS = ("standard_no", "voltage_level")
MIN_CORE_FIELDS = 2

#: Scan windows. The file name is always scanned in full; the text window is the
#: document head, where the cover page, the designation and the 适用范围 clause live.
REGEX_SCAN_CHARS = 1000
LLM_SCAN_CHARS = 2000

#: ``(Q/GDW|GB/T|GB|IEC|DL/T)`` followed by a number, an optional sub-part and an
#: optional year - the shape the platform documents. Used as the SECOND attempt for
#: ``standard_no``: :func:`~rag.nlp.doc_context.detect_standard_id` runs first and
#: accepts a wider allowlist (NB/MT/JB/YD/... and the international bodies) behind a
#: boundary check, so the two agree whenever both match; this pattern adds the
#: year-less forms the allowlist rejects for non-enterprise prefixes ("GB 1234").
#: A multi-part designation keeps all of its parts ("IEC 61850-9-2").
_STANDARD_NO_RE = re.compile(r"(Q/GDW|GB/T|GB|DL/T|IEC)\s*\d+(?:\.\d+)?(?:\s*-\s*\d+)*(?:\s*-\s*\d{4})?", re.IGNORECASE)

#: A voltage level, keeping a compound rating whole: "0.6/1kV" and "450/750V" are
#: the forms cable documents use, and reporting only the denominator would lose the
#: part a question names. A RANGE is kept too ("1kV～10kV"): the metadata matcher
#: compares the question's own words against this value, so a question naming 10kV
#: still matches a document that declares only the range - the reverse is not true.
#: The separator of a compound rating is "/" in text and "_" in a FILE NAME (a slash
#: cannot appear in a name), and the corpus is full of the second spelling -
#: "450_750V聚氯乙烯绝缘电缆采购标准.pdf". The trailing check is an
#: ASCII-alphanumeric lookahead rather than ``\b``, because the unit is followed by
#: CJK in this corpus ("450/750V及以下") and ``\b`` does not fire between "V" and a
#: CJK character.
_VOLTAGE_UNIT = r"(?:kV|KV|kv|V)(?![0-9A-Za-z])"
#: The separator of a compound rating, in every spelling the corpus uses: "/" in text,
#: "_" in a file name (a slash cannot appear in one), and the FULLWIDTH "／" - the
#: 450／750V document is named with it, and missing it reported "750V" as the level,
#: which is half the rating and wrong for both display and matching.
_VOLTAGE_SEP = r"[/_／]"
_VOLTAGE_RE = re.compile(r"(?:\d+(?:\.\d+)?\s*" + _VOLTAGE_SEP + r"\s*)?\d+(?:\.\d+)?\s*" + _VOLTAGE_UNIT + r"(?:\s*[～~\-—]\s*\d+(?:\.\d+)?\s*" + _VOLTAGE_UNIT + r")?")

#: Document types as the corpus names them.
DOC_TYPE_KEYWORDS = ("通用技术规范", "专用技术规范", "采购范本", "技术条件", "数据手册")

#: The CORE COUNT a cable document is about, which is the one category that tells a
#: standard's parts apart: 国网 splits a multi-core-count standard by part -
#: 《Q/GDW 73286.2 第2部分：220kV单芯…》 and 《…73286.3 第3部分：220kV三芯…》 - so
#: "哪个部分" and "几芯" are the same question, and a corpus answers a 三芯 question
#: from the 三芯 part only when it can be told which part that is.
#:
#: A count written as a construction ("1×800mm²" is one core, "3×400mm²" is three)
#: is read as the same thing, because a table's section column writes it that way
#: while the cover and the file name write 单芯/三芯.
CORE_TYPE_KEYWORDS = ("单芯", "双芯", "两芯", "三芯", "四芯", "五芯")

_CORE_COUNT_WORDS = {"单芯": 1, "双芯": 2, "两芯": 2, "三芯": 3, "四芯": 4, "五芯": 5}

#: ``3×400``, ``1x800``, ``3 × 25`` - the construction spelling of a core count.
_CORE_CONSTRUCTION_RE = re.compile(r"(?<!\d)([1-5])\s*[×xX*]\s*\d")

#: How dominant one construction count has to be in a document's head before it is
#: reported as the document's own: the general part of a standard lists ``1×…`` AND
#: ``3×…`` sections, so a bare majority there is an artefact, not a fact.
CORE_COUNT_MAJORITY = 0.8

_YEAR_RE = re.compile(r"(?:19|20)\d{2}")

#: The LLM is asked for a bare JSON object with exactly these keys.
_METADATA_SYSTEM_PROMPT = (
    "你是线缆行业文档的元数据抽取器。只输出一个 JSON 对象，不要解释、不要 Markdown 代码块、不要多余文字。\n"
    '输出格式固定为：{"standard_no": "", "voltage_level": "", "core_type": "", "cable_type": "", "doc_type": "", "year": ""}\n'
    "抽取规则：\n"
    "- standard_no：文档所依据的标准编号，例如 Q/GDW 13237-2017、GB/T 12706.1-2020；没有就填空字符串。\n"
    "- voltage_level：电压等级，保留完整写法，例如 0.6/1kV、450/750V；没有就填空字符串。\n"
    "- core_type：芯数，只能从 单芯 / 双芯 / 三芯 / 四芯 / 五芯 中选一个（单芯电缆写 1×…，三芯写 3×…）；无法判断就填空字符串。\n"
    "- cable_type：线缆类别，例如 架空绝缘导线、电力电缆、控制电缆、布电线；没有就填空字符串。\n"
    "- doc_type：文档类型，只能从 通用技术规范 / 专用技术规范 / 采购范本 / 技术条件 / 数据手册 中选一个；都不是就填空字符串。\n"
    "- year：文档或标准的年份，四位数字；没有就填空字符串。\n"
    "所有字段值都必须是字符串；不确定的字段填空字符串，不要编造。"
)

#: Hard cap on one LLM call. The extraction is an enhancement; a slow provider must
#: not hold the ingest worker.
LLM_TIMEOUT_SECONDS = 20.0


@dataclass
class AutoTagResult:
    """What the extraction produced, and how."""

    fields: dict[str, str] = field(default_factory=dict)
    source: str = "none"
    used_llm: bool = False

    def __bool__(self) -> bool:
        return bool(self.fields)


def clean_value(value: Any) -> str:
    """One metadata value: a trimmed single-line string, or ""."""
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace("\u00a0", " ")
    text = re.sub(r"\s*[\r\n]+\s*", " ", text)
    return " ".join(text.split()).strip()


def normalize_standard_no(value: str) -> str:
    """``q/gdw73289.2-2026`` -> ``Q/GDW 73289.2-2026``.

    The prefix is uppercased and separated from the number by one space, which is
    how the designation is written in the corpus and by
    :func:`~rag.nlp.doc_context.detect_standard_id` - one spelling means the
    metadata filter and the chunk prefix match the same text.
    """
    text = clean_value(value).upper().replace(" ", "")
    if not text:
        return ""
    match = re.match(r"^([A-Z]+(?:/[A-Z]+)?)(.*)$", text)
    if not match:
        return clean_value(value)
    prefix, rest = match.group(1), match.group(2)
    return f"{prefix} {rest}" if rest else prefix


def _scan_text(filename: str, text: str, limit: int) -> str:
    """The file name plus the head of the document, in that order."""
    name = " ".join(str(filename or "").split())
    body = str(text or "")[: max(0, int(limit or 0))]
    return f"{name}\n{body}".strip()


def _standard_no(scan: str, filename: str) -> str:
    """The document's own designation.

    :func:`detect_standard_id` first (allowlisted, boundary-checked, Unicode dashes),
    with the platform's simple pattern as the fallback for the year-less forms it
    deliberately rejects.
    """
    detected = detect_standard_id(filename, [scan])
    if detected:
        return detected
    match = _STANDARD_NO_RE.search(scan)
    return normalize_standard_no(match.group(0)) if match else ""


def _voltage_level(scan: str) -> str:
    match = _VOLTAGE_RE.search(scan)
    if not match:
        return ""
    # A file name cannot contain "/", so the corpus spells a compound rating
    # "450_750V" there; metadata is stored in the slash spelling either way, so that
    # the value a question is matched against is the one the documents print.
    value = re.sub(r"\s*_\s*", "/", clean_value(match.group(0)))
    value = re.sub(r"\s*/\s*", "/", value)
    return value.replace("kv", "kV").replace("KV", "kV")


def _doc_type(scan: str) -> str:
    for keyword in DOC_TYPE_KEYWORDS:
        if keyword in scan:
            return keyword
    return ""


def _core_type(scan: str) -> str:
    """The core count the document is about, as 单芯 / 三芯 / ….

    The keyword spelling wins over the construction spelling: a document whose cover
    says 三芯 is the three-core part even though its parameter tables are full of
    ``3×400`` rows, and one that only ever writes ``1×800`` is the single-core part.
    """
    for keyword in CORE_TYPE_KEYWORDS:
        if keyword in scan:
            return keyword
    match = _CORE_CONSTRUCTION_RE.search(scan)
    if not match:
        return ""
    count = int(match.group(1))
    for word, value in _CORE_COUNT_WORDS.items():
        if value == count:
            return word
    return ""


def core_type_of(filename: str, text: str, *, scan_chars: int = REGEX_SCAN_CHARS) -> str:
    """The core count for a WHOLE document, name first.

    Measured while previewing a backfill: the plain :func:`_core_type` scan read the
    three-core part of the 220kV standard as 单芯, because the part's body contains
    ``1×…`` rows somewhere and the keyword list is tried in a fixed order before the
    file name is looked at separately. A file name that SAYS the count is the document
    speaking about itself, so it is asked first; only when it says nothing does the
    head get a vote, and then only a construction count that dominates the head
    (:data:`CORE_COUNT_MAJORITY`) - the general part of a standard lists every section
    of every core count, and giving it a count would be a wrong, filterable fact.
    """
    named = _core_type(_scan_text(filename, "", 0))
    if named:
        return named
    counts: dict[int, int] = {}
    for match in _CORE_CONSTRUCTION_RE.finditer(str(text or "")[: max(0, int(scan_chars or 0))]):
        count = int(match.group(1))
        counts[count] = counts.get(count, 0) + 1
    if not counts:
        return ""
    total = sum(counts.values())
    count, hits = max(counts.items(), key=lambda item: item[1])
    if hits / total < CORE_COUNT_MAJORITY:
        return ""
    for word, value in _CORE_COUNT_WORDS.items():
        if value == count:
            return word
    return ""


def _year(scan: str) -> str:
    match = _YEAR_RE.search(scan)
    return match.group(0) if match else ""


def extract_by_regex(filename: str, text: str, *, scan_chars: int = REGEX_SCAN_CHARS) -> dict[str, str]:
    """The zero-token pass: five fields off the file name and the document head."""
    scan = _scan_text(filename, text, scan_chars)
    if not scan:
        return {}
    fields = {
        "standard_no": _standard_no(scan, filename),
        "voltage_level": _voltage_level(scan),
        "core_type": core_type_of(filename, text, scan_chars=scan_chars),
        "doc_type": _doc_type(scan),
        "year": _year(scan),
    }
    return {key: value for key, value in fields.items() if value}


def missing_core_fields(fields: dict[str, str]) -> list[str]:
    """The identifying fields the fast path did not fill."""
    return [name for name in CORE_FIELDS if not clean_value((fields or {}).get(name))]


def needs_llm(fields: dict[str, str]) -> bool:
    """Whether the fast path left too little to skip the model.

    Fewer than :data:`MIN_CORE_FIELDS` identifying fields found means the document
    head did not declare what it is, which is exactly when one cheap call pays for
    itself. A document the fast path fully identified never reaches the model.
    """
    return len(CORE_FIELDS) - len(missing_core_fields(fields)) < MIN_CORE_FIELDS


def parse_llm_fields(answer: Any) -> dict[str, str]:
    """The five fields out of a model answer, ignoring anything else it said.

    Tolerates a code fence, a leading sentence and an ``</think>`` block, because a
    small model does all three; a value the model invented for a field it cannot
    know is kept only if it is a string, and the caller decides what to trust.
    """
    if answer is None:
        return {}
    if isinstance(answer, dict):
        data = answer
    else:
        text = re.sub(r"^.*</think>", "", str(answer), flags=re.DOTALL)
        text = re.sub(r"```(?:json)?", "", text)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            _LOG.warning("[AutoMetadata] the model answer carries no JSON object: %r", str(answer)[:200])
            return {}
        try:
            data = json.loads(match.group(0))
        except (ValueError, TypeError):
            _LOG.warning("[AutoMetadata] could not parse the model answer: %r", str(answer)[:200])
            return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for name in METADATA_FIELDS:
        value = clean_value(data.get(name))
        if value and value.lower() not in {"", "null", "none", "n/a", "unknown", "未知", "无"}:
            out[name] = normalize_standard_no(value) if name == "standard_no" else value
    return out


async def extract_by_llm(llm: Any, filename: str, text: str, *, scan_chars: int = LLM_SCAN_CHARS, timeout_seconds: float = LLM_TIMEOUT_SECONDS) -> dict[str, str]:
    """One call, one JSON object, at most ``timeout_seconds`` seconds.

    The message is the file name plus the document head, sized so that the head
    keeps its whole :data:`LLM_SCAN_CHARS` window: the name is already on its own
    line, so it is not repeated inside the snippet.

    Raises on a provider failure - :func:`auto_tag` is the caller that decides what
    a failure means (it means "keep what the regex found").
    """
    if llm is None:
        return {}
    name = " ".join(str(filename or "").split())
    body = str(text or "")[: max(0, int(scan_chars or 0))]
    if not name and not body:
        return {}
    answer = await asyncio.wait_for(llm.async_chat(_METADATA_SYSTEM_PROMPT, [{"role": "user", "content": f"文档名：{name}\n正文片段：\n{body}"}]), timeout=timeout_seconds)
    if isinstance(answer, tuple):
        answer = answer[0]
    return parse_llm_fields(answer)


#: How far into a document a designation has to appear to count as cover-page identity,
#: and how often it has to appear in total. The pair is what separates the document's own
#: number from a citation: a standard prints its own number on the cover, in the running
#: head and in its clauses, while the standards it APPLIES appear once, in a list.
TITLE_PAGE_CHARS = 300
IDENTITY_REPEATS = 2

#: How many leading lines count as the cover, and how much text a line may carry AROUND
#: a designation and still read as a cover line rather than as a sentence.
COVER_LINES = 4
COVER_TAIL_CHARS = 30

#: Words that turn a designation into a CITATION of somebody else's document. This is
#: what keeps "本产品符合 GB/T 12706.1 的规定" - a 规格书's own cover line - from becoming
#: that document's identity, which the repeat count alone cannot see.
_CITATION_CUES = ("依据", "按照", "符合", "引用", "参见", "参照", "遵守", "执行", "根据", "满足", "采用", "适用", "见 ") 

#: Designations that are never a document's OWN number: GB/T 1.1 is the standardisation
#: directive every Chinese standard cites in its foreword.
_GUIDELINE_DESIGNATIONS = ("GBT1.1", "GBT1.2", "GBT20001", "GBT20000", "GB1.1")

_DESIGNATION_RE = re.compile(r"(?:Q\s*/?\s*GDW|GB\s*/?\s*T|GB|DL\s*/?\s*T|JB\s*/?\s*T|NB\s*/?\s*T|YD\s*/?\s*T|IEC|ISO)\s*\d+(?:\.\d+)?(?:-\d{4})?", re.IGNORECASE)


def designation_scan_text(text: str) -> str:
    """The text a designation is matched in, with ``_`` read as the separator it is.

    An archived file routinely spells the qualifier with underscores
    (``Q_GDW 73289.2-2026 450_750V…``) because a slash cannot live in a file name, and
    the folder's own convention says the three spellings are the same designation. The
    substitution is length-preserving, so an offset found in the result is an offset in
    the original - which is what lets the cover-line check look at what comes BEFORE a
    match.
    """
    return re.sub(r"_", " ", str(text or ""))

#: Where a cable is laid, as the corpus names it. Domain knowledge, so it lives here
#: with the rest of the cable rules rather than in the generic projection.
_ENVIRONMENT_CUES = (("海底", "海底"), ("海缆", "海底"), ("直埋", "直埋"), ("隧道", "隧道"), ("桥架", "桥架"), ("架空", "架空"), ("水下", "水下"))


def cover_identity(text: str, *, limit: int = TITLE_PAGE_CHARS) -> tuple[str, str]:
    """``(designation, evidence)`` when the document's COVER states its own number.

    A cover line states the number and little else: ``Q/GDW 73289.2-2026`` on its own
    line, or ``标准号：…``. A line that CITES a standard - "本产品符合 GB/T 12706.1 的
    规定" - is the same shape to a frequency count and a different thing to a reader, so
    the cue in front of the designation disqualifies the line. That distinction is the
    whole reason this is not "the number that repeats most".
    """
    head = str(text or "")[: max(0, int(limit or 0))]
    for line in designation_scan_text(head).splitlines()[:COVER_LINES]:
        stripped = " ".join(line.split())
        if not stripped or len(stripped) > 120:
            continue
        for match in _DESIGNATION_RE.finditer(stripped):
            designation = re.sub(r"[\s/]+", "", match.group(0)).upper()
            if any(designation.startswith(prefix) for prefix in _GUIDELINE_DESIGNATIONS):
                continue
            before = stripped[: match.start()]
            after = stripped[match.end() :]
            if any(cue in before for cue in _CITATION_CUES):
                continue
            if len(before.strip(" -—_|:：")) > 12 or len(after.strip(" -—_|:：")) > COVER_TAIL_CHARS:
                continue
            return designation, f"stated on the cover line {stripped[:60]!r}"
    return "", ""


def metadata_candidates(filename: str, text: str, *, fields: dict[str, str] | None = None, scan_chars: int = REGEX_SCAN_CHARS) -> list:
    """The CANDIDATES this document offers, each with its source and its confidence.

    The cable-domain extractor: everything cable-specific lives here (the voltage
    patterns, the core-count rules, the seat environment), and the generic projection in
    ``rag/nlp/retrieval_projection.py`` never learns a cable word.

    Two things are deliberately never merged. ``document_standard_no`` is offered by the
    file name, by a cover-page identity, by the metadata store and - last and weakest -
    by the standard family; ``referenced_standard_nos`` is offered by every OTHER
    designation the body carries. A document that only cites standards therefore gets no
    identity at all rather than the most-cited one.
    """
    from rag.nlp.retrieval_projection import (
        SOURCE_DOCUMENT_BODY,
        SOURCE_FILE_NAME,
        SOURCE_METADATA_STORE,
        SOURCE_TITLE_PAGE,
        MetadataCandidate,
    )

    name = " ".join(str(filename or "").split())
    body = str(text or "")
    head = body[: max(0, int(scan_chars or 0))]
    fields = fields or {}
    candidates: list[MetadataCandidate] = []

    name_designations = _designations(name)
    counts: dict[str, int] = {}
    # Counted over the MATCHES, not over `_designations`, which is a set: counting its
    # elements gives every designation exactly one vote and quietly disables the
    # cover-page identity rule.
    for match in _DESIGNATION_RE.finditer(designation_scan_text(body)):
        designation = re.sub(r"[\s/]+", "", match.group(0)).upper()
        if any(designation.startswith(prefix) for prefix in _GUIDELINE_DESIGNATIONS):
            continue
        counts[designation] = counts.get(designation, 0) + 1

    for designation in sorted(name_designations):
        candidates.append(MetadataCandidate("document_standard_no", designation, SOURCE_FILE_NAME, 0.9, "printed in the file name"))
    cover, cover_evidence = cover_identity(body, limit=TITLE_PAGE_CHARS)
    if cover and counts.get(cover, 0) >= IDENTITY_REPEATS:
        candidates.append(MetadataCandidate("document_standard_no", cover, SOURCE_TITLE_PAGE, 0.95, f"{cover_evidence}, and {counts[cover]} times in the document"))
    stored = clean_value(fields.get("standard_no"))
    if stored:
        candidates.append(MetadataCandidate("document_standard_no", normalize_standard_no(stored), SOURCE_METADATA_STORE, 0.85, "metadata store"))

    own = {str(candidate.value) for candidate in candidates if candidate.key == "document_standard_no"}
    referenced = sorted(designation for designation in counts if designation not in own)
    if referenced:
        candidates.append(MetadataCandidate("referenced_standard_nos", tuple(referenced), SOURCE_DOCUMENT_BODY, 0.5, "cited in this document's own text"))

    voltage = _voltage_level(name)
    if voltage:
        candidates.append(MetadataCandidate("voltage_level", voltage, SOURCE_FILE_NAME, 0.9, "printed in the file name"))
    else:
        voltage = _voltage_level(body[:TITLE_PAGE_CHARS])
        if voltage:
            candidates.append(MetadataCandidate("voltage_level", voltage, SOURCE_DOCUMENT_BODY, 0.6, f"within the first {TITLE_PAGE_CHARS} characters"))

    core = core_type_of(name, head, scan_chars=scan_chars)
    if core:
        source = SOURCE_FILE_NAME if _core_type(name) else SOURCE_DOCUMENT_BODY
        candidates.append(MetadataCandidate("core_count", core, source, 0.9 if source == SOURCE_FILE_NAME else 0.7, "printed in the file name" if source == SOURCE_FILE_NAME else f"one core count dominates the first {scan_chars} characters"))

    cable_type = clean_value(fields.get("cable_type"))
    if cable_type:
        candidates.append(MetadataCandidate("cable_type", cable_type, SOURCE_METADATA_STORE if fields.get("cable_type") else SOURCE_DOCUMENT_BODY, 0.8, "metadata store"))
    doc_type = _doc_type(head) or clean_value(fields.get("doc_type"))
    if doc_type:
        source = SOURCE_FILE_NAME if doc_type in name else SOURCE_DOCUMENT_BODY
        candidates.append(MetadataCandidate("document_type", doc_type, source, 0.85 if source == SOURCE_FILE_NAME else 0.65, "the document type its own words state"))
    for cue, value in _ENVIRONMENT_CUES:
        if cue in name:
            candidates.append(MetadataCandidate("cable_environment", value, SOURCE_FILE_NAME, 0.85, f"the file name says {cue}"))
            break
    return candidates


def _designations(text: str) -> set[str]:
    """Every standard designation in a text, normalized, guidelines excluded."""
    found = set()
    for match in _DESIGNATION_RE.finditer(designation_scan_text(text)):
        designation = re.sub(r"[\s/]+", "", match.group(0)).upper()
        if any(designation.startswith(prefix) for prefix in _GUIDELINE_DESIGNATIONS):
            continue
        found.add(designation)
    return found


def family_candidate(designation: str, *, family: str, part: int, year: str = "") -> Any:
    """A ``document_standard_no`` the FAMILY implies - the constrained last resort.

    Only a caller that has established the family from the corpus may use it, and it is
    ordered last and carries the lowest confidence precisely so that it can never
    outrank anything the document says about itself.
    """
    from rag.nlp.retrieval_projection import SOURCE_FAMILY_INFERENCE, MetadataCandidate

    value = f"{designation}.{part}-{year}" if year else f"{designation}.{part}"
    return MetadataCandidate("document_standard_no", value, SOURCE_FAMILY_INFERENCE, 0.6, f"inferred as part {part} of {family}")


async def auto_tag(
    filename: str, text: str, *, llm: Any = None, scan_chars: int = REGEX_SCAN_CHARS, llm_scan_chars: int = LLM_SCAN_CHARS, timeout_seconds: float = LLM_TIMEOUT_SECONDS
) -> AutoTagResult:
    """Metadata for one document: regex first, one LLM call only if it must.

    Never raises. Every failure path - no model, a provider error, a timeout, an
    unparseable answer - degrades to what the fast path found, logs a warning, and
    lets the ingest continue: a document without metadata is exactly as retrievable
    as it was before this module existed, while a document that stalls the parse is
    not retrievable at all.
    """
    try:
        fields = extract_by_regex(filename, text, scan_chars=scan_chars)
    except Exception:  # noqa: BLE001 - the fast path is pure, but never fail an ingest
        _LOG.exception("[AutoMetadata] regex extraction failed for %r", filename)
        return AutoTagResult(fields={}, source="none")

    if not needs_llm(fields) or llm is None:
        if needs_llm(fields):
            _LOG.info("[AutoMetadata] %r: %s and no chat model is available; keeping the %d field(s) the fast path found", filename, "missing " + ", ".join(missing_core_fields(fields)), len(fields))
        return AutoTagResult(fields=fields, source="regex" if fields else "none")

    try:
        llm_fields = await extract_by_llm(llm, filename, text, scan_chars=llm_scan_chars, timeout_seconds=timeout_seconds)
    except Exception as exc:  # noqa: BLE001 - a model failure must not fail the ingest
        _LOG.warning("[AutoMetadata] %r: the model pass failed (%s: %s); keeping the %d field(s) the fast path found", filename, type(exc).__name__, exc, len(fields))
        return AutoTagResult(fields=fields, source="regex" if fields else "none")

    # The fast path read the value off the document, so it wins; the model fills what
    # is still missing (including `cable_type`, which no regex guesses).
    merged = dict(llm_fields)
    merged.update(fields)
    _LOG.info(
        "[AutoMetadata] %r: fast path=%s, model filled=%s -> %s",
        filename,
        ", ".join(sorted(fields)) or "-",
        ", ".join(sorted(name for name in llm_fields if name not in fields)) or "-",
        ", ".join(f"{key}={value}" for key, value in merged.items()) or "-",
    )
    if not merged:
        return AutoTagResult(fields={}, source="none", used_llm=True)
    return AutoTagResult(fields=merged, source="regex+llm" if fields else "llm", used_llm=True)


def document_text(chunks: Sequence[dict], limit: int = LLM_SCAN_CHARS) -> str:
    """The head of the document's text, reassembled from its parsed chunks.

    The parser hands back chunks, not a text stream, so the "first N characters" a
    metadata pass wants is the head of their concatenation in reading order. The
    walk stops as soon as ``limit`` characters are collected, so a large document
    costs nothing extra.
    """
    parts: list[str] = []
    budget = max(0, int(limit or 0))
    for chunk in chunks or []:
        body = chunk.get("content_with_weight")
        if not isinstance(body, str) or not body:
            body = chunk.get("text")
        if not isinstance(body, str) or not body:
            continue
        parts.append(body[:budget])
        budget -= len(parts[-1])
        if budget <= 0:
            break
    return "\n".join(parts)


__all__ = [
    "CORE_FIELDS",
    "CORE_TYPE_KEYWORDS",
    "DOC_TYPE_KEYWORDS",
    "LLM_SCAN_CHARS",
    "LLM_TIMEOUT_SECONDS",
    "METADATA_FIELDS",
    "MIN_CORE_FIELDS",
    "REGEX_SCAN_CHARS",
    "AutoTagResult",
    "auto_tag",
    "clean_value",
    "document_text",
    "extract_by_llm",
    "extract_by_regex",
    "family_candidate",
    "metadata_candidates",
    "missing_core_fields",
    "needs_llm",
    "normalize_standard_no",
    "parse_llm_fields",
]
