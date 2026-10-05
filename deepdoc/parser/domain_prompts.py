#
#  Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
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
"""
Domain-aware vision prompt helpers shared by the deepdoc and rag layers.

This module is intentionally dependency-free (standard library only) so that
both `deepdoc.*` (low level parsing) and `rag.*` (orchestration) can import it
without introducing a circular import between the two layers.
"""

import logging

__all__ = [
    "CABLE_STRONG_KEYWORDS",
    "CABLE_WEAK_KEYWORDS",
    "STRONG_HIT_THRESHOLD",
    "WEAK_HIT_THRESHOLD",
    "DOMAIN_VISION_INSTRUCTIONS",
    "resolve_domain_with_confidence",
    "inject_domain_instruction",
]


# High-confidence keywords: nearly exclusive to cable documents, so a single
# hit is already a reliable signal.
CABLE_STRONG_KEYWORDS = {
    "电缆",
    "cable",
    "线缆",
    "myjv",
    "yjv",
    "bvr",
    "rvv",
    "kvv",
    "铠装",
    "交联聚乙烯",
    "xlpe",
    "pvc绝缘",
    "铜芯",
    "铝芯",
}

# Low-confidence keywords: common power/engineering terms, so at least
# WEAK_HIT_THRESHOLD distinct hits are required before inferring the domain.
CABLE_WEAK_KEYWORDS = {
    "导体",
    "绝缘",
    "护套",
    "屏蔽",
    "芯数",
    "截面积",
    "conductor",
    "insulation",
    "sheath",
    "armor",
}

STRONG_HIT_THRESHOLD = 1
WEAK_HIT_THRESHOLD = 3

DOMAIN_VISION_INSTRUCTIONS = {
    "cable": (
        "\n\nSpecial Instruction: This image is from a cable industry standard or catalog. "
        "Please carefully identify and explicitly describe cable structures (e.g., conductor, insulation, armor, sheath), "
        "cross-section diagrams, wiring schematics, cable models (e.g., MYJV22), and electrical specifications. "
        "Transcribe any visible tabular data related to cable dimensions precisely."
    ),
    # Future verticals (fiber, semiconductor, ...) can be added here without
    # touching the rest of the parsing pipeline (Open/Closed Principle).
}


def resolve_domain_with_confidence(
    kwargs: dict,
    context_text: str = "",
) -> tuple[str, str]:
    """
    Conservative 3-tier domain resolution.

    Tier 1: explicit `domain` kwarg (never overridden).
    Tier 2: `parser_config.domain` (dataset/UI configuration).
    Tier 3: keyword auto-inference (high-precision only; may return "").

    Returns:
        (domain, reason) where reason ∈ {"explicit", "parser_config",
        "auto_strong(N)", "auto_weak(N)", "none"}.
    """
    # Tier 1: explicit code-level
    domain = kwargs.get("domain")
    if domain:
        return str(domain).lower(), "explicit"

    # Tier 2: dataset-level parser_config
    pc = kwargs.get("parser_config") or {}
    if isinstance(pc, dict) and pc.get("domain"):
        return str(pc["domain"]).lower(), "parser_config"

    # Tier 3: conservative auto-inference
    text = (context_text + " " + str(kwargs.get("filename", ""))).lower()
    if not text.strip():
        return "", "none"

    strong_hits = sum(1 for kw in CABLE_STRONG_KEYWORDS if kw in text)
    weak_hits = sum(1 for kw in CABLE_WEAK_KEYWORDS if kw in text)

    if strong_hits >= STRONG_HIT_THRESHOLD:
        return "cable", f"auto_strong({strong_hits})"
    if weak_hits >= WEAK_HIT_THRESHOLD:
        return "cable", f"auto_weak({weak_hits})"

    return "", "none"


def inject_domain_instruction(
    prompt,
    domain: str,
    figure_idx: int = -1,
    reason: str = "",
):
    """
    Append the domain-specific instruction to the prompt.

    The prompt is returned unchanged when no domain is resolved, so upstream
    generic behavior is preserved. A non-str prompt (defensive guard against a
    caller passing a pre-built message list) is also returned unchanged, with a
    warning, instead of raising.
    """
    if not isinstance(prompt, str):
        logging.warning(f"[DomainPrompt] figure={figure_idx} domain={domain} reason={reason} skipped: prompt is not str")
        return prompt

    instruction = DOMAIN_VISION_INSTRUCTIONS.get((domain or "").lower(), "")
    if instruction:
        logging.info(f"[DomainPrompt] figure={figure_idx} domain={domain} reason={reason} injected")
        return prompt + instruction
    return prompt
