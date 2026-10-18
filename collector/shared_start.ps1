$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$shareFolder = Split-Path -Parent $taskRoot
try {
    if (-not (Test-Path -LiteralPath (Join-Path $shareFolder 'snapshot.json'))) {
        throw 'Shared data has not arrived. Place this program in the extracted collector folder beside snapshot.json, and wait for OneDrive.'
    }
    $candidates = @(
        "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe"
    )
    $taskPython = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $taskPython) { throw 'Install Python from https://www.python.org/downloads/windows/ and run this file again.' }
    $hasPillow = & $taskPython -c 'import importlib.util; print(int(importlib.util.find_spec("PIL") is not None))'
    if ($hasPillow -ne '1') {
        & $taskPython -m pip install Pillow
        if ($LASTEXITCODE -ne 0) { throw 'Pillow installation failed.' }
    }
    try {
        $existing = Invoke-RestMethod -Uri 'http://127.0.0.1:8766/api/status' -TimeoutSec 2
    } catch { $existing = $null }
    if ($existing) {
        if ($existing.identity -ne 'kiwoom-shared-archive-viewer-v1') { throw 'A different collector already uses port 8766. Close that collector on this computer first.' }
        & $taskPython -B (Join-Path $taskRoot 'shared_viewer.py') --folder $shareFolder --open-only
        exit
    }
    $taskPythonw = Join-Path (Split-Path -Parent $taskPython) 'pythonw.exe'
    $arguments = '-B "' + (Join-Path $taskRoot 'shared_viewer.py') + '" --folder "' + $shareFolder + '"'
    Start-Process -FilePath $taskPythonw -ArgumentList $arguments -WorkingDirectory $taskRoot -WindowStyle Hidden
} catch {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'Shared collector') | Out-Null
}
