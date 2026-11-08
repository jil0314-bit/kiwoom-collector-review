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
    $collectorNew = Start-Process -FilePath $collectorPython -ArgumentList '-B', 'app.py' -WorkingDirectory $collectorRoot -WindowStyle Hidden -PassThru
    @{ok=$true;process=$collectorNew.Id} | ConvertTo-Json | Set-Content -LiteralPath $collectorResult -Encoding UTF8
} catch {
    @{ok=$false;error=$_.Exception.Message} | ConvertTo-Json | Set-Content -LiteralPath $collectorResult -Encoding UTF8
}
