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
"""Masking of stored credentials on their way out to a client.

A provider credential must never reach the browser in cleartext, but the
client still has to tell "a credential is stored" apart from "none is
configured". ``mask_secret`` therefore keeps a short recognisable prefix and
suffix and replaces the middle with ``SECRET_MASK``.

The same sentinel is what makes a round trip safe: a client that echoes the
masked value back is understood as "leave the stored credential alone"
(``resolve_secret_on_write``), so a read-mask / write-back cycle can never
overwrite a real key with its own mask. A real credential cannot contain the
sentinel, so the check is unambiguous.
"""

import json
from typing import Any

# Real API keys never contain this, which is what makes the round trip safe.
SECRET_MASK = "****"

# Below this length, revealing a 3-char prefix and a 4-char suffix would expose
# most of the secret, so short values are masked whole.
_MIN_LEN_FOR_PARTIAL_MASK = 12

# Credential fields carried inside a provider's JSON bundle (Bedrock, XunFei
# Spark, PaddleOCR, MinerU, ...). Structural fields (``auth_mode``,
# ``region``, ``group_id``, ``api_version``) deliberately do not match, so the
# provider forms keep the values they need for their own logic.
_SECRET_FIELD_MARKERS = ("key", "token", "secret", "password", "passwd", "credential")


def _mask_text(value: str) -> str:
    if len(value) < _MIN_LEN_FOR_PARTIAL_MASK:
        return SECRET_MASK
    return f"{value[:3]}{SECRET_MASK}{value[-4:]}"


def _looks_secret(field_name: str) -> bool:
    lowered = field_name.lower()
    return any(marker in lowered for marker in _SECRET_FIELD_MARKERS)


def is_masked(value: Any) -> bool:
    """Report whether ``value`` is (or contains) a mask produced by this module."""
    return isinstance(value, str) and SECRET_MASK in value


def _parse_json_object(value: str) -> dict | None:
    trimmed = value.strip()
    if not trimmed.startswith("{"):
        return None
    try:
        parsed = json.loads(trimmed)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _mask_bundle(bundle: dict) -> dict:
    masked = {}
    for field_name, field_value in bundle.items():
        if isinstance(field_value, str) and field_value and _looks_secret(field_name):
            masked[field_name] = _mask_text(field_value)
        else:
            masked[field_name] = field_value
    return masked


def mask_secret(value: Any) -> Any:
    """Return a display-safe form of a stored credential.

    Handles the three shapes ``TenantModelInstance.api_key`` takes: a bare key
    string, a JSON bundle string, and an already-parsed bundle dict. ``None``
    and ``""`` pass through unchanged so "not configured" stays distinguishable
    from "configured".
    """
    if value is None:
        return None
    if isinstance(value, dict):
        return _mask_bundle(value)
    if not isinstance(value, str):
        return value
    if not value:
        return value

    bundle = _parse_json_object(value)
    if bundle is None:
        return _mask_text(value)
    return json.dumps(_mask_bundle(bundle))


def _merge_bundle(incoming: dict, stored: Any) -> str:
    """Overlay ``incoming`` onto the stored bundle, skipping masked fields."""
    stored_bundle = stored if isinstance(stored, dict) else (_parse_json_object(stored) if isinstance(stored, str) else None)
    merged = dict(stored_bundle or {})
    for field_name, field_value in incoming.items():
        if is_masked(field_value):
            # The client echoed our mask, so it never saw this value: keep the
            # stored one rather than persisting the mask as the credential.
            continue
        merged[field_name] = field_value
    return json.dumps(merged)


def resolve_secret_on_write(incoming: Any, stored: Any) -> Any:
    """Decide what credential to persist for an update.

    ``incoming`` is what the client sent, ``stored`` what the database holds.
    An empty or masked ``incoming`` means the client did not supply a new
    credential, so ``stored`` is returned unchanged.
    """
    if incoming is None:
        return stored
    if isinstance(incoming, str) and not incoming.strip():
        return stored
    if isinstance(incoming, dict):
        return _merge_bundle(incoming, stored)
    if isinstance(incoming, str):
        if is_masked(incoming):
            return stored
        bundle = _parse_json_object(incoming)
        if bundle is None:
            return incoming
        return _merge_bundle(bundle, stored)
    return incoming


def client_supplied_secret(value: Any) -> bool:
    """Report whether the client sent a usable credential (not empty, not a mask)."""
    if value is None:
        return False
    if isinstance(value, dict):
        if not value:
            return False
        return not all(is_masked(v) for v in value.values())
    if isinstance(value, str):
        return bool(value.strip()) and not is_masked(value)
    return True
