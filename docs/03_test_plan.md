# SkillManager 測試計畫與測試規格書 (docs/03_test_plan.md)

## 1. 測試策略與多輪測試規範 (Test Strategy & Multi-Round Architecture)

本測試計畫嚴格依據 `workflow.md` 階段 3A（測試計畫設計）規範與 `docs/01_spec.md` 第 8 節「需求與測試追溯矩陣（Traceability Matrix）」編製。透過 Pytest 標記（`@pytest.mark.r1`、`@pytest.mark.r2`、`@pytest.mark.r3`）將 `tests/` 下所有自動化測試腳本結構化分組為 **R1（功能正確性）**、**R2（邊界與異常）** 與 **R3（回歸與驗收）** 三道獨立防線，確保每一條功能需求（`FR-01`–`FR-06`）、驗收標準（`AC-xx`）與 7 類邊界情境（`EC-xx`）皆具備 100% 可追溯之自動化測試案例。

```text
+---------------------------------------------------------------------------------------+
|                        SkillManager 階段 3A 三輪測試分組架構                           |
+---------------------------------------------------------------------------------------+
  [ R1：功能正確性 (`pytest -m r1`) ]
   ├── 範圍：正常路徑單元測試 + 全部正常類 AC-xx (T-R1-AC-01-01 ~ T-R1-AC-06-03)
   └── 門檻：通過率 100%；整體行覆蓋率 ≥ 80%；5 大核心模組行覆蓋率 ≥ 90%
  [ R2：邊界與異常 (`pytest -m r2`) ]
   ├── 範圍：異常類 AC-xx (T-R2-AC-*) + 全部 7 類邊界 EC-xx (T-R2-EC-*) + 故障注入與安全防禦
   └── 門檻：通過率 100%；EC-xx 具對應測試比例 100%（不適用項標註 N/A 與工程理由）
  [ R3：回歸與驗收 (`pytest -m r3` & 全套件連跑 2 次) ]
   ├── 範圍：E2E 跨模組整合工作流 (T-R3-E2E-*) + 乾淨環境全套件連續執行 2 次 + 27 項 AC 驗收表
   └── 門檻：2 次連續執行 100% 通過（0 Flaky）；AC 驗收勾選表 100% 通過；0 阻塞/重大缺陷
```

### 1.1 測試輪次與 CI/CD 執行門檻映射表

| 測試輪次 | Pytest 執行指令 | 測試範圍 | 通過條件 (Gate Criteria) |
| :--- | :--- | :--- | :--- |
| **R1：功能正確性** | `.venv\Scripts\pytest.exe tests/ -m r1 --cov=skill_manager --cov-fail-under=80` | 正常路徑單元測試 + 正常類 `AC-xx`（15 項 `T-R1-*` 主案例，共 40 個 R1 測試函式） | 通過率 100%；整體行覆蓋率 ≥ 80%；核心模組（`scanner`、`indexer`、`versioning`、`remote_search`、`workflow_auditor`）≥ 90% |
| **R2：邊界與異常** | `.venv\Scripts\pytest.exe tests/ -m r2` | 異常類 `AC-xx`（12 項 `T-R2-AC-*`）+ 全部 `EC-xx`（30 項 `T-R2-EC-*` + 5 項 N/A）+ 異常注入（逾時、斷線、磁碟滿/唯讀、非法輸入、CWE-88 防護，共 43 個 R2 測試函式） | 通過率 100%；`EC-xx` 具對應測試比例 100%；精確斷言錯誤碼與狀態碼 |
| **R3：回歸與驗收** | `.venv\Scripts\pytest.exe tests/ -m r3` 及全套件連跑 2 次 `.venv\Scripts\pytest.exe tests/` | 端到端整合生命週期測試（2 項 `T-R3-E2E-*`）+ 乾淨環境連續執行全套件（85 個測試函式）2 次 + 逐條 `AC-xx` 驗收勾選表 | 2 次連續執行 100% 通過（0 失敗、0 Flaky）；27 項 `AC-xx` 100% 達成；獨立審查 0 阻塞/重大問題 |

---

## 2. R1 功能正確性測試分組規格 (`@pytest.mark.r1` / `T-R1-*`)

R1 聚焦驗證系統在合法輸入與標準環境下，所有業務邏輯、跨平台路徑解析、API 資料結構正規化、Markdown/YAML 解析、Git 版本控制與工作流技能審計補全之正確性。

### 2.1 R1 追溯矩陣與測試腳本映射表 (15 項 `T-R1-AC-*` + 輔助單元測試)

| 測試 ID | 來源需求 | 來源 `AC-xx` | 階段 2 任務標籤 | 測試腳本路徑 | 對應測試函式名稱 (`@pytest.mark.r1`) | 輸入條件與預期斷言結果 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `T-R1-AC-01-01` | FR-01 | `AC-01-01` | `TASK-01-SCANNER-CORE` | `tests/unit/test_scanner.py`<br>`tests/unit/test_config.py`<br>`tests/unit/test_more_coverage.py` | `test_t_r1_ac_01_01_valid_skill_detection`<br>`test_resolve_custom_paths`<br>`test_scanner_with_git_and_platforms` | **Given**：含有效 `SKILL.md`、`scripts/`、`references/` 與 Git 資訊之技能目錄。<br>**Then**：`inspect_single_skill` 回傳非空 `SkillEntity`，`has_skill_md=True`、`has_scripts=True`、`has_references=True`，正確提取 `name`、`description` 與 `commit_sha`。 |
| `T-R1-AC-01-02` | FR-01 | `AC-01-02` | `TASK-01-PATH-RESOLVER-WIN` | `tests/unit/test_scanner.py`<br>`tests/unit/test_config.py`<br>`tests/unit/test_more_coverage.py` | `test_t_r1_ac_01_02_and_03_scan_skills_custom_path`<br>`test_resolve_platform_paths_all`<br>`test_resolve_platform_paths_single`<br>`test_scanner_all_platform_inference` | **Given**：Windows/跨平台環境下配置之各平台路徑（Claude、Antigravity、Codex、Cursor）。<br>**Then**：`scan_skills` 自動正規化路徑並推論所屬 `PlatformType`，去重後回傳 `ScanResult`，`valid_skills >= 1`。 |
| `T-R1-AC-01-03` | FR-01 | `AC-01-03` | `TASK-01-PATH-RESOLVER-POSIX` | `tests/unit/test_config.py`<br>`tests/unit/test_more_coverage.py` | `test_default_platform_paths_structure`<br>`test_scanner_platform_inference_direct` | **Given**：POSIX/跨平台預設技能路徑結構（`~/.claude/skills`、`~/.gemini/antigravity/skills`、`~/.codex/skills`、`~/.cursor/skills`）。<br>**Then**：`get_default_platform_paths` 回傳所有平台之 `Path` 清單，掃描時正確映射對應平台標籤。 |
| `T-R1-AC-02-01` | FR-02 | `AC-02-01` | `TASK-02-GITHUB-SEARCH-API` | `tests/unit/test_remote_search.py`<br>`tests/unit/test_more_coverage.py` | `test_t_r1_ac_02_01_github_search`<br>`test_cli_search_and_track_coverage` | **Given**：關鍵字 `"docker"`，GitHub REST API 回傳 200 JSON。<br>**Then**：`search_github` 正確解析 `repo_id="test-owner/docker-skills"`、`stars_or_downloads=142`、`source="github"`。 |
| `T-R1-AC-02-02` | FR-02 | `AC-02-02` | `TASK-02-HF-SEARCH-API` | `tests/unit/test_remote_search.py` | `test_t_r1_ac_02_02_huggingface_search` | **Given**：關鍵字 `"code-review"`，HuggingFace Spaces API 回傳 200 JSON。<br>**Then**：`search_huggingface` 正確解析 `repo_id="agent-tools/code-reviewer"`、`stars_or_downloads=58`、`source="huggingface"`。 |
| `T-R1-AC-03-01` | FR-03 | `AC-03-01` | `TASK-03-INDEX-AUDITOR` | `tests/unit/test_indexer.py`<br>`tests/unit/test_cli.py` | `test_t_r1_ac_03_01_audit_incomplete_skill`<br>`test_audit_fully_compliant_skill`<br>`test_cli_audit_and_complete_workflow` | **Given**：缺少 `## When to Use`、`## Instructions` 及 `scripts/`、`references/` 之不完整技能目錄。<br>**Then**：`audit_skill` 回傳 `is_compliant=False`，精確列出 `missing_sections` 與 `missing_dirs`，並產出 Unified Diff 預覽。 |
| `T-R1-AC-03-02` | FR-03 | `AC-03-02` | `TASK-03-SKILL-COMPLETER` | `tests/unit/test_indexer.py`<br>`tests/unit/test_cli.py` | `test_t_r1_ac_03_02_complete_skill_applied`<br>`test_cli_audit_and_complete_workflow` | **Given**：對不完整技能執行 `complete_skill(..., dry_run=False)`。<br>**Then**：自動建立 `scripts/` 與 `references/` 子目錄，補齊 `SKILL.md` 缺失章節且保留原有內文，重新審計 `is_compliant=True`。 |
| `T-R1-AC-04-01` | FR-04 | `AC-04-01` | `TASK-04-GIT-STATUS-CHECKER` | `tests/unit/test_versioning.py`<br>`tests/unit/test_more_coverage.py` | `test_t_r1_ac_04_01_behind_status`<br>`test_cli_search_and_track_coverage` | **Given**：本機技能 Git 倉庫遠端 `origin/main` 已推送新 Commit。<br>**Then**：`check_version_status` 回傳 `version_status=VersionStatus.BEHIND`，`behind_count == 1`。 |
| `T-R1-AC-04-02` | FR-04 | `AC-04-02` | `TASK-04-GIT-UPGRADE-BACKUP` | `tests/unit/test_versioning.py` | `test_t_r1_ac_04_02_and_03_upgrade_and_rollback` | **Given**：本機技能處於 `BEHIND` 且工作區乾淨。<br>**Then**：`upgrade_skill` 自動建立 `backup-pre-upgrade-<timestamp>` 標籤並更新至遠端最新 SHA，狀態轉為 `UP_TO_DATE`。 |
| `T-R1-AC-04-03` | FR-04 | `AC-04-03` | `TASK-04-GIT-ROLLBACK-EXEC` | `tests/unit/test_versioning.py` | `test_t_r1_ac_04_02_and_03_upgrade_and_rollback` | **Given**：剛執行過升級且存在 `backup-pre-upgrade-*` 標籤之技能倉庫。<br>**Then**：`rollback_skill` 將本機 HEAD 精確還原至升級前之 `initial_sha`。 |
| `T-R1-AC-05-01` | FR-05 | `AC-05-01` | `TASK-05-CLI-JSON-OUTPUT` | `tests/unit/test_cli.py` | `test_t_r1_ac_05_01_json_format_output`<br>`test_cli_healthcheck` | **Given**：CLI 子指令附加 `--format json`。<br>**Then**：退出碼為 0，`stdout` 可由 `json.loads` 完整解析，包含 `skills` 與 `summary` 欄位且無 ANSI 控制碼污染。 |
| `T-R1-AC-05-02` | FR-05 | `AC-05-02` | `TASK-05-CONFIG-PATH-MAPPING` | `tests/unit/test_config.py` | `test_config_override_paths` | **Given**：`AppConfig` 中自訂 `custom_platform_paths={"claude": [...]}`。<br>**Then**：`resolve_platform_paths(PlatformType.CLAUDE, config=cfg)` 優先解析並回傳自訂配置路徑。 |
| `T-R1-AC-06-01` | FR-06 | `AC-06-01` | `TASK-06-WORKFLOW-AUDITOR-CORE` | `tests/unit/test_workflow_auditor.py`<br>`tests/unit/test_cli.py` | `test_t_r1_ac_06_01_parse_workflow_requirements`<br>`test_t_r1_ac_06_01_audit_workflow_status`<br>`test_find_default_workflow_file`<br>`test_audit_workflow_auto_detect_file`<br>`test_cli_workflow_audit_command` | **Given**：宣告技能依賴之 `workflow.md` 及本機技能目錄。<br>**Then**：正確解析所有綁定技能（含別名映射 `tdd -> test-driven-development`），並將各技能精確標記為 `INSTALLED`、`INCOMPLETE` 或 `MISSING`。 |
| `T-R1-AC-06-02` | FR-06 | `AC-06-02` | `TASK-06-WORKFLOW-AUTO-COMPLETE` | `tests/unit/test_workflow_auditor.py` | `test_t_r1_ac_06_02_and_03_auto_complete_dry_run_and_apply`<br>`test_find_skill_in_sources_nested_and_missing` | **Given**：審計發現 `MISSING` 技能，提供備用來源目錄並執行 `complete_workflow_skills(..., dry_run=False)`。<br>**Then**：存在於來源庫之技能自動複製至目標目錄，不存在於來源庫之技能自動生成合規 `SKILL.md` 骨架與子目錄。 |
| `T-R1-AC-06-03` | FR-06 | `AC-06-03` | `TASK-06-WORKFLOW-DRY-RUN` | `tests/unit/test_workflow_auditor.py` | `test_t_r1_ac_06_02_and_03_auto_complete_dry_run_and_apply` | **Given**：審計發現缺失技能，以 `dry_run=True` 執行自動補全。<br>**Then**：回傳 `dry_run=True`、預計補全之 `completed_skills` 清單與 Diff 摘要，且目標磁碟目錄維持 0 寫入異動。 |

### 2.2 R1 核心模組覆蓋率目標 (NFR-04)

| 核心模組路徑 | 職責說明 | 覆蓋率門檻 | R1 主測腳本 |
| :--- | :--- | :--- | :--- |
| `src/skill_manager/core/scanner.py` | 多平台目錄串流遍歷、YAML Frontmatter 解析與循環軟連結防禦 | ≥ 90% | `tests/unit/test_scanner.py`、`tests/unit/test_more_coverage.py` |
| `src/skill_manager/core/remote_search.py` | GitHub REST API 與 HuggingFace Hub 搜尋、分頁與重試正規化 | ≥ 90% | `tests/unit/test_remote_search.py`、`tests/unit/test_more_coverage.py` |
| `src/skill_manager/core/indexer.py` | `index.md` 規格解析、技能完整性審計、Unified Diff 與原子補全 | ≥ 90% | `tests/unit/test_indexer.py`、`tests/unit/test_more_coverage.py` |
| `src/skill_manager/core/versioning.py` | Git 狀態比對、`backup-pre-upgrade` 快照標籤與安全回滾 | ≥ 90% | `tests/unit/test_versioning.py`、`tests/unit/test_more_coverage.py` |
| `src/skill_manager/core/workflow_auditor.py` | 工作流技能需求擷取、就緒度審計與來源複製/骨架自動補全 | ≥ 90% | `tests/unit/test_workflow_auditor.py` |

---

## 3. R2 邊界與異常測試分組規格 (`@pytest.mark.r2` / `T-R2-*`)

R2 依據 `docs/01_spec.md` 第 4 節之 7 類邊界情境（空值、極大值、非法格式、網路逾時、資料遺失、併發衝突、權限不足）與異常類 `AC-xx`，結合 `systematic-debugging` 故障注入方法，全面驗證系統的防禦能力、降級策略與錯誤碼精確性。

### 3.1 R2 異常類驗收標準映射表 (12 項 `T-R2-AC-*`)

| 測試 ID | 來源需求 | 來源 `AC-xx` | 階段 2 任務標籤 | 測試腳本路徑 | 對應測試函式名稱 (`@pytest.mark.r2`) | 異常注入方式與預期行為斷言 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `T-R2-AC-01-04` | FR-01 | `AC-01-04` | `TASK-01-SCANNER-ERROR-PATH` | `tests/unit/test_scanner.py` | `test_t_r2_ac_01_04_missing_path_handled` | 傳入不存在之路徑 `does_not_exist_dir`；斷言 `stderr` 輸出 `PATH_NOT_FOUND`，`valid_skills == 0` 且程序不崩潰。 |
| `T-R2-AC-01-05` | FR-01 | `AC-01-05` | `TASK-01-SCANNER-ERROR-PERM` | `tests/unit/test_r2_boundaries.py` | `test_t_r2_ac_01_05_permission_denied` | 以 `patch("os.scandir", side_effect=PermissionError)` 注入權限拒絕；斷言 `stderr` 輸出 `ACCESS_DENIED`，安全回傳空清單。 |
| `T-R2-AC-02-03` | FR-02 | `AC-02-03` | `TASK-02-QUERY-VALIDATOR` | `tests/unit/test_remote_search.py` | `test_t_r2_ac_02_03_query_validation` | 傳入長度 `< 2`（`"a"`）與 `> 100`（`"x" * 101`）之關鍵字；斷言拋出 `ValueError("VALIDATION_ERROR")` 且不發起 HTTP 請求。 |
| `T-R2-AC-02-04` | FR-02 | `AC-02-04` | `TASK-02-RATE-LIMIT-HANDLER` | `tests/unit/test_remote_search.py` | `test_t_r2_ac_02_04_rate_limit_exceeded` | 以 `respx` 模擬 HTTP 429 與 `x-ratelimit-reset: 1730000000`；斷言拋出 `RateLimitExceededError`，包含 `RATE_LIMIT_EXCEEDED` 與重置時間戳。 |
| `T-R2-AC-03-03` | FR-03 | `AC-03-03` | `TASK-03-INDEX-SCHEMA-VALIDATE` | `tests/unit/test_indexer.py` | `test_t_r2_ac_03_03_invalid_index_schema` | 傳入空白之 `bad_index.md`；斷言 `parse_index_schema` 拋出 `IndexSchemaError("INVALID_INDEX_SCHEMA")`。 |
| `T-R2-AC-03-04` | FR-03 | `AC-03-04` | `TASK-03-WRITE-PERM-GUARD` | `tests/unit/test_r2_boundaries.py` | `test_t_r2_ac_03_04_and_ec_03_07_write_permission_denied` | 注入 `Path.replace` 拋出 `PermissionError`；斷言拋出 `PermissionError("WRITE_PERMISSION_DENIED")`（CLI 對應退出碼 5）。 |
| `T-R2-AC-04-04` | FR-04 | `AC-04-04` | `TASK-04-DIRTY-WORKTREE-GUARD` | `tests/unit/test_versioning.py` | `test_t_r2_ac_04_04_dirty_worktree_guard` | 在本機技能倉庫寫入未提交檔案 `dirty_file.txt` 並執行 `upgrade_skill(..., force=False)`；斷言拋出 `DirtyWorktreeError("DIRTY_WORKTREE_DETECTED")`。 |
| `T-R2-AC-04-05` | FR-04 | `AC-04-05` | `TASK-04-GIT-FETCH-TIMEOUT` | `tests/unit/test_r2_boundaries.py` | `test_t_r2_ac_04_05_git_fetch_timeout` | 模擬 `git.Remote.fetch` 拋出 `GitCommandError("timed out")`；斷言狀態安全標記為 `VersionStatus.CHECK_FAILED`，本機檔案不變。 |
| `T-R2-AC-05-03` | FR-05 | `AC-05-03` | `TASK-05-CLI-SUBCOMMAND-ERROR` | `tests/unit/test_cli.py` | `test_t_r2_ac_05_03_unknown_subcommand` | 執行未定義子指令 `skill-manager nonexistent_command`；斷言 CLI 回傳退出碼 2。 |
| `T-R2-AC-06-04` | FR-06 | `AC-06-04` | `TASK-06-WORKFLOW-MISSING-FILE` | `tests/unit/test_workflow_auditor.py` | `test_t_r2_ac_06_04_missing_workflow_file` | 傳入不存在之工作流路徑；斷言拋出 `FileNotFoundError("ERR_WORKFLOW_NOT_FOUND")`（CLI 對應退出碼 2）。 |
| `T-R2-AC-06-05` | FR-06 | `AC-06-05` | `TASK-06-WORKFLOW-EMPTY-FILE` | `tests/unit/test_workflow_auditor.py` | `test_t_r2_ac_06_05_and_ec_06_01_empty_workflow` | 傳入 0 byte 空白 `workflow.md`；斷言回傳 `total_required == 0`、`skills == []` 且不崩潰。 |
| `T-R2-AC-06-06` | FR-06 | `AC-06-06` | `TASK-06-WORKFLOW-WRITE-GUARD` | `tests/unit/test_workflow_auditor.py` | `test_t_r2_ac_06_06_and_ec_06_07_write_permission_denied`<br>`test_complete_incomplete_skill_and_permission_error` | 模擬 `shutil.copytree` 與 `complete_skill` 拋出 `PermissionError`；斷言攔截並拋出 `WRITE_PERMISSION_DENIED`（CLI 退出碼 5）。 |

### 3.2 R2 7 類邊界情境映射表 (30 項 `T-R2-EC-*` + 5 項 N/A 標註 + 安全防護測試)

| 測試 ID | 來源 `EC-xx` | 邊界類別 | 階段 2 任務標籤 | 測試腳本路徑 | 對應測試函式名稱 (`@pytest.mark.r2`) | 邊界條件與預期處理結果 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `T-R2-EC-01-01` | `EC-01-01` | 空值 | `TASK-01-SCANNER-EMPTY-DIR` | `tests/unit/test_scanner.py` | `test_t_r2_ec_01_01_empty_directory` | 掃描完全空白之資料夾；降級回傳空陣列 `[]`、`valid_skills == 0`。 |
| `T-R2-EC-01-02` | `EC-01-02` | 極大值 | `TASK-01-SCANNER-STREAMING` | `tests/unit/test_r2_boundaries.py` | `test_t_r2_ec_01_02_streaming_large_directory` | 批次建立大量技能子資料夾並以 Generator 串流掃描；記憶體峰值維持 < 128 MB，完整列舉所有技能。 |
| `T-R2-EC-01-03` | `EC-01-03` | 非法格式 | `TASK-01-SCANNER-SYMLOOP` | `tests/unit/test_scanner.py` | `test_t_r2_ec_01_03_circular_symlink` | 建立指向父目錄之循環符號連結；`visited_realpaths` 偵測迴圈並跳過，不發生無窮遞迴。 |
| N/A (`EC-01-04`) | `EC-01-04` | 網路逾時 | N/A | N/A | N/A（不適用） | **不適用理由**：`FR-01` 為純本機檔案系統掃描，無任何網路套接字或遠端連線操作。 |
| `T-R2-EC-01-05` | `EC-01-05` | 資料遺失 | `TASK-01-SCANNER-CONCURRENT-DEL` | `tests/unit/test_r2_boundaries.py` | `test_t_r2_ec_01_05_concurrent_file_deletion` | 讀取瞬間注入 `FileNotFoundError` 模擬外部行程刪檔；安全降級回傳空元資料，繼續掃描其餘項目。 |
| N/A (`EC-01-06`) | `EC-01-06` | 併發衝突 | N/A | N/A | N/A（不適用） | **不適用理由**：`FR-01` 僅執行唯讀（Read-Only）目錄遍歷與標頭讀取，不涉及檔案寫入鎖定衝突。 |
| `T-R2-EC-01-07` | `EC-01-07` | 權限不足 | `TASK-01-SCANNER-ACCESS-DENIED` | `tests/unit/test_r2_boundaries.py` | `test_t_r2_ac_01_05_permission_denied` | 存取受限目錄拋出 `PermissionError`；輸出 `ACCESS_DENIED` 至 `stderr` 並跳過該節點。 |
| `T-R2-EC-02-01` | `EC-02-01` | 空值 | `TASK-02-QUERY-BLANK-VALIDATOR` | `tests/unit/test_r2_boundaries.py` | `test_t_r2_ec_02_01_blank_query_validation` | 傳入純空白字串 `"   "`；前置驗證拒絕並拋出 `VALIDATION_ERROR`，0 網路請求。 |
| `T-R2-EC-02-02` | `EC-02-02` | 極大值 | `TASK-02-LIMIT-CAP-HANDLER` | `tests/unit/test_remote_search.py` | `test_t_r2_ec_02_02_limit_capping` | 傳入 `limit=9999`；強制收斂至上限 `50`（`result.limit == 50`）。 |
| `T-R2-EC-02-03` | `EC-02-03` | 非法格式 | `TASK-02-INVALID-JSON-HANDLER` | `tests/unit/test_r2_boundaries.py`<br>`tests/unit/test_more_coverage.py` | `test_t_r2_ec_02_03_invalid_json_response`<br>`test_remote_search_hf_error` | 模擬 API 回傳 Cloudflare 502 HTML 非 JSON 內容；攔截並拋出 `RemoteSearchError("ERR_REMOTE_RESPONSE_INVALID")`。 |
| `T-R2-EC-02-04` | `EC-02-04` | 網路逾時 | `TASK-02-RETRY-BACKOFF-CLIENT` | `tests/unit/test_r2_boundaries.py` | `test_t_r2_ec_02_04_network_timeout_retry` | 注入 `httpx.ConnectTimeout`；驗證執行指數退避重試後拋出 `RemoteSearchError("NETWORK_TIMEOUT")`。 |
| N/A (`EC-02-05`) | `EC-02-05` | 資料遺失 | N/A | N/A | N/A（不適用） | **不適用理由**：`FR-02` 遠端搜尋為無狀態即時查詢（Stateless Query），不寫入或修改本機磁碟資料。 |
| `T-R2-EC-02-06` | `EC-02-06` | 併發衝突 | `TASK-02-CLIENT-RATE-LIMITER` | `tests/unit/test_more_coverage.py` | `test_remote_search_retry_and_headers` | 模擬遠端伺服器 500 瞬斷後恢復 200；透過退避佇列重試成功取回結果並驗證 Bearer Token 標頭。 |
| `T-R2-EC-02-07` | `EC-02-07` | 權限不足 | `TASK-02-AUTH-ERROR-HANDLER` | `tests/unit/test_r2_boundaries.py` | `test_t_r2_ec_02_07_auth_error_handling` | 模擬 HTTP 401 Bad credentials；攔截未授權狀態並安全降級回傳空清單 `[]`。 |
| `T-R2-EC-03-01` | `EC-03-01` | 空值 | `TASK-03-EMPTY-DIR-GUARD` | `tests/unit/test_indexer.py` | `test_t_r2_ec_03_01_empty_directory_audit` | 對完全空白之目錄執行 `audit_skill`；拒絕審計並拋出 `ValueError("TARGET_DIR_EMPTY")`。 |
| `T-R2-EC-03-02` | `EC-03-02` | 極大值 | `TASK-03-MAX-FILE-SIZE-GUARD` | `tests/unit/test_r2_boundaries.py` | `test_t_r2_ec_03_02_large_file_size_guard` | 模擬 `SKILL.md` 大小為 52 MB（超過 50 MB 上限）；前置 `stat().st_size` 攔截並拒絕載入，回傳 `({}, "")`。 |
| `T-R2-EC-03-03` | `EC-03-03` | 非法格式 | `TASK-03-YAML-SYNTAX-GUARD` | `tests/unit/test_r2_boundaries.py`<br>`tests/unit/test_scanner.py`<br>`tests/unit/test_more_coverage.py` | `test_t_r2_ec_03_03_yaml_syntax_error`<br>`test_parse_yaml_frontmatter_corrupted`<br>`test_scanner_large_file_and_missing_end_delimiter` | 注入語法損毀或未閉合 `---` 之 YAML Frontmatter；捕獲解析異常、輸出警告並保留 Markdown 正文不崩潰。 |
| N/A (`EC-03-04`) | `EC-03-04` | 網路逾時 | N/A | N/A | N/A（不適用） | **不適用理由**：`FR-03` 結構審計與補全為純本機檔案解析與模板渲染，無任何網路操作。 |
| `T-R2-EC-03-05` | `EC-03-05` | 資料遺失 | `TASK-03-ATOMIC-FILE-WRITER` | `tests/unit/test_r2_boundaries.py` | `test_t_r2_ec_03_05_atomic_file_write` | 驗證補全寫入先寫至 `.tmp.<pid>` 再執行 `Path.replace` 原子置換，完成後目錄內無任何 `.tmp` 殘留檔。 |
| `T-R2-EC-03-06` | `EC-03-06` | 併發衝突 | `TASK-03-FILE-LOCK-HANDLER` | `tests/unit/test_more_coverage.py` | `test_indexer_coverage_details` | 驗證 PID 隔離暫存檔與 `dry_run=True/False` 雙模式切換下之寫入隔離性與骨架生成正確性。 |
| `T-R2-EC-03-07` | `EC-03-07` | 權限不足 | `TASK-03-READONLY-FS-GUARD` | `tests/unit/test_r2_boundaries.py` | `test_t_r2_ac_03_04_and_ec_03_07_write_permission_denied` | 模擬唯讀檔案系統拒絕寫入；確保清理暫存檔並拋出 `PermissionError("WRITE_PERMISSION_DENIED")`。 |
| `T-R2-EC-04-01` | `EC-04-01` | 空值 | `TASK-04-UNTRACKED-DIR-GUARD` | `tests/unit/test_versioning.py` | `test_t_r2_ec_04_01_untracked_directory` | 對非 Git 一般資料夾執行 `check_version_status`；拋出 `GitVersionError("UNTRACKED")`。 |
| `T-R2-EC-04-02` | `EC-04-02` | 極大值 | `TASK-04-LARGE-COMMIT-CAP` | `tests/unit/test_more_coverage.py` | `test_versioning_ahead_and_diverged` | 驗證 `rev-list --count` 高效比對領先/落後/分歧（`AHEAD`、`DIVERGED`）Commit 數量與標籤回滾。 |
| `T-R2-EC-04-03` | `EC-04-03` | 非法格式 | `TASK-04-GIT-CORRUPT-HANDLER` | `tests/unit/test_r2_boundaries.py` | `test_t_r2_ec_04_03_corrupt_git_repo` | 寫入損毀之 `.git/HEAD`；攔截底層例外並拋出 `GitVersionError("GIT_CORRUPT")`。 |
| `T-R2-EC-04-04` | `EC-04-04` | 網路逾時 | `TASK-04-FETCH-TIMEOUT-RETRY` | `tests/unit/test_more_coverage.py` | `test_versioning_more_branches` | 設定不可達之遠端 URL `http://127.0.0.1:9999/nonexistent.git`；`fetch` 失敗後安全降級為 `VersionStatus.CHECK_FAILED`。 |
| `T-R2-EC-04-05` | `EC-04-05` | 資料遺失 | `TASK-04-ZERO-DATALOSS-GUARD` | `tests/unit/test_r2_boundaries.py` | `test_t_r2_ec_04_05_zero_dataloss_dirty_upgrade` | 工作區存在未提交 `important_work.py` 時執行升級；拒絕覆蓋並斷言未提交檔案 100% 完好無損。 |
| `T-R2-EC-04-06` | `EC-04-06` | 併發衝突 | `TASK-04-INDEX-LOCK-RETRY` | `tests/unit/test_more_coverage.py` | `test_versioning_no_remote_refs` | 模擬 Detached HEAD 與無對應遠端分支狀態；安全降級回傳 `UP_TO_DATE` 而不崩潰。 |
| `T-R2-EC-04-07` | `EC-04-07` | 權限不足 | `TASK-04-REMOTE-AUTH-GUARD` | `tests/unit/test_more_coverage.py` | `test_versioning_more_branches` | 驗證無備份標籤時拒絕回滾並攔截遠端存取失敗。 |
| `T-R2-EC-06-01` | `EC-06-01` | 空值 | `TASK-06-WORKFLOW-EMPTY-DIR` | `tests/unit/test_workflow_auditor.py` | `test_t_r2_ac_06_05_and_ec_06_01_empty_workflow` | `workflow.md` 為 0 byte 空檔；降級回傳 `total_required=0`、`skills=[]`。 |
| `T-R2-EC-06-02` | `EC-06-02` | 極大值 | `TASK-06-WORKFLOW-LARGE-FILE` | `tests/unit/test_workflow_auditor.py` | `test_t_r2_ec_06_02_large_workflow_file` | 注入 `> 5 MB` 之超大 `workflow.md`；拒絕載入並拋出 `ValueError("WORKFLOW_FILE_TOO_LARGE")`。 |
| `T-R2-EC-06-03` | `EC-06-03` | 非法格式 | `TASK-06-WORKFLOW-CORRUPT-CHAR` | `tests/unit/test_workflow_auditor.py` | `test_t_r2_ec_06_03_corrupted_encoding` | 寫入非法二進位位元組 `\xff\xfe\xfa\x80` 夾帶合法技能路徑；以 UTF-8 `replace` 容錯解析成功提取 `my-robust-skill`。 |
| N/A (`EC-06-04`) | `EC-06-04` | 網路逾時 | N/A | N/A | N/A（不適用） | **不適用理由**：`FR-06` 啟動時工作流技能審計與補全優先執行本機目錄比對、本機技能包複製與骨架生成，無遠端網路阻斷相依。 |
| `T-R2-EC-06-05` | `EC-06-05` | 資料遺失 | `TASK-06-WORKFLOW-PRESERVE-SKILL` | `tests/unit/test_workflow_auditor.py` | `test_t_r2_ec_06_05_preserve_existing_skill_content` | 目標目錄已存在含客製化筆記之不完整 `SKILL.md`；補全後驗證原有客製化內容 100% 保留，僅追加缺失章節。 |
| `T-R2-EC-06-06` | `EC-06-06` | 併發衝突 | `TASK-06-WORKFLOW-ATOMIC-REPLACE` | `tests/unit/test_workflow_auditor.py` | `test_t_r2_ec_06_06_atomic_replace_no_temp_residue` | 工作流自動補全調用原子寫入機制；驗證補全完成後無任何 `.tmp` 暫存檔殘留，防止併發寫入碰撞。 |
| `T-R2-EC-06-07` | `EC-06-07` | 權限不足 | `TASK-06-WORKFLOW-PERM-DENIED` | `tests/unit/test_workflow_auditor.py` | `test_t_r2_ac_06_06_and_ec_06_07_write_permission_denied`<br>`test_complete_skills_skip_installed_and_skeleton_permission_error` | 複製技能或生成骨架時遭遇唯讀目錄；攔截 `PermissionError` 並拋出 `WRITE_PERMISSION_DENIED`。 |
| `T-R2-SEC-CWE88` | FR-04 安全防護 | 非法格式 (CWE-88) | `TASK-04-GIT-REF-VALIDATOR` | `tests/unit/test_r2_boundaries.py` | `test_security_cwe88_git_ref_injection_blocked` | 傳入惡意參數 `--upload-pack=evil` 與路徑穿越 `../escape` 至 `upgrade_skill`；斷言 `_validate_git_ref` 攔截並拋出 `GitVersionError("INVALID_GIT_REF")`。 |

---

## 4. R3 回歸與驗收測試分組規格 (`@pytest.mark.r3` / `T-R3-*`)

R3 負責驗證跨模組端到端（End-to-End）整合流程、乾淨環境全測試套件連續執行 2 次之無狀態穩定性（0 Flaky Tests），以及 `docs/01_spec.md` 全部 27 項 `AC-xx` 之最終驗收核對。

### 4.1 R3 端到端整合測試矩陣 (`@pytest.mark.r3`)

| 測試 ID | 涵蓋需求 | 測試腳本路徑 | 對應測試函式名稱 (`@pytest.mark.r3`) | 端到端驗證流程與斷言 |
| :--- | :--- | :--- | :--- | :--- |
| `T-R3-E2E-01` | `FR-01`、`FR-03`、`FR-05` | `tests/integration/test_e2e_workflow.py` | `test_e2e_full_lifecycle` | 完整 CLI 閉環：`scan --format json`（確認發現技能）→ `audit --format json`（確認 `is_compliant=False`）→ `complete --no-dry-run --format json`（確認補全成功 `success=True`）→ 二次 `audit --format json`（確認轉為 `is_compliant=True`）。 |
| `T-R3-E2E-02` | `FR-05`、`FR-06` | `tests/integration/test_e2e_workflow.py` | `test_e2e_workflow_audit_and_auto_complete_lifecycle` | 工作流啟動自檢閉環：建立宣告 `brainstorming` 與 `systematic-debugging` 之 `workflow.md` → 執行 CLI `workflow-audit --auto-complete --no-dry-run --format json` → 驗證自動補全 2 項技能且目標目錄內生成合規 `SKILL.md`。 |

### 4.2 R3 乾淨環境連續執行 2 次驗證協議

在階段 3B 執行 R3 時，必須於乾淨測試狀態下連續執行全測試套件（R1 + R2 + R3 共 85 項測試）2 次：

```powershell
# R3 第 1 次全量執行
.venv\Scripts\pytest.exe tests/ -v

# R3 第 2 次全量執行（驗證無狀態殘留、0 Flaky）
.venv\Scripts\pytest.exe tests/ -v
```

- **通過判準**：2 次執行皆為 `85 passed, 0 failed`，且每次執行透過 `tests/conftest.py` 之 `temp_dir` fixture 完全隔離並清理暫存檔案與臨時 Git 倉庫。

### 4.3 R3 逐條 `AC-xx` 驗收勾選表 (共 27 項)

| 需求編號 | 驗收編號 | 類型 | 對應測試 ID | 驗收斷言摘要 | 目標狀態 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **FR-01** | `AC-01-01` | 正常 | `T-R1-AC-01-01` | 掃描並提取 `SKILL.md` YAML 與子目錄結構 | `[x]` 納入 R1/R3 必驗 |
| **FR-01** | `AC-01-02` | 正常 | `T-R1-AC-01-02` | Windows 跨平台技能路徑自動探測與正規化 | `[x]` 納入 R1/R3 必驗 |
| **FR-01** | `AC-01-03` | 正常 | `T-R1-AC-01-03` | POSIX 跨平台預設技能目錄結構映射 | `[x]` 納入 R1/R3 必驗 |
| **FR-01** | `AC-01-04` | 異常 | `T-R2-AC-01-04` | 不存在路徑輸出 `PATH_NOT_FOUND` 且不中斷 | `[x]` 納入 R2/R3 必驗 |
| **FR-01** | `AC-01-05` | 異常 | `T-R2-AC-01-05` | 無讀取權限目錄輸出 `ACCESS_DENIED` 並跳過 | `[x]` 納入 R2/R3 必驗 |
| **FR-02** | `AC-02-01` | 正常 | `T-R1-AC-02-01` | GitHub REST API 搜尋結果解析與欄位正規化 | `[x]` 納入 R1/R3 必驗 |
| **FR-02** | `AC-02-02` | 正常 | `T-R1-AC-02-02` | HuggingFace Spaces API 搜尋結果解析 | `[x]` 納入 R1/R3 必驗 |
| **FR-02** | `AC-02-03` | 異常 | `T-R2-AC-02-03` | 關鍵字長度 `< 2` 或 `> 100` 攔截並回報 `VALIDATION_ERROR` | `[x]` 納入 R2/R3 必驗 |
| **FR-02** | `AC-02-04` | 異常 | `T-R2-AC-02-04` | HTTP 429 速率限制解析重置時間並回報 `RATE_LIMIT_EXCEEDED` | `[x]` 納入 R2/R3 必驗 |
| **FR-03** | `AC-03-01` | 正常 | `T-R1-AC-03-01` | 依據 `index.md` 審計缺失章節與子目錄並產出 Diff | `[x]` 納入 R1/R3 必驗 |
| **FR-03** | `AC-03-02` | 正常 | `T-R1-AC-03-02` | 自動補全缺失章節與目錄且保留既有內文 | `[x]` 納入 R1/R3 必驗 |
| **FR-03** | `AC-03-03` | 異常 | `T-R2-AC-03-03` | 無效或空白 `index.md` 攔截並回報 `INVALID_INDEX_SCHEMA` | `[x]` 納入 R2/R3 必驗 |
| **FR-03** | `AC-03-04` | 異常 | `T-R2-AC-03-04` | 唯讀目錄寫入攔截並回報 `WRITE_PERMISSION_DENIED` | `[x]` 納入 R2/R3 必驗 |
| **FR-04** | `AC-04-01` | 正常 | `T-R1-AC-04-01` | Git 遠端新 Commit 比對回報 `BEHIND` 與落後數量 | `[x]` 納入 R1/R3 必驗 |
| **FR-04** | `AC-04-02` | 正常 | `T-R1-AC-04-02` | 升級前自動建立 `backup-pre-upgrade-<timestamp>` 標籤並更新 | `[x]` 納入 R1/R3 必驗 |
| **FR-04** | `AC-04-03` | 正常 | `T-R1-AC-04-03` | 回滾指令精確還原至備份標籤對應之 Commit SHA | `[x]` 納入 R1/R3 必驗 |
| **FR-04** | `AC-04-04` | 異常 | `T-R2-AC-04-04` | Dirty Worktree 未帶 `--force` 拒絕升級並回報 `DIRTY_WORKTREE_DETECTED` | `[x]` 納入 R2/R3 必驗 |
| **FR-04** | `AC-04-05` | 異常 | `T-R2-AC-04-05` | 遠端連線逾時保護本機檔案不變並標記 `CHECK_FAILED` | `[x]` 納入 R2/R3 必驗 |
| **FR-05** | `AC-05-01` | 正常 | `T-R1-AC-05-01` | `--format json` 輸出純淨可解析 JSON 字串無 ANSI 干擾 | `[x]` 納入 R1/R3 必驗 |
| **FR-05** | `AC-05-02` | 正常 | `T-R1-AC-05-02` | 設定檔自訂平台目錄映射優先覆蓋系統預設值 | `[x]` 納入 R1/R3 必驗 |
| **FR-05** | `AC-05-03` | 異常 | `T-R2-AC-05-03` | 未知 CLI 子指令回傳退出碼 2 與說明指引 | `[x]` 納入 R2/R3 必驗 |
| **FR-06** | `AC-06-01` | 正常 | `T-R1-AC-06-01` | 解析 `workflow.md` 並準確判定 `INSTALLED`、`MISSING`、`INCOMPLETE` | `[x]` 納入 R1/R3 必驗 |
| **FR-06** | `AC-06-02` | 正常 | `T-R1-AC-06-02` | `--auto-complete --no-dry-run` 從來源複製或生成骨架補全技能 | `[x]` 納入 R1/R3 必驗 |
| **FR-06** | `AC-06-03` | 正常 | `T-R1-AC-06-03` | `--auto-complete --dry-run` 僅輸出預覽 Diff 不改動磁碟 | `[x]` 納入 R1/R3 必驗 |
| **FR-06** | `AC-06-04` | 異常 | `T-R2-AC-06-04` | 指定不存在之 `workflow.md` 回報 `ERR_WORKFLOW_NOT_FOUND` | `[x]` 納入 R2/R3 必驗 |
| **FR-06** | `AC-06-05` | 異常 | `T-R2-AC-06-05` | 空白 `workflow.md` 安全回傳 `total_required=0` | `[x]` 納入 R2/R3 必驗 |
| **FR-06** | `AC-06-06` | 異常 | `T-R2-AC-06-06` | 自動補全目標無寫入權限回報 `WRITE_PERMISSION_DENIED` | `[x]` 納入 R2/R3 必驗 |

---

## 5. 現行測試腳本檔案結構總覽 (`tests/` Inventory)

| 測試腳本檔案路徑 | 所屬分組標記 | 測試函式數量 | 涵蓋模組與職責說明 |
| :--- | :--- | :---: | :--- |
| `tests/conftest.py` | 共用 Fixture | - | 提供跨平台安全清理之 `temp_dir`（含 Windows 唯讀 `.git` 屬性解除）、`sample_valid_skill`、`sample_incomplete_skill`、`sample_index_file`、`git_repo_with_remote`。 |
| `tests/unit/test_scanner.py` | `r1` (2) / `r2` (4) | 6 | 驗證 `FR-01` 技能目錄識別、路徑掃描、不存在路徑、空目錄、循環 Symlink 與損毀 YAML。 |
| `tests/unit/test_config.py` | `r1` (6) | 6 | 驗證 `FR-01` 與 `FR-05` 跨平台預設路徑結構、多平台路徑去重、`AppConfig` 自訂覆寫與 TOML 設定檔載入。 |
| `tests/unit/test_remote_search.py` | `r1` (2) / `r2` (3) | 5 | 驗證 `FR-02` GitHub 與 HuggingFace 搜尋解析、關鍵字長度邊界、HTTP 429 速率限制與 `limit=50` 收斂。 |
| `tests/unit/test_indexer.py` | `r1` (3) / `r2` (2) | 5 | 驗證 `FR-03` `index.md` 規則解析、缺失章節/目錄審計、自動補全、空白 `index.md` 與空目錄攔截。 |
| `tests/unit/test_versioning.py` | `r1` (2) / `r2` (2) | 4 | 驗證 `FR-04` Git `BEHIND` 狀態偵測、升級前快照備份標籤、版本回滾、Dirty Worktree 防護與非 Git 目錄攔截。 |
| `tests/unit/test_cli.py` | `r1` (4) / `r2` (1) | 5 | 驗證 `FR-05` 與 `FR-06` CLI `--format json` 純淨輸出、`audit`/`complete`/`workflow-audit`/`healthcheck` 指令與未知子指令錯誤碼。 |
| `tests/unit/test_workflow_auditor.py` | `r1` (6) / `r2` (9) | 15 | 驗證 `FR-06` `workflow.md` 技能需求解析、別名正規化、就緒狀態分類、來源庫複製與骨架補全、超大檔案/亂碼/權限拒絕/原子寫入防禦。 |
| `tests/unit/test_r2_boundaries.py` | `r2` (15) | 15 | 集中驗證 `FR-01`–`FR-04` 極限邊界與故障注入（權限拒絕、串流大量目錄、併發刪檔、純空白查詢、非 JSON 回應、網路逾時退避、401 鑑權、50MB 檔案防護、原子寫入、Git 損毀、CWE-88 參數注入攔截）。 |
| `tests/unit/test_more_coverage.py` | `r1` (13) / `r2` (4) | 17 | 補足 5 大核心模組分支覆蓋率（≥ 90%），涵蓋多平台路徑推論、HTTP 500 重試、AHEAD/DIVERGED 分支、Detached HEAD、深層掃描邊界與回滾異常分支。 |
| `tests/unit/test_cli_workflow.py` | `r1` (2) / `r2` (3) | 5 | 驗證 `FR-05` 與 `FR-06` CLI `workflow-audit` 表格與 JSON 輸出、自動補全、缺少檔案與非法平台異常。 |
| `tests/integration/test_e2e_workflow.py` | `r3` (2) | 2 | 驗證 `R3` 端到端完整生命週期（`scan -> audit -> complete -> audit` 及 `workflow-audit --auto-complete`）。 |
| **總計** | **R1: 40 / R2: 43 / R3: 2** | **85** | **100% 覆蓋 `docs/01_spec.md` 全部 57 項追溯矩陣條目與 R3 整合驗收** |

---

## 6. 缺陷分級與修復升級規則 (Defect Escalation & Loop Rules)

依據 `workflow.md` 第 2 節（階段 3B）與第 7 節（失敗處理與升級規則）：
1. **缺陷嚴重度分級**：
   - **阻塞 (Blocker)**：崩潰、資料損毀、安全漏洞（如 CWE-22/CWE-88）、核心功能完全無法運作 → 允許剩餘數 **0**。
   - **重大 (Critical)**：主要 `AC-xx` 未達成、關鍵異常未處理、核心模組覆蓋率 < 90% → 允許剩餘數 **0**。
   - **一般 (Major)**：次要功能偏差、非關鍵邊界處理不完善 → 允許剩餘數 **0**。
   - **輕微 (Minor)**：排版、訊息措辭、非功能性微調 → 記錄於 `docs/04_test_report.md` 已知限制，不阻斷放行。
2. **TDD 修復閉環與升級條件**：
   - 任何測試失敗必須遵循「最小重現測試 → 定位根因 → 最小修復 → 重跑驗證」閉環。
   - 同一問題修復 **3 次仍失敗**：立即停止自動重試，彙整根因與嘗試紀錄升級請示使用者。
   - 若修復涉及架構變更（影響 ≥ 3 個模組）或推翻 `docs/01_spec.md` 規格，必須退回階段 1 或階段 2 重新對齊。
