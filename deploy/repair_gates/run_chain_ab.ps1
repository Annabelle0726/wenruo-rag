# Sequential A/B chain acceptance: production arm (docker exec) then candidate arm
# (docker run of the one-file overlay image), so the two runs never contend for LLM
# rate limits or warm caches at the same time.
$ErrorActionPreference = 'Continue'
$repo = "C:\Projects\RAG\wenruo-rag"
Set-Location $repo

Write-Output "==================== PRODUCTION ARM ===================="
docker exec wenruo-rag-cpu sh -lc "rm -rf /tmp/chain && mkdir -p /tmp/chain"
docker cp deploy\repair_gates\agentic_chain_acceptance.py wenruo-rag-cpu:/tmp/chain.py
docker exec -e CHAIN_OUT=/tmp/chain -w /ragflow wenruo-rag-cpu python /tmp/chain.py > "$env:TEMP\chain_prod.txt" 2>&1
Write-Output "prod exit=$LASTEXITCODE"
Get-Content "$env:TEMP\chain_prod.txt" | Select-String -Pattern 'RERANK CHAIN|^assistant|^thinking_mode|^final_top_n|^query_is_exact|^elapsed_s|^patched|^B[0-9]|^     call|^rerank_chunks|^post_run_pool|^answer_markers|^answer_len|^answer_head|FAILED'
Remove-Item -Recurse -Force deploy\repair_gates\chain_out_prod -ErrorAction SilentlyContinue
docker cp wenruo-rag-cpu:/tmp/chain/. deploy\repair_gates\chain_out_prod
Write-Output "prod artifacts copied"

Write-Output "==================== CANDIDATE ARM ===================="
Remove-Item -Recurse -Force deploy\repair_gates\chain_out_cand -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path deploy\repair_gates\chain_out_cand | Out-Null
docker run --rm --name rr-chain-cand --network wenruo-rag_ragflow `
  --env-file deploy\repair_gates\chain_conf\prod.env `
  -v "$repo\deploy\repair_gates\chain_conf\service_conf.yaml:/ragflow/conf/service_conf.yaml:ro" `
  -v "$repo\deploy\repair_gates\agentic_chain_acceptance.py:/chain.py:ro" `
  -v "$repo\deploy\repair_gates\chain_out_cand:/out" `
  -w /ragflow --entrypoint python my-wenruorag:candidate-reservation-c7096920 /chain.py > "$env:TEMP\chain_cand.txt" 2>&1
Write-Output "cand exit=$LASTEXITCODE"
Get-Content "$env:TEMP\chain_cand.txt" | Select-String -Pattern 'RERANK CHAIN|^assistant|^thinking_mode|^final_top_n|^query_is_exact|^elapsed_s|^patched|^B[0-9]|^     call|^rerank_chunks|^post_run_pool|^answer_markers|^answer_len|^answer_head|FAILED|Error|Traceback'
Write-Output "==================== DONE ===================="
