param([Parameter(Mandatory=$true)][int]$CollectorProcessId)
$ErrorActionPreference = 'Stop'
$collectorRoot = $PSScriptRoot
$collectorResult = Join-Path $collectorRoot 'data\admin_restart_result.json'
$collectorPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe'
try {
    $collectorReady = $false
    for ($collectorAttempt = 0; $collectorAttempt -lt 72; $collectorAttempt++) {
        $collectorSnapshot = Invoke-RestMethod 'http://127.0.0.1:8766/api/status' -TimeoutSec 5
        if (-not $collectorSnapshot.state.busy) { $collectorReady = $true; break }
        Start-Sleep -Seconds 5
    }
    if (-not $collectorReady) { throw '수집 완료 대기 시간 초과. 기존 수집기는 유지했습니다.' }
    $collectorProcess = Get-Process -Id $CollectorProcessId
    $collectorListener = Get-NetTCPConnection -LocalPort 8766 -State Listen |
        Where-Object { $_.OwningProcess -eq $CollectorProcessId -and $_.LocalAddress -eq '127.0.0.1' }
    if (-not $collectorListener -or $collectorProcess.Path -ne $collectorPython) {
        throw '수집기 프로세스 식별 실패. 중단하지 않았습니다.'
    }
    Stop-Process -Id $CollectorProcessId
    Wait-Process -Id $CollectorProcessId -Timeout 10 -ErrorAction SilentlyContinue
    $collectorNew = Start-Process -FilePath $collectorPython -ArgumentList '-B', 'app.py' -WorkingDirectory $collectorRoot -WindowStyle Hidden -PassThru
    @{ok=$true;process=$collectorNew.Id} | ConvertTo-Json | Set-Content -LiteralPath $collectorResult -Encoding UTF8
} catch {
    @{ok=$false;error=$_.Exception.Message} | ConvertTo-Json | Set-Content -LiteralPath $collectorResult -Encoding UTF8
}
