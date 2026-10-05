"""Add an audited published Wiki from a read-only snapshot to a base export.

Must run only against the isolated COPY of the source volumes. No source writes.
The original base package remains untouched; the output is a separate package.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import shutil
import uuid
import yaml
import pymysql
from elasticsearch import Elasticsearch
from elasticsearch.helpers import scan
from policy import WIKI_FIELDS, sanitize, verify_package, digest
from transfer import write, TABLES

def query(db, sql, args=()):
    with db.cursor() as c:
        c.execute(sql,args)
        return list(c.fetchall())

def read(db,table,key,ids):
    fields=','.join('`'+k+'`' for k in TABLES[table])
    return query(db,f'SELECT {fields} FROM `{table}` WHERE `{key}` IN ('+','.join(['%s']*len(ids))+')',ids)

def main(a):
    base=Path(a.base);manifest,rows=verify_package(base)
    cfg=yaml.safe_load(Path(a.config).read_text());m=cfg['mysql'];e=cfg['es']
    db=pymysql.connect(host='mysql',user=m['user'],password=m['password'],database=m['name'],cursorclass=pymysql.cursors.DictCursor)
    es=Elasticsearch('http://es:9200',basic_auth=(e['username'],e['password']))
    tenant=manifest['tenant'];kids={r['id'] for r in rows['knowledgebase']}
    production={}
    for line in (base/'es'/f'ragflow_{tenant}.jsonl').open(encoding='utf-8'):
        h=json.loads(line);production[h['_id']]=h['_source']
    gens=read(db,'wiki_generation','kb_id',list(kids))
    gens=[g for g in gens if g.get('active_index')]
    if len(gens)!=1:raise ValueError('Expected exactly the reviewed published Wiki')
    generation=gens[0];kid=generation['kb_id'];source_tenant=generation['tenant_id']
    source_index=generation['active_index']
    # Verify the published generation's source chunk bodies match production.
    preview='ragflow_'+a.preview_tenant
    source_chunks={h['_id']:h['_source'] for h in scan(es,index=preview,query={'query':{'bool':{'filter':[{'term':{'kb_id':kid}}],'must_not':[{'exists':{'field':'compile_kwd'}}]}}})}
    if len(source_chunks)!=314:raise ValueError('Reviewed source chunk set changed')
    if any(k not in production or v.get('content_with_weight')!=production[k].get('content_with_weight') for k,v in source_chunks.items()):
        raise ValueError('Wiki source chunks differ from current production')
    source_docs={v['doc_id'] for v in source_chunks.values()}
    if not source_docs.issubset({r['id'] for r in rows['document'] if r['kb_id']==kid}):raise ValueError('Wiki source document outside selected scope')
    people=query(db,'SELECT id,email,nickname,password,access_token FROM user')
    replacements={source_tenant:tenant,a.preview_tenant:tenant};secrets=[m['password'],e['password']]
    for p in people:
        replacements[p['id']]=tenant
        for k in ('email','nickname'):
            if p.get(k) and len(p[k])>2:replacements[p[k]]='admin@wenruo.local' if k=='email' else 'Wenruo Administrator'
        secrets.extend(p[k] for k in ('password','access_token') if p.get(k))
    for table in ('tenant_model_instance','tenant_llm'):
        secrets.extend(r['api_key'] for r in query(db,f'SELECT api_key FROM {table}') if r.get('api_key'))
    kbs=read(db,'knowledgebase','id',[kid]);pipeline=kbs[0]['pipeline_id']
    canvases=read(db,'user_canvas','id',[pipeline])
    if len(canvases)!=1 or canvases[0]['tenant_id']!=source_tenant:raise ValueError('Pipeline scope mismatch')
    dsl=json.loads(canvases[0]['dsl']);params=dsl['components']['compiler_0']['obj']['params']
    groups=read(db,'compilation_template_group','id',params['compilation_template_group_id'])
    templates=read(db,'compilation_template','group_id',[g['id'] for g in groups])
    if len(groups)!=1 or len(templates)!=1 or any(r['tenant_id']!=source_tenant for r in groups+templates):raise ValueError('Template scope mismatch')
    providers={r['id']:r['provider_name'] for r in rows['tenant_model_provider']}
    instances={r['id']:r['instance_name'] for r in rows['tenant_model_instance']}
    names={r['model_name']+'@'+instances[r['instance_id']]+'@'+providers[r['provider_id']] for r in rows['tenant_model']}
    if params['llm_id'] not in names:raise ValueError('Compiler model not in target model metadata')
    output=Path(a.output);shutil.copytree(base,output)
    (output/'manifest.json').unlink()
    target_index='wiki_build_'+kid+'_'+uuid.uuid4().hex
    replacements[source_index]=target_index
    schema=es.indices.get_mapping(index=source_index)[source_index]['mappings']
    # Mapping inherited an unused tombstone field from the source chunk index.
    schema.get('properties',{}).pop('deleted_doc_id',None)
    if set(schema.get('properties',{}))-WIKI_FIELDS:raise ValueError('Unreviewed Wiki mapping fields: '+','.join(sorted(set(schema.get('properties',{}))-WIKI_FIELDS)))
    write(output/'es'/f'{target_index}.schema.json',{'mappings':schema,'settings':{'number_of_shards':1,'number_of_replicas':0}})
    kinds=collections.Counter();pages=set();refs=set();vector_dims=collections.Counter()
    with (output/'es'/f'{target_index}.jsonl').open('w',encoding='utf-8') as f:
        for h in scan(es,index=source_index):
            s=h['_source']
            if s.get('kb_id')!=kid or set(s)-WIKI_FIELDS:raise ValueError('Wiki record outside whitelist')
            kind=s.get('compile_kwd');kinds[kind]+=1
            for dim in (1024,3072):
                if f'q_{dim}_vec' in s:
                    if len(s[f'q_{dim}_vec'])!=dim:raise ValueError('Wiki vector dimension mismatch')
                    vector_dims[str(dim)]+=1
            if kind=='wiki_page':
                if not (s.get('content_with_weight') or s.get('md_with_weight')):raise ValueError('Empty Wiki page')
                slug=s.get('slug_kwd')
                if not slug or slug in pages:raise ValueError('Missing/duplicate Wiki slug')
                pages.add(slug)
            ids=s.get('source_doc_ids',[])
            if isinstance(ids,str):ids=json.loads(ids)
            refs.update(ids)
            f.write(json.dumps({'_id':h['_id'],'_source':sanitize(s,replacements,secrets)},ensure_ascii=False)+'\n')
    if refs!=source_docs or len(pages)!=579:raise ValueError('Wiki source coverage/page count changed')
    rows['wiki_generation']=sanitize(gens,replacements,secrets)
    rows['user_canvas']=sanitize(canvases,replacements,secrets)
    rows['compilation_template_group']=sanitize(groups,replacements,secrets)
    rows['compilation_template']=sanitize(templates,replacements,secrets)
    # Keep production parsing bindings; store the verified Wiki pipeline as an
    # owned configuration without changing the next parse of production PDFs.
    write(output/'database.json',rows)
    manifest['wiki']=dict(status='verified-existing-publication',pages=len(pages),records=sum(kinds.values()),record_kinds=dict(kinds),source_documents=len(source_docs),source_chunks_verified=len(source_chunks),vector_dimensions=dict(vector_dims),pipeline_id=pipeline,template_groups=len(groups),templates=len(templates))
    manifest['indices'][target_index]=sum(kinds.values())
    manifest['tables']={k:len(v) for k,v in rows.items()}
    manifest['files']={p.relative_to(output).as_posix():digest(p) for p in output.rglob('*') if p.is_file()}
    write(output/'manifest.json',manifest);verify_package(output)
    print(json.dumps(manifest['wiki']))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',required=True);p.add_argument('--output',required=True);p.add_argument('--config',required=True);p.add_argument('--preview-tenant',required=True)
    main(p.parse_args())
