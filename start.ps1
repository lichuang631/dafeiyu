$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
if (Test-Path -LiteralPath (Join-Path $taskRoot '云端部署\运行在服务器.txt')) {
    Write-Host '大肥鱼已迁移到服务器 203.0.113.10，无需启动电脑上的机器人。'
    Write-Host '需要修改设置时，请打开同目录的“云端面板.bat”。'
    exit 0
}
$logDir = Join-Path $taskRoot 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
foreach ($entry in @(
    @{ Name='astrbot'; Exe=(Join-Path $taskRoot 'AstrBot-4.29.4\.venv\Scripts\python.exe'); Dir=(Join-Path $taskRoot 'AstrBot-4.29.4'); Args=@('main.py'); Port=6185 },
    @{ Name='napcat'; Exe=(Join-Path $taskRoot 'NapCat\node.exe'); Dir=(Join-Path $taskRoot 'NapCat'); Args=@('index.js','-q','100000002'); Port=6099 }
)) {
    $portCheck = [System.Net.Sockets.TcpClient]::new()
    try { $portCheck.Connect('127.0.0.1', $entry.Port); $running=$true } catch { $running=$false } finally { $portCheck.Dispose() }
    if ($running) { Write-Host "$($entry.Name) is already listening on $($entry.Port)."; continue }
    $proc = Start-Process -FilePath $entry.Exe -ArgumentList $entry.Args -WorkingDirectory $entry.Dir -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir "$($entry.Name).out.log") -RedirectStandardError (Join-Path $logDir "$($entry.Name).err.log") -PassThru
    $proc.Id | Set-Content -LiteralPath (Join-Path $logDir "$($entry.Name).pid") -Encoding ASCII
    Write-Host "$($entry.Name) started: $($proc.Id)"
}
