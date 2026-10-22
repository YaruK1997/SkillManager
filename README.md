# SkillManager — Cross-Platform Local AI Skills & Plugins Manager

**SkillManager** 是一套跨平台（Windows / macOS / Linux）全域 AI 技能與插件管理工具，支援 **Claude Code**、**Google Antigravity**、**OpenAI Codex / Copilot**、**Cursor** 等開發環境。

## 核心功能

1. **跨平台全域技能掃描 (`scan`)**：自動探測本機各平台全域技能目錄，解析 `SKILL.md` 之 YAML Frontmatter 與 Git 版本狀態。
2. **遠端技能檢索 (`search`)**：串接 GitHub REST API 與 HuggingFace Hub API，支援 3 次指數退避重試與 Rate Limit 防護。
3. **依據 `index.md` 結構審計與補全 (`audit` / `complete`)**：比對索引規範，自動產出 Unified Diff 並透過原子寫入（Atomic Replace）安全補全缺失章節與子目錄。
4. **版本控制與安全更新 (`track`)**：比對本機與遠端 Commit SHA，支援升級前自動建立快照標籤（`backup-pre-upgrade-<timestamp>`）、Dirty Worktree 保護與一鍵回滾（`rollback`）。
5. **雙模輸出 (`--format table|json`)**：支援終端 Rich 表格與無 ANSI 色碼之純 JSON 輸出，方便其他 AI Agent 或腳本直接串接。

## 快速開始

### 本機執行 (使用 `uv`)

```powershell
# 建立 Python 3.15 虛擬環境並安裝
uv venv --python 3.15
uv pip install -e .

# 掃描本機所有平台技能
.venv\Scripts\skill-manager scan --format table

# 搜尋遠端技能
.venv\Scripts\skill-manager search "code-review" --source all

# 審計並補全技能
.venv\Scripts\skill-manager audit --target ./my-skill --index ./index.md
.venv\Scripts\skill-manager complete --target ./my-skill --index ./index.md --no-dry-run

# 追蹤版本與升級回滾
.venv\Scripts\skill-manager track status --target ./my-skill
.venv\Scripts\skill-manager track upgrade --target ./my-skill
.venv\Scripts\skill-manager track rollback --target ./my-skill
```

### 容器化部署 (Docker Compose)

```powershell
docker compose up -d --build
docker compose ps
```

