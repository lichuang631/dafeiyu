$ErrorActionPreference = 'Stop'
$portReady = $false
$client = [System.Net.Sockets.TcpClient]::new()
try {
    $client.Connect('127.0.0.1', 16185)
    $portReady = $true
} catch {
    $portReady = $false
} finally {
    $client.Dispose()
}
if (-not $portReady) {
    Write-Host '请在新打开的服务器登录窗口输入服务器密码；该窗口保持打开即可。'
    $sshExe = (Get-Command ssh.exe -ErrorAction Stop).Source
    Start-Process -FilePath $sshExe -WindowStyle Normal -ArgumentList @(
        '-N', '-o', 'ExitOnForwardFailure=yes',
        '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=6',
        '-L', '127.0.0.1:16185:127.0.0.1:6185',
        '-L', '127.0.0.1:16099:127.0.0.1:6099',
        'root@203.0.113.10'
    )
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        $client = [System.Net.Sockets.TcpClient]::new()
        try {
            $client.Connect('127.0.0.1', 16185)
            $portReady = $true
        } catch {
            $portReady = $false
        } finally {
            $client.Dispose()
        }
        if ($portReady) { break }
        Start-Sleep -Seconds 1
    }
    if (-not $portReady) { throw '尚未连接服务器。请检查登录窗口中的提示，再重新打开。' }
}
Start-Process 'http://127.0.0.1:16185'
Write-Host 'AstrBot 面板：http://127.0.0.1:16185'
Write-Host 'QQ 登录面板：http://127.0.0.1:16099/webui'
Write-Host '关闭管理窗口只会断开面板连接，服务器上的大肥鱼会继续运行。'
