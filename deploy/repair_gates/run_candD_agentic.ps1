# Bound Agentic question + non-QGDW sanity query on BOTH images, throwaway containers.
$ErrorActionPreference = 'Continue'
$repo = "C:\Projects\RAG\wenruo-rag"
Set-Location $repo

$PROD = "my-wenruorag:candidate-fusionfix-2daccc2f"
$CAND = "my-wenruorag:candidate-rerankD-4498c2ed"
$SANITY_B64 = "MjIwa1Yg5LiJ6Iqv5rW357yG55qE5Li76KaB57uT5p6E5pyJ5ZOq5Lqb77yf"

New-Item -ItemType Directory -Force -Path deploy\repair_gates\candD_agentic | Out-Null

$base = @(
  "--network", "wenruo-rag_ragflow",
  "--env-file", "deploy\repair_gates\chain_conf\prod.env",
  "-v", "$repo\deploy\repair_gates\chain_conf\service_conf.yaml:/ragflow/conf/service_conf.yaml:ro",
  "-v", "$repo\deploy\repair_gates\abc_matrix_tmp.py:/tmp/abc_matrix.py:ro",
  "-v", "$repo\deploy\repair_gates\agentic_chain_acceptance.py:/tmp/agentic_chain_acceptance.py:ro",
  "-v", "$repo\deploy\repair_gates\candD_agentic:/out",
  "-w", "/ragflow"
)

foreach ($pair in @(@('PROD', $PROD, 'A'), @('CAND', $CAND, 'D'))) {
  $tag = $pair[0]; $img = $pair[1]; $var = $pair[2]
  Write-Output "==================== BOUND AGENTIC :: $tag (VARIANT=$var) ===================="
  docker run --rm @base -e "VARIANT=$var" -e ACC_OUT=/out --entrypoint python $img /tmp/abc_matrix.py 2>&1 |
    Select-String -Pattern '^=====|^validated|^STEP|^RESERVATION|^PROSE|^SCORE_FILL|^DOC/TABLE|^final window|^carriers in|^CARRIER|^carrier |^answer |^grounding|^MISMATCH|^FAILED'
  Write-Output ""
  Write-Output "==================== SANITY (non-QGDW) :: $tag ===================="
  docker run --rm @base -e "CHAIN_QUESTION_B64=$SANITY_B64" -e CHAIN_OUT=/out --entrypoint python $img /tmp/agentic_chain_acceptance.py 2>&1 |
    Select-String -Pattern '^===|^assistant |^thinking_mode|^query_is_exact|^elapsed_s|^B[1-8]_|^     call|^post_run_pool|^answer_markers|^answer_len|^CHAIN ACCEPTANCE FAILED'
  Write-Output ""
}
Write-Output "DONE"
