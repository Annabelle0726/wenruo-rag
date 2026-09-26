#
#  Copyright 2024 The InfiniFlow Authors. All Rights Reserved.
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
from datetime import datetime

from peewee import JOIN, SQL, fn

from api.constants import DATASET_NAME_LIMIT
from api.db import TenantPermission, UserTenantRole
from api.db.db_models import DB, Document, Knowledgebase, KnowledgebaseAuthorization, User, UserCanvas, UserTenant
from api.db.joint_services.kb_authorization_service import MEMBER_ROLES, SUBJECT_DEPARTMENT, SUBJECT_USER, can_read_dataset, can_write_dataset
from api.db.joint_services.tenant_model_service import get_composite_model_name_by_ids
from api.db.services import duplicate_name
from api.db.services.common_service import CommonService
from api.db.services.user_service import TenantService
from api.utils.api_utils import get_parser_config, requested_tenant_id
from common.constants import StatusEnum
from common.misc_utils import get_uuid
from common.time_utils import current_timestamp, datetime_format


def _base_model_name(embd_id: str) -> str:
    """Return the base model name by stripping provider/instance suffix from an embd_id."""
    parts = embd_id.rsplit("@", 2)
    return parts[0]


def _active_workspace(user_id, active_tenant_id=None):
    """The workspace a dataset decision is made in for `user_id`.

    An explicitly supplied id wins, so a caller that already resolved the
    workspace keeps it. Otherwise the caller's active workspace is resolved with
    the ``X-Tenant-Id`` request header, exactly as ``@require_tenant_admin``
    does: API and SDK callers name their target workspace there, and a header
    naming a workspace the caller holds no membership on is ignored by the
    resolver rather than trusted.
    """
    if active_tenant_id:
        return active_tenant_id
    return TenantService.resolve_active_tenant_id(user_id, requested_tenant_id())


def _kb_embedding_base_name(kb, resolved_names) -> str:
    """Resolve a dataset's embedding reference to its base model name.

    ``tenant_embd_id`` — or ``embd_id`` itself when it stores a raw
    tenant_model id — is resolved through ``resolved_names`` (id to
    ``model@instance@provider``). An id that no longer resolves falls back to
    the composite base name when ``embd_id`` holds one, otherwise to the id
    itself so only exact matches group together.
    """
    embd_id = (kb.embd_id or "").strip()
    ref = (getattr(kb, "tenant_embd_id", None) or "").strip()
    if not ref and "@" not in embd_id:
        ref = embd_id
    if not ref:
        return _base_model_name(embd_id)
    composite = resolved_names.get(ref)
    if composite:
        return _base_model_name(composite)
    if embd_id and embd_id != ref:
        return _base_model_name(embd_id)
    return ref


def validate_dataset_embedding_models(kbs):
    """Validate that all given datasets use the same embedding model (or all use none).

    Embedding references are resolved through tenant_model first, so datasets
    storing a raw tenant_model id and datasets storing a legacy
    ``model@instance@provider`` composite compare equal when they point at the
    same model.

    Returns an error message string on failure, or ``None`` on success.
    """
    # Either all datasets have an embedding model, or none do. Mixing is not allowed.
    embd_ids = [kb.embd_id for kb in kbs if kb.embd_id]
    has_embd = len(embd_ids) > 0
    if has_embd and len(embd_ids) != len(kbs):
        return "Cannot search across datasets where some have embedding models and others do not."
    if has_embd:
        candidates = []
        for kb in kbs:
            if not kb.embd_id:
                continue
            ref = (getattr(kb, "tenant_embd_id", None) or "").strip()
            if not ref and "@" not in kb.embd_id:
                ref = kb.embd_id.strip()
            if ref:
                candidates.append(ref)
        try:
            resolved_names = get_composite_model_name_by_ids(candidates)
        except Exception:  # noqa: BLE001 - resolution is best-effort; unresolvable ids keep their raw value
            resolved_names = {}
        embd_nms = {_kb_embedding_base_name(kb, resolved_names) for kb in kbs if kb.embd_id}
        if len(embd_nms) > 1:
            return f"Datasets use different embedding models: {[kb.embd_id for kb in kbs]}"
    return None


class KnowledgebaseService(CommonService):
    """Service class for managing dataset operations.

    This class extends CommonService to provide specialized functionality for dataset
    management, including document parsing status tracking, access control, and configuration
    management. It handles operations such as listing, creating, updating, and deleting
    knowledge bases, as well as managing their associated documents and permissions.

    The class implements a comprehensive set of methods for:
    - Document parsing status verification
    - Knowledge base access control
    - Parser configuration management
    - Tenant-based dataset organization

    Attributes:
        model: The Knowledgebase model class for database operations.
    """

    model = Knowledgebase

    @classmethod
    def save(cls, **kwargs):
        from api.db.services.workspace_member_service import save_owned_asset

        return save_owned_asset(cls.model, kwargs)

    @classmethod
    def _readable_filter(cls, user_id, tenant_ids):
        """The SQL form of `can_read_dataset`, applied over a workspace scope.

        Every listing path builds its WHERE clause from this one expression, so
        the masking happens in SQL and never in the frontend: a dataset that
        fails here is absent from the result set, which is also what stops a
        dataset hidden from the list from being searched by a guessed id.

        `tenant_ids` is the workspace scope being listed -- the active workspace
        for the dataset page, or every joined workspace when answering "what may
        this user read at all" (the admin console). The scope only narrows the
        result: membership, management and grants are all decided against the
        dataset's own workspace, so a scope naming a workspace the caller never
        joined still yields nothing from it.

        Within the scope a dataset is readable when the caller manages its
        workspace, or is a member of it and the dataset is shared with it, or the
        caller created it, or a `custom` grant names the caller or their
        department. An empty scope, and any permission value this build does not
        know, read nothing.
        """
        if not user_id or not tenant_ids:
            return SQL("1 = 0")
        if isinstance(tenant_ids, str):
            tenant_ids = [tenant_ids]

        # A manager governs every dataset of the workspace it administers, read
        # per row so one query serves a scope of several workspaces. The
        # subqueries are wrapped in `fn.EXISTS`: `ModelSelect.exists()` would run
        # the query on the spot and return a bool, and its own alias context is
        # what makes the correlated reference resolve to the wrong table.
        manages_workspace = fn.EXISTS(
            UserTenant.select().where(
                (UserTenant.user_id == user_id)
                & (UserTenant.tenant_id == cls.model.tenant_id)
                & (UserTenant.role.in_([UserTenantRole.OWNER, UserTenantRole.ADMIN]))
                & (UserTenant.status == StatusEnum.VALID.value)
            )
        )

        # The caller's department in the dataset's own workspace. A missing
        # membership or an unplaced member yields NULL, and `= NULL` matches no
        # row, so a department grant never captures a member who was never
        # placed in a department.
        department_in_workspace = UserTenant.select(UserTenant.department_id).where(
            (UserTenant.user_id == user_id) & (UserTenant.tenant_id == cls.model.tenant_id) & (UserTenant.role.in_(MEMBER_ROLES)) & (UserTenant.status == StatusEnum.VALID.value)
        )

        # Membership on the dataset's own workspace. Requiring it instead of
        # trusting the caller's scope is what keeps this expression sufficient on
        # its own: a scope naming a workspace the caller never joined still reads
        # nothing out of it. A pending `invite` row is not a membership.
        member_of_workspace = fn.EXISTS(
            UserTenant.select().where(
                (UserTenant.user_id == user_id) & (UserTenant.tenant_id == cls.model.tenant_id) & (UserTenant.role.in_(MEMBER_ROLES)) & (UserTenant.status == StatusEnum.VALID.value)
            )
        )

        granted = fn.EXISTS(
            KnowledgebaseAuthorization.select().where(
                (KnowledgebaseAuthorization.kb_id == cls.model.id)
                & (
                    ((KnowledgebaseAuthorization.subject_type == SUBJECT_USER) & (KnowledgebaseAuthorization.subject_id == user_id))
                    | ((KnowledgebaseAuthorization.subject_type == SUBJECT_DEPARTMENT) & (KnowledgebaseAuthorization.subject_id == department_in_workspace))
                )
            )
        )

        return (
            cls.model.tenant_id.in_(list(tenant_ids))
            & (cls.model.status == StatusEnum.VALID.value)
            & (
                manages_workspace
                | ((cls.model.permission == TenantPermission.TEAM.value) & member_of_workspace)
                | (cls.model.created_by == user_id)
                | ((cls.model.permission == TenantPermission.CUSTOM.value) & granted)
            )
        )

    @classmethod
    @DB.connection_context()
    def writable(cls, kb_id, user_id, active_tenant_id=None):
        """Whether `user_id` may change one dataset.

        The write counterpart of `accessible`, and the gate every mutating path
        has to pass: upload, parse, re-parse, edit, delete, index and the
        artifact/collection writes. It answers to the creator and the managers of
        the owning workspace only -- a member granted `custom` read access may
        retrieve a dataset but must never be able to change it, which is why this
        never consults `permission`.
        """
        e, kb = cls.get_by_id(kb_id)
        if not e or kb.status != StatusEnum.VALID.value:
            return False
        return can_write_dataset(user_id, _active_workspace(user_id, active_tenant_id), kb)

    @classmethod
    @DB.connection_context()
    def is_parsed_done(cls, kb_id):
        # Check if all documents in the dataset have completed parsing
        #
        # Args:
        #     kb_id: Knowledge base ID
        #
        # Returns:
        #     If all documents are parsed successfully, returns (True, None)
        #     If any document is not fully parsed, returns (False, error_message)
        from api.db.services.document_service import DocumentService
        from common.constants import TaskStatus

        # Get dataset information
        kbs = cls.query(id=kb_id)
        if not kbs:
            return False, "Knowledge base not found"
        kb = kbs[0]

        # Get all documents in the dataset
        docs, _ = DocumentService.get_by_kb_id(kb_id, 1, 1000, "create_time", True, "", [], [])

        # Check parsing status of each document
        for doc in docs:
            # If document is being parsed, don't allow chat creation
            if doc["run"] == TaskStatus.RUNNING.value or doc["run"] == TaskStatus.CANCEL.value or doc["run"] == TaskStatus.FAIL.value:
                return False, f"Document '{doc['name']}' in dataset '{kb.name}' is still being parsed. Please wait until all documents are parsed before starting a chat."
            # If document is not yet parsed and has no chunks, don't allow chat creation
            if doc["run"] == TaskStatus.UNSTART.value and doc["chunk_num"] == 0:
                return False, f"Document '{doc['name']}' in dataset '{kb.name}' has not been parsed yet. Please parse all documents before starting a chat."

        return True, None

    @classmethod
    @DB.connection_context()
    def list_documents_by_ids(cls, kb_ids):
        # Get document IDs associated with given dataset IDs
        # Args:
        #     kb_ids: List of dataset IDs
        # Returns:
        #     List of document IDs
        doc_ids = cls.model.select(Document.id.alias("document_id")).join(Document, on=(cls.model.id == Document.kb_id)).where(cls.model.id.in_(kb_ids))
        doc_ids = list(doc_ids.dicts())
        doc_ids = [doc["document_id"] for doc in doc_ids]
        return doc_ids

    @classmethod
    @DB.connection_context()
    def get_all_kb_by_tenant_ids(cls, tenant_ids, user_id):
        # will get all permitted kb, be cautious.
        fields = [
            cls.model.name,
            cls.model.avatar,
            cls.model.language,
            cls.model.permission,
            cls.model.doc_num,
            cls.model.token_num,
            cls.model.chunk_num,
            cls.model.status,
            cls.model.create_date,
            cls.model.update_date,
        ]
        # find team kb, owned kb, managed kb and granted kb
        kbs = cls.model.select(*fields).where(cls._readable_filter(user_id, tenant_ids))
        # sort by create_time asc
        kbs = kbs.order_by(cls.model.create_time.asc())
        # maybe cause slow query by deep paginate, optimize later.
        offset, limit = 0, 50
        res = []
        while True:
            kb_batch = kbs.offset(offset).limit(limit)
            _temp = list(kb_batch.dicts())
            if not _temp:
                break
            res.extend(_temp)
            offset += limit
        return res

    @classmethod
    @DB.connection_context()
    def get_kb_ids(cls, tenant_id):
        # Get all dataset IDs for a tenant
        # Args:
        #     tenant_id: Tenant ID
        # Returns:
        #     List of dataset IDs
        fields = [
            cls.model.id,
        ]
        kbs = cls.model.select(*fields).where(cls.model.tenant_id == tenant_id)
        kb_ids = [kb.id for kb in kbs]
        return kb_ids

    @classmethod
    @DB.connection_context()
    def get_detail(cls, kb_id):
        # Get detailed information about a dataset
        # Args:
        #     kb_id: Knowledge base ID
        # Returns:
        #     Dictionary containing dataset details
        fields = [
            cls.model.id,
            cls.model.embd_id,
            cls.model.avatar,
            cls.model.name,
            cls.model.language,
            cls.model.description,
            cls.model.permission,
            cls.model.doc_num,
            cls.model.token_num,
            cls.model.chunk_num,
            cls.model.parser_id,
            cls.model.pipeline_id,
            UserCanvas.title.alias("pipeline_name"),
            UserCanvas.avatar.alias("pipeline_avatar"),
            cls.model.parser_config,
            cls.model.pagerank,
            cls.model.graphrag_task_id,
            cls.model.graphrag_task_finish_at,
            cls.model.raptor_task_id,
            cls.model.raptor_task_finish_at,
            cls.model.mindmap_task_id,
            cls.model.mindmap_task_finish_at,
            cls.model.wiki_task_id,
            cls.model.wiki_task_finish_at,
            cls.model.skill_task_id,
            cls.model.skill_task_finish_at,
            cls.model.structure_graph_task_id,
            cls.model.structure_graph_task_finish_at,
            cls.model.structure_mindmap_task_id,
            cls.model.structure_mindmap_task_finish_at,
            cls.model.timeline_task_id,
            cls.model.timeline_task_finish_at,
            cls.model.session_graph_task_id,
            cls.model.session_graph_task_finish_at,
            cls.model.session_essence_task_id,
            cls.model.session_essence_task_finish_at,
            cls.model.structure_task_id,
            cls.model.structure_task_finish_at,
            cls.model.create_time,
            cls.model.update_time,
        ]
        kbs = (
            cls.model.select(*fields)
            .join(UserCanvas, on=(cls.model.pipeline_id == UserCanvas.id), join_type=JOIN.LEFT_OUTER)
            .where((cls.model.id == kb_id), (cls.model.status == StatusEnum.VALID.value))
            .dicts()
        )
        if not kbs:
            return None
        return kbs[0]

    @classmethod
    @DB.connection_context()
    def update_parser_config(cls, id, config):
        # Update parser configuration for a dataset
        # Args:
        #     id: Knowledge base ID
        #     config: New parser configuration
        e, m = cls.get_by_id(id)
        if not e:
            raise LookupError(f"dataset({id}) not found.")

        def dfs_update(old, new):
            # Deep update of nested configuration
            for k, v in new.items():
                if k not in old:
                    old[k] = v
                    continue
                if isinstance(v, dict) and isinstance(old[k], dict):
                    dfs_update(old[k], v)
                elif isinstance(v, list) and isinstance(old[k], list):
                    old[k] = list(set(old[k] + v))
                else:
                    old[k] = v

        dfs_update(m.parser_config, config)
        cls.update_by_id(id, {"parser_config": m.parser_config})

    @classmethod
    @DB.connection_context()
    def delete_field_map(cls, id):
        e, m = cls.get_by_id(id)
        if not e:
            raise LookupError(f"dataset({id}) not found.")

        m.parser_config.pop("field_map", None)
        cls.update_by_id(id, {"parser_config": m.parser_config})

    @classmethod
    @DB.connection_context()
    def get_field_map(cls, ids):
        # Get field mappings for knowledge bases
        # Args:
        #     ids: List of dataset IDs
        # Returns:
        #     Dictionary of field mappings
        conf = {}
        for k in cls.get_by_ids(ids):
            if k.parser_config and "field_map" in k.parser_config:
                conf.update(k.parser_config["field_map"])
        return conf

    @classmethod
    @DB.connection_context()
    def get_by_name(cls, kb_name, tenant_id):
        # Get dataset by name and tenant ID
        # Args:
        #     kb_name: Knowledge base name
        #     tenant_id: Tenant ID
        # Returns:
        #     Tuple of (exists, knowledge_base)
        kb = cls.model.select().where((cls.model.name == kb_name) & (cls.model.tenant_id == tenant_id) & (cls.model.status == StatusEnum.VALID.value))
        if kb:
            return True, kb[0]
        return False, None

    @classmethod
    @DB.connection_context()
    def get_all_ids(cls):
        # Get all dataset IDs
        # Returns:
        #     List of all dataset IDs
        return [m["id"] for m in cls.model.select(cls.model.id).dicts()]

    @classmethod
    @DB.connection_context()
    def create_with_name(cls, *, name: str, tenant_id: str, parser_id: str | None = None, created_by: str | None = None, **kwargs):
        """Create a dataset (knowledgebase) by name with kb_app defaults.

        This encapsulates the creation logic used in kb_app.create so other callers
        (including RESTFul endpoints) can reuse the same behavior.

        `tenant_id` is the workspace that owns the dataset. `created_by` is the
        dataset's author, and it equals `tenant_id` only for an owner, whose
        tenant id IS their user id: a member creating a dataset in a workspace it
        joined must be recorded as the author by its own user id, otherwise the
        dataset is attributed to the workspace and the creator cannot read or
        edit it again.

        Every failure is reported as a plain string message so a route can wrap it
        in an error result; the caller answers `(False, message)`.

        Returns:
            (ok: bool, model_or_msg): On success, returns (True, Knowledgebase model instance);
                                      on failure, returns (False, error_message).
        """
        # Validate name
        if not isinstance(name, str):
            return False, "Dataset name must be string."
        dataset_name = name.strip()
        if dataset_name == "":
            return False, "dataset name can't be empty"
        if len(dataset_name.encode("utf-8")) > DATASET_NAME_LIMIT:
            return False, f"Dataset name length is {len(dataset_name)} which is large than {DATASET_NAME_LIMIT}"

        # Deduplicate name within tenant
        dataset_name = duplicate_name(
            cls.query,
            name=dataset_name,
            tenant_id=tenant_id,
            status=StatusEnum.VALID.value,
        )

        # Verify tenant exists
        ok, _t = TenantService.get_by_id(tenant_id)
        if not ok:
            return False, "Tenant not found."

        # Build payload. The explicit fields come last so the optional fields
        # carried by `**kwargs` (description, language, permission, avatar,
        # parser_config, ...) can never override the identity of the dataset.
        kb_id = get_uuid()
        payload = {
            **kwargs,
            "id": kb_id,
            "name": dataset_name,
            "tenant_id": tenant_id,
            "created_by": created_by or tenant_id,
            "parser_id": (parser_id or "naive"),
        }

        # Update parser_config (always override with validated default/merged config)
        payload["parser_config"] = get_parser_config(parser_id, kwargs.get("parser_config"))
        payload["parser_config"]["llm_id"] = _t.llm_id

        return True, payload

    @classmethod
    @DB.connection_context()
    def get_list(cls, user_id, active_tenant_id, page_number, items_per_page, orderby, desc, id, name, keywords, parser_id=None, ids=None):
        # Get list of knowledge bases with filtering and pagination
        # Args:
        #     user_id: Current user ID
        #     active_tenant_id: The workspace being listed; an empty value lists nothing
        #     page_number: Page number for pagination
        #     items_per_page: Number of items per page
        #     orderby: Field to order by
        #     desc: Boolean indicating descending order
        #     id: Optional ID filter
        #     name: Optional name filter
        #     keywords: Optional keywords filter
        #     parser_id: Optional parser ID filter
        # Returns:
        #     List of knowledge bases
        #     Total count of knowledge bases
        kbs = cls.model.select()
        if id:
            kbs = kbs.where(cls.model.id == id)
        if ids:
            kbs = kbs.where(cls.model.id.in_(ids))
        if name:
            kbs = kbs.where(cls.model.name == name)
        if keywords:
            kbs = kbs.where(fn.LOWER(cls.model.name).contains(keywords.lower()))
        if parser_id:
            kbs = kbs.where(cls.model.parser_id == parser_id)

        kbs = kbs.where(cls._readable_filter(user_id, active_tenant_id))

        if desc:
            kbs = kbs.order_by(cls.model.getter_by(orderby).desc())
        else:
            kbs = kbs.order_by(cls.model.getter_by(orderby).asc())

        total = kbs.count()
        kbs = kbs.paginate(page_number, items_per_page)

        return list(kbs.dicts()), total

    @classmethod
    @DB.connection_context()
    def get_accessible_ids(cls, user_id, active_tenant_id, ids):
        kbs = cls.model.select(cls.model.id).where(cls.model.id.in_(ids), cls._readable_filter(user_id, active_tenant_id))
        return {kb.id for kb in kbs}

    @classmethod
    @DB.connection_context()
    def get_owner_filter(cls, user_id, active_tenant_id):
        owners = (
            cls.model.select(
                cls.model.tenant_id.alias("id"),
                User.nickname.alias("label"),
                fn.COUNT(cls.model.id).alias("count"),
            )
            .join(User, on=(cls.model.tenant_id == User.id))
            .where(cls._readable_filter(user_id, active_tenant_id))
            .group_by(cls.model.tenant_id, User.nickname)
        )
        return list(owners.dicts())

    @classmethod
    @DB.connection_context()
    def accessible(cls, kb_id, user_id, active_tenant_id=None):
        """Whether `user_id` may read one dataset.

        The by-id counterpart of `_readable_filter`, and the gate every caller
        that resolves a dataset id has to pass: chunk retrieval, search, the bot
        API, assistant configuration. The workspace is resolved from the caller
        when the caller does not already know it, so the existing call sites keep
        working unchanged.
        """
        e, kb = cls.get_by_id(kb_id)
        if not e or kb.status != StatusEnum.VALID.value:
            return False
        return can_read_dataset(user_id, _active_workspace(user_id, active_tenant_id), kb)

    @classmethod
    @DB.connection_context()
    def get_kb_by_id(cls, kb_id, user_id):
        # Get dataset by ID and user ID
        # Args:
        #     kb_id: Knowledge base ID
        #     user_id: User ID
        # Returns:
        #     List containing dataset information
        e, kb = cls.get_by_id(kb_id)
        if not e or not cls.accessible(kb_id, user_id):
            return []
        return [kb.to_dict()]

    @classmethod
    @DB.connection_context()
    def get_kb_by_name(cls, kb_name, user_id):
        # Get dataset by name and user ID
        # Args:
        #     kb_name: Knowledge base name
        #     user_id: User ID
        # Returns:
        #     List containing dataset information
        kbs = cls.query(name=kb_name, status=StatusEnum.VALID.value)
        for kb in kbs:
            if cls.accessible(kb.id, user_id):
                return [kb.to_dict()]
        return []

    @classmethod
    @DB.connection_context()
    def atomic_increase_doc_num_by_id(cls, kb_id):
        data = {}
        data["update_time"] = current_timestamp()
        data["update_date"] = datetime_format(datetime.now())
        data["doc_num"] = cls.model.doc_num + 1
        num = cls.model.update(data).where(cls.model.id == kb_id).execute()
        return num

    @classmethod
    @DB.connection_context()
    def update_document_number_in_init(cls, kb_id, doc_num):
        """
        Only use this function when init system
        """
        ok, kb = cls.get_by_id(kb_id)
        if not ok:
            return
        kb.doc_num = doc_num

        dirty_fields = kb.dirty_fields
        if cls.model._meta.combined.get("update_time") in dirty_fields:
            dirty_fields.remove(cls.model._meta.combined["update_time"])

        if cls.model._meta.combined.get("update_date") in dirty_fields:
            dirty_fields.remove(cls.model._meta.combined["update_date"])

        try:
            kb.save(only=dirty_fields)
        except ValueError as e:
            if str(e) == "no data to save!":
                pass  # that's OK
            else:
                raise e

    @classmethod
    @DB.connection_context()
    def decrease_document_num_in_delete(cls, kb_id, doc_num_info: dict):
        kb_row = cls.model.get_by_id(kb_id)
        if not kb_row:
            raise RuntimeError(f"kb_id {kb_id} does not exist")
        update_dict = {
            "doc_num": kb_row.doc_num - doc_num_info["doc_num"],
            "chunk_num": kb_row.chunk_num - doc_num_info["chunk_num"],
            "token_num": kb_row.token_num - doc_num_info["token_num"],
            "update_time": current_timestamp(),
            "update_date": datetime_format(datetime.now()),
        }
        return cls.model.update(update_dict).where(cls.model.id == kb_id).execute()

    @classmethod
    @DB.connection_context()
    def get_null_tenant_embd_id_row(cls):
        fields = [cls.model.id, cls.model.tenant_id, cls.model.embd_id]
        objs = cls.model.select(*fields).where(cls.model.tenant_embd_id.is_null())
        return list(objs)
