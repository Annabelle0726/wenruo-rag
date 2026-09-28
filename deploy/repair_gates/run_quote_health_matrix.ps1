$ErrorActionPreference = 'Stop'
$repo = 'C:\Projects\RAG\wenruo-rag'
$tmp  = Join-Path $env:TEMP 'qh_matrix'
New-Item -ItemType Directory -Force -Path $tmp | Out-Null

function Sha([string]$p) { (Get-FileHash -Algorithm SHA256 -Path $p).Hash.ToLower() }

# Authoritative pre-repair bytes: the untouched candidate image never received the repair.
docker cp qh_cand:/ragflow/api/db/services/dialog_service.py "$tmp\pre_fix.py" | Out-Null
"PRE_FIX_HOST_SHA=$(Sha "$tmp\pre_fix.py")"
"POST_FIX_HOST_SHA=$(Sha "$repo\api\db\services\dialog_service.py")"

docker cp "$repo\deploy\repair_gates\quote_health_red_probe.py"   qh_base:/tmp/quote_health_red_probe.py   | Out-Null
docker cp "$repo\deploy\repair_gates\quote_health_red_wrapper.py" qh_base:/tmp/quote_health_red_wrapper.py | Out-Null
"PROBE_HOST_SHA=$(Sha "$repo\deploy\repair_gates\quote_health_red_probe.py")"
"PROBE_BOX_SHA=$((docker exec qh_base sha256sum /tmp/quote_health_red_probe.py).Split(' ')[0])"

foreach ($phase in @('RED', 'GREEN')) {
    $src = if ($phase -eq 'RED') { "$tmp\pre_fix.py" } else { "$repo\api\db\services\dialog_service.py" }
    docker cp $src qh_base:/ragflow/api/db/services/dialog_service.py | Out-Null
    "$($phase)_IN_CONTAINER_SHA=$((docker exec qh_base sha256sum /ragflow/api/db/services/dialog_service.py).Split(' ')[0])"
    docker exec qh_base sh -c 'find /ragflow -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null; true' | Out-Null
    $out = "$tmp\$phase.txt"
    $ErrorActionPreference = 'Continue'
    $arm = if ($phase -eq 'RED') { 'red' } else { 'green' }
    docker exec -e "QUOTE_HEALTH_ARM=$arm" qh_base python /tmp/quote_health_red_wrapper.py 2>&1 | Out-File -FilePath $out -Encoding utf8
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    "$($phase)_EXIT=$code"
    $verdictLine = (Get-Content $out -Encoding utf8 | Select-String -Pattern '"verdict":' | Select-Object -Last 1).Line
    "$($phase)_VERDICT=$verdictLine"
    # The gate encodes required behaviour: the unrepaired source must FAIL it, the repaired one must PASS.
    $observed = if ($verdictLine -match '"verdict": "PASS"') { 'PASS' } else { 'FAIL' }
    $expected = if ($phase -eq 'RED') { 'FAIL' } else { 'PASS' }
    $label = if ($phase -eq 'RED') { 'RED_GATE_RESULT' } else { 'GREEN_GATE_RESULT' }
    "$label=$(if ($observed -eq 'FAIL' -and $phase -eq 'RED') { 'FAIL_AS_EXPECTED' } elseif ($observed -eq $expected) { 'PASS' } else { "UNEXPECTED_$observed" })"
    "$($phase)_LINES=$((Get-Content $out | Measure-Object -Line).Lines)"
}
"MATRIX_DONE"

# --- Read-only identity checks: the arm is only meaningful if these hold ---
"BASE_IMAGE_SHA=$((docker run --rm --entrypoint sha256sum my-wenruorag:repair-798288f8 /ragflow/api/db/services/dialog_service.py).Split(' ')[0])"
"CANDIDATE_IMAGE_SHA=$((docker run --rm --entrypoint sha256sum my-wenruorag:candidate-74a0c3a61-correction /ragflow/api/db/services/dialog_service.py).Split(' ')[0])"

$guard = @{
    'rag/nlp/search.py'                                       = 'abdf9a25813c00dda59b393ae3cd29143a33e98409e9cbfa056a92b8c7ea6912'
    'rag/nlp/doc_context.py'                                  = 'd0a61bda36c0632367d265ffd11bc8248637d59289f9107df333b968317a14e6'
    'rag/retrieval/decomposition.py'                          = 'ee2a060d95be16acc099d18a15cc0ef630857ea6e38c047edd80d8828fdffc9f'
    'rag/retrieval/chunk_profile.py'                          = '248a6af9bcf8a83582b38b3b2c197c4405c77e72da0c6304f6931c7d8ae362da'
    'rag/nlp/retrieval_projection.py'                         = '5618bfb01fded4f429a51a6ecbe2714ed60f31f306b8bf606d74674b62ecab98'
    'api/apps/restful_apis/chunk_api.py'                      = 'e63a7ac4df731da35dc636a809e4a3ec6795df18aa81a14f5d7152b74ef9bd79'
    'rag/svr/task_executor_refactor/dataflow_service.py'      = '0132bdc4bf425d00a7dd38badb74dacd5da788ac3720d3a2d86dcbdc85ea8965'
    'rag/advanced_rag/harness/tools/text_processing.py'       = 'a3007bdbb6ba95a21faf0720d8e1171e817f4d80e3b4d6fbd67e6efba6e3299d'
}
$guardFail = 0
foreach ($rel in $guard.Keys | Sort-Object) {
    $actual = Sha (Join-Path $repo $rel)
    $ok = $actual -eq $guard[$rel]
    if (-not $ok) { $guardFail++ }
    "EIGHT_FILE_GUARD $rel $([string]$ok.ToString().ToUpper()) $actual"
}
"EIGHT_FILE_GUARD_RESULT=$(if ($guardFail -eq 0) { 'PASS' } else { "FAIL($guardFail)" })"
