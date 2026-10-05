"""Initialize once, isolate Compose, wait for the backend, then restore."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import time
import urllib.request

ROOT=Path(__file__).resolve().parent
PRIVATE=ROOT/'private'

def docker(*args, **kwargs):
    return subprocess.run(['docker',*args],check=True,capture_output=True,text=True,encoding='utf-8',**kwargs).stdout

def resources(project):
    return {kind:docker(kind,'ls','--filter','label=com.docker.compose.project='+project,'--format','{{.Name}}').split() for kind in ('volume','network')}

def initialize(args):
    if PRIVATE.exists():
        raise ValueError('Private state already exists; use start. Existing passwords are never reset.')
    if not re.fullmatch(r'wenruo-delivery-[a-z0-9-]+',args.project):
        raise ValueError('Use a unique wenruo-delivery-... project name')
    if any(resources(args.project).values()) or docker('ps','-a','--filter','label=com.docker.compose.project='+args.project,'-q').strip():
        raise ValueError('Existing project resources: refusing to generate different passwords')
    names=docker('volume','ls','--format','{{.Name}}').split()
    if any(n.startswith(args.project+'_') for n in names): raise ValueError('Existing volume prefix')
    with socket.socket() as s: s.bind(('0.0.0.0',args.port))
    from policy import verify_package
    verify_package(Path(args.package).resolve())
    image=json.loads(docker('image','inspect',args.image))[0]['Id']
    env=dict(DELIVERY_PROJECT=args.project,RAGFLOW_IMAGE=image,SOURCE_COMMIT=args.revision,
        DELIVERY_PACKAGE=Path(args.package).resolve().as_posix(),SVR_WEB_HTTP_PORT=str(args.port),
        MYSQL_DBNAME='rag_flow',MYSQL_USER='root',MYSQL_HOST='mysql',MYSQL_PORT='3306',
        MINIO_USER='wenruo',MINIO_HOST='minio',ES_USER='elastic',ES_HOST='es01',REDIS_HOST='redis',
        DOC_ENGINE='elasticsearch',DB_TYPE='mysql',API_PROXY_SCHEME='python',REGISTER_ENABLED='0',
        ENABLE_REGISTER='0',RAGFLOW_INIT_SUPERUSER='0',SHOW_CABLE_ONLY='true',USE_DOCLING='false',LANG='zh_CN.UTF-8')
    for k in ('MYSQL_PASSWORD','MINIO_PASSWORD','ELASTIC_PASSWORD','REDIS_PASSWORD','SECRET_KEY'):
        env[k]=secrets.token_hex(32)
    # Marker is bound to credentials, project, image and package. Never printed.
    env['DELIVERY_INSTANCE']=hashlib.sha256(json.dumps(env,sort_keys=True).encode()).hexdigest()
    PRIVATE.mkdir(mode=0o700)
    (PRIVATE/'runtime.env').write_text(''.join(k+'='+v+'\n' for k,v in env.items()),encoding='utf-8')
    (PRIVATE/'admin-password.txt').write_text(secrets.token_urlsafe(24)+'\n',encoding='utf-8')
    (PRIVATE/'identity.json').write_text(json.dumps(dict(env_sha256=hashlib.sha256((PRIVATE/'runtime.env').read_bytes()).hexdigest(),project=args.project,instance=env['DELIVERY_INSTANCE'])))
    if os.name=='nt':
        account=subprocess.run(['whoami'],capture_output=True,text=True,check=True).stdout.strip()
        subprocess.run(['icacls',str(PRIVATE),'/inheritance:r','/grant:r',account+':(OI)(CI)F','SYSTEM:(OI)(CI)F'],capture_output=True,check=True)
    else:
        for p in PRIVATE.iterdir():p.chmod(0o600)
    print('Initialized local credentials. Administrator password: delivery/private/admin-password.txt')

def start(args):
    identity=json.loads((PRIVATE/'identity.json').read_text())
    if hashlib.sha256((PRIVATE/'runtime.env').read_bytes()).hexdigest()!=identity['env_sha256']:
        raise ValueError('Runtime configuration changed; refusing possible password/volume mismatch')
    values=dict(line.split('=',1) for line in (PRIVATE/'runtime.env').read_text().splitlines())
    project=identity['project']
    for kind,names in resources(project).items():
        for name in names:
            labels=json.loads(docker(kind,'inspect',name))[0].get('Labels',{}) or {}
            if labels.get('org.wenruo.delivery.instance')!=identity['instance']:
                raise ValueError('Resource does not belong to this initialization: '+name)
    ids=docker('ps','-a','--filter','label=com.docker.compose.project='+project,'-q').split()
    for cid in ids:
        c=json.loads(docker('inspect',cid))[0]
        if c['Config']['Labels'].get('org.wenruo.delivery.instance')!=identity['instance']:
            raise ValueError('Foreign container in project')
    command=['docker','compose','--project-name',project,'--env-file',str(PRIVATE/'runtime.env'),'-f',str(ROOT/'compose.yaml'),'--profile','cpu']
    clean_env={k:v for k,v in os.environ.items() if k not in values and not k.startswith('COMPOSE_')}
    subprocess.run(command+['config','--quiet'],env=clean_env,check=True)
    subprocess.run(command+['up','-d'],env=clean_env,check=True)
    base='http://127.0.0.1:'+values['SVR_WEB_HTTP_PORT']
    deadline=time.monotonic()+args.timeout
    while True:
        try:
            with urllib.request.urlopen(base+'/api/v1/system/version',timeout=5) as response:
                result=json.load(response)
                if result.get('code')==0 and result.get('data'):break
        except (OSError,ValueError):pass
        if time.monotonic()>deadline:raise TimeoutError('Backend readiness failed; restore was not attempted')
        time.sleep(2)
    password=(PRIVATE/'admin-password.txt').read_text().strip()
    subprocess.run(command+['exec','-T','wenruo-rag-cpu','python','/ragflow/delivery/transfer.py','restore','/delivery-package'],env=clean_env,input=password,text=True,check=True)
    print('Backend and restored data verified. '+base+'/login')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='operation',required=True)
    init=sub.add_parser('init');init.add_argument('--project',required=True);init.add_argument('--image',required=True)
    init.add_argument('--revision',required=True);init.add_argument('--package',required=True);init.add_argument('--port',type=int,default=9222)
    run=sub.add_parser('start');run.add_argument('--timeout',type=int,default=600)
    a=p.parse_args()
    try: initialize(a) if a.operation=='init' else start(a)
    except Exception as exc:
        # subprocess command/env and provider exceptions may contain credentials.
        if isinstance(exc,(ValueError,TimeoutError,FileNotFoundError)):p.exit(1,str(exc)+'\n')
        p.exit(1,type(exc).__name__+': operation failed; inspect private local logs.\n')
