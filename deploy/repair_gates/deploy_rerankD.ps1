# Phase 2: recreate wenruo-rag-cpu on Variant D via the documented compose chain, then
# wait for readiness. The chain's resolution was pre-verified to match the live container
# for env (141 = 130 compose + 12 image, zero drift), mounts, ports, restart, network, cmd.
$ErrorActionPreference = 'Continue'
Set-Location "C:\Projects\RAG\wenruo-rag\docker"

Write-Output "==== compose up -d (image pinned by release_rerankD_override.yml, listed LAST) ===="
docker compose -p wenruo-rag --profile cpu `
  -f docker-compose.yml `
  -f ../deploy/p0_baseline/p07_obs_override.yml `
  -f ../deploy/repair_baseline/repair_candidate_override.yml `
  -f ../deploy/release_nine_file_override.yml `
  -f ../deploy/release_fusion_override.yml `
  -f ../deploy/release_rerankD_override.yml `
  up -d wenruo-rag-cpu 2>&1 | Select-Object -Last 8
Write-Output "compose exit=$LASTEXITCODE"

Write-Output ""
Write-Output "==== readiness poll (status + ports + server log) ===="
$ready = $false
for ($i = 1; $i -le 40; $i++) {
  Start-Sleep -Seconds 10
  $st = docker inspect wenruo-rag-cpu --format '{{.State.Status}}' 2>$null
  $t80 = (Test-NetConnection -ComputerName 127.0.0.1 -Port 80 -InformationLevel Quiet -WarningAction SilentlyContinue)
  $t9380 = (Test-NetConnection -ComputerName 127.0.0.1 -Port 9380 -InformationLevel Quiet -WarningAction SilentlyContinue)
  $logs = docker logs --tail 400 wenruo-rag-cpu 2>&1 | Out-String
  $srv = if ($logs -match 'Running on http|Uvicorn running|RAGFlow is ready|Server started') { 'yes' } else { 'no' }
  Write-Output ("t+{0,3}s status={1} port80={2} port9380={3} server-log-ready={4}" -f ($i*10), $st, $t80, $t9380, $srv)
  if ($st -eq 'running' -and $t80 -and $t9380) { $ready = $true; break }
}
Write-Output "READY=$ready"
Write-Output ""
Write-Output "==== final container identity ===="
docker inspect wenruo-rag-cpu --format 'image={{.Image}} running={{.State.Running}} restarts={{.RestartCount}} health={{.State.Health.Status}} started={{.State.StartedAt}}'
docker exec wenruo-rag-cpu sha256sum /ragflow/rag/retrieval/rerank.py
docker images --no-trunc --format '{{.Repository}}:{{.Tag}} {{.ID}}' | Select-String -Pattern 'candidate-rerankD|rollback|latest'
