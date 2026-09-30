# Downloads uv and CPython 3.12 into this repo (.tools, .python), creates .venv,
# and installs requirements.txt. No system Python required.
#Requires -Version 5.1
param(
    [string]$InferenceUrl = "",
    [string]$ApiKey = "",
    [string]$ChatModel = "",
    [string]$EmbeddingModel = ""
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = "SilentlyContinue"

$UvVersion = "0.12.19"
$PythonVersion = "3.12"

$projectRoot = Split-Path -Parent $PSScriptRoot
$toolsDir = Join-Path $projectRoot ".tools"
$pythonDir = Join-Path $projectRoot ".python"
$uvExe = Join-Path $toolsDir "uv.exe"
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$envPath = Join-Path $projectRoot ".env"
$examplePath = Join-Path $projectRoot ".env.example"

Set-Location $projectRoot
New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null

function Get-WindowsArch {
    $arch = $env:PROCESSOR_ARCHITEW6432
    if (-not $arch) { $arch = $env:PROCESSOR_ARCHITECTURE }
    switch ($arch) {
        "AMD64" { return "x86_64-pc-windows-msvc" }
        "ARM64" { return "aarch64-pc-windows-msvc" }
        default { throw "Unsupported Windows architecture: $arch" }
    }
}

function Install-Uv {
    if (Test-Path -LiteralPath $uvExe) {
        $versionText = & $uvExe --version
        if ($versionText -match [regex]::Escape($UvVersion)) {
            Write-Host "uv $UvVersion is already in .tools"
            return
        }
    }

    $target = Get-WindowsArch
    $url = "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-$target.zip"
    $zipPath = Join-Path $toolsDir "uv.zip"
    $extractDir = Join-Path $toolsDir "uv-extract"

    Write-Host "Downloading uv $UvVersion ($target)..."
    Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing
    if (Test-Path -LiteralPath $extractDir) {
        Remove-Item -LiteralPath $extractDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $extractDir | Out-Null
    Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force
    $downloaded = Join-Path $extractDir "uv.exe"
    if (-not (Test-Path -LiteralPath $downloaded)) {
        throw "uv.exe was not found in the downloaded archive."
    }
    Move-Item -LiteralPath $downloaded -Destination $uvExe -Force
    Remove-Item -LiteralPath $extractDir -Recurse -Force
    Remove-Item -LiteralPath $zipPath -Force
}

function Test-VcRuntimePresent {
    return Test-Path -LiteralPath (Join-Path $env:SystemRoot "System32\vcruntime140.dll")
}

function Install-VcRedist {
    if (Test-VcRuntimePresent) { return }

    $arch = $env:PROCESSOR_ARCHITEW6432
    if (-not $arch) { $arch = $env:PROCESSOR_ARCHITECTURE }
    $redistName = "vc_redist.x64.exe"
    $redistUrl = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
    if ($arch -eq "ARM64") {
        $redistName = "vc_redist.arm64.exe"
        $redistUrl = "https://aka.ms/vs/17/release/vc_redist.arm64.exe"
    }

    $installer = Join-Path $toolsDir $redistName
    Write-Host "CPython needs the Microsoft Visual C++ runtime. Downloading it..."
    Invoke-WebRequest -Uri $redistUrl -OutFile $installer -UseBasicParsing
    Write-Host "A Windows prompt may ask for administrator rights to install the runtime."
    try {
        $proc = Start-Process -FilePath $installer -ArgumentList "/install", "/quiet", "/norestart" -Wait -PassThru -Verb RunAs
    } catch {
        throw "Visual C++ runtime was not installed. Approve the Windows prompt or install it manually, then run this script again. $($_.Exception.Message)"
    }
    $code = $proc.ExitCode
    # 0 = installed, 1638 = another version already present, 3010 = success, reboot required.
    if ($code -ne 0 -and $code -ne 1638 -and $code -ne 3010) {
        throw "Visual C++ runtime installer exited with code $code."
    }
}

function Set-DotEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $utf8 = New-Object System.Text.UTF8Encoding $false
    $lines = New-Object System.Collections.Generic.List[string]
    if (Test-Path -LiteralPath $envPath) {
        foreach ($line in [System.IO.File]::ReadAllLines($envPath)) {
            $lines.Add($line)
        }
    }
    $pattern = "^\s*#?\s*$([regex]::Escape($Name))\s*="
    $updated = $false
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index] -match $pattern) {
            $lines[$index] = "$Name=$Value"
            $updated = $true
            break
        }
    }
    if (-not $updated) { $lines.Add("$Name=$Value") }
    [System.IO.File]::WriteAllLines($envPath, $lines, $utf8)
}

function Normalize-InferenceUrl {
    param([Parameter(Mandatory = $true)][string]$Url)
    $normalized = $Url.Trim().TrimEnd("/")
    if ($normalized -match '/v1$') {
        $normalized = $normalized.Substring(0, $normalized.Length - 3).TrimEnd("/")
        Write-Host "Stored OLLAMA_URL without /v1. The app appends /v1/embeddings and /v1/chat/completions."
    }
    return $normalized
}

Install-VcRedist
Install-Uv

$env:UV_PYTHON_INSTALL_DIR = $pythonDir
Write-Host "Installing CPython $PythonVersion into .python ..."
& $uvExe python install $PythonVersion --install-dir $pythonDir --no-registry --no-config
if ($LASTEXITCODE -ne 0) { throw "uv python install failed with exit code $LASTEXITCODE." }

$venvReady = $false
if (Test-Path -LiteralPath $venvPython) {
    & $venvPython -c "import sys"
    if ($LASTEXITCODE -eq 0) { $venvReady = $true }
}
if (-not $venvReady) {
    Write-Host "Creating .venv ..."
    if (Test-Path -LiteralPath (Join-Path $projectRoot ".venv")) {
        & $uvExe venv .venv --python $PythonVersion --managed-python --clear --force --no-config
    } else {
        & $uvExe venv .venv --python $PythonVersion --managed-python --no-config
    }
    if ($LASTEXITCODE -ne 0) { throw "uv venv failed with exit code $LASTEXITCODE." }
}

Write-Host "Installing Python packages from requirements.txt (без sentence-transformers; см. requirements-rerank.txt)."
& $uvExe pip install --python $venvPython --managed-python --no-config -r (Join-Path $projectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "uv pip install failed with exit code $LASTEXITCODE." }

if (-not (Test-Path -LiteralPath $envPath)) {
    if (-not (Test-Path -LiteralPath $examplePath)) {
        throw ".env.example was not found."
    }
    Copy-Item -LiteralPath $examplePath -Destination $envPath
    Write-Host "Created .env from .env.example"
}

$wroteInference = $false
if ($InferenceUrl) {
    Set-DotEnvValue -Name "INFERENCE_BACKEND" -Value "lmstudio"
    Set-DotEnvValue -Name "OLLAMA_URL" -Value (Normalize-InferenceUrl -Url $InferenceUrl)
    $wroteInference = $true
}
if ($ApiKey) {
    Set-DotEnvValue -Name "OPENAI_API_KEY" -Value $ApiKey
    $wroteInference = $true
}
if ($ChatModel) {
    Set-DotEnvValue -Name "OLLAMA_CHAT_MODEL" -Value $ChatModel
    $wroteInference = $true
}
if ($EmbeddingModel) {
    Set-DotEnvValue -Name "OLLAMA_EMBEDDING_MODEL" -Value $EmbeddingModel
    $wroteInference = $true
}

Write-Host ""
Write-Host "Python is ready: $venvPython"
if ($wroteInference) {
    Write-Host "Cloud model settings were written to .env."
} else {
    Write-Host "Point .env at the cloud model before the first launch:"
    Write-Host "  INFERENCE_BACKEND=lmstudio"
    Write-Host "  OLLAMA_URL=https://api.example.com"
    Write-Host "  OPENAI_API_KEY=..."
    Write-Host "  OLLAMA_CHAT_MODEL=..."
    Write-Host "  OLLAMA_EMBEDDING_MODEL=..."
    Write-Host "OLLAMA_URL is the base address without /v1."
}
Write-Host "Start the app with start.bat"
