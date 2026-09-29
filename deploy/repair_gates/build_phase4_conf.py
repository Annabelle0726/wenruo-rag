"""Build the Phase-4 datastore-isolation config: the candidate image's own service_conf.yaml
with ONLY the ES and Redis endpoints redirected to the disposable repair services.

Test configuration only. No product module is modified, and the pristine image keeps its
own shipped config; this file is bind-mounted read-only for acceptance runs.
"""
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / "phase4_service_conf_base.yaml"
DST = HERE / "phase4_service_conf.yaml"

SUBS = [
    (b"hosts: 'http://127.0.0.1:1200'", b"hosts: 'http://repair-es:9200'"),
    (b"host: 'localhost:6379'", b"host: 'redis:6379'"),
]

data = SRC.read_bytes()
for old, new in SUBS:
    count = data.count(old)
    assert count == 1, f"expected exactly one {old!r}, found {count}"
    data = data.replace(old, new)
DST.write_bytes(data)

lines = data.split(b"\r\n")
print("written bytes:", len(data))
for line in lines:
    if b"repair-es" in line or b"redis:6379" in line:
        print("  patched:", line.decode())
assert b"127.0.0.1:1200" not in data, "ES endpoint still points at the image default"
assert b"localhost:6379" not in data, "Redis endpoint still points at the image default"
print("ISOLATION_CONFIG_OK")
