$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$stateDirectory = Join-Path $projectRoot '.ops'
$forwarderScript = Join-Path $projectRoot 'scripts\local_web_access.py'
$localUrl = 'http://127.0.0.1:18080'
if (Get-NetTCPConnection -LocalPort 18080 -State Listen -ErrorAction SilentlyContinue) {
    try {
        $health = Invoke-RestMethod -Uri "$localUrl/api/health" -TimeoutSec 5
        if ($health.status -eq 'healthy' -and $health.database -eq 'ready') {
            Write-Output "Local platform access is ready: $localUrl"
            exit 0
        }
    } catch { }
    throw 'Port 18080 is occupied by a different or unhealthy service; no process was stopped.'
}
New-Item -ItemType Directory -Path $stateDirectory -Force | Out-Null
$pythonLauncher = (Get-Command py.exe).Source
& $pythonLauncher -3.13 -c 'import paramiko' 2>$null
if ($LASTEXITCODE -ne 0) {
    throw 'Python 3.13 or Paramiko is missing. Install scripts/requirements-local-access.txt first.'
}
$arguments = '-3.13 -X utf8 "' + $forwarderScript + '"'
$process = Start-Process -FilePath $pythonLauncher -ArgumentList $arguments `
    -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $stateDirectory 'local-web-access.log') `
    -RedirectStandardError (Join-Path $stateDirectory 'local-web-access-error.log')
for ($attempt = 0; $attempt -lt 25; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri "$localUrl/api/health" -TimeoutSec 2
        if ($health.status -eq 'healthy' -and $health.database -eq 'ready') {
            Write-Output "Local platform access is ready: $localUrl"
            exit 0
        }
    } catch { }
    $process.Refresh()
    if ($process.HasExited) { throw 'SSH forwarding failed; inspect the private .ops access logs.' }
    Start-Sleep -Seconds 1
}
throw 'Local forwarding has not become healthy; inspect the private .ops access logs.'
