#!/bin/sh
echo "--- which pythons ---"
which -a python python3 2>&1
ls -d /usr/bin/python* /usr/local/bin/python* 2>&1
echo "--- site-packages pytest-ish ---"
ls /ragflow/.venv/lib/python3.13/site-packages 2>/dev/null | grep -i -E 'pytest|_pytest|pluggy|iniconfig' || echo "none in .venv"
echo "--- any pytest binary anywhere ---"
find / -xdev -name "pytest*" -maxdepth 6 2>/dev/null | head -20
echo "--- pip present? ---"
python -m pip --version 2>&1 | tail -2
echo "--- network egress test (pypi) ---"
timeout 20 python -c "
import socket
try:
    socket.create_connection(('pypi.org',443),timeout=8); print('PYPI_REACHABLE=YES')
except Exception as e:
    print('PYPI_REACHABLE=NO', type(e).__name__, e)
" 2>&1 | tail -3
