"""Generate login encryption keys on the customer's machine, once."""
import os
from pathlib import Path
import sys
from Cryptodome.PublicKey import RSA

root=Path('/delivery-state')
private=root/'login-private.pem';public=root/'login-public.pem'
if private.exists() != public.exists():
    raise RuntimeError('Incomplete local login key pair; refusing to replace keys')
if not private.exists():
    key=RSA.generate(2048)
    with private.open('xb') as f:f.write(key.export_key())
    private.chmod(0o600)
    with public.open('xb') as f:f.write(key.public_key().export_key())
if RSA.import_key(private.read_bytes()).public_key().export_key()!=public.read_bytes():
    raise RuntimeError('Local login key pair mismatch')
os.execv('/ragflow/entrypoint.sh',['/ragflow/entrypoint.sh',*sys.argv[1:]])
