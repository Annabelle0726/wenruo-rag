"""Keyword-driven text processing shared by the retrieval tools.

Sentence splitting, light stemming, and the keyword narrowing/highlighting that
keeps chunk payloads token-cheap: retrieval returns full chunks, and narrowing
cuts each one down to the sentences that actually carry the query terms.

Lives in its own module because it is pure text work — no retrieval, no store
access — and is reused well beyond ``search`` (grep/sed narrowing, memory,
navigation).
"""

import hashlib
import logging
import re

from rag.nlp.doc_context import clear_prefix
from functools import lru_cache

_LOG = logging.getLogger(__name__)


def _compact_keywords(kw: str, max_terms: int = 15) -> str:
    """Deduplicate and cap a formalize / extract_keywords keyword string.

    The extraction prompt asks the model for 3-10 terms *plus* 2-3 synonyms each,
    which models answer with a 40-60 word redundant synonym run (e.g. "average
    distance left field line MLB retractable roof stadiums 2024 ... retractable
    dome covered stadium mean distance outfield" — ~350 chars). Appending that
    whole run onto the query diluted the vector leg and dragged BM25 onto
    unrelated docs. This keeps the recall terms but drops the redundancy:
    dedupe (preserving order) and cap at ``max_terms`` so it stays a compact
    hint instead of a pollution source. Accepts both space- and comma-separated
    input (single-turn extract_keywords emits spaces; multi-turn formalize
    emits commas).
    """
    if not kw:
        return ""
    tokens = re.split(r"[,\s]+", (kw or "").strip())
    seen: list[str] = []
    for t in tokens:
        t = t.strip()
        if not t:
            continue
        if t not in seen:
            seen.append(t)
        if len(seen) >= max_terms:
            break
    return " ".join(seen)


# Sentence terminators: Chinese 。！？；, English ! ? ;, newline, and a
# digit-guarded English period (so "3.14" / "v1.2" don't split).
_SENT_END = re.compile(r"[。！？；!?;]+|(?<!\d)\.(?!\d)")

# Block-level HTML elements and markdown tables are kept ATOMIC — never split by
# sentence terminators — so a whole table / list / block counts as ONE "sentence"
# for keyword matching and narrowing (a keyword inside one keeps the whole block).
_HTML_TAG = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)\b([^>]*)>")

# Only BLOCK-level containers are protected. Inline tags (<b>, <i>, <a>, <span>,
# <em>, <strong>, <code>, ...) are deliberately excluded so ordinary prose that
# contains inline formatting still splits into sentences normally.
_HTML_BLOCK_TAGS = {
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "td",
    "th",
    "caption",
    "colgroup",
    "ul",
    "ol",
    "li",
    "dl",
    "dt",
    "dd",
    "div",
    "p",
    "pre",
    "blockquote",
    "section",
    "article",
    "aside",
    "nav",
    "main",
    "figure",
    "figcaption",
    "header",
    "footer",
    "address",
    "details",
    "summary",
    "form",
    "fieldset",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
}

# Markdown table: a header row with a pipe, a separator row of dashes/colons/
# pipes, then zero+ body rows with a pipe.
_MD_TABLE = re.compile(
    r"^[ \t]*\|?[^\n]*\|[^\n]*\r?\n" r"[ \t]*\|?[ \t]*:?-{1,}:?[ \t]*(?:\|[ \t]*:?-{1,}:?[ \t]*)+\|?[ \t]*\r?\n" r"(?:[ \t]*\|?[^\n]*\|[^\n]*\r?\n?)*",
    re.MULTILINE,
)


def _html_block_spans(text: str) -> list[tuple[int, int]]:
    """Outermost balanced block-level HTML element spans (nesting-aware).

    Uses a tag stack (not a regex) so nested elements (e.g. a ``<table>`` with
    ``<td>``s, or nested ``<div>``s) yield ONE span for the outermost element and
    are never truncated at the first close tag the way a non-greedy regex would.
    Unclosed / stray tags are ignored (that region just falls back to plain
    sentence splitting).
    """
    spans: list[tuple[int, int]] = []
    stack: list[tuple[str, int]] = []
    for m in _HTML_TAG.finditer(text):
        name = m.group(2).lower()
        if name not in _HTML_BLOCK_TAGS:
            continue
        if m.group(1):  # closing tag </name>
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == name:
                    start = stack[i][1]
                    del stack[i:]
                    if not stack:  # closed an outermost block
                        spans.append((start, m.end()))
                    break
            # a stray </name> with no matching open is ignored
        elif not m.group(3).rstrip().endswith("/"):  # opening (skip self-closing)
            stack.append((name, m.start()))
    return spans


def _protected_spans(text: str) -> list[tuple[int, int]]:
    """Non-overlapping ``(start, end)`` spans kept atomic, in order.

    Covers block-level HTML elements and markdown tables; overlapping spans are
    merged (unioned) so a match that straddles two is never split.
    """
    spans = _html_block_spans(text)
    spans += [(m.start(), m.end()) for m in _MD_TABLE.finditer(text)]
    spans.sort()
    merged: list[tuple[int, int]] = []
    last_end = -1
    for s, e in spans:
        if s < last_end:  # overlaps an already-kept span -> union it in
            if e > last_end:
                merged[-1] = (merged[-1][0], e)
                last_end = e
            continue
        merged.append((s, e))
        last_end = e
    return merged


def _split_plain(text: str) -> list[str]:
    """Terminator-based sentence split, keeping each terminator attached."""
    sents: list[str] = []
    start = 0
    for m in _SENT_END.finditer(text):
        end = m.end()
        seg = text[start:end]
        if seg.strip():
            sents.append(seg)
        start = end
    if start < len(text):
        tail = text[start:]
        if tail.strip():
            sents.append(tail)
    return sents


def _split_sentences(text: str) -> list[str]:
    """Split ``text`` into sentences, keeping each terminator attached.

    Block-level HTML elements (``<table>``, ``<div>``, ``<p>``, ``<ul>``, ... —
    see :data:`_HTML_BLOCK_TAGS`) and markdown tables are treated as a single
    atomic sentence and are never split internally, so a keyword falling inside
    one keeps the whole block together.
    """
    if not text:
        return []
    spans = _protected_spans(text)
    if not spans:
        return _split_plain(text)

    sents: list[str] = []
    pos = 0
    for s, e in spans:
        if s > pos:
            sents.extend(_split_plain(text[pos:s]))
        block = text[s:e]
        if block.strip():
            sents.append(block)
        pos = e
    if pos < len(text):
        sents.extend(_split_plain(text[pos:]))
    return sents


# ---------------------------------------------------------------------------
# Stem-tolerant keyword matching (ported from agentic_search4 v8)
#
# Substring matching misses inflected forms: "nominations" misses "nominated",
# "company" misses "companies". Keywords are derived from the question, which
# states things in the inflected form ("which band HEADLINED", "was NOMINATED
# three times"), so the failing direction is the common one. Both sides are
# therefore reduced to a stem before comparison.
# ---------------------------------------------------------------------------
try:  # available at runtime — nltk already backs rag/nlp/synonym.py
    from nltk.stem import PorterStemmer as _PorterStemmer

    _porter_stem = _PorterStemmer().stem
except Exception:  # pragma: no cover - exercised only where nltk is absent
    _porter_stem = None

# Longest first: "nominations" must lose "ations", not just the trailing "s".
_STEM_SUFFIXES = (
    ("ations", ""),
    ("ation", ""),
    ("ated", ""),
    ("ates", ""),
    ("ate", ""),
    ("ings", ""),
    ("ing", ""),
    ("ies", "i"),
    ("ied", "i"),
    ("ed", ""),
    ("es", ""),
    ("s", ""),
)

_WORD_RE = re.compile(r"[a-z0-9]+")


def _fallback_stem(word: str) -> str:
    """Suffix stripper used when nltk is unavailable. Approximates Porter."""
    w = word
    for suffix, replacement in _STEM_SUFFIXES:
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            w = w[: len(w) - len(suffix)] + replacement
            break
    if len(w) > 3 and w.endswith("y"):
        w = w[:-1] + "i"
    if len(w) > 3 and w.endswith("e"):
        w = w[:-1]
    if len(w) > 3 and w[-1] == w[-2] and w[-1] not in "aeiou":
        w = w[:-1]  # running -> runn -> run
    return w


@lru_cache(maxsize=8192)
def _stem(word: str) -> str:
    return _porter_stem(word) if _porter_stem else _fallback_stem(word)


def _stemmable(token: str) -> bool:
    """Only plain ASCII words are stemmed.

    Identifiers ("1344259", "2020-21"), notation ("PPG") and CJK text must match
    verbatim — stemming would corrupt them, and it has no meaning for Chinese.
    """
    return len(token) >= 4 and token.isascii() and token.isalpha()


def _keyword_forms(kwds: list[str]) -> tuple[list[str], list[tuple[str, ...]]]:
    """Split keywords into verbatim substrings and stem sequences.

    A keyword whose tokens are ALL stemmable becomes a stem sequence (matched
    anywhere as a contiguous run of stems); anything containing an identifier,
    notation or CJK falls back to a verbatim substring match.
    """
    verbatim: list[str] = []
    stemmed: list[tuple[str, ...]] = []
    for kw in kwds or []:
        k = (kw or "").strip().lower()
        if not k:
            continue
        tokens = _WORD_RE.findall(k)
        if tokens and all(_stemmable(t) for t in tokens):
            stemmed.append(tuple(_stem(t) for t in tokens))
        else:
            verbatim.append(k)
    return verbatim, stemmed


def _sentence_stems(sentence: str) -> list[str]:
    return [_stem(t) if _stemmable(t) else t for t in _WORD_RE.findall(sentence.lower())]


def _sentence_matches(low: str, stems: list[str], verbatim: list[str], stemmed: list[tuple[str, ...]]) -> bool:
    """True when a sentence contains a verbatim keyword or a contiguous stem run."""
    if any(v in low for v in verbatim):
        return True
    for seq in stemmed:
        width = len(seq)
        for start in range(len(stems) - width + 1):
            if tuple(stems[start : start + width]) == seq:
                return True
    return False


_FACT_RE = re.compile(
    r"(\d[\d,\.]*(?:st|nd|rd|th)?%?)"
    r"|(19|20)\d{2}"  # years
    r"|\b(percent|percentage|million|billion|thousand|km|km2|sq\s*km|m\s*above|m)"
    r"\b",
    re.IGNORECASE,
)
_PROPER_NOUN_RE = re.compile(r"(?<![.!?]\.)\b[A-Z][a-z]{2,}\b")


def _is_fact_dense_sentence(sent: str) -> bool:
    """Heuristically flag a sentence that carries a fact the answer may hinge on
    but which does not necessarily contain the query keywords — a number, a year,
    a percentage, or a proper noun / named entity. Such sentences are kept during
    narrowing even when they sit far from any keyword hit, so a numeric or
    entity answer is never dropped just because it lacks the keyword phrasing.
    """
    low = sent.lower()
    if _FACT_RE.search(sent) or _FACT_RE.search(low):
        return True
    if _PROPER_NOUN_RE.search(sent):
        return True
    return False


#: Plain-text chunks at or below this size are handed over whole instead of being
#: cut down to their keyword sentences. A short chunk IS the evidence: the 605-char
#: page-1 chunk of 《柔性拖链技术规格书》 carries the jacket material, its colour and
#: the outer diameter in adjacent lines, and window-narrowing around one keyword
#: hit dropped the rest of it (the "印字/屏蔽" lines sat outside the window).
#: Token cost is bounded by the chunk itself, so keeping it whole is cheap.
_SHORT_PLAIN_TEXT_CHARS = 1200

#: How ``_narrow_content`` treated a payload: long prose reduced to its keyword
#: sentences, short prose handed over whole, prose no keyword occurs in, or a
#: structured payload (always whole).
_NARROWED = "narrowed"
_SHORT_WHOLE = "short_whole"
_NO_KEYWORD = "no_keyword"
_TABLE = "table"


def _mentions_any_keyword(text: str, kwds: list[str]) -> bool:
    """True when ``text`` contains a keyword, stem-tolerant (see ``_sentence_matches``)."""
    verbatim, stemmed = _keyword_forms(kwds)
    if not verbatim and not stemmed:
        return False
    return _sentence_matches(text.lower(), _sentence_stems(text), verbatim, stemmed)


def _narrow_content(content: str, kwds: list[str]) -> tuple[str, bool, str]:
    """Return ``(payload, keyword_matched, mode)``; never returns nothing to use.

    ``mode`` is ``_NARROWED`` (long prose reduced to its keyword sentences),
    ``_SHORT_WHOLE`` (short prose, handed over as it is), ``_NO_KEYWORD`` (no
    keyword occurs in the payload) or ``_TABLE`` (structured text, always whole).

    Matching is stem-tolerant: a keyword matches any word sharing its stem, so
    "nominations" finds "nominated". Sentences that are fact-dense (numbers /
    years / percentages / proper nouns) are kept regardless of keyword distance,
    so numeric or named-entity answers survive narrowing.

    ``keyword_matched`` is what a *filtering* caller drops on. Callers that must
    not lose evidence (the retrieval tools) keep the payload whatever the mode:
    retrieval already ranked the chunk, and the keyword list comes from a rewrite
    of the question, so no overlap says the phrasing differs, not that the chunk
    is irrelevant. That asymmetry is what emptied the evidence on
    《柔性拖链技术规格书》: the page-2 HTML table was kept whole for every question
    while the page-1 prose chunk was discarded unless the wording overlapped it
    verbatim, so the jacket / colour / diameter / marking questions reached the
    model with no evidence for them (`[hybrid_search] Kept 2 of 5 passage(s)` in
    the server log). Being dropped also renumbered every later citation.
    """
    # Structured tables must be returned whole. A keyword hit anywhere in a big
    # table (e.g. the capitals-by-latitude table) otherwise narrows to the hit
    # sentence +/- neighbours and DROPS the far end of the table — precisely the
    # "table truncated at -4.58°N, Maseru (-29.3°) missing" bug on FRAMES Q408.
    # A table row is one data point, not a sentence, so keyword-window narrowing is
    # wrong here; keep the full table (it is already rank-sorted by the retriever).
    # Markdown pipe tables (>=3 rows with >=2 pipes) get the same full-text pass:
    # their answer rows often sit mid-table (e.g. a rank row at ~62% of a 14.7K-char
    # table), and sentence-window narrowing truncates them to a header-only snippet.
    low_content = content.lower()
    if "<table" in low_content or "<tr" in low_content or "<td" in low_content:
        return "..." + _highlight_keywords(content, kwds) + "...", True, _TABLE
    pipe_rows = sum(1 for line in content.splitlines() if line.count("|") >= 2)
    if pipe_rows >= 3:
        return "..." + _highlight_keywords(content, kwds) + "...", True, _TABLE

    # Short prose is the evidence in full, exactly like a table row. A keyword-less
    # payload comes back byte-identical: nothing was cut, so there is nothing to
    # mark with the ellipsis convention.
    if len(content) <= _SHORT_PLAIN_TEXT_CHARS:
        if not _mentions_any_keyword(content, kwds):
            return content, False, _SHORT_WHOLE
        return "..." + _highlight_keywords(content, kwds) + "...", True, _SHORT_WHOLE

    sents = _split_sentences(content)
    # Stem-tolerant matching: a keyword matches any word sharing its stem, so
    # "nominations" finds "nominated" and "company" finds "companies".
    verbatim, stemmed = _keyword_forms(kwds)
    if not sents or (not verbatim and not stemmed):
        return content, False, _NO_KEYWORD
    keep: set[int] = set()
    matched = False
    for i, s in enumerate(sents):
        low = s.lower()
        if _sentence_matches(low, _sentence_stems(s), verbatim, stemmed):
            matched = True
            for j in range(max(0, i - 2), min(len(sents), i + 3)):
                keep.add(j)
        elif _is_fact_dense_sentence(s):
            # Keep fact-dense sentences even without a keyword hit so the answer
            # value (a bare figure, a date, a proper noun) is never lost.
            for j in range(max(0, i - 1), min(len(sents), i + 2)):
                keep.add(j)
    if not matched:
        # No keyword anywhere: hand the payload over as it is. A caller that only
        # wants keyword-bearing passages drops it on ``keyword_matched``; the
        # retrieval tools keep it (see the docstring).
        return content, False, _NO_KEYWORD
    narrowed = "".join(sents[i] for i in sorted(keep)).strip()
    return "..." + _highlight_keywords(narrowed, kwds) + "...", True, _NARROWED


def _highlight_keywords(text: str, kwds: list[str]) -> str:
    """Star the verbatim keyword phrases AND any word sharing a keyword's stem.

    Full keyword phrases are matched first and starred as ONE contiguous span, so
    a multi-word entity like "Atlanta Braves" becomes ``*Atlanta Braves*`` — never
    ``*Atlanta* *Braves*`` — because the downstream cross-check matches entities
    with a bounded contiguous regex that a per-word star would break.
    """
    phrases = sorted({(kw or "").strip().lower() for kw in kwds or [] if (kw or "").strip()}, key=len, reverse=True)
    terms: list[str] = list(phrases)
    # Add stem-matched words NOT already inside a phrase, so "nominated" still
    # gets starred for keyword "nominations" while "Atlanta Braves" stays whole.
    verbatim, stemmed = _keyword_forms(kwds)
    stem_set = {s for seq in stemmed for s in seq}
    if stem_set:
        for word in re.findall(r"[A-Za-z]+", text):
            low = word.lower()
            if _stemmable(low) and _stem(low) in stem_set and not any(low in p for p in phrases):
                terms.append(low)
    if not terms:
        return text
    # Longest first so a phrase wins over a word it contains; one pass, so an
    # already-starred span is never starred again.
    pattern = re.compile("|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True)), re.IGNORECASE)
    return pattern.sub(lambda m: f"*{m.group(0)}*", text)


def _split_keyword_terms(keywords: str) -> list[str]:
    """Normalize a keyword string into match terms.

    Comma-separated terms are used as they are; fewer than three of them falls
    back to space-split bigrams, because a bare keyword blob ("finale run time")
    is more discriminative as bigrams than as single words. Mirrors the term
    construction the Go port uses (``SplitKeywords``).
    """
    kwds = [k.strip().lower() for k in (keywords or "").split(",") if k.strip()]
    if not kwds:
        return []
    if len(kwds) < 3:
        words = [k.strip().lower() for k in (keywords or "").split(" ") if k.strip()]
        bigrams = [f"{words[i]} {words[i + 1]}" for i in range(len(words) - 1)]
        if bigrams:
            return bigrams
    return kwds


def _rewrite_payloads(chunks: list[dict], kwds: list[str], *, drop_unmatched: bool) -> tuple[list[dict], dict[str, int]]:
    """Write each chunk's narrowed payload back in place; returns (chunks, counts).

    ``drop_unmatched`` is for the callers whose contract IS a keyword filter
    (graph exploration, wiki lookup, the grep fallback): they keep only payloads a
    keyword occurs in. The retrieval tools pass ``False`` so a passage is never
    lost to a keyword miss (``_narrow_content`` explains why that matters).
    """
    counts: dict[str, int] = {}
    out: list[dict] = []
    dedup: set[str] = set()
    for ck in chunks:
        payload, matched, mode = _narrow_content(ck.get("content_with_weight") or ck.get("content") or "", kwds)
        counts[mode] = counts.get(mode, 0) + 1
        if drop_unmatched and not matched:
            continue
        payload_hash = hashlib.md5(payload.encode("utf-8")).hexdigest()
        if payload_hash in dedup:
            continue
        dedup.add(payload_hash)
        ck["content_with_weight"] = payload
        # The payload is this stage's own text, so a recorded ingest prefix no longer describes the
        # content: state that no prefix is recorded rather than leave a stale extent behind.
        clear_prefix(ck)
        if "content" in ck:
            ck["content"] = payload
        ck.pop("highlight", None)
        out.append(ck)
    return out, counts


def _narrow_by_keywords(chunks: list[dict], keywords: str) -> list[dict]:
    """Keep only the chunks a keyword occurs in, narrowed to its sentences.

    The filtering form, for callers whose contract is a keyword filter (graph
    exploration, wiki lookup, grep). Retrieval must not use it: see
    ``_narrow_or_keep``.
    """
    kwds = _split_keyword_terms(keywords)
    if not kwds or not chunks:
        return chunks
    kept, _counts = _rewrite_payloads(chunks, kwds, drop_unmatched=True)
    return kept


def _narrow_or_keep(chunks: list[dict], keywords: str, label: str) -> list[dict]:
    """Shrink each retrieved chunk to its keyword sentences; drop none of them.

    No keyword overlap does not mean irrelevant — the retriever already ranked
    these chunks, and the keywords come from a rewrite of the question, so the
    wording of the chunk need not repeat them. Dropping the non-matching chunks
    emptied the evidence exactly when the answer lived in prose while a sibling
    table chunk survived (structured text is exempt from narrowing), which is how
    the jacket / marking questions on 《柔性拖链技术规格书》 lost their only source.
    The log line names the keywords: without them, a thin pool is indistinguishable
    from keywords that never matched anything.
    """
    kwds = _split_keyword_terms(keywords)
    if not kwds or not chunks:
        return chunks
    kept, counts = _rewrite_payloads(chunks, kwds, drop_unmatched=False)
    _LOG.info(
        "[%s] %d passage(s) -> %d kept (%d narrowed, %d short kept whole, %d no keyword hit, %d structured kept whole); keywords=[%s]",
        label,
        len(chunks),
        len(kept),
        counts.get(_NARROWED, 0),
        counts.get(_SHORT_WHOLE, 0),
        counts.get(_NO_KEYWORD, 0),
        counts.get(_TABLE, 0),
        keywords,
    )
    return kept
