# SkillManager 系統實作計畫書 (Implementation Plan)

## 1. 實作計畫總覽

本計畫依據 `docs/01_spec.md` 需求規格書制定，採用 Python 3.15+ 技術棧，搭配 Typer、Pydantic v2、HTTPX、GitPython 與 Rich 進行模組化開發。
所有實作任務遵循測試驅動開發（TDD）原則，分拆為獨立之工作單元（Work Units）。

---

## 2. 模組分層架構與目錄規劃

```text
Skill-manager/
├── pyproject.toml              # 專案依賴與工具鏈配置 (uv / pip)
├── README.md                   # 專案使用說明
├── docs/                       # 規格與流程文件
│   ├── 01_spec.md
│   ├── 01_plan.md
│   └── 01_spec_review.md
├── src/
│   └── skill_manager/
│       ├── __init__.py
│       ├── cli.py              # Typer CLI 介面與命令入口
│       ├── config.py           # Pydantic 設定檔管理模型與路徑解析
│       ├── models.py           # 核心資料模型 (SkillEntity, SearchItem 等)
│       └── core/
│           ├── __init__.py
│           ├── scanner.py      # 本機目錄掃描與平台探測器 (FR-01)
│           ├── remote_search.py# GitHub & HuggingFace 搜尋用戶端 (FR-02)
│           ├── indexer.py      # index.md 規範審計與骨架補全引擎 (FR-03)
│           └── versioning.py   # Git / HF 狀態比對、快照與更新 (FR-04)
└── tests/
    ├── conftest.py             # 測試固定裝置 (Fixtures, 假目錄, Mock Server)
    ├── unit/
    │   ├── test_scanner.py     # FR-01 單元測試
    │   ├── test_search.py      # FR-02 單元測試 (含 Mock API)
    │   ├── test_indexer.py     # FR-03 單元測試
    │   ├── test_versioning.py  # FR-04 單元測試 (含本機假 Git Repo)
    │   └── test_cli.py         # FR-05 CLI 命令測試
    └── integration/
        ├── test_e2e_workflow.py# 整合流程測試
        └── test_boundaries.py  # R2 邊界情境 (EC-xx) 測試
```

---

## 3. 實作任務分解 (Tasks Breakdown)

### 任務群組 1：專案骨架與資料模型基礎 (TASK-00)
- **目標**：建立專案配置、虛擬環境、CI 與核心 Pydantic 資料模型。
- **子任務**：
  - `TASK-00-01`：初始化 `pyproject.toml`，配置 `typer`、`pydantic>=2.0`、`httpx`、`gitpython`、`rich`、`pytest`、`pytest-cov`。
  - `TASK-00-02`：編寫 `src/skill_manager/models.py`，定義 `SkillEntity`、`AuditResult`、`SearchItem`、`VersionStatus` 資料類別。
  - `TASK-00-03`：編寫 `src/skill_manager/config.py`，實作跨平台路徑解析函式（自動展開 `%USERPROFILE%` 與 `$HOME`）。
- **驗證方式**：執行 `pytest tests/unit/test_config.py` 驗證 Windows 與 POSIX 路徑展開正確性。

---

### 任務群組 2：本機多平台技能掃描引擎 (TASK-01 - 支援 FR-01)
- **目標**：遍歷本機 Claude、Antigravity、Codex、Cursor 全域技能目錄，解析 YAML frontmatter。
- **子任務**：
  - `TASK-01-01`：編寫 `core/scanner.py` 之 `scan_directory` 產生器，使用 `os.scandir` 遍歷目錄。
  - `TASK-01-02`：實作 `parse_skill_metadata`，抽取 `SKILL.md` 之 YAML 頭部內容。
  - `TASK-01-03`：實作循環符號連結（Symlink Loop）檢測與權限異常防禦。
- **對應測試 ID**：`T-R1-AC-01-01`, `T-R1-AC-01-02`, `T-R1-AC-01-03`, `T-R2-AC-01-04`, `T-R2-AC-01-05`, `T-R2-EC-01-01`, `T-R2-EC-01-02`, `T-R2-EC-01-03`, `T-R2-EC-01-07`。
- **驗證方式**：建立具備各類合法與毀損目錄之假檔案樹（Fixture），執行 `pytest tests/unit/test_scanner.py`。

---

### 任務群組 3：遠端技能搜尋用戶端 (TASK-02 - 支援 FR-02)
- **目標**：串接 GitHub REST API 與 HuggingFace Hub API 檢索遠端技能。
- **子任務**：
  - `TASK-02-01`：編寫 `core/remote_search.py`，封裝 `httpx.AsyncClient`，實作連線逾時（5s）與傳輸逾時（10s）。
  - `TASK-02-02`：實作 GitHub Topic 搜尋（`agent-skills`, `claude-skills`）與 Token 鑑權標頭注入。
  - `TASK-02-03`：實作 HuggingFace Hub API 搜尋轉換與下載量指標統計。
  - `TASK-02-04`：實作 HTTP 429 Rate Limit 攔截器與 3 次指數退避重試邏輯。
- **對應測試 ID**：`T-R1-AC-02-01`, `T-R1-AC-02-02`, `T-R2-AC-02-03`, `T-R2-AC-02-04`, `T-R2-EC-02-01`, `T-R2-EC-02-02`, `T-R2-EC-02-03`, `T-R2-EC-02-04`, `T-R2-EC-02-07`。
- **驗證方式**：使用 `respx` 模擬 GitHub 與 HuggingFace API 回應，驗證成功解析、分頁與重試機制。

---

### 任務群組 4：index.md 規範審計與補全引擎 (TASK-03 - 支援 FR-03)
- **目標**：比對目標技能與 `index.md` 規範，產出差異報告與安全補全寫入。
- **子任務**：
  - `TASK-03-01`：編寫 `core/indexer.py` 之 `parse_index_schema`，解析 Markdown 標題階層與必要欄位清單。
  - `TASK-03-02`：實作 `audit_skill`，比對 YAML frontmatter 缺少之鍵值與缺少之章節標題。
  - `TASK-03-03`：實作 `generate_completion_diff`，輸出標準 Unified Diff 格式文字。
  - `TASK-03-04`：實作原子寫入機制（寫入 `.tmp` 檔案並置換），確保斷電或異常時 0 檔案毀損。
- **對應測試 ID**：`T-R1-AC-03-01`, `T-R1-AC-03-02`, `T-R2-AC-03-03`, `T-R2-AC-03-04`, `T-R2-EC-03-01`, `T-R2-EC-03-02`, `T-R2-EC-03-03`, `T-R2-EC-03-05`, `T-R2-EC-03-07`。
- **驗證方式**：對殘缺之 `SKILL.md` 執行補全測試，驗證補全後重新審計通過且原有自訂內文完整保留。

---

### 任務群組 5：技能版本控制與更新追蹤 (TASK-04 - 支援 FR-04)
- **目標**：檢查技能本機 Git 狀態，比對遠端 Commit SHA，執行安全升級與快照回滾。
- **子任務**：
  - `TASK-04-01`：編寫 `core/versioning.py`，封裝 Git CLI 與 GitPython，讀取本機 HEAD 與遠端追蹤分支 SHA。
  - `TASK-04-02`：實作版本狀態判定邏輯（`UP_TO_DATE`、`BEHIND`、`AHEAD`、`DIVERGED`、`UNTRACKED`）。
  - `TASK-04-03`：實作升級前安全備份機制（建立 `backup-pre-upgrade-<timestamp>` 標籤）。
  - `TASK-04-04`：實作 Dirty Working Tree 檢驗攔截與衝突保護。
  - `TASK-04-05`：實作快照回滾邏輯，一鍵還原至指定標籤。
- **對應測試 ID**：`T-R1-AC-04-01`, `T-R1-AC-04-02`, `T-R1-AC-04-03`, `T-R2-AC-04-04`, `T-R2-AC-04-05`, `T-R2-EC-04-01`, `T-R2-EC-04-02`, `T-R2-EC-04-03`, `T-R2-EC-04-04`, `T-R2-EC-04-05`。
- **驗證方式**：在測試目錄建立本機 Bare Git 倉庫作為遠端，模擬推送新 Commit、本機升級與回滾全流程。

---

### 任務群組 6：CLI 介面與輸出格式器 (TASK-05 - 支援 FR-05)
- **目標**：串接各核心模組至 Typer CLI，實作表格渲染與乾淨 JSON 輸出旗標。
- **子任務**：
  - `TASK-05-01`：編寫 `cli.py`，註冊子指令 `scan`、`search`、`audit`、`complete`、`track`、`config`。
  - `TASK-05-02`：實作 Rich 終端視覺化（彩色表格、進度條、狀態面板）。
  - `TASK-05-03`：實作 `--format json` 輸出管道，禁止 ANSI 色碼干擾標準輸出。
- **對應測試 ID**：`T-R1-AC-05-01`, `T-R1-AC-05-02`, `T-R2-AC-05-03`。
- **驗證方式**：使用 `typer.testing.CliRunner` 測試全數子指令之標準輸出與退出碼。

---

## 4. 階段 2 實作與驗證時程檢核點

1. **里程碑 1**：TASK-00 與 TASK-01 完成，本機目錄多平台掃描與 JSON 輸出通過單元測試（耗時門檻驗證 ≤ 1500 ms）。
2. **里程碑 2**：TASK-02 完成，GitHub 與 HuggingFace API 檢索與重試防禦通過測試。
3. **里程碑 3**：TASK-03 完成，依據 `index.md` 之審計與原子補全通過測試。
4. **里程碑 4**：TASK-04 與 TASK-05 完成，Git 版本比對、升級快照與完整 CLI 介面整合。
5. **里程碑 5**：全量自動化測試執行，行覆蓋率達到 ≥ 80%，核心模組達到 ≥ 90%。

