# Gates + retrieval regression for BOTH images, each in a throwaway container so the
# running production container is never touched.
$ErrorActionPreference = 'Continue'
$repo = "C:\Projects\RAG\wenruo-rag"
Set-Location $repo

$PROD = "my-wenruorag:candidate-fusionfix-2daccc2f"      # sha256:26a44ae5...
$CAND = "my-wenruorag:candidate-rerankD-4498c2ed"        # sha256:44a3e353...

New-Item -ItemType Directory -Force -Path deploy\repair_gates\candD_out | Out-Null

$base = @(
  "--network", "wenruo-rag_ragflow",
  "--env-file", "deploy\repair_gates\chain_conf\prod.env",
  "-v", "$repo\deploy\repair_gates\chain_conf\service_conf.yaml:/ragflow/conf/service_conf.yaml:ro",
  "-v", "$repo\deploy\repair_gates\test_reservation_budget_gate.py:/tmp/gates/test_reservation_budget_gate.py:ro",
  "-v", "$repo\deploy\repair_gates\test_qgdw_policy_repair_gate.py:/tmp/reg/test_qgdw_policy_repair_gate.py:ro",
  "-v", "$repo\test\unit_test\rag\retrieval:/tmp/reg/retrieval:ro",
  "-v", "$repo\deploy\repair_gates\phase4_pytestdeps:/tmp/pytestdeps:ro",
  "-v", "$repo\deploy\repair_gates\candD_out:/out",
  "-e", "PYTHONPATH=/tmp/pytestdeps:/tmp",
  "-w", "/ragflow"
)

foreach ($pair in @(@('PROD', $PROD), @('CAND', $CAND))) {
  $tag = $pair[0]; $img = $pair[1]
  Write-Output "==================== $tag :: $img ===================="
  Write-Output "---- contract gates ----"
  docker run --rm @base --entrypoint python $img -m pytest -p no:cacheprovider -q --no-header -c /dev/null `
    /tmp/gates/test_reservation_budget_gate.py 2>&1 |
    Select-String -Pattern '^FAILED|^ERROR|passed|failed'
  Write-Output "---- qgdw policy repair gate ----"
  docker run --rm @base --entrypoint python $img -m pytest -p no:cacheprovider -q --no-header -c /dev/null `
    /tmp/reg/test_qgdw_policy_repair_gate.py 2>&1 |
    Select-String -Pattern '^FAILED|^ERROR|passed|failed'
  Write-Output "---- retrieval regression (JUnit -> /out) ----"
  docker run --rm @base --entrypoint python $img -m pytest -p no:cacheprovider -q --no-header -c /dev/null `
    /tmp/reg --ignore=/tmp/reg/retrieval/test_retrieval_health.py --junitxml=/out/junit_$tag.xml 2>&1 |
    Select-Object -Last 1
  Write-Output ""
}
Get-ChildItem deploy\repair_gates\candD_out | Select-Object Name,Length | Format-Table -AutoSize
Write-Output "DONE"
