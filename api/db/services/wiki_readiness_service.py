"""Read-only preparation checks shared by the Wiki page and enqueue boundary."""
from common import settings
from common.constants import LLMType


def wiki_readiness(kb, user_id):
    from api.db.db_models import WikiGeneration, UserCanvas
    from api.db.services.document_service import DocumentService
    from api.db.services.knowledgebase_service import KnowledgebaseService
    from api.db.joint_services.kb_authorization_service import _can_manage_tenant
    from api.db.joint_services.tenant_model_service import resolve_model_config, get_model_config_by_id
    from rag.svr.task_executor_refactor.dataset_wiki_generator import _wiki_eligible_docs, _validate_wiki_eligible_docs, _pipeline_compiler_llm_id
    docs, _ = DocumentService.get_by_kb_id(kb_id=kb.id, page_number=0, items_per_page=0,
        orderby="create_time", desc=False, keywords="", run_status=[], types=[], suffix=[])
    parsed = [d for d in docs if str(d.get("status", "1")) == "1" and d.get("chunk_num", 0) > 0 and float(d.get("progress", 0)) >= 1]
    enabled_docs = [d for d in docs if str(d.get("status", "1")) == "1"]
    checks = {"parsed": bool(parsed) and len(parsed) == len(enabled_docs), "pipeline": bool(kb.pipeline_id), "template": False, "models": False}
    models = []
    try:
        eligible = _wiki_eligible_docs(parsed, kb.tenant_id)
        checks["template"] = bool(eligible) and len(eligible) == len(parsed)
        ids = {str(d["id"]): _pipeline_compiler_llm_id(d.get("pipeline_id") or "") for d in parsed}
        pipelines = {d.get("pipeline_id") for d in parsed}
        valid_pipelines = {c.id for c in UserCanvas.select().where(UserCanvas.id.in_(pipelines), UserCanvas.tenant_id == kb.tenant_id, UserCanvas.canvas_category == "dataflow_canvas")}
        checks["pipeline"] = bool(pipelines) and pipelines == valid_pipelines
        if checks["template"]:
            _validate_wiki_eligible_docs(eligible)
        for name in set(ids.values()):
            if not name:
                raise ValueError("Compiler model is missing")
            resolve_model_config(kb.tenant_id, LLMType.CHAT, name)
        emb = get_model_config_by_id(kb.tenant_id, LLMType.EMBEDDING, kb.tenant_embd_id) if kb.tenant_embd_id else resolve_model_config(kb.tenant_id, LLMType.EMBEDDING, kb.embd_id)
        checks["models"] = bool(emb) and bool(ids)
        models = sorted(set(ids.values())) + [str(emb.get("llm_name") or kb.embd_id or "")]
    except (ValueError, LookupError):
        pass
    state = WikiGeneration.get_or_none(WikiGeneration.kb_id == kb.id)
    writable = KnowledgebaseService.writable(kb.id, user_id)
    supported = hasattr(settings.docStoreConn, "es")
    dimensions = []
    if supported:
        from common.wiki_generation import readable_index
        result = settings.docStoreConn.es.search(index=readable_index(kb.tenant_id, kb.id),
            query={"bool": {"filter": [{"term": {"kb_id": kb.id}}, {"term": {"compile_kwd": "wiki_page"}}]}},
            size=1, ignore_unavailable=True, source_includes=["q_*_vec"])
        for hit in result.get("hits", {}).get("hits", []):
            dimensions = sorted({len(v) for k, v in hit.get("_source", {}).items() if k.startswith("q_") and k.endswith("_vec") and isinstance(v, list)})
    return {
        "stored_dimensions": dimensions,
        "checks": checks, "parsed_files": len(parsed), "total_files": len(docs),
        "pipeline_id": kb.pipeline_id, "models": models,
        "can_manage_models": _can_manage_tenant(user_id, kb.tenant_id),
        "can_write": writable, "building": bool(state and state.building_token),
        "safe_generation": supported,
        "ready": all(checks.values()) and supported and writable and not (state and state.building_token),
        # A config check is not a provider availability probe or proof of equal vectors.
        "compatibility": "isolated_rebuild" if supported else "unsupported_store",
    }
