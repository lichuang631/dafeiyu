$ErrorActionPreference = 'Stop'
foreach ($entry in @(
    @{ Name='astrbot'; Exe=(Join-Path $PSScriptRoot 'AstrBot-4.29.4\.venv\Scripts\python.exe') },
    @{ Name='napcat'; Exe=(Join-Path $PSScriptRoot 'NapCat\node.exe') }
)) {
    $pidFile = Join-Path $PSScriptRoot "logs\$($entry.Name).pid"
    if (-not (Test-Path -LiteralPath $pidFile)) { continue }
    $servicePid = [int](Get-Content -LiteralPath $pidFile)
    $proc = Get-Process -Id $servicePid -ErrorAction SilentlyContinue
    if ($proc -and $proc.Path -eq $entry.Exe) { Stop-Process -Id $servicePid; Write-Host "$($entry.Name) stopped." }
    Remove-Item -LiteralPath $pidFile
}
