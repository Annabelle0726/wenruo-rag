# Candidate arm of the end-to-end chain acceptance, plus the single-pass differential
# replay (raw published question through hybrid_search) on BOTH images, which is the
# only configuration in which the compared-document reservation policy engages.
$ErrorActionPreference = 'Continue'
$repo = "C:\Projects\RAG\wenruo-rag"
Set-Location $repo

$img = "my-wenruorag:candidate-reservation-c7096920"
$common = @(
  "--network", "wenruo-rag_ragflow",
  "--env-file", "deploy\repair_gates\chain_conf\prod.env",
  "-v", "$repo\deploy\repair_gates\chain_conf\service_conf.yaml:/ragflow/conf/service_conf.yaml:ro",
  "-w", "/ragflow"
)

Write-Output "==================== CANDIDATE ARM (chain) ===================="
Remove-Item -Recurse -Force deploy\repair_gates\chain_out_cand -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path deploy\repair_gates\chain_out_cand | Out-Null
docker run --rm --name rr-chain-cand @common `
  -v "$repo\deploy\repair_gates\agentic_chain_acceptance.py:/chain.py:ro" `
  -v "$repo\deploy\repair_gates\chain_out_cand:/out" `
  --entrypoint python $img /chain.py > "$env:TEMP\chain_cand.txt" 2>&1
Write-Output "cand exit=$LASTEXITCODE"
Get-Content "$env:TEMP\chain_cand.txt" | Select-String -Pattern 'RERANK CHAIN|^assistant|^thinking_mode|^final_top_n|^query_is_exact|^elapsed_s|^patched|^search_calls|^B[0-9]|^     call|^rerank_chunks|^post_run_pool|^answer_markers|^answer_len|^answer_head|FAILED|Error|Traceback|UnicodeDecode'

Write-Output "==================== SINGLE-PASS DIFFERENTIAL ===================="
docker cp deploy\repair_gates\agentic_bound_replay.py wenruo-rag-cpu:/tmp/agentic_bound_replay.py
Write-Output "---- PASS-A: production (deployed fusionfix, rerank.py 1152c59a) ----"
docker exec -w /ragflow wenruo-rag-cpu python /tmp/agentic_bound_replay.py > "$env:TEMP\pass_prod.txt" 2>&1
Write-Output "prod pass exit=$LASTEXITCODE"
Get-Content "$env:TEMP\pass_prod.txt" | Select-String -Pattern 'published question|assistant |formalized query|^B[0-9]|^     call|^policy|^final allocation'

Write-Output "---- PASS-B: candidate (rerank.py c7096920) ----"
docker run --rm --name rr-pass-cand @common `
  -v "$repo\deploy\repair_gates\agentic_bound_replay.py:/pass.py:ro" `
  --entrypoint python $img /pass.py > "$env:TEMP\pass_cand.txt" 2>&1
Write-Output "cand pass exit=$LASTEXITCODE"
Get-Content "$env:TEMP\pass_cand.txt" | Select-String -Pattern 'published question|assistant |formalized query|^B[0-9]|^     call|^policy|^final allocation'
Write-Output "==================== DONE ===================="
