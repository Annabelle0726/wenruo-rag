#!/bin/sh
# Phase-4 remaining groups: the real closure chain, the numeric Rev-3.1 gate, and the corrected
# degradation differential invariant. Runs inside a disposable candidate container; pytest is supplied
# read-only from /td and the conftest control proves no image dependency is shadowed by it.
set -u

OUT=/out
mkdir -p "$OUT" /tmp/p4
cd /ragflow
export PYTHONPATH=/td

cp /gates/test_qv_revision31_gate.py /gates/test_degradation.py /tmp/p4/
cp /gates/conftest_phase4.py /tmp/p4/conftest.py
# The degradation gate loads the FROZEN production Dealer from /tmp/baseline_search.py; it ships in the
# harness's own fixtures directory, not at the harness root.
cp /fixtures/corpus.json /fixtures/sql-documents.json /tmp/
cp /gates/fixtures/baseline_search.py /tmp/baseline_search.py
ls -l /tmp/corpus.json /tmp/sql-documents.json /tmp/baseline_search.py

banner() { echo; echo "################ $1 ################"; }

banner "GROUP 3 - real Dealer.search -> Dealer.retrieval -> _body_text -> carries_value"
python /gates/phase4_final_closure.py >"$OUT/g_closure.log" 2>&1
echo "exit=$?"
grep -E '^VERDICT |^ABORTED_BY|^FIRST FAILING|^GROUP F PASSED' "$OUT/g_closure.log"

banner "GROUP 1b - numeric Rev-3.1 semantic guard (pytest)"
cd /tmp/p4
python -m pytest test_qv_revision31_gate.py -q -p no:cacheprovider \
  -o asyncio_mode=auto -o asyncio_default_fixture_loop_scope=function >"$OUT/g_qv31.log" 2>&1
echo "exit=$?"
grep -E '^\[control\]|passed|failed|error' "$OUT/g_qv31.log" | tail -12

banner "GROUP 9 - corrected degradation differential invariant (authorised _source quartet)"
python -m pytest test_degradation.py -q -p no:cacheprovider \
  -o asyncio_mode=auto -o asyncio_default_fixture_loop_scope=function \
  -k "healthy_semantic_differential or healthy_differential_is_not_vacuous" >"$OUT/g_differential.log" 2>&1
echo "exit=$?"
grep -E '^\[control\]|passed|failed|error' "$OUT/g_differential.log" | tail -12

banner "PHASE 4 REMAINING GROUPS COMPLETE"
