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

### 任務群組 7：工作流技能審計與啟動自動補全 (TASK-06 - 支援 FR-06)
- **目標**：解析 `workflow.md` 所需技能依賴，比對本機各平台已安裝技能庫，並支援自備用來源或 indexer 骨架自動補全。
- **子任務**：
  - `TASK-06-01`：在 `src/skill_manager/models.py` 新增 `WorkflowSkillStatus`、`WorkflowSkillRequirement`、`WorkflowAuditResult`、`WorkflowCompleteResult` 資料類別。
  - `TASK-06-02`：編寫 `src/skill_manager/core/workflow_auditor.py` 之 `parse_workflow_requirements`，使用正規表達式與 Markdown 標題掃描提取技能引用。
  - `TASK-06-03`：實作 `audit_workflow_skills`，結合 `core.scanner` 與 `core.indexer` 比對已安裝技能名稱與結構完整性（判定 `INSTALLED`、`MISSING`、`INCOMPLETE`）。
  - `TASK-06-04`：實作 `complete_workflow_skills`，支援自指定備用來源目錄複製技能檔案，或利用 `core.indexer.complete_skill` 產生標準補全骨架，支援 `--dry-run` 模擬輸出與原子寫入。
  - `TASK-06-05`：在 `src/skill_manager/cli.py` 註冊 `workflow-audit` 子指令，整合 Rich 終端表格渲染與 `--format json` 輸出，提供 `--auto-complete`、`--dry-run/--no-dry-run`、`--source` 等旗標。
- **對應測試 ID**：`T-R1-AC-06-01`, `T-R1-AC-06-02`, `T-R1-AC-06-03`, `T-R2-AC-06-04`, `T-R2-AC-06-05`, `T-R2-AC-06-06`, `T-R2-EC-06-01`, `T-R2-EC-06-02`, `T-R2-EC-06-03`, `T-R2-EC-06-05`, `T-R2-EC-06-06`, `T-R2-EC-06-07`。
- **驗證方式**：編寫單元測試 `tests/unit/test_workflow_auditor.py` 與 CLI 整合測試 `tests/unit/test_cli_workflow.py`。

---

## 4. 階段 2 實作與驗證時程檢核點

1. **里程碑 1**：TASK-00 與 TASK-01 完成，本機目錄多平台掃描與 JSON 輸出通過單元測試（耗時門檻驗證 ≤ 1500 ms）。
2. **里程碑 2**：TASK-02 完成，GitHub 與 HuggingFace API 檢索與重試防禦通過測試。
3. **里程碑 3**：TASK-03 完成，依據 `index.md` 之審計與原子補全通過測試。
4. **里程碑 4**：TASK-04 與 TASK-05 完成，Git 版本比對、升級快照與完整 CLI 介面整合。
5. **里程碑 5**：TASK-06 完成，工作流技能依賴解析、比對、自動補全與 CLI `workflow-audit` 整合通過測試。
6. **里程碑 6**：全量自動化測試執行，行覆蓋率達到 ≥ 80%，核心模組達到 ≥ 90%。



---

## 5. v0.3.0 實作任務規劃 (TUI 現代化與技能全域執行開關)

依據 `docs/08_update_plan.md`，v0.3.0 拆解為以下獨立實作任務，支援平行 Worktree 隔離開發：

### 任務群組 8：核心模型擴充與事件定義 (T-S2-01-MODEL - 支援 FR-07, FR-09)
- **目標**：在 `models.py` 新增 `SkillExecutionMode` 與 `GlobalPolicyMode`；新增 `events.py` 定義型別安全之 UI 事件。
- **子任務**：
  - `T-S2-01-01`：於 `src/skill_manager/models.py` 新增 `SkillExecutionMode`（`RESIDENT` / `ON_DEMAND`）與 `GlobalPolicyMode`（`ALL_RESIDENT` / `ALL_ON_DEMAND` / `CUSTOM`），擴充 `SkillEntity` 新增 `execution_mode` 欄位。
  - `T-S2-01-02`：新增 `src/skill_manager/events.py`，定義 `ScanProgressEvent`、`SkillSelectedEvent`、`SkillModeChangedEvent`、`GlobalPolicyChangedEvent`、`AuditCompleteEvent`、`VersionUpdateEvent`、`LogEvent`。
- **對應測試 ID**：`T-R1-AC-07`, `T-R1-AC-09`。
- **驗證方式**：編寫 `tests/unit/test_events_and_models.py` 驗證事件建構與型別序列化。

### 任務群組 9：技能執行模式控制器 (T-S2-02-MODE - 支援 FR-07, FR-08)
- **目標**：新增 `src/skill_manager/core/mode_controller.py`，實作單一技能常駐/按需原子切換與全域策略總開關。
- **子任務**：
  - `T-S2-02-01`：實作 `toggle_skill_mode(skill_path, target_mode)`，以正則或 YAML AST 安全更新 `SKILL.md` 之 `activation` 與 `alwaysApply` 屬性，使用 `.tmp` 與 `os.replace` 原子替換。
  - `T-S2-02-02`：實作 `apply_global_policy(policy, skills, platform)`，批次切換全數常駐或全數按需，並於 `config.toml` 之 `[skill_modes]` 留存個別偏好快照，切回 `CUSTOM` 時完整還原。
- **對應測試 ID**：`T-R1-AC-07`, `T-R1-AC-08`, `T-R2-EC-07`, `T-R2-EC-08`, `T-R2-EC-09`, `T-R2-EC-10`。
- **驗證方式**：編寫 `tests/unit/test_mode_controller.py` 驗證原子寫入、語法損毀保護、快照儲存與精確還原。

### 任務群組 10：掃描引擎模式識別 (T-S2-03-SCANNER - 支援 FR-07)
- **目標**：擴充 `src/skill_manager/core/scanner.py`，於掃描目錄時自動自 `SKILL.md` YAML Frontmatter 識別該技能之執行模式。
- **子任務**：
  - `T-S2-03-01`：解析 `activation`（`resident` -> `RESIDENT`）與 `alwaysApply`（`true` -> `RESIDENT`），若未宣告則預設為 `ON_DEMAND`。
  - `T-S2-03-02`：將模式資訊封裝入 `SkillEntity.execution_mode`。
- **對應測試 ID**：`T-R1-AC-07`。
- **驗證方式**：更新 `tests/unit/test_scanner.py` 驗證不同 YAML 配置下的模式解析。

### 任務群組 11：非同步核心配接層 (T-S2-04-ASYNC - 支援 FR-09)
- **目標**：新增 `src/skill_manager/core/async_adapter.py`，封裝耗時作業為非同步 Worker 與生成器。
- **子任務**：
  - `T-S2-04-01`：實作 `async_scan_skills` 非同步生成器，提供進度回呼。
  - `T-S2-04-02`：封裝 `async_check_version`，使用 `asyncio.to_thread` 執行 Git fetch，設定 5 秒超時防護。
  - `T-S2-04-03`：封裝非同步遠端市集搜尋與工作流審計。
- **對應測試 ID**：`T-R1-AC-09`, `T-R2-EC-12`。
- **驗證方式**：編寫 `tests/unit/test_async_adapter.py` 驗證非同步協程與超時取消行為。

### 任務群組 12：Textual TUI 主應用與佈局 (T-S2-05-TUI-APP - 支援 FR-10)
- **目標**：實作 `src/skill_manager/tui/app.py`，建立雙欄響應式佈局、頂部狀態列、分頁容器與全域快捷鍵。
- **子任務**：
  - `T-S2-05-01`：宣告 `SkillManagerApp` 繼承 `textual.app.App`，配置 TCSS 樣式。
  - `T-S2-05-02`：實作 Header 元件，即時顯示版本、當前全域策略狀態列（📌常駐/⚡按需計數）與快捷鍵導覽。
  - `T-S2-05-03`：配置 TabbedContent，包含四大分頁：本機技能庫、工作流審計、遠端市集、系統設定。
- **對應測試 ID**：`T-R1-AC-10`, `T-R2-EC-14`。
- **驗證方式**：使用 Textual Pilot 自動化測試框架測試應用程式初始化、快捷鍵與分頁切換。

### 任務群組 13：TUI 互動元件庫 (T-S2-06-TUI-WIDGETS - 支援 FR-10, FR-11, FR-12)
- **目標**：實作各分頁專屬 Widget。
- **子任務**：
  - `T-S2-06-01`：`src/skill_manager/tui/widgets/skill_tree.py`，呈現技能名稱、模式徽章（`[📌常駐]` / `[⚡按需]`）、狀態標籤，綁定 `Space/M` 模式切換。
  - `T-S2-06-02`：`src/skill_manager/tui/widgets/diff_viewer.py`，語法高亮渲染 Unified Diff 與缺失結構。
  - `T-S2-06-03`：`src/skill_manager/tui/widgets/global_switch_modal.py`，彈窗選擇全域策略（全常駐/全按需/自訂）。
  - `T-S2-06-04`：`src/skill_manager/tui/widgets/workflow_view.py`，工作流依賴矩陣與選擇性補全。
- **對應測試 ID**：`T-R1-AC-10`, `T-R1-AC-11`, `T-R1-AC-12`。
- **驗證方式**：編寫各 Widget 之 Textual Pilot 單元測試。

### 任務群組 14：原生檔案總管開啟模組 (T-S2-07-PLATFORM-OPEN - 支援 FR-14)
- **目標**：實作跨平台原生檔案總管開啟函式。
- **子任務**：
  - `T-S2-07-01`：判斷 Windows (`explorer.exe`)、macOS (`open`)、Linux (`xdg-open`)。
  - `T-S2-07-02`：路徑防護與轉義，禁止 `shell=True`，杜絕注入與崩潰。
- **對應測試 ID**：`T-R1-AC-14`, `T-R2-EC-13`。
- **驗證方式**：編寫 `tests/unit/test_platform_open.py` 驗證不同 OS 下之命令引數組裝。

### 任務群組 15：雙模入口整合與 CLI mode 指令 (T-S2-08-CLI-MODE - 支援 FR-13)
- **目標**：升級 `src/skill_manager/cli.py`，新增 `mode` 指令、`tui` 指令與無 TTY 降級。
- **子任務**：
  - `T-S2-08-01`：新增 `skill-manager mode` 指令，支援單一技能與 `--global` 全域開關切換及 `--format json`。
  - `T-S2-08-02`：新增 `skill-manager tui` 指令；當無子指令且 `sys.stdin.isatty()` 時預設啟動 TUI；無 TTY 或指定 `--no-tui` 時降級輸出 Help。
- **對應測試 ID**：`T-R1-AC-13`, `T-R2-EC-11`。
- **驗證方式**：使用 `CliRunner` 測試無 TTY 環境與各子指令輸出。

### 任務群組 16：相依更新與發布準備 (T-S2-09-DEPS)
- **目標**：更新 `pyproject.toml`，新增 `textual>=0.80.0`，版本升級至 `0.3.0`。
- **驗證方式**：容器內執行 `uv lock` 與全套件測試。
