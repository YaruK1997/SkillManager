# SkillManager 測試計畫與測試規格書 (docs/03_test_plan.md)

## 1. 測試策略與多輪驗證架構 (Test Strategy & Architecture)

本測試計畫依據 `docs/01_spec.md` 需求規格書與追溯矩陣制定，結合 `systematic-debugging` 系統化除錯工程方法，針對 SkillManager 跨平台全域技能管理系統，建立分層、多輪遞進的驗證防線：

```text
+-------------------------------------------------------------------------------+
|                      SkillManager 三輪測試分層架構                             |
+-------------------------------------------------------------------------------+
  [ 階段 3A: 測試設計 ]
   ├── R1: 功能正確性套件 (單元測試 + 正常路徑驗證) ─── 門檻: 通過率 100%, 覆蓋率 >= 80% (核心 >= 90%)
   ├── R2: 極限邊界與異常注入套件 (邊界測試 + 故障模擬) ── 門檻: 通過率 100%, EC 對應率 100%
   └── R3: 乾淨環境回歸驗收 (2 次無狀態連續執行) ──── 門檻: 0 失敗, 0 不穩定測試 (Flaky)
```

---

## 2. 測試輪次與覆蓋門檻規範 (Test Rounds Specification)

| 測試輪次 | 測試主題 | 涵蓋範圍 | 通過放行門檻 |
| :--- | :--- | :--- | :--- |
| **R1：功能正確性** | 正常路徑與業務邏輯驗證 | 正常類 `AC-xx`（測試 ID `T-R1-*`）+ 核心模組單元測試 | 通過率 100%；專案整體行覆蓋率 ≥ 80%；核心模組（`scanner`、`indexer`、`versioning`、`remote_search`）≥ 90% |
| **R2：邊界與異常** | 極值、故障注入與邊際防禦 | 異常類 `AC-xx` + 全部 `EC-xx`（測試 ID `T-R2-*`）+ 異常注入 | 通過率 100%；`EC-xx` 對應測試覆蓋率 100%；斷言具體錯誤代碼與狀態碼 |
| **R3：回歸與驗收** | 乾淨環境一致性與逐條驗收 | 乾淨虛擬環境連續執行全測試套件 2 次 + AC 逐條驗收勾選表 | 2 次執行 100% 通過（0 失敗、0 Flaky）；AC 驗收勾選表 100% 達成；0 阻塞與重大缺陷 |

---

## 3. 極端邊界推演與異常注入設計 (Systematic Debugging Injection)

依據 7 大邊界類別，規劃確定性故障注入模式：

### 3.1 檔案與檔案系統邊界 (FR-01, FR-03)
- **空目錄與空檔案**：注入完全空白目錄與零位元組檔案，驗證系統安全降級回傳空清單，不崩潰（`T-R2-EC-01-01`、`T-R2-EC-03-01`）。
- **極大檔案防禦**：注入 > 50 MB 之超大虛擬檔案，驗證系統在進入正則解析前透過 `stat().st_size` 阻斷，保護記憶體小於 128 MB（`T-R2-EC-03-02`）。
- **循環符號連結 (Circular Symlink)**：建立指向自身的目錄軟連結，驗證遍歷時透過 `visited_realpaths` 追蹤機制防止遞迴爆棧（`T-R2-EC-01-03`）。
- **併發檔案刪除**：在目錄遍歷至檔案讀取瞬間注入 `FileNotFoundError`，驗證系統安全跳過被移除之檔案（`T-R2-EC-01-05`）。
- **唯讀檔案系統與權限拒絕**：注入 `PermissionError`，驗證原子寫入中止並拋出明確錯誤代碼 `WRITE_PERMISSION_DENIED`，不殘留 `.tmp` 垃圾檔（`T-R2-AC-03-04`、`T-R2-EC-03-07`）。

### 3.2 網路傳輸與遠端 API 邊界 (FR-02, FR-04)
- **API 速率限制 (Rate Limit 429)**：模擬 GitHub 標頭 `x-ratelimit-reset` 與 429 回應，驗證解析重置時間並正確拋出 `RateLimitExceededError`（`T-R2-AC-02-04`）。
- **連線逾時與指數退避**：注入 `httpx.ConnectTimeout`，驗證重試間隔遵循 1s、2s、4s 指數退避，達到 3 次上限後終止（`T-R2-EC-02-04`）。
- **惡意非 JSON 內容**：模擬 Cloudflare 攔截或 HTML 錯誤頁，驗證防止 `JSONDecodeError` 溢出為未捕獲例外，封裝為 `ERR_REMOTE_RESPONSE_INVALID`（`T-R2-EC-02-03`）。
- **遠端私有倉庫未授權 (401/403)**：模擬 Token 失效，驗證安全降級為空結果並提示鑑權指引（`T-R2-EC-02-07`）。

### 3.3 版本控制與 Git 邊界 (FR-04)
- **Dirty Worktree 衝突防禦**：本機存在未提交變更時執行更新，驗證安全拒絕覆蓋，保護工作區 0 檔案遺失（`T-R2-AC-04-04`、`T-R2-EC-04-05`）。
- **Git 倉庫毀損**：注入損毀的 `.git/HEAD` 檔案，驗證封裝為 `GIT_CORRUPT` 錯誤代碼（`T-R2-EC-04-03`）。
- **Git 遠端不可達逾時**：模擬遠端無響應，驗證自動將版本狀態標記為 `CHECK_FAILED` 並保護本機 Commit 不變（`T-R2-AC-04-05`）。

---

## 4. 需求與測試覆蓋率矩陣 (Traceability Matrix & Test Mapping)

本套件 54 項自動化測試對應 `docs/01_spec.md` 全部需求：

| 測試 ID | 來源規格 | 測試類別 | 實作測試函式 | 所在檔案 |
| :--- | :--- | :--- | :--- | :--- |
| `T-R1-AC-01-01` | AC-01-01 | R1 功能 | `test_t_r1_ac_01_01_valid_skill_detection` | `tests/unit/test_scanner.py` |
| `T-R1-AC-01-02` | AC-01-02 | R1 功能 | `test_t_r1_ac_01_02_and_03_scan_skills_custom_path` | `tests/unit/test_scanner.py` |
| `T-R1-AC-01-03` | AC-01-03 | R1 功能 | `test_default_platform_paths_structure` | `tests/unit/test_config.py` |
| `T-R2-AC-01-04` | AC-01-04 | R2 異常 | `test_t_r2_ac_01_04_missing_path_handled` | `tests/unit/test_scanner.py` |
| `T-R2-AC-01-05` | AC-01-05 | R2 異常 | `test_t_r2_ac_01_05_permission_denied` | `tests/unit/test_r2_boundaries.py` |
| `T-R2-EC-01-01` | EC-01-01 | R2 邊界 | `test_t_r2_ec_01_01_empty_directory` | `tests/unit/test_scanner.py` |
| `T-R2-EC-01-02` | EC-01-02 | R2 邊界 | `test_t_r2_ec_01_02_streaming_large_directory` | `tests/unit/test_r2_boundaries.py` |
| `T-R2-EC-01-03` | EC-01-03 | R2 邊界 | `test_t_r2_ec_01_03_circular_symlink` | `tests/unit/test_scanner.py` |
| `T-R2-EC-01-05` | EC-01-05 | R2 邊界 | `test_t_r2_ec_01_05_concurrent_file_deletion` | `tests/unit/test_r2_boundaries.py` |
| `T-R2-EC-01-07` | EC-01-07 | R2 邊界 | `test_t_r2_ac_01_05_permission_denied` | `tests/unit/test_r2_boundaries.py` |
| `T-R1-AC-02-01` | AC-02-01 | R1 功能 | `test_t_r1_ac_02_01_github_search` | `tests/unit/test_remote_search.py` |
| `T-R1-AC-02-02` | AC-02-02 | R1 功能 | `test_t_r1_ac_02_02_huggingface_search` | `tests/unit/test_remote_search.py` |
| `T-R2-AC-02-03` | AC-02-03 | R2 異常 | `test_t_r2_ac_02_03_query_validation` | `tests/unit/test_remote_search.py` |
| `T-R2-AC-02-04` | AC-02-04 | R2 異常 | `test_t_r2_ac_02_04_rate_limit_exceeded` | `tests/unit/test_remote_search.py` |
| `T-R2-EC-02-01` | EC-02-01 | R2 邊界 | `test_t_r2_ec_02_01_blank_query_validation` | `tests/unit/test_r2_boundaries.py` |
| `T-R2-EC-02-02` | EC-02-02 | R2 邊界 | `test_t_r2_ec_02_02_limit_capping` | `tests/unit/test_remote_search.py` |
| `T-R2-EC-02-03` | EC-02-03 | R2 邊界 | `test_t_r2_ec_02_03_invalid_json_response` | `tests/unit/test_r2_boundaries.py` |
| `T-R2-EC-02-04` | EC-02-04 | R2 邊界 | `test_t_r2_ec_02_04_network_timeout_retry` | `tests/unit/test_r2_boundaries.py` |
| `T-R2-EC-02-06` | EC-02-06 | R2 邊界 | `test_remote_search_retry_and_headers` | `tests/unit/test_more_coverage.py` |
| `T-R2-EC-02-07` | EC-02-07 | R2 邊界 | `test_t_r2_ec_02_07_auth_error_handling` | `tests/unit/test_r2_boundaries.py` |
| `T-R1-AC-03-01` | AC-03-01 | R1 功能 | `test_t_r1_ac_03_01_audit_incomplete_skill` | `tests/unit/test_indexer.py` |
| `T-R1-AC-03-02` | AC-03-02 | R1 功能 | `test_t_r1_ac_03_02_complete_skill_applied` | `tests/unit/test_indexer.py` |
| `T-R2-AC-03-03` | AC-03-03 | R2 異常 | `test_t_r2_ac_03_03_invalid_index_schema` | `tests/unit/test_indexer.py` |
| `T-R2-AC-03-04` | AC-03-04 | R2 異常 | `test_t_r2_ac_03_04_and_ec_03_07_write_permission_denied` | `tests/unit/test_r2_boundaries.py` |
| `T-R2-EC-03-01` | EC-03-01 | R2 邊界 | `test_t_r2_ec_03_01_empty_directory_audit` | `tests/unit/test_indexer.py` |
| `T-R2-EC-03-02` | EC-03-02 | R2 邊界 | `test_t_r2_ec_03_02_large_file_size_guard` | `tests/unit/test_r2_boundaries.py` |
| `T-R2-EC-03-03` | EC-03-03 | R2 邊界 | `test_t_r2_ec_03_03_yaml_syntax_error` | `tests/unit/test_r2_boundaries.py` |
| `T-R2-EC-03-05` | EC-03-05 | R2 邊界 | `test_t_r2_ec_03_05_atomic_file_write` | `tests/unit/test_r2_boundaries.py` |
| `T-R2-EC-03-06` | EC-03-06 | R2 邊界 | `test_indexer_coverage_details` | `tests/unit/test_more_coverage.py` |
| `T-R2-EC-03-07` | EC-03-07 | R2 邊界 | `test_t_r2_ac_03_04_and_ec_03_07_write_permission_denied` | `tests/unit/test_r2_boundaries.py` |
| `T-R1-AC-04-01` | AC-04-01 | R1 功能 | `test_t_r1_ac_04_01_behind_status` | `tests/unit/test_versioning.py` |
| `T-R1-AC-04-02` | AC-04-02 | R1 功能 | `test_t_r1_ac_04_02_and_03_upgrade_and_rollback` | `tests/unit/test_versioning.py` |
| `T-R1-AC-04-03` | AC-04-03 | R1 功能 | `test_t_r1_ac_04_02_and_03_upgrade_and_rollback` | `tests/unit/test_versioning.py` |
| `T-R2-AC-04-04` | AC-04-04 | R2 異常 | `test_t_r2_ac_04_04_dirty_worktree_guard` | `tests/unit/test_versioning.py` |
| `T-R2-AC-04-05` | AC-04-05 | R2 異常 | `test_t_r2_ac_04_05_git_fetch_timeout` | `tests/unit/test_r2_boundaries.py` |
| `T-R2-EC-04-01` | EC-04-01 | R2 邊界 | `test_t_r2_ec_04_01_untracked_directory` | `tests/unit/test_versioning.py` |
| `T-R2-EC-04-02` | EC-04-02 | R2 邊界 | `test_versioning_ahead_and_diverged` | `tests/unit/test_more_coverage.py` |
| `T-R2-EC-04-03` | EC-04-03 | R2 邊界 | `test_t_r2_ec_04_03_corrupt_git_repo` | `tests/unit/test_r2_boundaries.py` |
| `T-R2-EC-04-04` | EC-04-04 | R2 邊界 | `test_versioning_more_branches` | `tests/unit/test_more_coverage.py` |
| `T-R2-EC-04-05` | EC-04-05 | R2 邊界 | `test_t_r2_ec_04_05_zero_dataloss_dirty_upgrade` | `tests/unit/test_r2_boundaries.py` |
| `T-R2-EC-04-06` | EC-04-06 | R2 邊界 | `test_versioning_no_remote_refs` | `tests/unit/test_more_coverage.py` |
| `T-R2-EC-04-07` | EC-04-07 | R2 邊界 | `test_versioning_more_branches` | `tests/unit/test_more_coverage.py` |
| `T-R1-AC-05-01` | AC-05-01 | R1 功能 | `test_t_r1_ac_05_01_json_format_output` | `tests/unit/test_cli.py` |
| `T-R1-AC-05-02` | AC-05-02 | R1 功能 | `test_config_override_paths` | `tests/unit/test_config.py` |
| `T-R2-AC-05-03` | AC-05-03 | R2 異常 | `test_t_r2_ac_05_03_unknown_subcommand` | `tests/unit/test_cli.py` |

---

## 5. R3 回歸測試與驗收檢核流程 (R3 Acceptance Protocol)

在階段 3B 執行 R3 時，必須嚴格落實以下協議：
1. **乾淨環境驗證**：連續執行兩次全量測試套件：
   ```powershell
   .venv\Scripts\pytest.exe -v
   .venv\Scripts\pytest.exe -v
   ```
   通過標準：兩次執行結果皆為 0 失敗，斷言一致，無任何 Flaky 不穩定測試。
2. **逐條 AC 驗收勾選表**：核對 AC-01-01 至 AC-05-03 共 21 項驗收條件，達到 100% 達成率。
3. **產出測試驗證報告**：執行日誌與檢驗清單正式記錄於 `docs/04_test_report.md`。

