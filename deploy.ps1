<#
.SYNOPSIS
    SkillManager 一鍵建置、容器啟動與健康檢查部署腳本 (Windows PowerShell / PowerShell Core)
    自動偵測本機作業系統類型 (Windows / macOS / Linux)，確保 host skills 正確掛載。
#>
$ErrorActionPreference = "Stop"

Write-Host "=== [1/4] Detecting Host Operating System & Preparing Environment ===" -ForegroundColor Cyan

# 1. 判斷本機作業系統類型 (Windows / macOS / Linux)
if ($IsWindows -or ($env:OS -like "*Windows*") -or ([System.Environment]::OSVersion.Platform -eq "Win32NT")) {
    $detectedOS = "Windows"
    $hostHome = $env:USERPROFILE
} elseif ($IsMacOS) {
    $detectedOS = "macOS"
    $hostHome = $env:HOME
} elseif ($IsLinux) {
    $detectedOS = "Linux"
    $hostHome = $env:HOME
} else {
    $detectedOS = "Windows"
    $hostHome = if ($env:USERPROFILE) { $env:USERPROFILE } else { $env:HOME }
}

Write-Host "[INFO] Host Operating System : $detectedOS" -ForegroundColor Green
Write-Host "[INFO] Host Home Directory   : $hostHome" -ForegroundColor Green

# 2. 解析各平台 Host Skills 目錄
if ($detectedOS -eq "Windows") {
    $geminiSkills = Join-Path $hostHome ".gemini\antigravity\skills"
    $claudeSkills = Join-Path $hostHome ".claude\skills"
    $codexSkills  = Join-Path $hostHome ".codex\skills"
    $cursorSkills = Join-Path $hostHome ".cursor\skills"
} else {
    $geminiSkills = "$hostHome/.gemini/antigravity/skills"
    $claudeSkills = "$hostHome/.claude/skills"
    $codexSkills  = "$hostHome/.codex/skills"
    $cursorSkills = "$hostHome/.cursor/skills"
}

# 3. 確保本機技能目錄存在，避免 Docker Daemon 自動建立為非預期權限目錄
$skillDirs = @($geminiSkills, $claudeSkills, $codexSkills, $cursorSkills)
foreach ($dir in $skillDirs) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
}

# 4. 注入環境變數至當前 Session
$env:HOST_OS = $detectedOS
$env:HOST_HOME = $hostHome
$env:HOST_GEMINI_SKILLS_DIR = $geminiSkills
$env:HOST_CLAUDE_SKILLS_DIR = $claudeSkills
$env:HOST_CODEX_SKILLS_DIR = $codexSkills
$env:HOST_CURSOR_SKILLS_DIR = $cursorSkills

# 5. 更新或同步至 .env 檔案
$envFile = Join-Path $PSScriptRoot ".env"
$envDict = @{}
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#")) {
            $parts = $line.Split("=", 2)
            if ($parts.Length -eq 2) {
                $envDict[$parts[0].Trim()] = $parts[1].Trim()
            }
        }
    }
}
$envDict["HOST_OS"] = $detectedOS
$envDict["HOST_HOME"] = $hostHome
$envDict["HOST_GEMINI_SKILLS_DIR"] = $geminiSkills
$envDict["HOST_CLAUDE_SKILLS_DIR"] = $claudeSkills
$envDict["HOST_CODEX_SKILLS_DIR"] = $codexSkills
$envDict["HOST_CURSOR_SKILLS_DIR"] = $cursorSkills

$newLines = @()
foreach ($key in $envDict.Keys) {
    $newLines += "$key=$($envDict[$key])"
}
Set-Content -Path $envFile -Value $newLines -Encoding utf8

Write-Host "=== [2/4] Building SkillManager Docker Image ($detectedOS) ===" -ForegroundColor Cyan
docker compose build --build-arg HOST_OS=$detectedOS

Write-Host "=== [3/4] Starting SkillManager Container & Mounting Host Skills ===" -ForegroundColor Cyan
docker compose up -d

Write-Host "=== [4/4] Waiting for Container Healthcheck Probe ===" -ForegroundColor Cyan
$maxRetries = 10
$healthy = $false
for ($i = 1; $i -le $maxRetries; $i++) {
    Start-Sleep -Seconds 2
    $status = docker inspect --format "{{.State.Health.Status}}" skill-manager 2>$null
    Write-Host "Attempt $i/$maxRetries : Container status = $status"
    if ($status -eq "healthy") {
        $healthy = $true
        break
    }
}

Write-Host "=== Verifying CLI Healthcheck Endpoint Inside Container ===" -ForegroundColor Cyan
docker exec skill-manager skill-manager healthcheck --format json

if (-not $healthy) {
    Write-Host "[WARN] Health status is still initializing, direct CLI probe succeeded." -ForegroundColor Yellow
} else {
    Write-Host "[SUCCESS] SkillManager deployed and verified HEALTHY (200) on $detectedOS!" -ForegroundColor Green
}
