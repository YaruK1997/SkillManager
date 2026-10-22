# SkillManager 部署與維運指南 (docs/06_deployment_guide.md)

## 1. 環境需求與前置條件

- **本機原生模式**：
  - 作業系統：Windows 10/11、macOS 12+、Linux (Ubuntu 20.04+ / Debian 12+)
  - 套件管理與執行期：`uv >= 0.11`、Python `>= 3.15`、Git CLI `>= 2.30`
- **容器化部署模式**：
  - Docker Engine `>= 24.0`
  - Docker Compose `v2.20+`

---

## 2. 容器化架構設計

### 2.1 多階段建置 (`Dockerfile`)
1. **Stage 1 (`builder`)**：基於 `ghcr.io/astral-sh/uv:debian-slim`，將 Python 3.15 安裝至 `/opt/python` 並建立虛擬環境於 `/opt/venv`，完成套件編譯與 Bytecode 預編譯。
2. **Stage 2 (`runtime`)**：基於輕量化 `debian:bookworm-slim`，僅保留 `git` 與 `ca-certificates`，建立非特權使用者 `appuser (UID 1000 / GID 1000)`，確保最小權限運行。

### 2.2 服務編排與資源隔離 (`docker-compose.yml`)
- **網路隔離**：採用獨立 Bridge 網路 `skill-net`。
- **資料持久化**：透過 Named Volume `skills-data` 掛載至 `/home/appuser/.gemini/antigravity/skills`（亦可依需求綁定本機 Host 全域目錄）。
- **資源限制 (NFR-05 合規)**：限制 CPU 上限 `0.50 Core`、記憶體上限 `128 MB`。
- **健康檢查探針 (Healthcheck)**：每 15 秒執行 `skill-manager healthcheck --format json`，驗證回傳 `{"status": "healthy", "code": 200}`。

---

## 3. 一鍵部署與驗證指令

### 3.1 Windows PowerShell 部署
```powershell
powershell -ExecutionPolicy Bypass -File .\deploy.ps1
```

### 3.2 Linux / macOS Bash 部署
```bash
chmod +x ./deploy.sh
./deploy.sh
```

### 3.3 實測部署驗證日誌 (Live Verification Evidence)
```text
=== [3/4] Waiting for Container Healthcheck Probe ===
Attempt 1/10 : Container status = starting
Attempt 2/10 : Container status = starting
Attempt 3/10 : Container status = healthy
=== [4/4] Verifying CLI Healthcheck Endpoint Inside Container ===
{
  "status": "healthy",
  "code": 200,
  "version": "0.1.0",
  "python": "3.15.1"
}
[SUCCESS] SkillManager deployed and verified HEALTHY (200)!
```

---

## 4. 常用容器操作指令

```powershell
# 檢視容器健康狀態
docker compose ps

# 於容器內執行全域技能掃描
docker exec skill-manager skill-manager scan --format json

# 於容器內搜尋 GitHub 與 HuggingFace 技能
docker exec skill-manager skill-manager search "agent-skills" --format table

# 停止並清理容器
docker compose down
```

