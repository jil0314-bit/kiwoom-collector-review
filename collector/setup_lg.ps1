param([string]$ExpectedUserSid = '')
$ErrorActionPreference = 'Stop'
try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    if ($ExpectedUserSid -and $identity.User.Value -ne $ExpectedUserSid) { throw '다른 관리자 계정으로 설치할 수 없습니다. 사용할 Windows 계정에서 설치하세요.' }
    if (-not ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        $arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -ExpectedUserSid "' + $identity.User.Value + '"'
        $process = Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments -PassThru -Wait
        exit $process.ExitCode
    }
    Set-Location -LiteralPath $PSScriptRoot
    # A copied installer must not replace the office computer's existing task.
    $existing = Get-ScheduledTask -TaskName 'KiwoomTop100Archive_2005' -ErrorAction SilentlyContinue
    if ($existing) {
        if ($existing.Actions.WorkingDirectory -ne $PSScriptRoot) { throw '이 PC에 다른 위치의 수집기가 등록되어 있습니다. 기존 수집기는 변경하지 않았습니다.' }
        if ($existing.State -eq 'Running') { throw '이 위치의 수집기가 이미 실행 중입니다. 재설치 대신 바탕화면 수집기 - LG그램을 실행하세요.' }
    }
    $client = New-Object Net.Sockets.TcpClient
    try { $client.Connect('127.0.0.1',8766); throw '8766 포트를 다른 프로그램 또는 수집기가 사용 중입니다. 기존 서버는 변경하지 않았습니다.' }
    catch [Net.Sockets.SocketException] { }
    finally { $client.Dispose() }
    Write-Host '[1/3] 설치 파일 확인'
    $packageRoot = Split-Path -Parent $PSScriptRoot
    $manifestPath = Join-Path $packageRoot 'PACKAGE_MANIFEST.json'
    if (Test-Path -LiteralPath $manifestPath) {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        foreach ($entry in $manifest.files) {
            $file = Join-Path $packageRoot $entry.path
            if (-not (Test-Path -LiteralPath $file) -or (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) { throw ('설치 파일 손상: ' + $entry.path + '. ZIP을 다시 풀어주세요.') }
        }
    }
    $bundledPython = Join-Path $PSScriptRoot '.runtime\python.exe'
    if (Test-Path -LiteralPath $bundledPython) {
        Write-Host '실행에 필요한 파일이 모두 포함되어 있습니다.'
        $python = $bundledPython
        & $python -B -c 'import struct,PIL;assert struct.calcsize("P")==8'
        if ($LASTEXITCODE -ne 0) { throw '포함된 실행 환경이 손상되었습니다. ZIP을 다시 풀어주세요.' }
    } else {
        $basePython = $null
        $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
        foreach ($version in @('3.14','3.13')) {
            $candidate = Join-Path $env:LOCALAPPDATA ('Programs\Python\Python' + $version.Replace('.','') + '\python.exe')
            if (Test-Path -LiteralPath $candidate) { $basePython = $candidate; break }
            if ($launcher) {
                try { $candidate = & $launcher.Source ('-' + $version) -c 'import sys;print(sys.executable)' 2>$null
                    if ($LASTEXITCODE -eq 0 -and $candidate -and (Test-Path -LiteralPath $candidate)) { $basePython = $candidate; break }
                } catch { }
            }
        }
        if (-not $basePython) { throw 'Python이 없습니다. LG_INSTALL.txt의 공식 링크에서 Python 3.14 64비트를 설치한 뒤 다시 실행하세요.' }
        & $basePython -c 'import sys,struct,tkinter;assert sys.version_info >= (3,13) and struct.calcsize("P")==8'
        if ($LASTEXITCODE -ne 0) { throw '64비트 Python 3.13과 tkinter가 필요합니다.' }
        Write-Host '[2/4] 수집기 전용 실행 환경 설치'
        & $basePython -m venv (Join-Path $PSScriptRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw '전용 Python 환경 생성 실패' }
        $python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
        & $python -m pip install --disable-pip-version-check --only-binary=:all: --index-url https://pypi.org/simple Pillow==13.0.0
        if ($LASTEXITCODE -ne 0) { throw 'Pillow 설치 실패. 인터넷 연결을 확인하세요.' }
    }
    & $python -B (Join-Path $PSScriptRoot 'configure_lg.py') --check
    if ($LASTEXITCODE -ne 0) { throw '수집기 실행 파일 검사 실패' }
    Write-Host '[2/3] 키움 인증정보 입력'
    if (Test-Path -LiteralPath $bundledPython) {
        & (Join-Path $PSScriptRoot 'configure_lg_easy.ps1')
    } else {
        & $python -B (Join-Path $PSScriptRoot 'configure_lg.py')
        if ($LASTEXITCODE -ne 0) { throw '인증정보 설정을 완료하지 않아 자동 실행은 등록하지 않았습니다.' }
    }
    Write-Host '[3/3] 자동 실행과 바탕화면 아이콘 등록'
    & (Join-Path $PSScriptRoot 'install_schedule.ps1')
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) '수집기 - LG그램.lnk'))
    $shortcut.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
    $shortcut.Arguments = '"' + (Join-Path $PSScriptRoot 'start.vbs') + '"'
    $shortcut.WorkingDirectory = $PSScriptRoot
    $shortcut.IconLocation = Join-Path $PSScriptRoot 'collector.ico'
    $shortcut.Save()
    & wscript.exe (Join-Path $PSScriptRoot 'start.vbs')
    Write-Host '설치 완료. 수집기 화면을 엽니다. 이후에는 바탕화면 수집기 - LG그램을 실행하세요.'
    Write-Host '설치만으로 실제 키움 조회나 0311 차트 연동 검증이 끝나는 것은 아닙니다.'
} catch {
    Write-Host ('설치 중지: ' + $_.Exception.Message) -ForegroundColor Red
    Read-Host 'Enter를 누르면 닫습니다'
    exit 1
}
