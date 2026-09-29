#!/bin/sh
echo "--- python ---"
python -V
echo "--- pytest ---"
python -m pytest --version 2>&1 | head -3
echo "--- pytest_asyncio ---"
python -c "import pytest_asyncio; print('pytest_asyncio', pytest_asyncio.__version__)" 2>&1 | tail -2
echo "--- mapping.json ---"
ls -la /ragflow/conf/mapping.json 2>&1
echo "--- service_conf es host ---"
sed -n '1,4p' /ragflow/conf/service_conf.yaml
echo "--- ninth file parse + marker ---"
python - <<'PY'
import ast
p = "/ragflow/api/db/services/dialog_service.py"
src = open(p, encoding="utf-8").read()
ast.parse(src)
print("ast_parse=OK")
print("generic_fallback_present=", "generic_fallback" in src)
print("quote_health_repair_present=", 'refs = {"retrieval_health": deepcopy(kbinfos["retrieval_health"])}' in src)
PY
echo "--- newline style of ninth file ---"
python -c "d=open('/ragflow/api/db/services/dialog_service.py','rb').read(); print('CRLF' if b'\r\n' in d else 'LF', 'bytes=', len(d))"
