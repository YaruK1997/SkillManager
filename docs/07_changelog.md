# SkillManager 變更日誌 (docs/07_changelog.md)

本檔案記錄 SkillManager 專案所有重大版本演進、功能異動與安全加固。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/) 標準，版本號採 [語意化版本 (Semantic Versioning)](https://semver.org/lang/zh-TW/) 規範。

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
