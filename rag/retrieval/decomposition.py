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
"""Module A — sub-query decomposition for multi-dimensional questions.

One retrieval statement per question does not survive a question that asks for
several parameters at once. Both legs of the hybrid score are diluted by extra
dimensions:

* the text leg is a query-RECALL ratio (``Qryr.token_similarity`` divides the
  matched term weight by the query's TOTAL term weight), so a passage covering
  one of four asked-for parameters scores at best a quarter of the text weight;
* the vector leg is one embedding of the whole sentence, whose centroid drifts
  away from every single-parameter clause.

The result is a pool whose members sit under the assistant's
``similarity_threshold``: the knowledge base contains chapter 5's thickness
clause and chapter 6's routine-test clause, and neither reaches the answer.

This module splits such a question into atomic sub-queries, and - separately
from the LLM call - strips structural hierarchy references ("第5章", "5.3.3",
"附录A") out of a search statement. A chapter number is a coordinate in the
document outline, not content the retriever should be asked to match; left in
the statement it takes weight away from the business entity next to it.

Everything here is best-effort: the LLM node is an optimization, and every
failure path returns "no sub-queries" so the caller retrieves the original
question exactly as before.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from typing import Sequence

from rag.prompts.generator import PROMPT_JINJA_ENV, gen_json
from rag.prompts.template import load_prompt
from rag.retrieval.chunk_profile import (
    NumericOccurrence,
    carries_value,
    comparison_sides,
    numeric_occurrences,
)

_LOG = logging.getLogger(__name__)

DECOMPOSITION_PROMPT = load_prompt("sub_query_decomposition")

#: Upper bound on the sub-queries one question may fan out into. Total routes
#: are this plus the original question, and every route is one retrieval round
#: trip, so the cap is a latency budget as much as a quality knob.
MAX_SUB_QUERIES = 4

#: A sub-query longer than this is a paraphrase of the original question, not an
#: atomic one; the model occasionally echoes the whole sentence back.
MAX_SUB_QUERY_CHARS = 120

#: ``第5章`` / ``第 5.3 节`` / ``第五章`` / ``第3条`` / ``第2款`` / ``第4部分``.
_SECTION_WORD_RE = re.compile(r"第\s*[0-9０-９一二三四五六七八九十百零]+(?:\s*[.．]\s*\d+)*\s*(?:章|节|条|款|部分|篇|项)")

#: ``附录A`` / ``附录 B`` / ``附录3``.
_APPENDIX_RE = re.compile(r"附录\s*[A-Za-z0-9一二三四五六七八九十]+")

#: A dotted section number glued to a section word (``第5章5.3.3``). The
#: lookbehind is what keeps this from touching data values: ``0.6/1kV`` and
#: ``1.2mm`` are not preceded by a section word, so they are never stripped.
_GLUED_SECTION_NUMBER_RE = re.compile(r"(?<=[章节条款篇项])\s*\d+(?:\.\d+){1,4}")

#: A dotted section number opening the statement (``5.3.3 绝缘标称厚度是多少``).
_LEADING_SECTION_NUMBER_RE = re.compile(r"^\s*\d+(?:\.\d+){1,4}\s*[、,，:：.．]?\s*")

#: Conjunctions that put two information needs in one sentence. ``和`` needs the
#: lookbehind because it also builds single words (饱和/柔和/温升和谐波...).
#:
#: The pattern is COMPOSED from the three slices below rather than written out as one
#: literal, so the deterministic planner (module E) can reuse one slice without
#: introducing a term of its own. The alternative ORDER is the order this constant has
#: always had, so the composition matches exactly what the single literal matched - the
#: slices are a partition of an existing vocabulary, not an extension of it.
_ENUMERATING_PATTERN = r"[、；;]|(?<![饱柔混搅调缓总均附])和|与|及|以及|还有"
_DISTRIBUTIVE_ADVERB_PATTERN = r"同时|分别|各自"
_COMPARATIVE_VERB_PATTERN = r"对比|比较|区别|不同|差异"

_CONJUNCTION_RE = re.compile(f"{_ENUMERATING_PATTERN}|{_DISTRIBUTIVE_ADVERB_PATTERN}|{_COMPARATIVE_VERB_PATTERN}")

#: The ENUMERATING slice alone: a conjunction that puts two noun phrases side by side, so
#: it enumerates either the dimensions a question asks about (导体、内衬层和铠装层) or the
#: two sides of a comparison (单芯和三芯). Only this slice separates; the other two do not.
ENUMERATING_CONJUNCTION_RE = re.compile(_ENUMERATING_PATTERN)

#: The ADVERBIAL slice alone: 同时/分别/各自 sit *inside* a clause and say the clause is
#: distributed over something already enumerated ("…和…分别有什么要求"). They terminate a
#: dimension head, which is what lets the planner read 铠装层 out of
#: "铠装层分别有什么技术要求" without a lexicon.
DISTRIBUTIVE_ADVERB_RE = re.compile(_DISTRIBUTIVE_ADVERB_PATTERN)

#: Interrogative markers. Two or more of them in one sentence is a second
#: information need even without a conjunction ("厚度是多少 电阻又是多少").
_INTERROGATIVE_RE = re.compile(r"多少|多大|是什么|有哪些|如何|怎样|要求|规定|标准|参数|数值|类型|区别|几")

#: Public alias of the interrogative marker set, for the planner (module E), which needs
#: the same vocabulary to find where a question's shared predicate begins. Same compiled
#: object as :data:`_INTERROGATIVE_RE` - no second list to drift out of step.
INTERROGATIVE_RE = _INTERROGATIVE_RE

#: Public alias of the whole conjunction pattern, for the planner (module E). A dimension head
#: ends at the first position any slice of this pattern matches, so the planner reads a question's
#: structure with the classifier's own vocabulary instead of one of its own.
CONJUNCTION_RE = _CONJUNCTION_RE

#: A question that wants a NORMATIVE CLAUSE rather than a value: it asks how
#: something is tested, which rule wins, what is required. On a standards corpus
#: this is the question shape a bidder fill-in table can never answer - the table
#: repeats parameter names, the clause is what states the rule - so it is also
#: the shape that needs a route aimed at the normative prose tier.
#:
#: ``例行[^，。？;；]{0,8}试验`` is not the same as the literal ``例行试验``: the live
#: failing question was 例行**交流电压**试验的维持时间是多少, and a term list without
#: the gap matches neither it nor 例行局部放电试验.
_CLAUSE_INTENT_RE = re.compile(
    r"例行[^，。？;；]{0,8}试验"
    r"|型式[^，。？;；]{0,8}试验"
    r"|抽样[^，。？;；]{0,6}(?:试验|检查|方案|规则)"
    r"|检验规则|验收规则|试验(?:标准|方法|条件|项目|程序|顺序)"
    r"|规则|条款|条文|规定|优先|为准|矛盾|冲突|不一致|判定|判据|合格"
    r"|如何执行|是否允许|应否|允许偏差|维持时间|持续时间|时限|频次|周期"
)

#: A weaker cue, used only for the ordering nudge: the question is about a
#: requirement or a test, so a table that merely repeats the query's nouns should
#: not outrank a passage that states something. Too broad for the prose floor - a
#: parameter table IS the right source for 绝缘电阻试验的数值是多少.
_REQUIREMENT_RE = re.compile(r"试验|要求|规定|标准|数值|参数|耐受|允许|不小于|不大于|极值")

#: What the clause route is anchored on. ``通用技术规范`` is the tier's own name -
#: a corpus puts it in the document title (《…第1部分：通用技术规范》), and the doc
#: store scores title tokens at ^10/^5, so the anchor RAISES the prose document's
#: passages instead of diluting them the way an unrelated appended term would.
#: ``正文条款`` adds the prose register a fill-in table does not carry. Deliberately
#: no ``第1部分``: a structural reference is exactly what this module strips from
#: every other search statement.
CLAUSE_ROUTE_ANCHOR = "通用技术规范 正文条款"

_WHITESPACE_RE = re.compile(r"\s+")


def strip_section_references(text: str) -> str:
    """Drop structural hierarchy references from a search statement.

    ``"第5章 5.3.3 绝缘标称厚度和绝缘电阻分别是多少"`` becomes
    ``"绝缘标称厚度和绝缘电阻分别是多少"``. Only outline coordinates are
    removed - section words, appendix labels (with an optional glued section
    number), and a leading dotted number. Numeric data (``0.6/1kV``, ``1.2mm``,
    ``20个工作日``) is deliberately left alone: it is content, and the BM25 leg
    needs it verbatim.

    A statement that is *only* a section reference (``"第5章"``) keeps its
    original text rather than collapsing to the empty string.
    """
    original = str(text or "")
    stripped = _GLUED_SECTION_NUMBER_RE.sub(" ", original)
    stripped = _SECTION_WORD_RE.sub(" ", stripped)
    stripped = _APPENDIX_RE.sub(" ", stripped)
    stripped = _LEADING_SECTION_NUMBER_RE.sub("", stripped)
    stripped = _WHITESPACE_RE.sub(" ", stripped).strip(" 　的,，、;；:：")
    return stripped if len(stripped) >= 2 else original.strip()


#: A figure in a question: ``800``, ``1200``, ``3.9``, ``0.6``.
_QUESTION_NUMBER_RE = re.compile(r"\d+(?:[.．]\d+)?")

#: How many of a question's own figures the cut will target. Two to four is what a
#: comparative parameter question names, and every extra one is a pass over the pool.
MAX_QUESTION_VALUES = 6

def question_numeric_occurrences(question: str) -> list[NumericOccurrence]:
    """Every numeric occurrence of ``question``, with offsets into the QUESTION AS GIVEN.

    **The offset contract.** Normalization (section-reference stripping, whitespace collapsing) is still how
    the extraction has always read a question, but its result is now a NORMALIZED COPY plus a
    normalized-index to original-index map, and every published occurrence is translated back through that
    map. Revision 2 handed out offsets into the copy, so ``第12部分  电压  220kV`` could not round-trip and a
    caller could not tell which characters an occurrence meant. The invariant, asserted per occurrence by
    the gate, is::

        question[occurrence.start:occurrence.end] == occurrence.text

    Two consequences worth stating. A figure normalization DELETED (a section number such as the ``12`` of
    ``第12部分``) has no occurrence, which is the existing semantics: an outline coordinate is not a value. A
    figure whose ORIGINAL spelling differs from its canonical form (the full-width dot of ``1．5``) is
    published as written, with offsets to match, while its CLASS is still decided on the canonical form - a
    recorded equivalence rather than a silent rewrite.
    """
    original = str(question or "")
    if not original:
        return []
    normalized, mapping = _normalize_with_map(original)
    if not normalized:
        return []
    translated: list[NumericOccurrence] = []
    for occurrence in numeric_occurrences(normalized):
        start = _map_index(mapping, occurrence.start)
        end = _map_end(mapping, occurrence.end)
        if start is None or end is None or end <= start:
            continue
        literal = original[start:end]
        if not literal:
            continue
        translated.append(
            replace(
                occurrence,
                text=literal,
                start=start,
                end=end,
                unit_end=None if occurrence.unit_end is None else _map_end(mapping, occurrence.unit_end),
                designation_span=_map_span(mapping, occurrence.designation_span),
                model_span=_map_span(mapping, occurrence.model_span),
            )
        )
    return translated


def question_value_occurrences(question: str) -> list[NumericOccurrence]:
    """The OCCURRENCES of ``question`` that project into the answer-value set, in the order it names them.

    This is the layer the audit's section 3 asked for: the projection is a filter over per-occurrence
    records, so two occurrences of one digit string keep two provenance records and two verdicts. The
    function it replaces returned a ``{text: class}`` map, in which a voltage ``0.6`` and a model ``0.6``
    in the same sentence collapsed onto whichever came last.

    The pre-existing extraction rule still governs the projection: a figure must carry two digits or a
    decimal part, which keeps ``800``/``1200``/``3.9``/``0.6`` and drops the ``1`` of ``1×800``. Figures
    that are dropped here are deliberately still visible in :func:`question_numeric_occurrences`, so a
    diagnosis can see what was dropped and why.
    """
    projected: list[NumericOccurrence] = []
    seen: set[str] = set()
    for occurrence in question_numeric_occurrences(question):
        if not occurrence.counts_as_value:
            continue
        digits = occurrence.text.replace(".", "").replace("．", "")
        if len(digits) < 2 and "." not in occurrence.text and "．" not in occurrence.text:
            continue
        if occurrence.text in seen:
            continue
        seen.add(occurrence.text)
        projected.append(occurrence)
        if len(projected) >= MAX_QUESTION_VALUES:
            break
    return projected


def _map_index(mapping: Sequence[int], index: int) -> int | None:
    """The original index a normalized index came from."""
    return mapping[index] if 0 <= index < len(mapping) else None


def _map_end(mapping: Sequence[int], index: int) -> int | None:
    """The original index one PAST the character a normalized end index follows."""
    if index <= 0 or index - 1 >= len(mapping):
        return None
    return mapping[index - 1] + 1


def _map_span(mapping: Sequence[int], span: tuple[int, int] | None) -> tuple[int, int] | None:
    if span is None:
        return None
    start = _map_index(mapping, span[0])
    end = _map_end(mapping, span[1])
    return None if start is None or end is None else (start, end)


def _emit(text: str, mapping: list[int], out: list[str], out_map: list[int], first: int, last: int) -> None:
    for index in range(first, last):
        out.append(text[index])
        out_map.append(mapping[index])


def _sub_with_map(text: str, mapping: list[int], pattern: re.Pattern, replacement: str) -> tuple[str, list[int]]:
    """``pattern.sub`` that keeps every surviving character's ORIGINAL index."""
    out: list[str] = []
    out_map: list[int] = []
    cursor = 0
    for match in pattern.finditer(text):
        if match.start() < cursor:
            continue
        _emit(text, mapping, out, out_map, cursor, match.start())
        if replacement:
            out.append(replacement)
            out_map.append(mapping[match.start()])
        cursor = match.end()
    _emit(text, mapping, out, out_map, cursor, len(text))
    return "".join(out), out_map


def _strip_chars(text: str, mapping: list[int], chars: str) -> tuple[str, list[int]]:
    start, end = 0, len(text)
    while start < end and text[start] in chars:
        start += 1
    while end > start and text[end - 1] in chars:
        end -= 1
    return text[start:end], mapping[start:end]


def _normalize_with_map(question: str) -> tuple[str, list[int]]:
    """``(normalized, normalized_index -> original_index)`` - the extraction's own normalization.

    Reproduces :func:`strip_section_references` step for step (glued section numbers, section words,
    appendix labels, a leading dotted number, whitespace collapsing, the leading/trailing strip) while
    recording where every surviving character came from, plus the same fallback for a question that is
    nothing but a section reference.
    """
    original = str(question or "")
    text, mapping = original, list(range(len(original)))
    for pattern in (_GLUED_SECTION_NUMBER_RE, _SECTION_WORD_RE, _APPENDIX_RE):
        text, mapping = _sub_with_map(text, mapping, pattern, " ")
    text, mapping = _sub_with_map(text, mapping, _LEADING_SECTION_NUMBER_RE, "")
    text, mapping = _sub_with_map(text, mapping, _WHITESPACE_RE, " ")
    text, mapping = _strip_chars(text, mapping, " 　的,，、;；:：")
    if len(text) >= 2:
        return text, mapping
    fallback = original.strip()
    offset = len(original) - len(original.lstrip())
    return fallback, list(range(offset, offset + len(fallback)))


def question_values(question: str, chunks: Sequence[dict] = ()) -> list[str]:
    """The literal figures a question asks about, in the order it names them.

    ``"针对 800 mm² 与 1200 mm² 的单芯与三芯电缆"`` -> ``["800", "1200"]``. These are the
    one class of term a passage can be checked against without a model: the answer
    either writes the figure the question named or it does not.

    Structural coordinates are dropped first (``第5章``, ``6.2.2``, ``附录A``, and the
    table/figure labels that go with them), because a chapter number is not a value to
    match on. What remains has to be at least two digits or carry a decimal part, which
    keeps ``800``/``1200``/``3.9``/``0.6`` and drops the ``1`` of ``1×800``.

    **Each occurrence is then CLASSIFIED by its own evidence** (:func:`chunk_profile.numeric_occurrences`,
    which publishes the classes and keeps the provenance) and only the classes that are not
    answer-bearing are dropped. That is a semantic boundary, and it is the one the value rules needed,
    because they ask whether a passage WRITES the figure the question asked for - a question about
    ``Q/GDW 73286.2`` is not asking for ``73286.2``, and every table of a standard carries the standard's
    own number in its header. The identity split matters here: when the question asks FOR the identity
    (``标准发布的是2026年版还是2025年版？``) that figure IS the answer, and it is returned.

    **``chunks`` is accepted and does NOT affect the result.** It used to: a figure the pool carried
    almost everywhere was discarded as indiscriminating. On a single-standard corpus that verdict is
    inverted - the answer-bearing figures (``800``, ``1200``, ``3.9``) are the ubiquitous ones and
    the identity tokens are the rare ones - so the test removed the values and kept the identities, and
    the red-team audit reproduced both halves. Ubiquity is evidence about DISCRIMINATION, and it is
    now reported as a diagnostic (:func:`_pool_share`) instead of deciding what the question asked for.
    The argument stays because ``rerank.DiversityPolicy.for_question`` passes the pool through; the
    gate asserts the invariance directly rather than trusting this sentence.
    """
    return [occurrence.text for occurrence in question_value_occurrences(question)]


def _pool_share(value: str, pool: Sequence[dict]) -> float:
    """The share of the pool's passages that carry ``value``.

    **Diagnostic only.** It reports how much a figure could discriminate the window; it does NOT decide
    whether the question asked for it (:func:`question_values`), because on a single-standard corpus
    that decision comes out inverted - the answering figures are the ubiquitous ones.
    """
    if not pool:
        return 0.0
    hits = sum(1 for chunk in pool if carries_value(chunk, (value,)))
    return hits / len(pool)


def looks_composite(question: str) -> bool:
    """Whether a question carries more than one information need.

    A cheap deterministic gate in front of the LLM node: a single-parameter
    question ("标称厚度是多少") has exactly one route and keeps the retrieval
    behaviour it has today, so the decomposition call and its extra round trips
    are spent only where they can change the outcome.

    The gate is deliberately recall-biased - a false positive costs one LLM call
    and a route that returns the same chunks, while a false negative leaves a
    composite question on the diluted single-route path.
    """
    text = _WHITESPACE_RE.sub(" ", str(question or "")).strip()
    if not text:
        return False
    if _CONJUNCTION_RE.search(text):
        return True
    return len(_INTERROGATIVE_RE.findall(text)) >= 2


def _normalized(text: str) -> str:
    return _WHITESPACE_RE.sub("", str(text or "")).lower()


def seeks_clause(question: str) -> bool:
    """Whether the question wants a normative clause rather than a value.

    "例行交流电压试验的维持时间是多少" and "两份规范对不上时以谁为准" are clause
    questions: their answer is prose that states a rule. "绝缘标称厚度是多少"
    is a value question, and a parameter table answers it fine.
    """
    return bool(_CLAUSE_INTENT_RE.search(str(question or "")))


def mentions_requirement(question: str) -> bool:
    """Whether the question is phrased as a requirement or a test at all.

    Used for the ordering nudge only (see ``DiversityPolicy``): broad enough to
    cover 绝缘电阻试验的数值是多少 without reserving that question's window for prose.
    """
    text = str(question or "")
    return bool(_CLAUSE_INTENT_RE.search(text) or _REQUIREMENT_RE.search(text))


def clause_route(question: str) -> str | None:
    """A deterministic extra route aimed at the normative PROSE tier, or None.

    Two measured failures this exists for. A fill-in parameter table repeats every
    parameter name and unit the question uses, so it wins the fused score and
    fills the window; the clause that answers the question never reaches the
    answer model ("只有表格，没有正文规定"). And when the question carries no
    standard number, no route is anchored anywhere near the 通用技术规范 document
    that holds the rule, so the clause is not recalled at all.

    The route keeps the user's own subject (so what comes back is on-topic) and
    appends :data:`CLAUSE_ROUTE_ANCHOR`. It is raised for by the doc store's
    title-token boost, so unlike an arbitrary appended keyword it does not dilute
    the passages it is meant to find.

    No LLM call: this must fire on every clause question, including the ones the
    decomposition node fails on.
    """
    text = _WHITESPACE_RE.sub(" ", str(question or "")).strip()
    if not text or not seeks_clause(text):
        return None
    subject = strip_section_references(text)[:MAX_SUB_QUERY_CHARS].strip()
    if not subject:
        return None
    return f"{subject} {CLAUSE_ROUTE_ANCHOR}"


def comparative_routes(question: str, sides: Sequence[str] | None = None) -> list[str]:
    """One deterministic route per side of a comparison, or ``[]``.

    The second measured comparative failure: "…单芯与三芯要求是否一致？" recalled the
    Part 2 (单芯) table and NOTHING from Part 3 (三芯), so the answer could only report
    one side. One shared query scores both documents' tables on the same words, and a
    slightly higher score for one of them fills the window with that document's table
    parts - which, for a table split into row-batches, is a dozen near-identical
    passages of ONE document. The other document's table was never retrieved, so no
    cut policy could bring it back.

    Each side therefore gets its own route: the side's own word plus the question's
    parameters, with every side marker removed so a route cannot match the OTHER
    side's wording. ``select_context`` reserves a slot per route, so both sides are in
    the window before the score fill. No LLM call: a comparative question must expand
    even when the decomposition node is unavailable.

    ``sides`` is injectable for callers that have already resolved them (the pipeline
    resolves them once and uses them for the document axis too).
    """
    text = _WHITESPACE_RE.sub(" ", str(question or "")).strip()
    if not text:
        return []
    resolved = list(sides) if sides is not None else comparison_sides(text)
    if len(resolved) < 2:
        return []

    subject = text
    for side in resolved:
        subject = subject.replace(side, " ")
    subject = strip_section_references(" ".join(subject.split()))[:MAX_SUB_QUERY_CHARS].strip()
    if not subject:
        return []

    routes: list[str] = []
    for side in resolved:
        route = _WHITESPACE_RE.sub(" ", f"{side} {subject}").strip()[:MAX_SUB_QUERY_CHARS].strip()
        if route and route not in routes:
            routes.append(route)
    return routes


def _sub_query_text(item) -> str:
    if isinstance(item, dict):
        for key in ("query", "question", "sub_query", "text"):
            value = item.get(key)
            if value:
                return str(value)
        return ""
    return str(item or "")


def parse_sub_queries(result, question: str, max_sub_queries: int = MAX_SUB_QUERIES) -> list[str]:
    """Normalize an LLM decomposition response into clean sub-queries.

    Accepts the documented ``{"sub_queries": [...]}`` shape (plus the common
    synonyms a model may emit), the bare list ``json_repair`` produces when the
    model answers with an array, and list members written as dicts. Returns the
    sub-queries with section references stripped, exact duplicates removed, and -
    because a sub-query that repeats the original question adds a round trip and
    no recall - the original question itself dropped.
    """
    if isinstance(result, dict):
        raw = []
        for key in ("sub_queries", "sub_questions", "queries", "questions"):
            value = result.get(key)
            if isinstance(value, list):
                raw = value
                break
    elif isinstance(result, list):
        raw = result
    else:
        return []

    original_key = _normalized(question)
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = _WHITESPACE_RE.sub(" ", _sub_query_text(item)).strip()
        if not text or len(text) < 2:
            continue
        if len(text) > MAX_SUB_QUERY_CHARS:
            text = text[:MAX_SUB_QUERY_CHARS].strip()
        text = strip_section_references(text)
        key = _normalized(text)
        if not key or key == original_key or key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= max_sub_queries:
            break
    return out


async def decompose_question(chat_mdl, question: str, max_sub_queries: int = MAX_SUB_QUERIES, outcome: dict | None = None) -> list[str]:
    """Split a composite question into atomic sub-queries.

    Returns an empty list - never raises - when there is no chat model, when the
    question is empty, or when the model call or its JSON response cannot be
    used. The caller then searches the original question alone, which is exactly
    the behaviour that predates this module.

    ``outcome``, when given, is filled in with what happened on the model side:
    ``error`` is ``"transport"`` when the call or its JSON parse failed, ``"parse"`` when the
    payload arrived but carried no usable sub-query, and ``None`` when it succeeded; ``items`` is
    the number of raw members the payload actually held. This is additive and optional - the
    return value and every failure path are unchanged - and it exists because P1-2's planner has to
    REPORT why the model channel was empty (fallback triggers T1 vs T2) rather than guess. The
    planner treats the model as provenance only, so this information never reaches a route.
    """
    if outcome is not None:
        outcome.clear()
        outcome.update({"error": "no_model", "items": 0})
    question = _WHITESPACE_RE.sub(" ", str(question or "")).strip()
    if not question or chat_mdl is None or max_sub_queries <= 0:
        return []
    try:
        rendered = PROMPT_JINJA_ENV.from_string(DECOMPOSITION_PROMPT).render(question=question, max_sub_queries=max_sub_queries)
        result = await gen_json(rendered, "Output:\n", chat_mdl)
    except Exception as exc:  # noqa: BLE001 - decomposition is an optimization
        _LOG.warning("[Decompose] failed for %r: %s", question[:80], exc)
        if outcome is not None:
            outcome.update({"error": "transport", "items": 0})
        return []
    if outcome is not None:
        outcome["items"] = len(result) if isinstance(result, (list, tuple)) else 1 if result else 0
    sub_queries = parse_sub_queries(result, question, max_sub_queries)
    if outcome is not None:
        outcome["error"] = None if sub_queries else "parse"
    _LOG.info("[Decompose] %r -> %s", question[:80], sub_queries)
    return sub_queries
