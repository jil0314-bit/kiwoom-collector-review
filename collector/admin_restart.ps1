param([Parameter(Mandatory=$true)][int]$CollectorProcessId,
      [ValidateRange(1,180)][int]$MaxWaitMinutes = 6)
$ErrorActionPreference = 'Stop'
$collectorRoot = $PSScriptRoot
$collectorResult = Join-Path $collectorRoot 'data\admin_restart_result.json'
$collectorPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe'
Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class CollectorProcessPath {
    [DllImport("kernel32.dll", SetLastError=true)] public static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
    [DllImport("kernel32.dll", SetLastError=true, CharSet=CharSet.Unicode)] public static extern bool QueryFullProcessImageName(IntPtr process, uint flags, StringBuilder path, ref uint size);
    [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr process);
    public static string Get(int pid) {
        IntPtr handle = OpenProcess(0x1000, false, pid);
        if (handle == IntPtr.Zero) return "";
        try { var path = new StringBuilder(1024); uint size = 1024;
            return QueryFullProcessImageName(handle, 0, path, ref size) ? path.ToString() : "";
        } finally { CloseHandle(handle); }
    }
}
'@
try {
    $collectorIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $collectorPrincipal = New-Object Security.Principal.WindowsPrincipal($collectorIdentity)
    if (-not $collectorPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw '관리자 권한이 없어 재시작하지 않았습니다. 기존 수집기는 유지합니다.'
    }
    $collectorTask = Get-ScheduledTask -TaskName 'KiwoomTop100Archive_2005'
    if ($collectorTask.Principal.RunLevel -ne 'Highest' -or $collectorTask.Actions[0].Execute -ne $collectorPython -or
        $collectorTask.Actions[0].WorkingDirectory -ne $collectorRoot) {
        throw '높은 권한의 이 프로젝트 예약 작업을 먼저 설치하세요. 기존 수집기는 유지합니다.'
    }
    $collectorReady = $false
    for ($collectorAttempt = 0; $collectorAttempt -lt ($MaxWaitMinutes * 12); $collectorAttempt++) {
        try {
            $collectorSnapshot = Invoke-RestMethod 'http://127.0.0.1:8766/api/status' -TimeoutSec 5
            $volumeSnapshot = Invoke-RestMethod 'http://127.0.0.1:8766/api/volume/status' -TimeoutSec 5
            $investorSnapshot = Invoke-RestMethod 'http://127.0.0.1:8766/api/investors/status' -TimeoutSec 5
            if (-not $collectorSnapshot.state.busy -and -not $collectorSnapshot.state.queued -and
                -not $volumeSnapshot.state.busy -and -not $volumeSnapshot.state.bars_busy -and
                -not $investorSnapshot.state.busy) {
                $collectorReady = $true
                break
            }
        } catch {
            # A slow status response is not proof that a worker is idle. Retry safely.
        }
        Start-Sleep -Seconds 5
    }
    if (-not $collectorReady) { throw '수집 완료 대기 시간 초과. 기존 수집기는 유지했습니다.' }
    $collectorProcess = Get-Process -Id $CollectorProcessId
    $collectorListener = Get-NetTCPConnection -LocalPort 8766 -State Listen |
        Where-Object { $_.OwningProcess -eq $CollectorProcessId -and $_.LocalAddress -eq '127.0.0.1' }
    $collectorActualPath = [CollectorProcessPath]::Get($CollectorProcessId)
    if (-not $collectorListener -or $collectorActualPath -ne $collectorPython) {
        throw '수집기 프로세스 식별 실패. 중단하지 않았습니다.'
    }
    Stop-Process -Id $CollectorProcessId
    Wait-Process -Id $CollectorProcessId -Timeout 10 -ErrorAction SilentlyContinue
    for ($collectorTaskWait = 0; $collectorTaskWait -lt 20 -and (Get-ScheduledTask -TaskName 'KiwoomTop100Archive_2005').State -eq 'Running'; $collectorTaskWait++) { Start-Sleep -Milliseconds 500 }
    Start-ScheduledTask -TaskName 'KiwoomTop100Archive_2005'
    $collectorNewPid = $null
    for ($collectorWait = 0; $collectorWait -lt 20; $collectorWait++) {
        $collectorPort = Get-NetTCPConnection -LocalPort 8766 -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalAddress -eq '127.0.0.1' -and $_.OwningProcess -ne $CollectorProcessId }
        if ($collectorPort) {
            $collectorNewPid = $collectorPort[0].OwningProcess
            if ([CollectorProcessPath]::Get($collectorNewPid) -eq $collectorPython) { break }
            $collectorNewPid = $null
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $collectorNewPid) { throw '예약 작업 시작 후 수집기 확인 시간 초과. 작업 스케줄러 결과를 확인하세요.' }
    @{ok=$true;process=$collectorNewPid;launch='scheduled-highest'} | ConvertTo-Json | Set-Content -LiteralPath $collectorResult -Encoding UTF8
} catch {
    @{ok=$false;error=$_.Exception.Message} | ConvertTo-Json | Set-Content -LiteralPath $collectorResult -Encoding UTF8
}
