#!/bin/sh
# Phase-4 in-image acceptance runner.
#
# Runs INSIDE a disposable container created from the candidate image, using the candidate image's OWN
# python and product modules. Harness/test files and the isolated-datastore config are mounted read-only;
# the only thing ever installed is pytest, into /tmp — the image and its .venv are never modified.
#
# Groups are run in order and each writes a full log under /out. A group's failure never prevents the
# remaining groups from running, so the report can name every verdict rather than the first abort.
set -u

OUT=/out
mkdir -p "$OUT"
cd /ragflow

banner() { echo; echo "################ $1 ################"; }

banner "ENVIRONMENT"
python -V
echo "candidate image product modules come from /ragflow (verify below):"
python - <<'PY'
import pathlib, sys
sys.path.insert(0, "/ragflow")
from common import settings
settings.init_settings()
from rag.nlp import search, doc_context, retrieval_projection
from rag.retrieval import decomposition, health_bridge
for m in (search, doc_context, retrieval_projection, decomposition, health_bridge):
    print(f"  {m.__name__:38s} -> {pathlib.Path(m.__file__).resolve()}")
PY

banner "PYTEST INSTALL (container-only target, image untouched)"
python -m pip install --quiet --target /tmp/td pytest pytest-asyncio >"$OUT/pip.log" 2>&1
echo "pip exit=$?"
PYTHONPATH=/tmp/td python -c "import pytest, pytest_asyncio; print('pytest', pytest.__version__, '/ pytest_asyncio', pytest_asyncio.__version__)" 2>&1 | tail -2
export PYTHONPATH=/tmp/td

cp /fixtures/corpus.json /fixtures/sql-documents.json /tmp/ 2>/dev/null
cp /gates/fixtures/baseline_search.py /tmp/baseline_search.py
mkdir -p /tmp/p4
cp /gates/test_qv_revision31_gate.py /tmp/p4/
cp /gates/test_degradation.py /tmp/p4/
echo "fixtures staged: $(ls /tmp/corpus.json /tmp/sql-documents.json /tmp/baseline_search.py 2>/dev/null | tr '\n' ' ')"

banner "GROUPS 1 2 4 5 6 7 - in_image_acceptance (identity, A numeric, B metadata, C propagation, D false-empty, E P0)"
python /gates/in_image_acceptance.py >"$OUT/g_inimage.log" 2>&1
echo "exit=$?"
grep -E '^VERDICT |^ABORTED_BY|^FIRST FAILING|^ALL GROUPS PASSED|^total failures' "$OUT/g_inimage.log"

banner "GROUP 3 - real Dealer.search -> Dealer.retrieval -> _body_text -> carries_value"
python /gates/phase4_final_closure.py >"$OUT/g_closure.log" 2>&1
echo "exit=$?"
grep -E '^VERDICT |^ABORTED_BY|^FIRST FAILING|^GROUP F PASSED' "$OUT/g_closure.log"

banner "GROUPS 8 9 - quote-health matrix + serialization visibility (GREEN arm)"
QUOTE_HEALTH_ARM=green python /gates/quote_health_red_probe.py >"$OUT/g_quote.log" 2>&1
echo "exit=$?"
tail -3 "$OUT/g_quote.log"

banner "GROUP 1b - numeric Rev-3.1 gate (pytest)"
cd /tmp/p4
python -m pytest test_qv_revision31_gate.py -q -p no:cacheprovider \
  -o asyncio_mode=auto -o asyncio_default_fixture_loop_scope=function >"$OUT/g_qv31.log" 2>&1
echo "exit=$?"
tail -5 "$OUT/g_qv31.log"

banner "GROUP 9b - corrected degradation differential invariant (authorised _source quartet)"
python -m pytest test_degradation.py -q -p no:cacheprovider \
  -o asyncio_mode=auto -o asyncio_default_fixture_loop_scope=function \
  -k "healthy_semantic_differential or healthy_differential_is_not_vacuous" >"$OUT/g_differential.log" 2>&1
echo "exit=$?"
tail -8 "$OUT/g_differential.log"

banner "PHASE 4 COMPLETE"
