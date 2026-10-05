#
#  Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
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

from __future__ import annotations

import re
import unicodedata


ARABIC_PRESENTATION_FORMS_RE = re.compile(r"[\uFB50-\uFDFF\uFE70-\uFEFF]")

# Conversation titles are shown in a narrow chat header, so they are clamped even
# when the model ignores the length instruction. 25 is the top of the band the
# titler prompt asks for: the header only has room for the identifiers a title is
# supposed to carry (standard number, material model, indicator), and a longer
# answer means the model padded it.
CONVERSATION_TITLE_MAX_CHARS = 25

_TITLE_LABEL_RE = re.compile(r"^(?:title|标题|标题[:：])\s*[:：]?\s*", re.IGNORECASE)
_TITLE_EDGE_RE = re.compile(r"^[\s\"'“”‘’`*#>\-–—:：]+")
_TITLE_TAIL_RE = re.compile(r"[\s\"'“”‘’`*#>.:：。!！?？~]+$")

# The year of a standard number is dead weight in a header: five characters of a
# budget that the material model and the indicator are worth more, because the same
# standard is asked about under many indicators. The lookbehind anchors the year on a
# digit, so a standard number ("Q/GDW 73289.2-2026", "IEC 60502-1:2014") loses it
# while a year standing on its own ("2026年电缆采购计划") and a year in a model name
# ("YJV22-2026") are left alone.
_TITLE_STANDARD_YEAR_RE = re.compile(r"(?<=\d)\s*[-–—:：]\s*(?:19|20)\d{2}(?=\D|$)")


def normalize_conversation_title(raw: str | None, max_chars: int = CONVERSATION_TITLE_MAX_CHARS) -> str:
    """Normalise an LLM-produced conversation title.

    Models wrap titles in quotes, prefix them with ``Title:``, or answer with a
    whole sentence. Keep the first line, strip that decoration, drop the year of any
    standard number it quoted, collapse whitespace and clamp the length so the header
    never overflows.
    """
    if not raw or not isinstance(raw, str):
        return ""

    line = next((candidate.strip() for candidate in raw.splitlines() if candidate.strip()), "")
    if not line:
        return ""

    line = _TITLE_LABEL_RE.sub("", line)
    line = _TITLE_EDGE_RE.sub("", line)
    line = _TITLE_TAIL_RE.sub("", line)
    # Before the clamp, so the characters the year frees are available to the model's
    # own wording instead of being cut off the end.
    line = _TITLE_STANDARD_YEAR_RE.sub("", line)
    line = re.sub(r"\s+", " ", line).strip()

    if len(line) > max_chars:
        line = line[:max_chars].rstrip()

    return line


def normalize_arabic_digits(text: str | None) -> str | None:
    if text is None or not isinstance(text, str):
        return text

    out = []
    for ch in text:
        code = ord(ch)
        if 0x0660 <= code <= 0x0669:
            out.append(chr(code - 0x0660 + 0x30))
        elif 0x06F0 <= code <= 0x06F9:
            out.append(chr(code - 0x06F0 + 0x30))
        else:
            out.append(ch)
    return "".join(out)


def normalize_arabic_presentation_forms(text: str | None) -> str | None:
    """Normalize Arabic presentation forms to canonical text when present."""
    if text is None or not isinstance(text, str):
        return text
    if not ARABIC_PRESENTATION_FORMS_RE.search(text):
        return text
    return unicodedata.normalize("NFKC", text)
