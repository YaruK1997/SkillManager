# SkillManager 變更日誌 (docs/07_changelog.md)

本檔案記錄 SkillManager 專案所有重大版本演進、功能異動與安全加固。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/) 標準，版本號採 [語意化版本 (Semantic Versioning)](https://semver.org/lang/zh-TW/) 規範。

---

## [0.3.0] - 2026-11-13

### Added (新增功能)
- **TUI 現代化全螢幕雙欄互動儀表板 (`tui.app`, `tui.widgets`) (FR-07, FR-08, FR-11, FR-14)**：
  - **核心架構與雙模合一**：基於 `textual>=0.80.0` 打造現代化終端使用者介面 `SkillManagerApp`，雙欄響應式佈局支援左右分割、側邊摺疊與自適應流式排版；支援雙模入口，使用者執行 `skill-manager` 預設進入 TUI，支援 `--no-tui`、`--non-interactive` 或無 TTY 環境安全平滑降級至 CLI。
  - **雙欄樹狀與差異檢視器**：
    - `SkillTree`：以樹狀節點展示各平台技能清單、啟用狀態、常駐模式標籤（`[ALWAYS]` / `[ON_DEMAND]` / `[DISABLED]`），支援即時過濾與選取事件。
    - `DiffViewer`：內建側邊即時語法高亮差異比對器，於切換模式或套用全域策略前提供 Before/After Diff 視覺化預覽。
  - **全域開關互動對話框 (`GlobalSwitchModal`)**：提供全域策略快速批次切換（全域常駐 / 全域按需 / 全域禁用 / 恢復預設），並於套用前即時計算受影響技能清單與變更預覽。
  - **工作流整合與遠端檢索面板**：
    - `WorkflowView`：整合工作流所需技能審計與一鍵自動補全。
    - `RemoteSearchView`：支援跨平台非同步檢索 GitHub 與 Hugging Face 技能倉庫。
  - **安全跨平台檔案總管喚起 (`core.platform_open`) (FR-13)**：
    - 支援 Windows (`explorer`)、macOS (`open`) 與 Linux (`xdg-open`) 一鍵開啟技能目錄。
    - 嚴禁 `shell=True`，實作嚴格路徑存在性校驗與路徑周遊安全防護（CWE-78 / CWE-22）。
  - **非同步事件驅動與效能保證 (`core.async_adapter`) (FR-10, NFR-06)**：
    - 封裝 8 大非同步背景 Worker，耗時 I/O（檔案掃描、網路檢索、Git 版本拉取）完全自 TUI 主執行緒解耦。
    - 確保終端渲染維持 60 FPS 流暢度，動態載入中指示器反饋。

- **技能全域執行開關與常駐策略控制器 (`core.mode_controller`) (FR-07, FR-08, FR-09)**：
  - **執行模式定義 (`SkillExecutionMode`)**：支援 `ALWAYS_ACTIVE`（全域常駐）、`ON_DEMAND`（特定時機按需調用）、`DISABLED`（禁用）與 `SYSTEM_DEFAULT`（依平台預設）。
  - **Frontmatter 元資料安全讀寫**：精準解析與變更 `SKILL.md` 中 `execution_mode` 欄位，嚴格保留現有註解與其餘 frontmatter 內容。
  - **原子替換與快照自動還原 (AC-08, EC-08, EC-09)**：
    - 寫入採用 `.tmp.<timestamp>` 暫存檔與同分割區原子替換（`replace`）。
    - 寫入前自動建立 `.snapshot.<timestamp>` 快照備份，若寫入失敗或異常自動 100% 回滾還原，達成 0 損壞、0 殘留。
  - **全域常駐策略管理 (`GlobalPolicyMode`)**：支援一鍵批次套用全域策略，並提供唯讀技能鎖定保護與強制覆寫（`force=True`）機制。

- **確定性五階段多代理人協作體系 (Brain ➔ Router ➔ 4 Workers)**：
  - 完整落地 `tools/router.py`（拓撲派發、Git Worktree 隔離生命週期、AST 快取對齊、Exit Code 確定性狀態機）。
  - 落地 `tools/run_stage3b.py` 與 `tools/run_stage4.py`，全量單元測試（R1/R2/R3）與資安檢查（Secrets/SAST/SCA/Least Privilege）自動化合規驗證。

### Fixed (缺陷修復與代碼整改)
- **邊界防禦與異常防護強化**：
  - 補足 13/13 (100%) `EC-07` 至 `EC-14` 邊界測試案例覆蓋：
    - `EC-07`：無 Frontmatter 之 `SKILL.md` 自動補齊標準 Frontmatter 結構。
    - `EC-08`：磁碟空間耗盡與 I/O 寫入中斷時之快照自動復原機制。
    - `EC-09`：目錄唯讀 (`PermissionError`) 之優雅錯誤報告與退出碼對齊。
    - `EC-10`：跨平台特殊字元與非 UTF-8 編碼字元集相容讀寫。
    - `EC-11`：無 TTY 終端、非互動 CI 環境自動降級 CLI。
    - `EC-12`：網路逾時與斷線重試保護。
    - `EC-13`：平台檔案總管開啟指令注入與路徑逃逸防護。
    - `EC-14`：終端尺寸小於 80x24 時之畫面尺寸過小提示與安全調度。

### Security (資安加固)
- **CWE-78 (指令注入防禦)**：
  - `core.platform_open` 嚴禁任何 `shell=True` 調用，以參數陣列隔離子程序執行。
- **CWE-22 (路徑周遊防禦)**：
  - 檔案總管開啟與模式控制器全面執行 `Path.resolve().is_relative_to()` 範圍限制。
- **Secrets & SAST 掃描**：
  - 通過 `run_stage4.py` 確定性資安閘門掃描，全專案 0 硬編碼金鑰、0 High/Medium 程式碼弱點。
- **Docker 容器最小權限原則**：
  - Multi-stage build，非 root `USER appuser (1000:1000)`，連續 3 次健康探針實測 200 OK。

---

## [0.2.0] - 2026-10-29

### Added (新增功能)
- **啟動時工作流所需技能審計與自動補全 (`core.workflow_auditor`) (FR-06)**：
  - **工作流需求解析 (`parse_workflow_requirements`)**：精準解析各類 Markdown 工作流規格文件（如 `workflow.md`、`AGENTS.md`），自動提取技能清單、章節綁定與路徑宣告，內建別名正規化（如 `tdd` 映射至 `test-driven-development`）。
  - **跨平台狀態審計 (`audit_workflow_skills`)**：自動探測各平台全域目錄與自訂目錄，對比工作流需求並分類為 `INSTALLED`、`MISSING` 與 `INCOMPLETE` 狀態。
  - **自動補全與骨架生成 (`complete_workflow_skills`)**：支援從本機來源目錄自動複製現有技能套件；若來源不存在則聯動 `core.indexer` 自動生成標準 `SKILL.md` 骨架與目錄結構。
  - **模擬演練 (`--dry-run`)**：完整支援 `--dry-run` 模式，輸出預覽變更檔案清單與 Diff，確保零未預期磁碟寫入。
- **CLI 命令擴展與規格對齊 (FR-05)**：
  - 新增 `skill-manager workflow-audit` 子指令，完整支援 `--workflow`、`--platform`、`--target-dir`、`--source`、`--auto-complete`、`--dry-run` 與 `--format table|json`。
  - 新增 `skill-manager config` 子指令，支援設定檔路徑查看與各平台目錄設定顯示。
  - `skill-manager scan` 增加 `--custom-paths` 與 `--custom_paths` 別名支援，並加入 `--depth` 範圍約束 (`min=1, max=5`)。
- **版本控制模型擴充 (`models.py`)**：
  - 新增 `VersionStatus.NETWORK_TIMEOUT` 列舉值，遠端連線異常時精準標記並回傳退出碼 7。
- **多輪極限自動化測試套件擴展**：
  - 測試案例由 54 項擴展至 **93 項**（43 R1、48 R2、2 R3），全量測試覆蓋率達 **88%**（核心模組均達 84%~97%）。
  - 連續 3 次全套件無狀態執行 100% 通過（0 Failures, 0 Flaky）。
  - 完整達成 AC-01-01 至 AC-06-06 全部 27 項驗收標準。
- **容器化與維運套件升級 (Phase 5)**：
  - 升級映像檔標籤至 `skill-manager:0.2.0`。
  - 整合多階段 `Dockerfile`（CPython 3.15 + uv 高速建構 + Debian Bookworm 輕量執行期）。
  - **跨平台 Host OS 偵測與本機技能掛載**：新增建構與啟動時自動判斷本機作業系統（Windows / macOS / Linux），自動預建立技能目錄並將 Host 端之 Gemini/Antigravity、Claude、Codex、Cursor 技能目錄透過 `docker-compose.yml` 綁定掛載至容器環境中。
  - 非特權使用者 `appuser (1000:1000)` 運行，配置 128 MB 記憶體上限與 Bridge 網路隔離。
  - 內建 Healthcheck 探針自動驗證回傳 `200/Healthy`。

### Fixed (缺陷修復與代碼整改)
- **Git 操作邊界強韌化 (`core.versioning`)**：
  - 修復 Detached HEAD 狀態下調用 `upgrade_skill` 存取 `active_branch.name` 拋出 `TypeError` 之問題，加入 `is_detached` 偵測與分支 fallback。
  - 修復無 Remote 之 Git 倉庫執行 `upgrade_skill` 拋出 `IndexError` 崩潰問題，增加守護檢查並拋出 `GitVersionError`。
  - 修復 `remote.fetch()` 與 `repo.git.reset()` 未受控拋出 `git.exc.GitCommandError` 之問題，全面包裹為自訂異常並映射安全退出碼。
  - 於 Windows 環境下在所有 Git 函式置入 `finally: repo.close()`，徹底消除 Popen Deallocator 警告與檔案控制代碼洩漏。
- **CLI 異常邊界處理 (`cli.py`)**：
  - 於 CLI `audit` 捕捉 `PermissionError`，輸出 `ACCESS_DENIED` 並以標準退出碼 5 退出，杜絕直通崩潰。
  - 修復 `workflow_audit_cmd` 在補全後二次審查未將 `--target-dir` 納入掃描路徑之問題，確保技能就緒狀態正確持久化探測。
- **原子寫入保護 (`core.indexer`)**：
  - 補全寫入時若拋出例外，於 `finally:` 區塊確保程序暫存檔 `.tmp.<pid>` 被安全刪除，達成 0 垃圾殘留。

### Security (資安加固)
- **CWE-22 (路徑周遊防禦)**：
  - `core.indexer`：在建立子目錄時強制檢查 `target_sub.resolve().is_relative_to(resolved_root)`，逃逸時拋出 `PATH_TRAVERSAL_BLOCKED`。
  - `core.workflow_auditor`：嚴格以白名單正則 `^[a-zA-Z0-9_\-]+$` 過濾技能名稱，自動剔除 `../` 或絕對路徑注入。
  - 新增專屬自動化測試 `test_security_cwe22_path_traversal_blocked` 與 `test_security_workflow_skill_name_path_traversal_blocked`。
- **CWE-88 (參數注入防禦)**：
  - `_validate_git_ref` 嚴格限制 `target_ref` 與 `tag_name`，攔截 `-` 旗標與 `..` 注入，由 `test_security_cwe88_git_ref_injection_blocked` 驗證。
- **SCA 弱點檢驗**：
  - 執行 `uv audit` 審查 41 個套件依賴，確認 **0 已知 CVE 漏洞**。
- **憑證與機敏資訊**：
  - 全專案 0 處硬編碼 Token 或密鑰，環境變數動態提取且不寫入日誌。

---

## [0.1.0] - 2026-10-23

### Added (新增功能)
- 跨平台全域技能掃描 (`core.scanner`)，支援 Claude、Antigravity、Codex/Copilot、Cursor。
- 遠端技能檢索 (`core.remote_search`)，整合 GitHub REST API 與 HuggingFace Hub API。
- 依據 `index.md` 規範審計與自動補全 (`core.indexer`)。
- 技能版本控制與更新追蹤 (`core.versioning`)。
- CLI 命令列介面 (`cli`)，支援 `--format table|json`。
- 初版 Docker 容器化與健康檢查探針。
