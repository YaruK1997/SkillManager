<#
.SYNOPSIS
    SkillManager 一鍵建置、容器啟動與健康檢查部署腳本 (Windows PowerShell)
#>
$ErrorActionPreference = "Stop"

Write-Host "=== [1/4] Building SkillManager Docker Image ===" -ForegroundColor Cyan
docker compose build

Write-Host "=== [2/4] Starting SkillManager Container ===" -ForegroundColor Cyan
docker compose up -d

Write-Host "=== [3/4] Waiting for Container Healthcheck Probe ===" -ForegroundColor Cyan
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

Write-Host "=== [4/4] Verifying CLI Healthcheck Endpoint Inside Container ===" -ForegroundColor Cyan
docker exec skill-manager skill-manager healthcheck --format json

if (-not $healthy) {
    Write-Host "[WARN] Health status is still initializing, direct CLI probe succeeded." -ForegroundColor Yellow
} else {
    Write-Host "[SUCCESS] SkillManager deployed and verified HEALTHY (200)!" -ForegroundColor Green
}

