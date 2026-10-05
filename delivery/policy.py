"""Versioned delivery contract. Fields not listed here cannot enter a package."""
import hashlib
import json
import re
from pathlib import Path

TABLES = {k: v.split() for k, v in {
    'tenant': 'id name llm_id tenant_llm_id embd_id tenant_embd_id asr_id tenant_asr_id img2txt_id tenant_img2txt_id rerank_id tenant_rerank_id tts_id tenant_tts_id ocr_id tenant_ocr_id parser_ids status',
    'knowledgebase': 'id tenant_id name language description category embd_id tenant_embd_id permission created_by doc_num token_num chunk_num similarity_threshold vector_similarity_weight parser_id pipeline_id parser_config pagerank status',
    'document': 'id kb_id parser_id pipeline_id parser_config source_type type created_by name location size token_num chunk_num progress suffix content_hash run status thumbnail',
    'dialog': 'id tenant_id created_by name description language llm_id tenant_llm_id llm_setting prompt_type prompt_config meta_data_filter similarity_threshold vector_similarity_weight top_n rerank_candidates_count top_k do_refer rerank_id tenant_rerank_id kb_ids status',
    'tenant_model_provider': 'id provider_name tenant_id',
    'tenant_model_instance': 'id instance_name provider_id status',
    'tenant_model': 'id model_name provider_id instance_id model_type status extra',
    'tenant_llm': 'tenant_id llm_factory model_type llm_name max_tokens status',
    'compilation_template_group': 'id tenant_id name description scope status',
    'compilation_template': 'id tenant_id group_id name description kind config is_builtin status',
    'wiki_generation': 'kb_id tenant_id active_index',
    'user_canvas': 'id tenant_id user_id title permission release description canvas_type canvas_category tags dsl',
    'file': 'id parent_id tenant_id created_by name location size type source_type',
    'file2document': 'id file_id document_id',
}.items()}
ES_FIELDS = set('available_int compile_kwd content_ltks content_prefix_chars_int content_prefix_hash_kwd content_prefix_kind_kwd content_prefix_version_int content_sm_ltks content_with_weight create_time create_timestamp_flt doc_id doc_type_kwd docnm_kwd id img_id kb_id knowledge_graph_kwd lat_lon page_num_int position_int q_3072_vec title_sm_tks title_tks top_int meta_fields'.split())
WIKI_FIELDS = ES_FIELDS | set('aliases chunk_hash_kwd claims embedding_model_kwd entity_kwd entity_names entity_names_kwd entity_type_kwd from_kwd map_checksum md_with_weight mention_count_int mode_kwd outlinks_int outlinks_kwd page_ids page_type_kwd page_version_int q_1024_vec related_kb_pages_kwd slug_kwd source_chunk_hashes source_chunk_ids source_doc_ids summary_with_weight synthesis_version_int title_kwd to_kwd topic_kwd type_kwd weight_int'.split())
SENSITIVE_KEY = re.compile(r'(api.?key|password|passwd|secret|credential|authorization|access.?token|refresh.?token|private.?key|cookie)', re.I)
TOKEN = re.compile(r'(?:sk-[A-Za-z0-9_-]{16,}|AIza[A-Za-z0-9_-]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|Bearer\s+[A-Za-z0-9_.-]{16,}|https?://[^\s/:]+:[^\s/@]+@)')

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def check_text(text, secrets=()):
    if TOKEN.search(text) or any(len(s) >= 6 and s in text for s in secrets if isinstance(s, str)):
        raise ValueError('Sensitive value detected; content withheld')

def sanitize(value, replacements, secrets):
    if isinstance(value, dict):
        return {k: ('' if SENSITIVE_KEY.search(k) else sanitize(v, replacements, secrets)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v, replacements, secrets) for v in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            return json.dumps(sanitize(parsed, replacements, secrets), ensure_ascii=False)
        for old, new in replacements.items():
            value = value.replace(old, new)
        # Free text is not silently edited: a prompt containing a secret blocks export.
        check_text(value, secrets)
    return value

def safe_path(root, name):
    p = (root / name).resolve()
    if not p.is_relative_to(root.resolve()) or p == root.resolve():
        raise ValueError('Package path escapes its root')
    return p

def verify_package(root):
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 2 or manifest.get('status') != 'verified-export':
        raise ValueError('Unsupported or incomplete package')
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()} - {'manifest.json'}
    if actual != set(manifest['files']):
        raise ValueError('Unexpected or missing package files')
    for name, sha in manifest['files'].items():
        if digest(safe_path(root, name)) != sha:
            raise ValueError('Package checksum mismatch: ' + name)
    rows = json.loads((root / 'database.json').read_text(encoding='utf-8'))
    if set(rows) - set(TABLES):
        raise ValueError('Forbidden table')
    for table, records in rows.items():
        if len(records) != manifest['tables'][table]:
            raise ValueError('Row count mismatch')
        for row in records:
            if set(row) - set(TABLES[table]):
                raise ValueError('Forbidden field: ' + table)
            check_text(json.dumps(row, ensure_ascii=False))
    tenant=manifest['tenant']
    if len(rows.get('tenant',[]))!=1 or rows['tenant'][0]['id']!=tenant:
        raise ValueError('Workspace identity mismatch')
    for records in rows.values():
        for row in records:
            for key in ('tenant_id','created_by','user_id'):
                if key in row and row[key]!=tenant:raise ValueError('Foreign ownership in package')
    kids={r['id'] for r in rows.get('knowledgebase',[])}
    docs={r['id'] for r in rows.get('document',[])}
    for row in rows.get('document',[])+rows.get('wiki_generation',[]):
        if row['kb_id'] not in kids:raise ValueError('Dangling dataset reference')
    for row in rows.get('dialog',[]):
        ids=json.loads(row['kb_ids']) if isinstance(row['kb_ids'],str) else row['kb_ids']
        if not set(ids).issubset(kids):raise ValueError('Dangling assistant binding')
    for row in rows.get('file2document',[]):
        if row['document_id'] not in docs:raise ValueError('Dangling file binding')
    return manifest, rows
