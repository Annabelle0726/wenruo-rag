"""Scan release files without printing secret values. Never package the inputs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

PATTERNS = {
    'private-key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----'),
    'provider-token': re.compile(rb'\b(?:sk-[a-zA-Z0-9_-]{20,150}|AIza[a-zA-Z0-9_-]{30,80})\b'),
    'bearer': re.compile(rb'Bearer [a-zA-Z0-9_.-]{24,256}'),
}

def scan(root, known, reviewed):
    files=0;hits=[];exceptions=[]
    for directory,dirs,names in os.walk(root):
        dirs[:]=[d for d in dirs if d not in ('.git','node_modules','__pycache__')]
        for name in names:
            p=Path(directory)/name
            if p.is_symlink():raise ValueError('Unreviewed symlink: '+str(p))
            rel=p.relative_to(root).as_posix();data=p.read_bytes();files+=1
            findings=[]
            for kind,pattern in PATTERNS.items():
                if pattern.search(data):findings.append(kind)
            for value in known:
                if len(value)>=6 and value.encode() in data:findings.append('known-source-secret');break
            if findings:
                sha=hashlib.sha256(data).hexdigest()
                if rel in reviewed and reviewed[rel]['sha256']==sha and 'known-source-secret' not in findings:
                    exceptions.append({'path':rel,'reason':reviewed[rel]['reason']})
                else:hits.append({'path':rel,'kinds':findings})
    return dict(files_scanned=files,unresolved=hits,reviewed_examples=exceptions,known_secret_count=len(known))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory');p.add_argument('--known-secrets-file');p.add_argument('--reviewed');p.add_argument('--report')
    a=p.parse_args();known=json.loads(Path(a.known_secrets_file).read_text()) if a.known_secrets_file else []
    reviewed=json.loads(Path(a.reviewed).read_text()) if a.reviewed else {}
    report=scan(Path(a.directory).resolve(),known,reviewed)
    text=json.dumps(report,ensure_ascii=False,indent=2)
    if a.report:Path(a.report).write_text(text,encoding='utf-8')
    print(text);sys.exit(bool(report['unresolved']))
