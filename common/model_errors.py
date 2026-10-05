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
"""The client-facing shape of a model-provider failure.

A provider refusal used to reach the browser as the exception's ``repr``: the
upstream JSON body, its request ids, sometimes its quota metric names, all inside
one red notification. None of that tells a reader what to do, and the part that
does — "the account is out of quota" or "you are asking too fast" — was the part
buried in it.

A provider connector raises an exception carrying one of the types below;
:func:`model_failure_response` turns that into the payload a client is shown, so
the wording lives in one place and the raw text is kept for the log. Providers
that leak their SDK's own exception instead are still recognised: the text of a
429 is unmistakable, and :func:`classify` reads it.

The frontend maps the same ``error_type`` onto its own translated strings, so a
toast does not depend on the language this backend happens to answer in.
"""

from typing import Any

#: The vector service refused because the account's quota is used up. A retry
#: cannot fix it before the quota resets or the key changes.
EMBEDDING_QUOTA_EXHAUSTED = "EMBEDDING_QUOTA_EXHAUSTED"
#: The vector service refused because the caller is asking too often right now.
#: The same request is expected to succeed again shortly.
EMBEDDING_RATE_LIMITED = "EMBEDDING_RATE_LIMITED"

#: Business code for a refusal about pacing rather than about the request.
#: Matches the status the provider itself answered with.
TOO_MANY_REQUESTS = 429

#: What a client may show for each recognised type. Short on purpose: the reader
#: needs to know whether to wait or to change something.
MESSAGES: dict[str, str] = {
    EMBEDDING_QUOTA_EXHAUSTED: "AI 向量化服务额度已耗尽，请更换 API Key 或等待额度重置后重试。",
    EMBEDDING_RATE_LIMITED: "AI 向量化服务请求过于频繁，请稍后重试。",
}

#: Fragments of a provider refusal that mean the account's quota is spent.
#:
#: Both this and a per-minute limit arrive as HTTP 429, so the body is what tells
#: them apart. Google names the offending metric with a `PerDay` / `PerMinute`
#: suffix, OpenAI answers `insufficient_quota` for a spent account and
#: `rate_limit_exceeded` for pacing — so only the daily and account-level
#: wordings are listed here, and everything else 429-shaped falls through to the
#: rate limit below.
QUOTA_EXHAUSTED_MARKERS = (
    "insufficient_quota",
    "insufficient quota",
    "exceeded your current quota",
    "perday",
    "per day",
    "daily quota",
    "daily limit",
    # A body that states the quota IS exhausted has said this is not a pacing
    # problem, whichever status carried it. This is the ONE phrase of the four
    # tried that survives contact with the real payloads: it catches the live
    # GeminiEmbed refusal ("Embedding quota exhausted") and matches no existing
    # fixture. `quota exceeded` was REMOVED because it does not mean "spent" -
    # Google's PER-MINUTE refusal reads "Quota exceeded for metric:
    # embed_content_free_tier_requests ... PerMinutePerProjectPerModel" with a
    # `retryDelay`, i.e. pacing - so matching it reported a spent account for a
    # problem that clears in 20 seconds. `exceeded your quota` and `out of quota`
    # matched nothing at all, so they were dropped rather than kept as unproven
    # risk.
    "quota exhausted",
)

#: Fragments of a provider refusal that mean the caller is asking too fast. The
#: first two are what a provider answers with when its body says nothing more
#: specific than "429".
RATE_LIMITED_MARKERS = (
    "429",
    "resource_exhausted",
    "resource exhausted",
    "rate limit",
    "ratelimit",
    "rate_limit",
    "too many requests",
    "requests per minute",
    "tpm limit",
)

#: How much of the upstream text travels with the response. It is there for the
#: log and for a support ticket, not for the screen — an upstream body runs to
#: kilobytes, and every one of them was reaching a notification before.
MAX_RAW_MESSAGE = 400


def classify(detail: str) -> str | None:
    """The recognised failure type for a provider's error text, or ``None``."""
    lowered = str(detail).lower()

    if any(marker in lowered for marker in QUOTA_EXHAUSTED_MARKERS):
        return EMBEDDING_QUOTA_EXHAUSTED
    if any(marker in lowered for marker in RATE_LIMITED_MARKERS):
        return EMBEDDING_RATE_LIMITED

    return None


def model_failure_response(error: BaseException) -> dict[str, Any] | None:
    """The standard payload for a recognised provider failure, else ``None``.

    ``None`` hands the failure back to the caller's own handling: only refusals
    a reader can act on are translated, so an ordinary bug keeps surfacing as
    one.
    """
    error_type = getattr(error, "error_type", None) or classify(str(error))
    message = MESSAGES.get(error_type)
    if message is None:
        return None

    raw_message = getattr(error, "raw_message", None) or str(error)

    return {
        "code": TOO_MANY_REQUESTS,
        "message": message,
        "error_type": error_type,
        "raw_message": str(raw_message)[:MAX_RAW_MESSAGE],
    }
