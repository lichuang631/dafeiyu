$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$voiceRoot = $PSScriptRoot
$voiceLock = [System.IO.File]::Open((Join-Path $voiceRoot 'manager.lock'), [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::ReadWrite)
try {
    $voiceLock.Lock(0, 1)
    $voiceLock.Unlock(0, 1)
} catch [System.IO.IOException] {
    Write-Host '本地声音已经在运行，无需重复启动。'
    return
} finally {
    $voiceLock.Dispose()
}
$stopFile = Join-Path $voiceRoot 'stop-request'
if (Test-Path -LiteralPath $stopFile) { Remove-Item -LiteralPath $stopFile }
$voicePython = Join-Path $voiceRoot '.venv\Scripts\python.exe'
$voiceManager = Join-Path $voiceRoot 'manager.py'
New-Item -ItemType Directory -Force -Path (Join-Path $voiceRoot 'logs') | Out-Null
Start-Process -FilePath $voicePython -ArgumentList @('-u', ('"' + $voiceManager + '"')) -WorkingDirectory $voiceRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $voiceRoot 'logs\manager.log') -RedirectStandardError (Join-Path $voiceRoot 'logs\manager-error.log')
Write-Host '本地语音已启动。连接中断会自动重连；不可用时大肥鱼会使用云端龙嫱。'
