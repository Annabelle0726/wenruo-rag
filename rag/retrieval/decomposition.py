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
from typing import Sequence

from rag.prompts.generator import PROMPT_JINJA_ENV, gen_json
from rag.prompts.template import load_prompt
from rag.retrieval.chunk_profile import carries_value, comparison_sides

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
_CONJUNCTION_RE = re.compile(r"[、；;]|(?<![饱柔混搅调缓总均附])和|与|及|以及|还有|同时|分别|各自|对比|比较|区别|不同|差异")

#: Interrogative markers. Two or more of them in one sentence is a second
#: information need even without a conjunction ("厚度是多少 电阻又是多少").
_INTERROGATIVE_RE = re.compile(r"多少|多大|是什么|有哪些|如何|怎样|要求|规定|标准|参数|数值|类型|区别|几")

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

#: A figure is only worth matching when the pool does NOT already carry it everywhere.
#:
#: ``220kV`` is named by most passages of a 220kV corpus, so matching on it would move
#: every candidate by the same factor - noise dressed as a signal. Measured on the live
#: 220kV index: ``800`` and ``1200`` appear in 18 of the Part 2 document's 40 table
#: passages (45%), which discriminates; ``220`` appears in nearly all of them.
MAX_VALUE_POOL_SHARE = 0.8


def question_values(question: str, chunks: Sequence[dict] = ()) -> list[str]:
    """The literal figures a question asks about, in the order it names them.

    ``"针对 800 mm² 与 1200 mm² 的单芯与三芯电缆"`` -> ``["800", "1200"]``. These are the
    one class of term a passage can be checked against without a model: the answer
    either writes the figure the question named or it does not.

    Structural coordinates are dropped first (``第5章``, ``6.2.2``, ``附录A``, and the
    table/figure labels that go with them), because a chapter number is not a value to
    match on. What remains has to be at least two digits or carry a decimal part, which
    keeps ``800``/``1200``/``3.9``/``0.6`` and drops the ``1`` of ``1×800`` and a bare
    "第 2 部分" style index that survived the strip.

    With a pool, a figure the pool already carries nearly everywhere is dropped as
    well: it cannot separate the passage that answers from the ones that do not. A
    question whose every figure is that common returns NO values, which turns the
    value-aware ordering off rather than adding a uniform nudge to every candidate.
    """
    text = _WHITESPACE_RE.sub(" ", strip_section_references(str(question or ""))).strip()
    if not text:
        return []

    found: list[str] = []
    for match in _QUESTION_NUMBER_RE.finditer(text):
        token = match.group(0).replace("．", ".")
        digits = token.replace(".", "")
        if len(digits) < 2 and "." not in token:
            continue
        if token not in found:
            found.append(token)
    if not found:
        return []

    pool = list(chunks or ())
    if pool:
        discriminating = [value for value in found if _pool_share(value, pool) <= MAX_VALUE_POOL_SHARE]
        # Every figure is common to the pool: there is nothing to target.
        found = discriminating
    return found[:MAX_QUESTION_VALUES]


def _pool_share(value: str, pool: Sequence[dict]) -> float:
    """The share of the pool's passages that carry ``value``."""
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


async def decompose_question(chat_mdl, question: str, max_sub_queries: int = MAX_SUB_QUERIES) -> list[str]:
    """Split a composite question into atomic sub-queries.

    Returns an empty list - never raises - when there is no chat model, when the
    question is empty, or when the model call or its JSON response cannot be
    used. The caller then searches the original question alone, which is exactly
    the behaviour that predates this module.
    """
    question = _WHITESPACE_RE.sub(" ", str(question or "")).strip()
    if not question or chat_mdl is None or max_sub_queries <= 0:
        return []
    try:
        rendered = PROMPT_JINJA_ENV.from_string(DECOMPOSITION_PROMPT).render(question=question, max_sub_queries=max_sub_queries)
        result = await gen_json(rendered, "Output:\n", chat_mdl)
    except Exception as exc:  # noqa: BLE001 - decomposition is an optimization
        _LOG.warning("[Decompose] failed for %r: %s", question[:80], exc)
        return []
    sub_queries = parse_sub_queries(result, question, max_sub_queries)
    _LOG.info("[Decompose] %r -> %s", question[:80], sub_queries)
    return sub_queries
