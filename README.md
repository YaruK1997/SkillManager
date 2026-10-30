# SkillManager — Cross-Platform Local AI Skills & Plugins Manager

[![Version](https://img.shields.io/badge/version-0.2.0-blue.svg)](docs/07_changelog.md)
[![Python](https://img.shields.io/badge/python-3.15%2B-blue.svg)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-93%20passed-success.svg)](docs/04_test_report.md)
[![Coverage](https://img.shields.io/badge/coverage-88%25-brightgreen.svg)](docs/04_test_report.md)
[![Security](https://img.shields.io/badge/security-0%20vulnerabilities-brightgreen.svg)](docs/05_security_audit.md)
[![Docker](https://img.shields.io/badge/docker-healthy-brightgreen.svg)](docs/06_deployment_guide.md)

**SkillManager** 是一套跨平台（Windows / macOS / Linux）本機全域 AI 技能與插件管理工具，支援 **Claude Code**、**Google Antigravity**、**OpenAI Codex / Copilot** 與 **Cursor** 等主流 Agent 開發環境。

---

## 🌟 核心功能

1. **跨平台全域技能掃描 (`scan`)**：
   - 自動探測本機各平台技能目錄，採用 `os.scandir` 串流走訪與 `visited_realpaths` 循環符號連結防護。
   - 完整解析 `SKILL.md` 之 YAML Frontmatter 與 Git 版本元數據。
2. **遠端技能檢索 (`search`)**：
   - 串接 GitHub REST API 與 HuggingFace Hub API 關鍵字與標籤查詢。
   - 內建 3 次指數退避重試（1s, 2s, 4s）與 HTTP 429 Rate Limit 防護機制。
3. **結構審計與原子補全 (`audit` / `complete`)**：
   - 比對 `index.md` 規範章節與目錄，產出標準 Unified Diff。
   - 採用 PID 隔離暫存檔搭配 `Path.replace()` 作業系統層級原子置換，防止斷電或中斷時產生半毀檔案。
4. **Git 版本控制與安全升級 (`track`)**：
   - 比對本機與遠端 Commit SHA（狀態：`UP_TO_DATE`、`BEHIND`、`AHEAD`、`DIVERGED`、`UNTRACKED`、`NETWORK_TIMEOUT`）。
   - 升級前自動建立 `backup-pre-upgrade-<timestamp>` 安全快照標籤，支援 Dirty Worktree 保護與一鍵回滾（`rollback`）。
5. **工作流技能審計與自動補全 (`workflow-audit`) [v0.2.0 新增]**：
   - 自動解析 `workflow.md`、`AGENTS.md` 之技能依賴與路徑參照，分類為 `INSTALLED`、`MISSING` 與 `INCOMPLETE`。
   - 支援從本地備用技能目錄複製安裝或調用 Indexer 引擎自動生成合規骨架，支援 `--dry-run` 預覽。
6. **設定檔與路徑覆寫 (`config`)**：
   - 支援 `config.toml` 配置各平台自訂目錄映射與 API 憑證。
7. **雙模輸出格式 (`--format table|json`)**：
   - 終端提供 Rich 高可讀性表格，亦可輸出無 ANSI 色碼之乾淨 JSON，便於 CI/CD 與其他 Agent 串接。

---

## 🚀 快速開始 (本機模式)

### 1. 環境安裝 (使用 `uv`)

```bash
# 1. 建立 Python 3.15 虛擬環境並安裝
uv venv --python 3.15
uv pip install -e .
```

### 2. 常用本機 CLI 指令

```powershell
# 掃描本機全域技能
skill-manager scan --format table

# 搜尋 GitHub 與 HuggingFace 遠端技能
skill-manager search "code-review" --source all --format table

# 依據 index.md 審計技能結構
skill-manager audit --target ./my-skill --index ./index.md

# 自動補全缺失章節與子目錄（實際寫入）
skill-manager complete --target ./my-skill --index ./index.md --no-dry-run

# 檢查 Git 版本狀態、升級與回滾
skill-manager track status --target ./my-skill
skill-manager track upgrade --target ./my-skill
skill-manager track rollback --target ./my-skill

# 審計當前工作流所需技能（支援自動補全）
skill-manager workflow-audit --workflow ./workflow.md --format table
skill-manager workflow-audit --workflow ./workflow.md --auto-complete --no-dry-run

# 查看目前設定檔配置
skill-manager config --show
```

---

## 🐳 容器化部署與維運 (Docker & Docker Compose)

SkillManager 提供符合生產生態之多階段建構 Docker 映像檔，具備非特權使用者運行、記憶體上限保護、獨立網路與內建 Healthcheck 探針。

### 1. 一鍵自動化部署腳本

專案已內建全自動化建置、啟動與健全度探針等待腳本：

- **Windows PowerShell**：
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\deploy.ps1
  ```
- **Linux / macOS Bash**：
  ```bash
  chmod +x ./deploy.sh
  ./deploy.sh
  ```

實測部署流程將自動完成映像檔構建、容器啟動與探針檢測，輸出如下驗證資訊：
```text
=== [1/4] Building SkillManager Docker Image ===
 Image skill-manager:0.2.0 Built
=== [2/4] Starting SkillManager Container ===
 Container skill-manager Started
=== [3/4] Waiting for Container Healthcheck Probe ===
Attempt 1/10 : Container status = starting
Attempt 2/10 : Container status = healthy
=== [4/4] Verifying CLI Healthcheck Endpoint Inside Container ===
{
  "status": "healthy",
  "code": 200,
  "version": "0.2.0",
  "python": "3.15.2"
}
[SUCCESS] SkillManager deployed and verified HEALTHY (200)!
```

---

### 2. 手動 Docker Compose 操作指令

#### 啟動服務
```bash
# 建置並於背景啟動容器
docker compose up -d --build

# 檢查容器運行與健康檢查狀態
docker compose ps
```

#### 檢視即時日誌
```bash
docker compose logs -f skill-manager
```

#### 於容器內執行 SkillManager 命令列
```bash
# 1. 探針健康狀態檢查 (JSON 輸出)
docker exec skill-manager skill-manager healthcheck --format json

# 2. 於容器內執行技能掃描
docker exec skill-manager skill-manager scan --format table

# 3. 於容器內搜尋遠端技能庫
docker exec skill-manager skill-manager search "agent-skills" --format table

# 4. 於容器內審計工作流程技能需求
docker exec skill-manager skill-manager workflow-audit --workflow /app/workflow.md --format table

# 5. 檢視容器內設定檔配置
docker exec skill-manager skill-manager config --show
```

#### 停止與清理容器
```bash
# 停止容器並保留資料卷
docker compose down

# 停止容器並一併清除 Volume 資料卷
docker compose down -v
```

---

### 3. 容器架構與安全規格

| 特性 | 規格說明 |
| :--- | :--- |
| **基礎映像檔** | Stage 1: `ghcr.io/astral-sh/uv:debian-slim` (CPython 3.15)<br>Stage 2: `debian:bookworm-slim` (極簡執行期) |
| **執行身分** | 非 Root 使用者 `appuser (UID 1000 / GID 1000)`，落實最小權限原則 |
| **網路隔離** | 專屬 Bridge 網路 `skill-net` |
| **資源限制** | CPU 限制 `0.50 Core`；記憶體限制 `128 MB`（保留 `32 MB`） |
| **資料持久化與掛載** | 自動跨平台判斷本機 OS (Windows `%USERPROFILE%` / macOS `$HOME` / Linux `$HOME`)，自動映射本機全域技能目錄至容器中 |
| **健康檢查探針** | 每 15 秒執行 `CMD skill-manager healthcheck --format json`，回傳 200/Healthy |

#### 本機技能目錄掛載 (自動跨平台支援)
SkillManager 於 Docker 建構與啟動時，會自動判斷本機作業系統類型（Windows / macOS / Linux），並透過 `docker-compose.yml` 將主機上的各 AI 技能目錄掛載至容器內：

```yaml
volumes:
  - ${HOST_GEMINI_SKILLS_DIR:-${HOST_HOME:-${USERPROFILE:-$HOME}}/.gemini/antigravity/skills}:/home/appuser/.gemini/antigravity/skills
  - ${HOST_CLAUDE_SKILLS_DIR:-${HOST_HOME:-${USERPROFILE:-$HOME}}/.claude/skills}:/home/appuser/.claude/skills
  - ${HOST_CODEX_SKILLS_DIR:-${HOST_HOME:-${USERPROFILE:-$HOME}}/.codex/skills}:/home/appuser/.codex/skills
  - ${HOST_CURSOR_SKILLS_DIR:-${HOST_HOME:-${USERPROFILE:-$HOME}}/.cursor/skills}:/home/appuser/.cursor/skills
```

透過一鍵部署腳本（`deploy.sh` 或 `deploy.ps1`）執行時，系統會自動探測 OS、預先確認目錄存在並將環境變數寫入 `.env`，確保本機技能得以無縫被容器內程式掃描與審計。

#### 設定遠端 API 憑證 (選用)
如需提高 GitHub 或 HuggingFace API 查詢上限，可於啟動前設定環境變數或建立 `.env` 檔案：
```bash
GITHUB_TOKEN=ghp_your_personal_access_token
HF_TOKEN=hf_your_huggingface_access_token
```

---

## 🔒 資訊安全與合規防禦 (Security & CWE Defense)

SkillManager 遵循安全編碼規範，並將安全性檢驗納入自動化測試套件（CI/CD 迴歸防護）：
- **CWE-78 (指令注入)**：0 處 `shell=True`、`os.system` 或 `eval`。
- **CWE-88 (參數注入)**：`_validate_git_ref` 白名單正則過濾，攔截 `--upload-pack` 等惡意 Git 旗標注入。
- **CWE-22 (路徑周遊)**：`indexer` 透過 `is_relative_to` 嚴守目錄邊界；`workflow_auditor` 白名單過濾 `../` 逃逸字串。
- **CWE-502 (反序列化)**：YAML 強制 `safe_load()`；設定檔採用唯讀 `tomllib.loads()`。
- **CWE-400 (資源耗盡)**：前置 50MB/10MB 檔案大小門檻、循環 Symlink 集合攔截、連線逾時保護。
- **SCA 依賴審計**：全專案經 `uv audit` 審查，**0 已知 CVE 漏洞**。

---

## 📖 專案工程文件導覽

本專案各階段規格、測試與部署文件均完整歸檔於 `docs/` 目錄：

- 📋 [需求規格說明書 (docs/01_spec.md)](docs/01_spec.md)：FR-01 至 FR-06 需求定義、27 項驗收標準 (AC) 與異常邊界 (EC)。
- 📐 [系統架構設計說明 (docs/02_architecture.md)](docs/02_architecture.md)：模組架構圖、資料模型與分層責任。
- 🧪 [測試計畫設計 (docs/03_test_plan.md)](docs/03_test_plan.md)：R1–R3 分組極限測試矩陣與追溯表。
- 📊 [測試執行與驗證報告 (docs/04_test_report.md)](docs/04_test_report.md)：93 項自動化測試通過紀錄、88% 覆蓋率與 Code Review 整改紀錄。
- 🛡️ [資訊安全審計報告 (docs/05_security_audit.md)](docs/05_security_audit.md)：CWE 靜態分析、機敏掃描與 SCA 清查。
- 🚢 [部署與維運指南 (docs/06_deployment_guide.md)](docs/06_deployment_guide.md)：詳細容器化編排、探針指標與維運手冊。
- 📝 [版本變更日誌 (docs/07_changelog.md)](docs/07_changelog.md)：v0.1.0 與 v0.2.0 詳細版本演進紀錄。
