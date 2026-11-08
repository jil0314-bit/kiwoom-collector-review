param([switch]$ValidateOnly)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Security
[Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object Windows.Forms.Form
$form.Text = 'LG그램 수집기 · 처음 한 번만 설정'
$form.Size = New-Object Drawing.Size(620,530)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.Font = New-Object Drawing.Font('Malgun Gothic',10)
$title = New-Object Windows.Forms.Label
$title.Text = '키움 인증정보만 넣으면 설치가 끝납니다.'
$title.SetBounds(22,18,565,30)
$title.Font = New-Object Drawing.Font('Malgun Gothic',13,[Drawing.FontStyle]::Bold)
$form.Controls.Add($title)
$help = New-Object Windows.Forms.Label
$help.Text = "계좌 비밀번호가 아닙니다. 키움 REST App Key와 App Secret입니다.`r`n아래 키움 페이지에서 '현재 나의 IP'를 허용 목록에 추가하세요."
$help.SetBounds(22,60,565,54);$form.Controls.Add($help)
$link = New-Object Windows.Forms.LinkLabel
$link.Text = '키움 허용 IP 등록 페이지 열기'
$link.SetBounds(22,118,540,26)
$link.Add_LinkClicked({ Start-Process 'https://openapi.kiwoom.com/intro/serviceInfo' })
$form.Controls.Add($link)
$keyLabel = New-Object Windows.Forms.Label
$keyLabel.Text = 'App Key';$keyLabel.SetBounds(22,162,110,28);$form.Controls.Add($keyLabel)
$key = New-Object Windows.Forms.TextBox
$key.SetBounds(135,158,440,32);$key.UseSystemPasswordChar=$true;$form.Controls.Add($key)
$secretLabel = New-Object Windows.Forms.Label
$secretLabel.Text = 'App Secret';$secretLabel.SetBounds(22,210,110,28);$form.Controls.Add($secretLabel)
$secret = New-Object Windows.Forms.TextBox
$secret.SetBounds(135,206,440,32);$secret.UseSystemPasswordChar=$true;$form.Controls.Add($secret)
$profile = New-Object Windows.Forms.TextBox
$profile.SetBounds(22,286,410,30);$profile.ReadOnly=$true;$form.Controls.Add($profile)
$browse = New-Object Windows.Forms.Button
$browse.Text='영웅문 폴더 (선택)';$browse.SetBounds(442,284,135,34)
$browse.Add_Click({
    $dialog=New-Object Windows.Forms.FolderBrowserDialog
    $dialog.Description='Portfolio.dat가 있는 영웅문 사용자 폴더. 모르면 취소하세요.'
    if ($dialog.ShowDialog() -eq 'OK') { $profile.Text=$dialog.SelectedPath }
    $dialog.Dispose()
})
$form.Controls.Add($browse)
$notice = New-Object Windows.Forms.Label
$notice.Text="영웅문 폴더는 모르면 비워두세요. 일반 수집은 가능합니다.`r`n인증정보는 이 Windows 계정으로 암호화합니다.`r`n0311 차트·영웅문 메모 저장은 연결 확인 후 별도 설정합니다."
$notice.SetBounds(22,330,565,76);$form.Controls.Add($notice)
$save = New-Object Windows.Forms.Button
$save.Text='저장하고 설치 완료';$save.SetBounds(157,425,280,46)
$state=@{saved=$false}
$save.Add_Click({
    try {
        $appKey=$key.Text.Trim();$appSecret=$secret.Text.Trim()
        if (-not $appKey -or -not $appSecret -or $key.Text -match '[\r\n\x00]' -or $secret.Text -match '[\r\n\x00]') { throw '입력값 확인' }
        if ($profile.Text -and -not (Test-Path -LiteralPath (Join-Path $profile.Text 'Portfolio.dat'))) { throw '영웅문 폴더 확인' }
        $folder=Join-Path $env:LOCALAPPDATA 'KiwoomCollector'
        [IO.Directory]::CreateDirectory($folder)>$null
        $plain=[Text.Encoding]::UTF8.GetBytes((@{key=$appKey;secret=$appSecret}|ConvertTo-Json -Compress))
        $encrypted=[Security.Cryptography.ProtectedData]::Protect($plain,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
        [Array]::Clear($plain,0,$plain.Length)
        $file=Join-Path $folder 'credentials.dpapi'
        [IO.File]::WriteAllBytes(($file+'.tmp'),$encrypted)
        Move-Item -LiteralPath ($file+'.tmp') -Destination $file -Force
        $file=Join-Path $folder 'settings.json'
        $settings=@{notebook_install=$true;hero4_profile=$profile.Text;memo_write_enabled=$false}|ConvertTo-Json
        [IO.File]::WriteAllText(($file+'.tmp'),$settings,[Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath ($file+'.tmp') -Destination $file -Force
        $key.Clear();$secret.Clear();$appKey='';$appSecret='';$state.saved=$true
        $form.Close()
    } catch {
        [Windows.Forms.MessageBox]::Show('App Key·App Secret과 선택한 영웅문 폴더를 확인하세요. 저장에 실패하면 설치를 중지합니다.','설정 확인')>$null
    }
})
$form.Controls.Add($save);$form.AcceptButton=$save
if ($ValidateOnly) { $form.Dispose(); 'PASS: credential form construction (no display or secret access)'; return }
[void]$form.ShowDialog();$form.Dispose()
if (-not $state.saved) { throw '설정 창을 취소했습니다. 자동 실행은 등록하지 않았습니다.' }
