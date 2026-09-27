"""Read-only Gemini model compatibility audit.

Answers one question: why does `gemini-embedding-1.0` return HTTP 404 for this deployment?

Strictly read-only: no embed_content call anywhere (so no quota is consumed and no vector is produced), no
DB write, no config change, no container recreate. The only network call is the SDK's model LISTING, which
the audit was explicitly authorised to use.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import sys

sys.path.insert(0, "/ragflow")

KB = "9463d93eb97511f1938f2592e9bc6fe4"
out: dict = {"embed_calls_made": 0}


def main() -> int:
    from api.db.joint_services.tenant_model_service import resolve_model_config
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from common.constants import LLMType

    ok, kb = KnowledgebaseService.get_by_id(KB)
    if not ok:
        print("AUDIT_JSON_BEGIN")
        print(json.dumps({"error": "KB not found"}))
        print("AUDIT_JSON_END")
        return 1
    owner = str(getattr(kb, "tenant_id", "") or "")
    out["kb_embd_id"] = getattr(kb, "embd_id", None)
    out["owner_tenant_fingerprint"] = hashlib.sha256(owner.encode()).hexdigest()[:12] if owner else None

    config = resolve_model_config(owner, LLMType.EMBEDDING, kb.embd_id)
    if not isinstance(config, dict):
        out["config_error"] = f"resolve_model_config returned {type(config).__name__}"
        print("AUDIT_JSON_BEGIN")
        print(json.dumps(out, ensure_ascii=False))
        print("AUDIT_JSON_END")
        return 0

    out["config_keys"] = sorted(str(key) for key in config.keys())
    out["db_model_name_exact"] = config.get("llm_name") or config.get("model_name") or config.get("model")
    out["base_url"] = config.get("base_url")
    out["provider_factory"] = config.get("llm_factory")
    secret = str(config.get("api_key") or "")
    out["credential_fingerprint_sha256_12"] = hashlib.sha256(secret.encode()).hexdigest()[:12] if secret else None
    out["credential_present"] = bool(secret)

    from rag.llm.embedding_model import GeminiEmbed

    name = out["db_model_name_exact"]
    try:
        client = GeminiEmbed(key=secret, model_name=name)
        out["class_received_model_name"] = name
        out["class_effective_model_name"] = client.model_name
        out["class_stripped_models_prefix"] = bool(name and str(name).startswith("models/"))
        out["class_adds_models_prefix"] = str(client.model_name).startswith("models/")
        out["class_default_when_absent"] = GeminiEmbed.__init__.__defaults__
    except Exception as exc:  # noqa: BLE001
        out["class_error"] = f"{type(exc).__name__}: {exc}"[:300]
        print("AUDIT_JSON_BEGIN")
        print(json.dumps(out, ensure_ascii=False))
        print("AUDIT_JSON_END")
        return 0

    # Read-only provider capability listing (authorised). No embedding request is issued.
    try:
        names = [getattr(model, "name", "") for model in itertools.islice(client.client.models.list(), 300)]
        out["listed_total_sampled"] = len(names)
        embedding_names = sorted({value for value in names if "embed" in str(value).lower()})
        out["listed_embedding_models"] = embedding_names[:30]
        target = str(client.model_name).split("/")[-1]
        out["target_present_in_listing"] = any(str(value).split("/")[-1] == target for value in names)
        out["gemini_embedding_001_present"] = any("gemini-embedding-001" in str(value) for value in names)
    except Exception as exc:  # noqa: BLE001
        out["list_error"] = f"{type(exc).__name__}: {exc}"[:300]

    print("AUDIT_JSON_BEGIN")
    print(json.dumps(out, ensure_ascii=False))
    print("AUDIT_JSON_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
