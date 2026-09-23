$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$serverPidFile = Join-Path $projectRoot ".runtime\server.pid"

if (Test-Path -LiteralPath $serverPidFile) {
    $serverPid = [int](Get-Content -LiteralPath $serverPidFile -Raw)
    $process = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
    if ($process) {
        $processInfo = Get-CimInstance `
            -ClassName Win32_Process `
            -Filter "ProcessId = $serverPid" `
            -ErrorAction SilentlyContinue
        $commandLine = [string]$processInfo.CommandLine
        if (
            $commandLine -match "uvicorn" -and
            $commandLine -match "chat\.server\.main:app"
        ) {
            Stop-Process -Id $serverPid
            $process.WaitForExit(5000) | Out-Null
            Write-Host "OK - Serveur Lasme LLM arrete."
        }
        else {
            Write-Warning (
                "Le PID enregistre appartient a un autre processus. " +
                "Il n'a pas ete arrete."
            )
        }
    }
    Remove-Item -LiteralPath $serverPidFile -Force
}
else {
    Write-Host "Aucun serveur Lasme LLM gere par start_local.ps1 n'est enregistre."
}

$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $python) {
    & $python -m scripts.serve stop
}
else {
    Write-Warning "Environnement Python absent : llama-server n'a pas ete arrete."
}
