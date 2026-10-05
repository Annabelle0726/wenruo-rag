#
#  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
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

"""Route guard for knowledge-base-bound chat assistants.

An assistant bound to knowledge bases is supposed to retrieve before it
answers, but that decision was left entirely to the model: the route prompt
asks it to call ``rag`` "for any question that needs evidence", and when the
model declines, the turn is answered from whatever the context window still
holds. That failure is silent — no retrieval, no citations, and often the
previous turn's material restated as this turn's answer (an assistant asked for
a comparison table on 2026-09-19 answered with the drawing material it had
retrieved for the previous question).

The guard removes the model from that decision. A knowledge-base-bound
assistant retrieves on every user turn; ``is_small_talk`` is the whitelist of
turns that carry nothing to look up. The whitelist matches the *whole*
normalized turn, so a greeting that opens a real question
("你好，介绍一下 YZ 系列电缆") still retrieves.
"""

from dataclasses import dataclass
import re

# A turn longer than this is never treated as small talk, whatever it matches:
# the whitelist is for one-liners, and a length ceiling keeps a future pattern
# edit from swallowing a real question.
_SMALL_TALK_MAX_CHARS = 32

_WHITESPACE_RE = re.compile(r"\s+")
# Quotes are dropped rather than spaced out so "what's your name" normalizes to
# "whats your name" instead of "what s your name".
_QUOTES_RE = re.compile(r"['\"'\"`]")
_PUNCTUATION_RE = re.compile(r"[^\w\s]", re.UNICODE)

# Full-match patterns over the normalized turn: lowercased, quotes removed,
# other punctuation turned into a space, whitespace collapsed and stripped.
_SMALL_TALK_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        # Greetings.
        r"(你|您)?好[呀啊哇哦哈奥]?",
        r"(hi|hii+|hey|hello)( there)?",
        r"嗨|哈喽|哈啰",
        r"(早上|上午|中午|下午|晚上)好",
        r"早安|午安|晚安",
        r"在吗|在么",
        # Thanks.
        r"(非常|十分|很)?(感谢|谢谢|多谢)(你|您)?(啦|了|哈|呀|哦)?",
        r"thanks?( you)?( very much)?|thank u|thx|3q",
        r"辛苦了?",
        # Acknowledgements.
        r"好[的嘞]?|嗯+|收到|明白了?|知道了?|行|可以",
        r"ok|okay|got it|alright",
        # Sign-offs.
        r"再见|拜拜|回见|bye|goodbye|see you|good night",
        # Questions about the assistant itself, which the system prompt answers.
        r"你是谁|你叫什么(名字)?|whats? your name|who are you",
        r"你(能|会)(做|干)?什么|你有什么功能|你能帮我(做)?什么|what can you do",
    )
)


def _normalize(question: str) -> str:
    text = str(question or "").strip().lower()
    text = _QUOTES_RE.sub("", text)
    text = _PUNCTUATION_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def is_small_talk(question: str) -> bool:
    """True when a turn carries nothing to retrieve for.

    An empty turn counts as small talk: there is no question to look up, so the
    guard stays out of the way.
    """
    normalized = _normalize(question)
    if not normalized:
        return True
    if len(normalized) > _SMALL_TALK_MAX_CHARS:
        return False
    return any(pattern.fullmatch(normalized) for pattern in _SMALL_TALK_PATTERNS)


@dataclass(frozen=True)
class MandatoryRetrieval:
    """A retrieval a chat turn must run before the model gets to answer."""

    tool: str
    question: str

    @property
    def arguments(self) -> dict:
        return {"question": self.question}


def mandatory_retrieval(question: str, *, tool: str = "rag") -> MandatoryRetrieval | None:
    """The retrieval this turn must run, or None when the turn is small talk.

    ``question`` is passed through unchanged: it is the turn as the user wrote
    it, which is what the retrieval graph is meant to be numbered and answered
    over.
    """
    if is_small_talk(question):
        return None
    return MandatoryRetrieval(tool=tool, question=str(question or ""))
