"""Container-internal credential probe (read-only, minimal calls).

Reuses the DEPLOYED client: `rag.llm.embedding_model.GeminiEmbed`, which is `google.genai` based
(`genai.Client(api_key=...)`) and builds its request config through its own `_build_embedding_config()`.
No endpoint, API version or model path is invented here.

Keys arrive only as transient per-process environment variables for this one `docker exec`; nothing is
written to the container, the DB, the KB, any production file, or the host filesystem.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

sys.path.insert(0, "/ragflow")

PROBE_TEXT = "线缆标准检索探针 fixed probe text"
MODEL = "gemini-embedding-001"


def fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def classify(message: str) -> str:
    low = message.lower()
    if "429" in low or "resource_exhausted" in low or "quota" in low:
        return "QUOTA_EXHAUSTED"
    if any(token in low for token in ("401", "403", "api key not valid", "invalid api key", "permission_denied", "unauthenticated")):
        return "INVALID"
    if any(token in low for token in ("404", "not_found", "not found", "endpoint")):
        return "OTHER_PROVIDER_FAILURE"
    return "OTHER_PROVIDER_FAILURE"


def probe(alias: str, key: str) -> dict:
    import numpy as np

    record: dict = {
        "alias": alias,
        "credential_fingerprint_sha256_12": fingerprint(key),
        "sdk": "google.genai via deployed GeminiEmbed",
        "model_requested": MODEL,
        "provider_allowed_models_checked": False,
    }
    try:
        from rag.llm.embedding_model import GeminiEmbed

        client = GeminiEmbed(key=key, model_name=MODEL)
        record["client_constructed"] = True
        record["auth_method"] = "genai.Client(api_key=<key>)"
        vector = None
        if hasattr(client, "encode_queries"):
            # Production shape, confirmed from the deployed source:
            #   search.py:105  qv, _ = await thread_pool_exec(emb_mdl.encode_queries, txt)   # txt is a STRING
            #   embedding_model.py  def encode_queries(self, text) -> (np.ndarray, token_count)
            record["call_path"] = "GeminiEmbed.encode_queries(<str>)"
            outcome = client.encode_queries(PROBE_TEXT)
            if isinstance(outcome, tuple):
                vector, record["token_count"] = outcome[0], int(outcome[1])
            else:
                vector = outcome
        if vector is None:
            record["call_path"] = "deployed client.client.models.embed_content + deployed _build_embedding_config()"
            config = client._build_embedding_config()
            try:
                record["task_type"] = str(getattr(config, "task_type", None))
                record["requested_output_dimensionality"] = getattr(config, "output_dimensionality", None)
            except Exception:  # noqa: BLE001
                pass
            response = client.client.models.embed_content(model=MODEL, contents=[PROBE_TEXT], config=config)
            vector = client._parse_embedding_response(response)[0]
        array = np.asarray(vector, dtype=float).reshape(-1)
        record.update(
            {
                "result": "SUCCESS",
                "http_result": "provider call returned normally (SDK)",
                "dimension": int(array.shape[0]),
                "norm": round(float(np.linalg.norm(array)), 6),
                "all_finite": bool(np.isfinite(array).all()),
                "vector_sha256_16": hashlib.sha256(array.tobytes()).hexdigest()[:16],
                "_vector": array,
            }
        )
    except Exception as exc:  # noqa: BLE001
        message = f"{type(exc).__name__}: {exc}"
        record.update({"result": classify(message), "error": message[:400], "client_constructed": record.get("client_constructed", False)})
    return record


def main() -> int:
    import numpy as np

    keys = [("KEY_1", os.environ.get("PROBE_KEY_1", "")), ("KEY_2", os.environ.get("PROBE_KEY_2", ""))]
    records = [probe(alias, key) for alias, key in keys if key]

    vectors = [(record["alias"], record["_vector"]) for record in records if record.get("result") == "SUCCESS"]
    compatibility: dict = {"status": "NOT_APPLICABLE", "reason": "not every key succeeded"}
    if len(vectors) == 2:
        left, right = vectors[0][1], vectors[1][1]
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        cosine = float(left.dot(right) / denominator) if denominator else 0.0
        compatibility = {
            "status": "SAME_MODEL_CREDENTIAL_COMPATIBILITY_OBSERVED",
            "label_meaning": "same model reached through different credentials; this is NOT proof that the vector spaces are identical",
            "dimension_match": int(left.shape[0]) == int(right.shape[0]),
            "dimension": int(left.shape[0]),
            "cosine_similarity": round(cosine, 8),
            "vector_byte_identical": bool(np.array_equal(left, right)),
            "provenance": "OBSERVED (two provider calls, identical probe text, identical deployed client and config)",
        }

    for record in records:
        record.pop("_vector", None)
    print("PROBE_JSON_BEGIN")
    print(json.dumps({"model": MODEL, "probe_text": PROBE_TEXT, "records": records, "compatibility": compatibility, "calls_made": len(records)}, ensure_ascii=False))
    print("PROBE_JSON_END")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
