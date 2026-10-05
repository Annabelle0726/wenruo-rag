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
"""Module D — the dynamic query router (adaptive retrieval parameters).

One retrieval configuration cannot serve a cable corpus, because the two ends of
it want opposite legs of the hybrid score:

* a question that carries a MODEL, a NUMBER or a TABLE REFERENCE is answered by a
  passage that repeats that literal token (``WDZC-YJY-0.6/1kV``, ``3×25``,
  ``偏心度``, ``表3``). The keyword leg finds it exactly; the embedding leg averages
  the question into a centroid that sits nowhere near a table row, so a
  vector-heavy configuration dilutes the very token that decides the answer. These
  questions therefore want the KEYWORD leg dominant and a WIDER recall window
  (more exact-match candidates to choose from).
* a question that asks for a CONCEPT, a comparison or a principle ("交联聚乙烯和
  聚氯乙烯绝缘的异同", "为什么…", "选型原则") is answered by prose that shares
  almost no surface words with the question, and a literal-match configuration
  returns the passages that merely repeat its nouns. These want the VECTOR leg
  dominant and a NARROWER window (precision over recall).
* a question about a REVISION, an EDITION or a comparison between clauses sits in
  between, and is served by the pipeline's own balanced settings.

The router is deliberately a pure regex/keyword decision - no LLM call, no I/O, no
storage - and it never touches the database or the assistant's stored sliders: the
overrides it returns live only in the memory of the request that computed them, so
the next turn, another assistant and the settings UI all keep the configured
values. A question that matches no rule returns
:data:`~rag.retrieval.query_router.PASS_THROUGH`, which leaves every caller-
supplied setting exactly as it was.

Ordering is the answer to "what if two rules match": the rules are tried in the
order numeric -> revision -> conceptual, and the FIRST match wins. A question that
names a table ("表3 中 3×25 的载流量与另一版本的异同") is a numeric question first -
its answer is in that table - and the comparison wording must not pull it onto the
vector-heavy path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Query shapes, in the order they are tried.
NUMERIC = "numeric"
REVISION = "revision"
CONCEPTUAL = "conceptual"
#: No rule matched: the caller's own configuration is used unchanged.
PASS_THROUGH = "default"

#: Vector-leg weight (the keyword leg takes ``1 - w``) and per-route recall window
#: for each shape. The values are a deliberate spread around the pipeline's own
#: balanced default (0.6 / 12): the numeric end leans on exact tokens, the
#: conceptual end on meaning, and the revision end stays balanced.
NUMERIC_VECTOR_WEIGHT = 0.25
NUMERIC_TOP_K = 20
REVISION_VECTOR_WEIGHT = 0.5
REVISION_TOP_K = 12
CONCEPTUAL_VECTOR_WEIGHT = 0.75
CONCEPTUAL_TOP_K = 10

# --- Numeric / model / table shape -----------------------------------------
#: A number with a unit the corpus writes next to a figure. Both the ASCII and the
#: typographic spellings are listed because a datasheet uses whichever its editor
#: produced: ``mm²``/``mm2``, ``Ω``/``ohm``/``欧``, ``℃``/``°C``, ``×``/``x``/``*``
#: are the same measurement to the reader and different bytes to a regex.
_NUMERIC_UNIT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:" r"mm\s*[²2³3]?|cm|kV|KV|kv|MV|V|mA|A|kA|Ω|ohm|MΩ|mΩ|欧|" r"℃|°C|K|Hz|kHz|MHz|GHz|kg|g|km|m\b|s\b|min|h\b|%|％|" r"kW|W|kWh|N|N·m|MPa|kPa|Pa|dB|pF|nF|µF|uF|mF|F\b|Ω/km" r")"
)
#: A conductor size written as a count times a section (``3×25``, ``3x25``,
#: ``4*16``), with optional units on either side (``3×25mm²``).
_DIMENSION_PAIR_RE = re.compile(r"\d+\s*[x×*]\s*\d+")
#: A table or figure reference: ``表3``, ``表 3``, ``表A.2``, ``附录表3``, ``图2``.
_TABLE_REF_RE = re.compile(r"(?:表|图)\s*[A-Za-z]?\s*\d+(?:\.\d+)*")
#: Cable-domain parameter names that only make sense as an exact value lookup. The
#: corpus writes these as table column headers, so a passage answers the question
#: by carrying the literal header next to the figure.
_NUMERIC_TERM_RE = re.compile(r"偏心度|厚度|外径|截面|载流量|直流电阻|绝缘电阻|标称值|允许偏差|节距|绞向|芯数|规格|型号|参数表|参数值|尺寸")

# --- Revision / edition shape ----------------------------------------------
_REVISION_RE = re.compile(
    r"对比|比较|修订|修订版|版本|年版|新版|旧版|现行版|替代|废止|作废|沿用|" r"现行有效|新旧|历次|变更(?:记录|内容)?|升版|换版|" r"第\s*[0-9０-９一二三四五六七八九十]+\s*部分|" r"(?:19|20)\d{2}\s*年"
)

# --- Conceptual / macro shape ---------------------------------------------
_CONCEPTUAL_RE = re.compile(
    r"异同|优缺点|优劣势|优势|劣势|利弊|原理|区别|差异|不同点|相同点|" r"为什么|为何|本质|概念|定义|含义|作用|意义|概述|综述|" r"选型原则|选型思路|如何选择|如何选型|适用场景|适用条件|发展趋势"
)

_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class RouteDecision:
    """The retrieval parameters one question asks for.

    ``vector_similarity_weight`` and ``routes_top_k`` are ``None`` for
    :data:`PASS_THROUGH`, and the caller keeps its own value for anything that is
    ``None`` - which is also how a caller that configures only one of the two
    keeps the other.
    """

    name: str
    vector_similarity_weight: float | None = None
    routes_top_k: int | None = None
    signal: str = ""

    @property
    def overrides(self) -> bool:
        """Whether this decision changes anything the caller supplied."""
        return self.vector_similarity_weight is not None or self.routes_top_k is not None


#: The shape tables and their decisions, in the order the router tries them.
_RULES: tuple[tuple[str, float, int], ...] = (
    (NUMERIC, NUMERIC_VECTOR_WEIGHT, NUMERIC_TOP_K),
    (REVISION, REVISION_VECTOR_WEIGHT, REVISION_TOP_K),
    (CONCEPTUAL, CONCEPTUAL_VECTOR_WEIGHT, CONCEPTUAL_TOP_K),
)


def _first_signal(question: str) -> dict[str, str]:
    """The first literal that matches each rule, for the transcript."""
    signals: dict[str, str] = {}
    for pattern in (_NUMERIC_UNIT_RE, _DIMENSION_PAIR_RE, _TABLE_REF_RE, _NUMERIC_TERM_RE):
        match = pattern.search(question)
        if match:
            signals[NUMERIC] = match.group(0)
            break
    match = _REVISION_RE.search(question)
    if match:
        signals[REVISION] = match.group(0)
    match = _CONCEPTUAL_RE.search(question)
    if match:
        signals[CONCEPTUAL] = match.group(0)
    return signals


def route_question(question: str) -> RouteDecision:
    """Decide the retrieval parameters for ``question``.

    Never raises and never consults anything outside its argument: an empty or
    unrecognised question gets :data:`PASS_THROUGH`, so the caller's configuration
    (the assistant's own sliders) applies unchanged.
    """
    text = _WHITESPACE_RE.sub(" ", str(question or "")).strip()
    if not text:
        return RouteDecision(PASS_THROUGH)

    signals = _first_signal(text)
    for name, weight, top_k in _RULES:
        signal = signals.get(name)
        if signal:
            return RouteDecision(name=name, vector_similarity_weight=weight, routes_top_k=top_k, signal=signal)
    return RouteDecision(PASS_THROUGH)
