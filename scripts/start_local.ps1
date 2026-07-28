$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot ".runtime"
$serverPidFile = Join-Path $runtimeRoot "server.pid"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Environnement Python absent. Executez d'abord : python -m venv .venv"
}

New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null

$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
$docker = if ($dockerCommand) {
    $dockerCommand.Source
}
else {
    $dockerFallback = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    if (Test-Path -LiteralPath $dockerFallback) {
        $dockerFallback
    }
    else {
        $null
    }
}

$ollamaReady = $false
try {
    Invoke-RestMethod `
        -Uri "http://127.0.0.1:11434/api/tags" `
        -TimeoutSec 2 | Out-Null
    $ollamaReady = $true
}
catch {
}
if (-not $ollamaReady) {
    $ollamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
    $ollama = if ($ollamaCommand) {
        $ollamaCommand.Source
    }
    else {
        Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    }
    if (-not (Test-Path -LiteralPath $ollama)) {
        throw "Ollama est introuvable. Installez Ollama avant de demarrer Lasme LLM."
    }
    Start-Process `
        -FilePath $ollama `
        -ArgumentList "serve" `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden | Out-Null
    Start-Sleep -Seconds 2
}

$searxEnabled = $false
$envFile = Join-Path $projectRoot ".env"
if (Test-Path -LiteralPath $envFile) {
    $searxEnabled = [bool](
        Select-String `
            -LiteralPath $envFile `
            -Pattern "^\s*SEARXNG_ENABLED\s*=\s*(true|1|yes|on)\s*$" `
            -Quiet
    )
}
if ($searxEnabled -and $docker) {
    & $docker compose `
        -f (Join-Path $projectRoot "infra\searxng\compose.yaml") `
        up -d
}
elseif ($searxEnabled) {
    Write-Warning "SearXNG est active mais Docker Desktop est introuvable."
}

if ($docker) {
    $runnerInspect = & $docker image inspect `
        "lasme-python-runner:latest" `
        2>$null
    $runnerVersion = $null
    if ($LASTEXITCODE -eq 0 -and $runnerInspect) {
        $runnerInfo = $runnerInspect | ConvertFrom-Json
        $runnerVersion = $runnerInfo[0].Config.Labels."com.lasme.runner.version"
    }
    if ($runnerVersion -ne "2") {
        Write-Host "Construction du runner Python isole..."
        & $docker build `
            -t "lasme-python-runner:latest" `
            (Join-Path $projectRoot "infra\runner")
        if ($LASTEXITCODE -ne 0) {
            throw "La construction du runner Python a echoue."
        }
    }
}
else {
    Write-Warning "Docker Desktop est introuvable : le runner Python sera indisponible."
}

$serverReady = $false
try {
    Invoke-RestMethod `
        -Uri "http://127.0.0.1:8000/api/health" `
        -TimeoutSec 2 | Out-Null
    $serverReady = $true
}
catch {
}
if (-not $serverReady) {
    $server = Start-Process `
        -FilePath $python `
        -ArgumentList @(
            "-m",
            "uvicorn",
            "chat.server.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000"
        ) `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -LiteralPath $serverPidFile -Value $server.Id -Encoding ascii
}

$deadline = [DateTime]::UtcNow.AddSeconds(20)
do {
    try {
        $health = Invoke-RestMethod `
            -Uri "http://127.0.0.1:8000/api/health" `
            -TimeoutSec 2
        break
    }
    catch {
        Start-Sleep -Milliseconds 500
    }
} while ([DateTime]::UtcNow -lt $deadline)

if (-not $health) {
    throw "Le serveur Lasme LLM n'a pas repondu dans le delai prevu."
}
if ($health.status -ne "ok") {
    $missingModels = @($health.checks.ollama.missing_models) -join ", "
    $details = if ($missingModels) {
        " Modeles manquants : $missingModels."
    }
    elseif ($health.checks.runner.status -ne "ok") {
        " Runner Docker indisponible."
    }
    else {
        ""
    }
    throw "Lasme LLM repond mais son etat est degrade.$details"
}

Write-Host "OK - Lasme LLM est pret : http://127.0.0.1:8000/"
Write-Host "  API : $($health.status) - Ollama : $($health.checks.ollama.status)"
Write-Host "  Runner Python : $($health.checks.runner.status)"
if ($health.checks.ocr.status -ne "ok") {
    Write-Warning (
        "OCR Tesseract indisponible. Les images utilisent Lasme Vision; " +
        "les PDF scannes necessitent Vision ou Tesseract."
    )
}
if ($searxEnabled) {
    Write-Host "  SearXNG demande : http://127.0.0.1:8080/"
}
