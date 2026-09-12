$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$envPath = Join-Path $projectRoot ".env"
$logsPath = Join-Path $projectRoot "logs"

Set-Location $projectRoot
New-Item -ItemType Directory -Force -Path $logsPath | Out-Null

if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual environment was not found: $python"
}

function Stop-ProjectPythonProcess {
    param([Parameter(Mandatory = $true)][string]$Pattern)

    $processes = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -match "^python(w)?\.exe$" -and $_.CommandLine -match $Pattern
    }
    foreach ($process in $processes) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Get-DotEnvValue {
    param([Parameter(Mandatory = $true)][string]$Name)

    if (-not (Test-Path -LiteralPath $envPath)) { return $null }
    $line = Get-Content -LiteralPath $envPath | Where-Object {
        $_ -match "^$([regex]::Escape($Name))="
    } | Select-Object -First 1
    if ($null -eq $line) { return $null }
    return ($line -split "=", 2)[1].Trim()
}

function Set-DotEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value
    )

    $lines = if (Test-Path -LiteralPath $envPath) {
        [System.Collections.Generic.List[string]](Get-Content -LiteralPath $envPath)
    } else {
        [System.Collections.Generic.List[string]]::new()
    }
    $prefix = "$Name="
    $updated = $false
    for ($index = 0; $index -lt $lines.Count; $index++) {
        if ($lines[$index].StartsWith($prefix, [System.StringComparison]::Ordinal)) {
            $lines[$index] = "$prefix$Value"
            $updated = $true
            break
        }
    }
    if (-not $updated) { $lines.Add("$prefix$Value") }
    [System.IO.File]::WriteAllLines($envPath, $lines, [System.Text.UTF8Encoding]::new($false))
}

function Wait-ForHealth {
    for ($attempt = 1; $attempt -le 20; $attempt++) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:5000/api/health" -TimeoutSec 2
            if ($response.StatusCode -eq 200) { return $true }
        } catch {
            Start-Sleep -Milliseconds 750
        }
    }
    return $false
}

Write-Host "Restarting Wiki QA..."
Stop-ProjectPythonProcess "scripts[\\/]telegram_bot_worker\.py"
Stop-ProjectPythonProcess "web_app\.py"
Start-Sleep -Seconds 1

$listeners = Get-NetTCPConnection -State Listen -LocalPort 5000 -ErrorAction SilentlyContinue
foreach ($listener in $listeners) {
    Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
}

$webStdout = Join-Path $logsPath "web_app_stdout.log"
$webStderr = Join-Path $logsPath "web_app_stderr.log"
Start-Process -FilePath $python -ArgumentList "web_app.py" -WorkingDirectory $projectRoot `
    -WindowStyle Hidden -RedirectStandardOutput $webStdout -RedirectStandardError $webStderr | Out-Null

if (-not (Wait-ForHealth)) {
    $details = if (Test-Path -LiteralPath $webStderr) {
        (Get-Content -LiteralPath $webStderr -Tail 20) -join [Environment]::NewLine
    } else { "Startup log was not created." }
    throw "Web application failed to start.`n$details"
}
Write-Host "[OK] Site: http://127.0.0.1:5000/"

$webAppEnabled = (Get-DotEnvValue "TELEGRAM_WEBAPP_ENABLED") -eq "true"
$cloudflared = Join-Path $projectRoot "cloudflared.exe"
if ($webAppEnabled -and (Test-Path -LiteralPath $cloudflared)) {
    $tunnelProcess = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -eq "cloudflared.exe" -and $_.ExecutablePath -eq $cloudflared
    } | Select-Object -First 1

    if ($null -eq $tunnelProcess) {
        $tunnelStdout = Join-Path $logsPath "cloudflared_stdout.log"
        $tunnelStderr = Join-Path $logsPath "cloudflared_stderr.log"
        Start-Process -FilePath $cloudflared `
            -ArgumentList @("tunnel", "--url", "http://127.0.0.1:5000", "--no-autoupdate") `
            -WorkingDirectory $projectRoot -WindowStyle Hidden `
            -RedirectStandardOutput $tunnelStdout -RedirectStandardError $tunnelStderr | Out-Null

        $tunnelUrl = $null
        for ($attempt = 1; $attempt -le 30 -and -not $tunnelUrl; $attempt++) {
            Start-Sleep -Seconds 1
            if (Test-Path -LiteralPath $tunnelStderr) {
                $logText = Get-Content -LiteralPath $tunnelStderr -Raw
                $match = [regex]::Match($logText, "https://[a-z0-9-]+\.trycloudflare\.com")
                if ($match.Success) { $tunnelUrl = $match.Value }
            }
        }
        if (-not $tunnelUrl) {
            throw "Cloudflare Tunnel did not provide a public URL. Check logs\cloudflared_stderr.log"
        }
        Set-DotEnvValue "TELEGRAM_WEBAPP_URL" "$tunnelUrl/telegram-app"
        Write-Host "[OK] Telegram Mini App: $tunnelUrl/telegram-app"
    } else {
        Write-Host "[OK] Cloudflare Tunnel is running"
    }
}

if ((Get-DotEnvValue "TELEGRAM_ENABLED") -eq "true") {
    Start-Process -FilePath $python -ArgumentList "scripts\telegram_bot_worker.py" `
        -WorkingDirectory $projectRoot -WindowStyle Hidden | Out-Null
    Start-Sleep -Seconds 2

    $worker = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.Name -match "^python(w)?\.exe$" -and $_.CommandLine -match "scripts[\\/]telegram_bot_worker\.py"
    } | Select-Object -First 1
    if ($null -eq $worker) {
        throw "Telegram worker failed to start. Check logs\wiki_qa_error.log"
    }
    Write-Host "[OK] Telegram worker is running"
}

Write-Host "Ready. Run update_wiki.bat separately to refresh the knowledge base."
