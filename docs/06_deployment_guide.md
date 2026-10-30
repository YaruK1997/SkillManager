# SkillManager 部署與維運指南 (docs/06_deployment_guide.md)

## 1. 環境需求與前置條件

- **本機原生模式 (Native Execution)**：
  - 作業系統：Windows 10/11 (PowerShell 7 / CMD)、macOS 12+ (Zsh / Bash)、Linux (Ubuntu 20.04+ / Debian 12+)
  - 套件管理與執行期：`uv >= 0.11`、Python `>= 3.15`、Git CLI `>= 2.30`
- **容器化部署模式 (Containerized Deployment)**：
  - Docker Engine `>= 24.0` (Docker Desktop 4.20+ / Docker CE)
  - Docker Compose `v2.20+`

---

## 2. 容器化架構設計

### 2.1 多階段建置 (`Dockerfile`)
1. **Stage 1 (`builder`)**：
   - 基於 `ghcr.io/astral-sh/uv:debian-slim`，透過 `uv` 高速建置工具將 CPython 3.15 安裝至 `/opt/python`。
   - 建立獨立虛擬環境於 `/opt/venv`，完成 `pyyaml` 與 `skill-manager` 及其依賴套件之編譯與 Bytecode 預編譯。
2. **Stage 2 (`runtime`)**：
   - 基於輕量化 `debian:bookworm-slim`，僅安裝 `git` 與 `ca-certificates` 等必要工具。
   - 建立非特權使用者 `appuser (UID 1000 / GID 1000)`，杜絕 Root 權限逃逸風險，落實最小權限原則。
   - 映像檔僅包含編譯後之 `/opt/python` 與 `/opt/venv`，維持極簡體積。

### 2.2 服務編排與資源隔離 (`docker-compose.yml`)
- **服務名稱**：`skill-manager`（映像檔標籤：`skill-manager:0.2.0`）
- **網路隔離**：綁定專屬 Bridge 網路 `skill-net`。
- **跨平台本機技能掛載 (Windows / macOS / Linux)**：
  - 於建構時自動偵測本機作業系統類型，取得各平台 Host Home 目錄（Windows: `%USERPROFILE%`，macOS / Linux: `$HOME`）。
  - 自動映射本機全域技能目錄至容器非 root 使用者環境：
    - `${HOST_GEMINI_SKILLS_DIR}:/home/appuser/.gemini/antigravity/skills`
    - `${HOST_CLAUDE_SKILLS_DIR}:/home/appuser/.claude/skills`
    - `${HOST_CODEX_SKILLS_DIR}:/home/appuser/.codex/skills`
    - `${HOST_CURSOR_SKILLS_DIR}:/home/appuser/.cursor/skills`
  - `docker-compose.yml` 支援 `${HOST_GEMINI_SKILLS_DIR:-${HOST_HOME:-${USERPROFILE:-$HOME}}/...}` 三層容錯回退機制。
- **資源限制 (NFR-05 合規)**：
  - CPU 限制：上限 `0.50 Core`（保留 `0.10 Core`）。
  - 記憶體限制：上限 `128 MB`（保留 `32 MB`）。
- **容器健康探針 (Healthcheck)**：
  - 間隔：15 秒，逾時：5 秒，重試：3 次。
  - 探針指令：`CMD skill-manager healthcheck --format json`。

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
=== [1/4] Detecting Host Operating System & Preparing Environment ===
[INFO] Host Operating System : macOS
[INFO] Host Home Directory   : /Users/yaru
[INFO] Host Gemini Skills    : /Users/yaru/.gemini/antigravity/skills
[INFO] Host Claude Skills    : /Users/yaru/.claude/skills

=== [2/4] Building SkillManager Docker Image (macOS) ===
 Image skill-manager:0.2.0 Built

=== [3/4] Starting SkillManager Container & Mounting Host Skills ===
 Container skill-manager Started

=== [4/4] Waiting for Container Healthcheck Probe ===
Attempt 1/10 : Container status = starting
Attempt 2/10 : Container status = healthy

=== Verifying CLI Healthcheck Endpoint Inside Container ===
{
  "status": "healthy",
  "code": 200,
  "version": "0.2.0",
  "python": "3.15.2"
}
[SUCCESS] SkillManager deployed and verified HEALTHY (200) on macOS!
  "code": 200,
  "version": "0.2.0",
  "python": "3.15.2"
}
[SUCCESS] SkillManager deployed and verified HEALTHY (200)!
```

---

## 4. 常用容器操作指令

```powershell
# 1. 檢視容器運行與健康狀態
docker compose ps

# 2. 檢視容器即時日誌
docker compose logs -f skill-manager

# 3. 於容器內執行全域技能掃描
docker exec skill-manager skill-manager scan --format json

# 4. 於容器內執行遠端技能搜尋
docker exec skill-manager skill-manager search "agent-skills" --format table

# 5. 於容器內執行工作流技能審計
docker exec skill-manager skill-manager workflow-audit --workflow /app/workflow.md --format table

# 6. 停止並移除容器與網路
docker compose down
```

---

## 5. 階段交付檢核清單 (Phase 5 Gate Checklist)

- [x] **輕量化映像檔建置**：`Dockerfile` 採用多階段構建（Builder / Runtime），非 root 使用者 `appuser (1000:1000)` 運行。
- [x] **服務編排與資源控制**：`docker-compose.yml` 配置獨立網路、Named Volume 與 128MB 記憶體上限。
- [x] **容器啟動與健康檢查**：容器啟動無報錯，Healthcheck 探針回傳 `healthy`，`healthcheck` 端點回傳 200/Healthy（Version 0.2.0）。
- [x] **一鍵部署腳本**：`deploy.ps1` 與 `deploy.sh` 實作自動建置、啟動、探針等待與終端驗證流程。
- [x] **文件齊備**：`docs/06_deployment_guide.md` 與 `docs/07_changelog.md` 已完整更新。
