"""READ-ONLY production state snapshot, for before/after identity guarding across a deploy.

Captures the identity-bearing configuration the deploy window must not disturb: model binding rows,
knowledge-base bindings, assistant retrieval parameters, the ES index shape, and the Redis keyspace
shape. Secrets are never printed - API keys are reduced to a sha256 prefix, which is enough to prove
"unchanged" and carries nothing usable.

Usage (inside the production container, read-only):
    python production_state_snapshot.py /tmp/state_before.json
"""
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, "/ragflow")

from common import settings

settings.init_settings()

from api.db.db_models import Knowledgebase, TenantModel, TenantModelInstance, TenantModelProvider
from api.db.services.knowledgebase_service import KnowledgebaseService
from rag.utils.redis_conn import REDIS_CONN
from rag.utils.es_conn import ESConnection

TENANT = "a9e28731ab7011f19b833887d563fb04"
KB = "014e4f2aab7911f191ac3887d563fb04"
INDEX = "ragflow_" + TENANT


def fingerprint(value):
    text = str(value or "")
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def model_rows():
    rows = []
    for row in TenantModelProvider.select().dicts():
        rows.append({"id": row.get("id"), "tenant_id": row.get("tenant_id"), "provider_name": row.get("provider_name"), "api_key_fp": fingerprint(row.get("api_key"))})
    instances = []
    for row in TenantModelInstance.select().dicts():
        instances.append({k: row.get(k) for k in ("id", "tenant_id", "provider_id", "model_name", "model_type", "api_key_fp" if False else "id")})
        instances[-1]["api_key_fp"] = fingerprint(row.get("api_key"))
    models = []
    for row in TenantModel.select().dicts():
        models.append({k: row.get(k) for k in ("id", "tenant_id", "model_name", "model_type", "provider_id", "instance_id")})
    return {"providers": rows, "instances": instances, "models": models}


def kb_rows():
    out = []
    for row in Knowledgebase.select().dicts():
        out.append({k: row.get(k) for k in ("id", "tenant_id", "name", "embd_id", "parser_id", "chunk_num", "doc_num")})
    return out


def es_shape():
    es = ESConnection().es
    if not es.indices.exists(index=INDEX):
        return {"exists": False}
    mapping = es.indices.get_mapping(index=INDEX)[INDEX]["mappings"]
    st = es.indices.get_settings(index=INDEX)[INDEX]["settings"]["index"]
    stats = es.indices.stats(index=INDEX)["indices"][INDEX]["primaries"]
    return {
        "exists": True,
        "properties_count": len(mapping.get("properties", {})),
        "dynamic_templates": len(mapping.get("dynamic_templates", [])),
        "similarity": sorted(st.get("similarity", {}).keys()),
        "number_of_shards": st.get("number_of_shards"),
        "docs_count": stats["docs"]["count"],
        "docs_deleted": stats["docs"]["deleted"],
        "mapping_fp": hashlib.sha256(json.dumps(mapping, sort_keys=True).encode()).hexdigest()[:16],
    }


def redis_shape():
    try:
        info = REDIS_CONN.REDIS.info("keyspace")
        return {"keyspace": {k: str(v) for k, v in info.items()}, "secret_key_present": bool(REDIS_CONN.get("ragflow:system:secret_key")), "synonyms_present": bool(REDIS_CONN.get("kevin_synonyms"))}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def main():
    target = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/state.json")
    ok, kb = KnowledgebaseService.get_by_id(KB)
    snapshot = {
        "models": model_rows(),
        "knowledgebases": kb_rows(),
        "primary_kb": {"id": KB, "found": bool(ok), "embd_id": getattr(kb, "embd_id", None), "name": getattr(kb, "name", None)} if ok else {"id": KB, "found": False},
        "es": es_shape(),
        "redis": redis_shape(),
    }
    target.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print("STATE_SNAPSHOT_WRITTEN", target)
    print("model_instances:", len(snapshot["models"]["instances"]), "providers:", len(snapshot["models"]["providers"]), "models:", len(snapshot["models"]["models"]))
    print("kbs:", len(snapshot["knowledgebases"]), "primary_kb_embd:", snapshot["primary_kb"].get("embd_id"))
    print("es:", json.dumps(snapshot["es"], ensure_ascii=False))
    print("api_key_fingerprints:", [row["api_key_fp"] for row in snapshot["models"]["providers"]])


if __name__ == "__main__":
    main()
