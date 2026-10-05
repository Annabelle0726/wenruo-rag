"""Isolated Wiki builds and a transactional publication pointer.

The source index is never renamed, cleared or restored. A build works on a
private snapshot. Only Wiki rows survive publication. Previous generations
are retained so in-flight readers can finish against their pinned index.
"""
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
import uuid
from functools import wraps


BUILD = ContextVar("wiki_build", default=None)


def claim(tenant_id, kb_id):
    from api.db.db_models import DB, WikiGeneration
    token = uuid.uuid4().hex
    with DB.connection_context(), DB.atomic():
        WikiGeneration.get_or_create(kb_id=kb_id, defaults={"tenant_id": tenant_id})
        row = WikiGeneration.select().where(WikiGeneration.kb_id == kb_id).for_update().get()
        if row.tenant_id != tenant_id or row.building_token:
            raise RuntimeError("知识成果正在处理，请稍后重试；旧版仍可阅读。 / Wiki is busy; previous results remain readable.")
        WikiGeneration.update(building_token=token).where(WikiGeneration.kb_id == kb_id).execute()
        return token, row.active_index or f"ragflow_{tenant_id}"


def release(kb_id, token):
    from api.db.db_models import DB, WikiGeneration
    with DB.connection_context():
        WikiGeneration.update(building_token="").where(
            WikiGeneration.kb_id == kb_id, WikiGeneration.building_token == token,
        ).execute()


def serialize_wiki_edit(function):
    """Manual edits/clears cannot race a build snapshot or publication."""
    @wraps(function)
    async def wrapped(dataset_id, tenant_id, *args, **kwargs):
        from api.db.services.knowledgebase_service import KnowledgebaseService
        from api.utils.api_utils import PermissionDeniedMessage
        if not KnowledgebaseService.writable(dataset_id, tenant_id):
            return False, PermissionDeniedMessage("no authorization")
        _, kb = KnowledgebaseService.get_by_id(dataset_id)
        try:
            token, _ = claim(kb.tenant_id, dataset_id)
        except RuntimeError as exc:
            return False, str(exc)
        try:
            return await function(dataset_id, tenant_id, *args, **kwargs)
        finally:
            release(dataset_id, token)
    return wrapped


def mark_failed():
    build = BUILD.get()
    if build:
        build.failed = True


def wiki_row(row):
    value = row.get("compile_kwd", "")
    return any(str(v).startswith("wiki_") for v in (value if isinstance(value, list) else [value]))


def scoped_index(tenant_id):
    build = BUILD.get()
    return build.index if build and build.tenant_id == tenant_id else f"ragflow_{tenant_id}"


def active_indexes(tenant_ids, kb_ids):
    from api.db.db_models import DB, WikiGeneration
    with DB.connection_context():
        return {r.kb_id: r.active_index for r in WikiGeneration.select().where(
            WikiGeneration.tenant_id.in_(tenant_ids), WikiGeneration.kb_id.in_(kb_ids),
            WikiGeneration.active_index != "",
        )}


def readable_index(tenant_id, kb_id):
    build = BUILD.get()
    if build and (build.tenant_id, build.kb_id) == (tenant_id, kb_id):
        return build.index
    return active_indexes([tenant_id], [kb_id]).get(kb_id, f"ragflow_{tenant_id}")


def read_plan(indexes, kb_ids, condition):
    """Include published Wiki generations, exclude superseded tenant Wiki rows.

    Source-only retrieval takes the original path without a publication lookup.
    Private build indexes are already pinned and never expanded.
    """
    if condition.get("must_not", {}).get("exists") == "compile_kwd":
        return indexes, []
    tenants = [i[len("ragflow_"):] for i in indexes if i.startswith("ragflow_")]
    if not tenants or not kb_ids:
        return indexes, []
    active = active_indexes(tenants, kb_ids)
    excluded = [{"bool": {"filter": [
        {"terms": {"_index": indexes}}, {"term": {"kb_id": kb}},
        {"prefix": {"compile_kwd": "wiki_"}},
    ]}} for kb in active]
    return list(dict.fromkeys([*indexes, *active.values()])), excluded


def _digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclass
class WikiBuild:
    tenant_id: str
    kb_id: str
    token: str
    index: str
    old_index: str
    old_digest: str
    failed: bool = False
    completed: bool = False
    source_digest: str = ""


class ESGenerationStore:
    def __init__(self, connection):
        self.conn = connection
        self.es = connection.es

    def rows(self, index, kb_id, wiki_only=False):
        from elasticsearch.helpers import scan
        query = {"bool": {"filter": [{"term": {"kb_id": kb_id}}]}}
        if wiki_only:
            query["bool"]["filter"].append({"prefix": {"compile_kwd": "wiki_"}})
        return {h["_id"]: h["_source"] for h in scan(self.es, index=index, query={"query": query})}

    def begin(self, tenant_id, kb_id):
        base = f"ragflow_{tenant_id}"
        token, old = claim(tenant_id, kb_id)
        build = WikiBuild(tenant_id, kb_id, token, f"wiki_build_{kb_id}_{token}", old, "")
        try:
            old_rows = self.rows(old, kb_id, wiki_only=True)
            build.old_digest = _digest(old_rows)
            source = {k: v for k, v in self.rows(base, kb_id).items() if not wiki_row(v)}
            build.source_digest = _digest({k: v for k, v in source.items() if not v.get("compile_kwd")})
            source.update(old_rows)
            # Preserve the actual vector mappings, including dimensions absent
            # from the repository's default dynamic templates.
            mapping = self.es.indices.get_mapping(index=base)[base]["mappings"]
            source_settings = self.es.indices.get_settings(index=base)[base]["settings"]["index"]
            clone_settings = {key: source_settings[key] for key in (
                "analysis", "similarity", "number_of_shards", "number_of_replicas", "max_result_window", "mapping"
            ) if key in source_settings}
            self.es.indices.create(index=build.index, mappings=mapping, settings=clone_settings)
            values = [dict(v, id=k) for k, v in source.items()]
            for offset in range(0, len(values), 200):
                errors = self.conn.insert(values[offset:offset + 200], build.index, kb_id)
                if errors:
                    raise RuntimeError("Wiki snapshot write failed")
            return build
        except BaseException:
            self.release(build)
            raise

    def validate(self, build):
        if build.failed or not build.completed:
            raise RuntimeError("Wiki generation did not complete")
        rows = self.rows(build.index, build.kb_id, wiki_only=True)
        pages = [r for r in rows.values() if r.get("compile_kwd") == "wiki_page"]
        if not pages or any(not (r.get("md_with_weight") or r.get("content_with_weight")) for r in pages):
            raise RuntimeError("Wiki generated pages failed validation")
        if _digest(self.rows(build.old_index, build.kb_id, wiki_only=True)) != build.old_digest:
            raise RuntimeError("Wiki changed during generation; publication refused")
        if build.source_digest:
            source = self.rows(f"ragflow_{build.tenant_id}", build.kb_id)
            if _digest({k: v for k, v in source.items() if not v.get("compile_kwd")}) != build.source_digest:
                raise RuntimeError("Source files changed during generation; retry required")
        return rows

    def publish(self, build):
        from api.db.db_models import DB, WikiGeneration
        from api.db.services.file_commit_service import FileCommitService
        from common.workspace_context import execution_user
        actor = execution_user.get()
        if actor:
            from api.db.services.knowledgebase_service import KnowledgebaseService
            if not KnowledgebaseService.writable(build.kb_id, actor, active_tenant_id=build.tenant_id):
                raise RuntimeError("Wiki publication permission was revoked")
        rows = self.validate(build)
        old = self.rows(build.old_index, build.kb_id, wiki_only=True)
        # Remove source snapshot before making this index visible to retrieval.
        deleted = self.es.delete_by_query(index=build.index, query={"bool": {"must_not": [
            {"prefix": {"compile_kwd": "wiki_"}},
        ]}}, refresh=True, conflicts="abort")
        if deleted.get("failures") or deleted.get("timed_out"):
            raise RuntimeError("Wiki snapshot cleanup incomplete")
        self.es.indices.refresh(index=build.index)
        with DB.connection_context(), DB.atomic():
            pointer = WikiGeneration.select().where(WikiGeneration.kb_id == build.kb_id).for_update().get()
            if pointer.building_token != build.token or (pointer.active_index or f"ragflow_{build.tenant_id}") != build.old_index:
                raise RuntimeError("Wiki publication ownership changed")
            # Histories and the publication pointer become visible together.
            for key, page in rows.items():
                if page.get("compile_kwd") != "wiki_page":
                    continue
                before = old.get(key, {})
                body = page.get("md_with_weight") or page.get("content_with_weight") or ""
                previous = before.get("md_with_weight") or before.get("content_with_weight") or ""
                if body == previous:
                    continue
                slug = page["slug_kwd"]
                kind = page.get("page_type_kwd", "entity")
                if not slug.startswith(f"{kind}/"):
                    slug = f"{kind}/{slug}"
                if not FileCommitService.record_page_edit(tenant_id=build.tenant_id, kb_id=build.kb_id,
                        page_type=kind, slug=slug, content_before=previous, content_after=body,
                        title="Regenerated by artifact compilation", strict=True):
                    raise RuntimeError("Wiki version history could not be saved")
            WikiGeneration.update(active_index=build.index, building_token="").where(
                WikiGeneration.kb_id == build.kb_id, WikiGeneration.building_token == build.token,
            ).execute()

    def release(self, build):
        release(build.kb_id, build.token)
        # Keep unsuccessful indexes private for diagnosis. Never delete a
        # generation here: a connection error can follow a committed publish.


async def generate_safely(ctx, run):
    from common import settings
    from common.misc_utils import thread_pool_exec
    if not hasattr(settings.docStoreConn, "es"):
        raise RuntimeError("Safe Wiki generation requires Elasticsearch; existing results are preserved.")
    store = ESGenerationStore(settings.docStoreConn)
    try:
        build = await thread_pool_exec(store.begin, ctx.tenant_id, ctx.kb_id)
    except Exception:
        import logging
        logging.exception("Wiki snapshot preparation failed")
        message = "无法准备安全生成环境，旧版成果已保留。 / Could not prepare safe generation; previous results are preserved."
        ctx.progress_cb(-1, message)
        raise RuntimeError(message) from None
    token = BUILD.set(build)
    original_progress = ctx._progress_cb
    def progress(prog=None, msg="", **kwargs):
        if prog is not None and prog < 0:
            build.failed = True
        if prog is not None and prog >= 1:
            build.completed = True
            prog = 0.98
        original_progress(prog, msg, **kwargs)
    ctx._progress_cb = progress
    try:
        await run()
        if ctx.callbacks.has_canceled(ctx.id):
            raise RuntimeError("Wiki generation was cancelled")
        BUILD.reset(token)
        token = None
        await thread_pool_exec(store.publish, build)
        original_progress(1.0, "Wiki generation completed; the new version is now available. / 知识成果生成完成，新版本已发布。")
    except BaseException as exc:
        import logging
        logging.exception("Wiki generation was not published: %s", type(exc).__name__)
        rate_limited = any(x in str(exc).lower() for x in ("429", "rate", "quota", "resource_exhausted"))
        failure_message = ("模型服务限流，请稍后重试。 / Model service rate limited. " if rate_limited else "生成未完成，请稍后重试。 / Generation incomplete. ") + "旧版成果已保留。 / Previous results are preserved."
        if "template" in str(exc).lower() or "pipeline" in str(exc).lower():
            failure_message = "编译模板或管道已失效，请检查配置；旧版成果已保留。 / Compiler template or pipeline is invalid; previous results are preserved."
        original_progress(-1, failure_message)
        raise RuntimeError(failure_message) from None
    finally:
        ctx._progress_cb = original_progress
        if token is not None:
            BUILD.reset(token)
        await thread_pool_exec(store.release, build)
