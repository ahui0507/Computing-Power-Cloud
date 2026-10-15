$ErrorActionPreference = 'Stop'
$pidPath = Join-Path $PSScriptRoot '.ops\local-web-access.pid'
if (-not (Test-Path -LiteralPath $pidPath)) {
    Write-Output 'No managed local forwarding process is recorded.'
    exit 0
}
$forwardingPid = [int](Get-Content -LiteralPath $pidPath -Raw)
$forwardingProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$forwardingPid"
if ($forwardingProcess) {
    $expectedScript = Join-Path $PSScriptRoot 'scripts\local_web_access.py'
    if (-not $forwardingProcess.CommandLine.Contains($expectedScript)) {
        throw 'The recorded PID belongs to a different process; nothing was stopped.'
    }
    Stop-Process -Id $forwardingPid
}
Remove-Item -LiteralPath $pidPath
Write-Output 'Local forwarding stopped. Remote platform services remain running.'
