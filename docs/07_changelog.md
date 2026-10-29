# SkillManager 變更日誌 (docs/07_changelog.md)

## [0.2.0] - 2026-10-29

### Added (新增功能)
- **工作流所需技能審計與啟動自動補全 (`core.workflow_auditor`) (FR-06)**：
  - **工作流需求解析 (`parse_workflow_requirements`)**：精準解析各類 Markdown 工作流程規範（如 `workflow.md`、`AGENTS.md`），識別章節技能綁定、路徑參照（`skills/<name>/SKILL.md`）與表格配置，並自動過濾非技能標題與符號。
  - **多來源搜尋與鏡像比對 (`find_skill_in_sources`)**：支援指定多個本地來源目錄（如 `skill-packs/`、`ai-tooling/skills` 等），比對同名技能目錄。
  - **跨平台狀態審計 (`audit_workflow_skills`)**：自動探測指定平台全域技能目錄（Antigravity、Claude、Codex、Cursor）或自訂目標目錄，審查工作流所需技能之安裝與完備狀態（`AVAILABLE`、`MISSING`、`INCOMPLETE`、`INVALID`）。
  - **自動補全與骨架生成 (`complete_workflow_skills`)**：支援從來源目錄自動複製現有技能套件；若來源不存在，則聯動 `core.indexer` 自動生成標準 `SKILL.md` 骨架與結構目錄，實現啟動時零技能缺漏阻礙。
  - **模擬演練防護 (`dry-run`)**：完整支援 `--dry-run` 模式，預覽變更動作與差量，確保檔案系統寫入安全性。
- **CLI 指令擴增 (`cli.workflow-audit`)**：
  - 新增 `skill-manager workflow-audit` 指令，提供 `--workflow`、`--platform`、`--target-dir`、`--source`、`--auto-complete`、`--dry-run` 及 `--format table|json` 等完整參數支援。
- **架構與自測交付**：
  - 更新 `docs/01_spec.md` (FR-06 / AC-06-01~06 / EC-06-01~07)、`docs/01_plan.md`、`docs/01_spec_review.md` 與 `docs/02_architecture.md`。
  - 新增 20 個單元與整合測試用例，全專案測試覆蓋率達 86%（核心審計模組達 90%）。

## [0.1.0] - 2026-10-23

### Added (新增功能)
- **跨平台全域技能掃描 (`core.scanner`)**：
  - 自動探測 Claude (`~/.claude/skills`)、Antigravity (`~/.gemini/antigravity/skills` & `builtin/skills`)、Codex/Copilot (`~/.codex/skills`)、Cursor (`~/.cursor/skills`) 全域目錄。
  - 採用 `os.scandir` 串流走訪與 `visited_realpaths` 循環符號連結防護。
  - 解析 `SKILL.md` 之 YAML Frontmatter 與 Git 版本元數據。
- **遠端技能檢索 (`core.remote_search`)**：
  - 整合 GitHub REST API 與 HuggingFace Hub API 關鍵字與標籤檢索。
  - 實作 HTTP 429 Rate Limit 重置時間解析與 3 次指數退避（1s, 2s, 4s）重試機制。
- **依據 `index.md` 規範審計與自動補全 (`core.indexer`)**：
  - 解析 `index.md` 標題層級，比對必要欄位與章節，生成標準 Unified Diff。
  - 實作 PID 隔離暫存檔搭配 `Path.replace()` 原子寫入（Atomic Replace），確保 0 資料遺失。
- **技能版本控制與更新追蹤 (`core.versioning`)**：
  - 比對本機 HEAD 與遠端追蹤分支 Commit SHA（`UP_TO_DATE`、`BEHIND`、`AHEAD`、`DIVERGED`、`UNTRACKED`、`CHECK_FAILED`）。
  - 升級前自動建立 `backup-pre-upgrade-<timestamp>` 安全快照標籤，並支援 Dirty Worktree 拒絕保護與一鍵回滾（`rollback`）。
- **CLI 與容器健康檢查 (`cli`)**：
  - 提供 `scan`、`search`、`audit`、`complete`、`track`、`healthcheck` 子指令。
  - 支援 `--format table`（Rich 視覺化表格）與 `--format json`（無 ANSI 色碼之純 JSON）。
- **容器化與部署套件**：
  - 多階段 `Dockerfile`（Python 3.15 + 非 root `appuser`）、`docker-compose.yml`（128 MB 記憶體限制 + Healthcheck 探針）、`deploy.ps1` 與 `deploy.sh`。

### Security (資安加固)
- **CWE-88 防護**：於 `core/versioning.py` 新增 `_validate_git_ref` 白名單正則校驗，攔截 `-` 開頭之 Git 旗標注入。
- **CWE-22 防護**：於 `core/indexer.py` 新增 `is_relative_to` 目錄邊界檢查，阻絕路徑周遊。
- **CWE-502 防護**：強制使用 `yaml.safe_load()` 與 `tomllib.load()`。

