$ErrorActionPreference = "Stop"

function Test-OllamaModel {
    param([Parameter(Mandatory = $true)][string]$Name)

    $escaped = [Regex]::Escape($Name)
    return [bool]((& ollama list) -match "^$escaped(?:\:latest)?\s")
}

function Install-HuggingFaceAlias {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Alias
    )

    if (Test-OllamaModel -Name $Alias) {
        Write-Host "OK - $Alias est deja installe."
        return
    }

    Write-Host "Telechargement de $Source..."
    & ollama pull $Source
    if ($LASTEXITCODE -ne 0) {
        throw "Le telechargement de $Source a echoue."
    }

    & ollama cp $Source $Alias
    if ($LASTEXITCODE -ne 0) {
        throw "La creation de l'alias $Alias a echoue."
    }

    # The Hugging Face manifest is only a temporary import name. Removing it
    # keeps one visible Ollama model per weight set; the blobs remain shared.
    & ollama rm $Source
    if ($LASTEXITCODE -ne 0) {
        throw "Le nettoyage du manifeste temporaire $Source a echoue."
    }
    Write-Host "OK - $Alias est pret sans doublon de manifeste."
}

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    throw "Ollama n'est pas disponible dans PATH."
}

Install-HuggingFaceAlias `
    -Source "hf.co/unsloth/SmolLM3-3B-GGUF:UD-Q6_K_XL" `
    -Alias "lasme-smol-fast"

Install-HuggingFaceAlias `
    -Source "hf.co/unsloth/Qwen3-VL-8B-Instruct-GGUF:UD-Q4_K_XL" `
    -Alias "lasme-qwen-vision"

Write-Host ""
Write-Host "Modeles Lasme disponibles :"
& ollama list
