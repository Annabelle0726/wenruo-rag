"""Whitelist export and resumable restore; run with the application's Python."""
import argparse
import base64
import collections
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import uuid

from policy import TABLES, ES_FIELDS, check_text, digest, sanitize, verify_package

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def connect():
    from common import settings
    settings.init_settings()
    from api.db.db_models import DB
    return DB, settings.docStoreConn.es, settings.STORAGE_IMPL

def query(db, sql, args=()):
    import pymysql
    with db.connection().cursor(pymysql.cursors.DictCursor) as cursor:
        cursor.execute(sql, args)
        return list(cursor.fetchall())

def select(db, table, key, ids):
    if table not in TABLES or key not in TABLES[table]:
        raise ValueError('Not in SQL contract')
    if not ids:
        return []
    fields = ','.join('`'+f+'`' for f in TABLES[table])
    return query(db, f'SELECT {fields} FROM `{table}` WHERE `{key}` IN (' + ','.join(['%s']*len(ids))+')', list(ids))

def export(args):
    from elasticsearch.helpers import scan
    from api.db.services.file2document_service import File2DocumentService
    db, es, storage = connect()
    out = Path(args.directory)
    out.mkdir(parents=True, exist_ok=False)
    target = uuid.uuid4().hex
    rows = {'tenant': select(db, 'tenant', 'id', [args.tenant])}
    rows['knowledgebase'] = [r for r in select(db, 'knowledgebase', 'tenant_id', [args.tenant]) if r['status']=='1']
    kids = [r['id'] for r in rows['knowledgebase']]
    rows['document'] = [r for r in select(db, 'document', 'kb_id', kids) if r['status']=='1']
    rows['dialog'] = select(db, 'dialog', 'id', args.assistant)
    if len(rows['dialog']) != len(args.assistant) or any(r['tenant_id'] != args.tenant for r in rows['dialog']):
        raise ValueError('Assistant selection does not belong to workspace')
    for r in rows['dialog']:
        if not set(json.loads(r['kb_ids'])).issubset(kids):
            raise ValueError('Assistant references an excluded dataset')
    for table in ('tenant_model_provider', 'tenant_llm', 'compilation_template_group', 'compilation_template', 'wiki_generation'):
        rows[table] = select(db, table, 'tenant_id', [args.tenant])
    providers = [r['id'] for r in rows['tenant_model_provider']]
    for table in ('tenant_model_instance', 'tenant_model'):
        rows[table] = select(db, table, 'provider_id', providers)
    # Never silently ship an unresolved pipeline or active Wiki publication.
    if any(r.get('pipeline_id') for r in rows['knowledgebase'] + rows['document']):
        raise ValueError('Pipeline reference needs an explicitly reviewed migration contract')
    if any(r.get('active_index') for r in rows['wiki_generation']):
        raise ValueError('Published Wiki requires separately verified source provenance')
    people = query(db, 'SELECT id,email,nickname,password,access_token FROM user')
    replacements = {args.tenant: target}
    secrets = []
    for p in people:
        replacements[p['id']] = target
        if p.get('email'): replacements[p['email']] = 'admin@wenruo.local'
        if p.get('nickname') and len(p['nickname']) > 2: replacements[p['nickname']] = 'Wenruo Administrator'
        secrets.extend(p[k] for k in ('password','access_token') if p.get(k))
    for table in ('tenant_llm','tenant_model_instance'):
        secrets.extend(r['api_key'] for r in query(db, f'SELECT api_key FROM {table}') if r.get('api_key'))
    secrets.extend(v for k,v in os.environ.items() if any(x in k.upper() for x in ('PASSWORD','SECRET','TOKEN','API_KEY')) and v)
    rows = sanitize(rows, replacements, secrets)
    rows['tenant'][0]['name'] = 'Wenruo Workspace'
    for row in rows['knowledgebase'] + rows['document'] + rows['dialog']:
        if 'created_by' in row: row['created_by'] = target
    for r in rows['tenant_model']:
        extra = json.loads(r.get('extra') or '{}')
        # Pricing and private endpoints do not belong in a credential-free seed.
        r['extra'] = json.dumps({k: extra[k] for k in ('max_tokens','max_model_len','dimension','dimensions','embedding_dimension','is_tools') if k in extra})
    objects = []; seen = set(); pdf_count = 0
    def copy_object(bucket, key, dest_bucket=None, dest_key=None, pdf=False):
        nonlocal pdf_count
        dest_bucket = dest_bucket or bucket; dest_key = dest_key or key
        pair = (dest_bucket, dest_key)
        if pair in seen: return
        data = storage.get(bucket, key)
        if not data: raise ValueError('Missing referenced object')
        check_text(data.decode('utf-8', errors='ignore'), secrets)
        if pdf:
            from pypdf import PdfReader
            if not data.startswith(b'%PDF-'): raise ValueError('Original is not PDF')
            document = PdfReader(io.BytesIO(data))
            if not document.pages: raise ValueError('Empty PDF')
            check_text('\n'.join(p.extract_text() or '' for p in document.pages), secrets)
            check_text(str(document.metadata), secrets)
            pdf_count += 1
        rel = 'objects/' + hashlib.sha256(data).hexdigest() + '.bin'
        (out/'objects').mkdir(exist_ok=True); (out/rel).write_bytes(data)
        objects.append(dict(bucket=dest_bucket,key=dest_key,path=rel,size=len(data),sha256=digest(out/rel)))
        seen.add(pair)
    # Reconstruct file-browser associations for precisely the selected documents.
    rows['file'] = [dict(id=target,parent_id=target,tenant_id=target,created_by=target,name='Wenruo Workspace',location='',size=0,type='folder',source_type='')]
    rows['file2document'] = []
    for d in rows['document']:
        bucket, key = File2DocumentService.get_storage_address(doc_id=d['id'])
        if d['type'] != 'pdf' and d.get('suffix','').lower() != 'pdf':
            raise ValueError('Unreviewed original file type')
        copy_object(bucket,key,d['kb_id'],d['location'],pdf=True)
        fid = uuid.uuid5(uuid.NAMESPACE_URL, target+':file:'+d['id']).hex
        rows['file'].append(dict(id=fid,parent_id=target,tenant_id=target,created_by=target,name=d['name'],location=d['location'],size=d['size'],type=d['type'],source_type='knowledgebase'))
        rows['file2document'].append(dict(id=uuid.uuid5(uuid.NAMESPACE_URL, target+':link:'+d['id']).hex,file_id=fid,document_id=d['id']))
    indices = {}; vector_count = 0; kinds = collections.Counter()
    for prefix in ('ragflow_', 'ragflow_doc_meta_'):
        source = prefix+args.tenant; dest = prefix+target
        if not es.indices.exists(index=source): raise ValueError('Source index missing')
        mapping = es.indices.get_mapping(index=source)[source]['mappings']
        # Removed-document tombstones are deliberately outside the live scope.
        mapping['properties'] = {k:v for k,v in mapping.get('properties',{}).items() if k in ES_FIELDS}
        options = es.indices.get_settings(index=source)[source]['settings']['index']
        options = {k:options[k] for k in ('analysis','similarity','number_of_shards') if k in options}
        options['number_of_replicas'] = 0
        if prefix=='ragflow_' and mapping['properties'].get('q_3072_vec',{}).get('dims') != 3072:
            raise ValueError('3072-dimension mapping missing')
        write(out/'es'/f'{dest}.schema.json', dict(mappings=mapping,settings=options))
        count = 0
        with (out/'es'/f'{dest}.jsonl').open('w',encoding='utf-8') as f:
            for hit in scan(es,index=source,query={'query':{'terms':{'kb_id':kids}}}):
                value=hit['_source']
                if value.get('deleted_doc_id'): continue
                if set(value)-ES_FIELDS: raise ValueError('Unreviewed ES fields: '+','.join(sorted(set(value)-ES_FIELDS)))
                value = sanitize(value,replacements,secrets)
                if 'q_3072_vec' in value:
                    if len(value['q_3072_vec']) != 3072: raise ValueError('Vector size mismatch')
                    vector_count += 1
                kinds[value.get('compile_kwd') or 'chunk'] += 1
                img = value.get('img_id')
                if img:
                    parts = img.split('-',1)
                    if len(parts)!=2 or parts[0] not in kids: raise ValueError('Image is outside dataset scope')
                    copy_object(*parts)
                f.write(json.dumps(dict(_id=hit['_id'],_source=value),ensure_ascii=False)+'\n'); count += 1
        indices[dest] = count
    write(out/'database.json',rows); write(out/'objects.json',objects)
    manifest = dict(format=2,status='verified-export',tenant=target,owner_email='admin@wenruo.local',
        tables={k:len(v) for k,v in rows.items()},indices=indices,objects=len(objects),pdf_count=pdf_count,
        vectors=vector_count,record_kinds=dict(kinds),wiki='NOT_MIGRATED: source production has no verified Wiki publication',
        files={p.relative_to(out).as_posix():digest(p) for p in out.rglob('*') if p.is_file()})
    write(out/'manifest.json',manifest); verify_package(out)
    print(json.dumps({k:v for k,v in manifest.items() if k!='files'},ensure_ascii=True))

def restore(args):
    from elasticsearch.helpers import bulk
    from werkzeug.security import generate_password_hash, check_password_hash
    db, es, storage = connect()
    out=Path(args.directory); manifest, rows=verify_package(out)
    tenant=manifest['tenant']; package_hash=digest(out/'manifest.json')
    password=sys.stdin.read().strip()
    if len(password)<16: raise ValueError('Administrator password must be generated locally')
    # SQL lock serializes restores even across two processes/containers.
    if query(db,"SELECT GET_LOCK('wenruo_delivery_restore',0) held")[0]['held'] != 1:
        raise ValueError('Another restore is running')
    db.execute_sql('CREATE TABLE IF NOT EXISTS delivery_restore (id VARCHAR(64) PRIMARY KEY, package_hash VARCHAR(64) NOT NULL, state VARCHAR(16) NOT NULL)')
    receipts=query(db,'SELECT id,package_hash,state FROM delivery_restore')
    if receipts and (len(receipts)!=1 or receipts[0]['package_hash']!=package_hash):
        raise ValueError('Target belongs to another package')
    if not receipts:
        for table in ('user','tenant','knowledgebase','document','dialog','conversation','api_token'):
            if query(db,f'SELECT COUNT(*) n FROM `{table}`')[0]['n']: raise ValueError('Target is not empty: '+table)
        if es.indices.exists(index='ragflow_*'): raise ValueError('Target has pre-existing data indices')
        if storage.conn.list_buckets(): raise ValueError('Target has pre-existing object buckets')
        db.execute_sql('INSERT INTO delivery_restore VALUES (%s,%s,%s)',(tenant,package_hash,'restoring'))
    from api.db import db_models as models
    existing=models.User.get_or_none(models.User.id==tenant)
    if existing and not check_password_hash(existing.password,base64.b64encode(password.encode()).decode()):
        raise ValueError('Password mismatch; existing password preserved')
    if receipts and receipts[0]['state']=='complete':
        if not existing: raise ValueError('Restore receipt exists without administrator')
        verify(args, connected=(db,es,storage))
        print('ALREADY_RESTORED: no data or password changed')
        return
    for name,count in manifest['indices'].items():
        schema=json.loads((out/'es'/f'{name}.schema.json').read_text())
        if not es.indices.exists(index=name): es.indices.create(index=name,body=schema)
        actual=es.indices.get_mapping(index=name)[name]['mappings']
        if actual != schema['mappings']: raise ValueError('Target mapping differs')
        def actions():
            for line in (out/'es'/f'{name}.jsonl').open(encoding='utf-8'):
                hit=json.loads(line); yield {'_index':name,**hit}
        bulk(es,actions(),chunk_size=30,request_timeout=120)
        es.indices.refresh(index=name)
        if es.count(index=name)['count']!=count: raise ValueError('Index count mismatch')
    for obj in json.loads((out/'objects.json').read_text()):
        data=(out/obj['path']).read_bytes()
        storage.put(obj['bucket'],obj['key'],data)
        if hashlib.sha256(storage.get(obj['bucket'],obj['key'])).hexdigest()!=obj['sha256']:
            raise ValueError('Object read-back failed')
    if not existing:
        model_map={m._meta.table_name:m for m in vars(models).values() if isinstance(m,type) and hasattr(m,'_meta')}
        with db.atomic():
            for table,records in rows.items():
                for row in records:
                    value=dict(row)
                    if table=='tenant_model_instance': value.update(api_key='',extra='{}')
                    if table=='tenant_llm': value.update(api_key='',api_base='',used_tokens=0)
                    for key,field in model_map[table]._meta.fields.items():
                        if key in value and field.__class__.__name__=='JSONField' and isinstance(value[key],str):
                            value[key]=json.loads(value[key])
                    model_map[table].create(**value)
            models.User.create(id=tenant,email='admin@wenruo.local',nickname='Wenruo Administrator',
                password=generate_password_hash(base64.b64encode(password.encode()).decode()),
                is_superuser=True,current_tenant_id=tenant,language='Chinese',login_channel='deployment-seed',status='1')
            models.UserTenant.create(id=uuid.uuid4().hex,user_id=tenant,tenant_id=tenant,role='owner',invited_by=tenant,status='1')
            db.execute_sql("UPDATE delivery_restore SET state='complete' WHERE id=%s",(tenant,))
    verify(args, connected=(db,es,storage))

def verify(args, connected=None):
    db,es,storage=connected or connect()
    out=Path(args.directory);manifest,rows=verify_package(out)
    tenant=manifest['tenant']
    users=query(db,'SELECT id,email,is_superuser,current_tenant_id FROM user')
    if len(users)!=1 or users[0]['id']!=tenant or users[0]['email']!='admin@wenruo.local' or not users[0]['is_superuser']:
        raise ValueError('Administrator isolation check failed')
    member=query(db,'SELECT user_id,tenant_id,role,status FROM user_tenant')
    if len(member)!=1 or member[0] != dict(user_id=tenant,tenant_id=tenant,role='owner',status='1'):
        raise ValueError('Owner membership check failed')
    for table in ('conversation','api_4_conversation','api_token','task','tenant_invite','tenant_langfuse'):
        if query(db,f'SELECT COUNT(*) n FROM `{table}`')[0]['n']: raise ValueError('Excluded rows present: '+table)
    for table in ('tenant_llm','tenant_model_instance'):
        if query(db,f"SELECT COUNT(*) n FROM `{table}` WHERE api_key IS NOT NULL AND api_key<>''")[0]['n']:
            raise ValueError('Provider credential present')
    for table,records in rows.items():
        if table=='compilation_template':
            count=query(db,'SELECT COUNT(*) n FROM compilation_template WHERE tenant_id=%s',(tenant,))[0]['n']
        else: count=query(db,f'SELECT COUNT(*) n FROM `{table}`')[0]['n']
        if count!=len(records): raise ValueError('SQL count mismatch: '+table)
    for name,count in manifest['indices'].items():
        if es.count(index=name)['count']!=count: raise ValueError('ES count mismatch')
        if name=='ragflow_'+tenant and es.indices.get_mapping(index=name)[name]['mappings']['properties']['q_3072_vec']['dims']!=3072:
            raise ValueError('Vector mapping mismatch')
    for obj in json.loads((out/'objects.json').read_text()):
        if hashlib.sha256(storage.get(obj['bucket'],obj['key'])).hexdigest()!=obj['sha256']: raise ValueError('Object mismatch')
    print('RESTORE_VERIFIED '+json.dumps({k:manifest[k] for k in ('tables','indices','objects','pdf_count','vectors','wiki')},ensure_ascii=True))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation',choices=['export','restore','verify']);p.add_argument('directory')
    p.add_argument('--tenant');p.add_argument('--assistant',action='append',default=[])
    a=p.parse_args();globals()[a.operation](a)
