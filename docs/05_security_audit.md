# SkillManager 資訊安全審計與弱點評估報告 (docs/05_security_audit.md)

## 1. 審計總覽 (Executive Summary)

- **審計階段**：階段 4 — 資訊安全檢查 (Security Audit & Vulnerability Assessment)
- **負責模型**：Gemini 4
- **審計日期**：2026-10-23
- **審計範圍**：`src/skill_manager/` 全模組原始碼、`tests/` 測試套件、`pyproject.toml` 相依配置、Git 儲存庫狀態
- **審計結論**：**通過 (PASSED — 0 High / 0 Medium / 0 Low Open Vulnerabilities)**

---

## 2. 靜態原始碼安全審查 (SAST & CWE 弱點分析)

依據 OWASP 與 CWE 標準，針對核心模組進行逐行靜態分析與主動防禦加固：

| CWE 編號 | 弱點類別 | 檢查模組與位置 | 審查與防禦實作細節 | 風險狀態 |
| :--- | :--- | :--- | :--- | :--- |
| **CWE-78 / CWE-88** | 指令注入 / 參數注入 (Command & Argument Injection) | `core/versioning.py` | 1. 全專案 0 處使用 `os.system`、`subprocess.Popen(shell=True)`、`eval` 或 `exec`。<br>2. 針對 `upgrade_skill` 與 `rollback_skill` 接收之 `target_ref` / `tag_name`，實作 `_validate_git_ref` 白名單正則校驗 (`^[a-zA-Z0-9_./\-]+$`)，強制攔截 `-` 開頭之惡意 Git 旗標注入（如 `--upload-pack`）。 | **安全 (已加固並由單元測試驗證)** |
| **CWE-22** | 路徑周遊 (Path Traversal) | `core/indexer.py`<br>`core/scanner.py` | 1. 所有路徑皆透過 `pathlib.Path.resolve()` 正規化。<br>2. 於 `complete_skill` 建立子目錄時，強制執行 `target_sub.is_relative_to(resolved_root)` 邊界檢查，阻絕 `../` 目錄逃逸寫入。 | **安全 (已加固)** |
| **CWE-502** | 不安全反序列化 (Deserialization of Untrusted Data) | `core/scanner.py`<br>`config.py` | 1. 解析 `SKILL.md` Frontmatter 嚴格採用 `yaml.safe_load()`，禁止執行任意 Python 物件標籤。<br>2. 設定檔解析採用標準庫 `tomllib.load()` 唯讀解析。 | **安全** |
| **CWE-400** | 資源耗盡 (Uncontrolled Resource Consumption / DoS) | `core/scanner.py`<br>`core/remote_search.py`<br>`core/versioning.py` | 1. 檔案讀取前強制檢查 `st_size > 50 MB`，阻斷超大二進位檔載入。<br>2. 目錄走訪具 `max_depth` 限制與 `visited_realpaths` 循環軟連結防禦。<br>3. HTTP 客戶端配置 `connect=5.0s, timeout=10.0s`；Git fetch 配置 `kill_after_timeout=15s`。 | **安全** |
| **CWE-377** | 不安全暫存檔與競態 (Insecure Temporary File) | `core/indexer.py` | 補全寫入採用程序隔離暫存檔 `SKILL.md.tmp.<pid>`，寫入完成後以 `Path.replace()` 執行作業系統層級原子替換（Atomic Replace）。 | **安全** |
| **CWE-319** | 明文傳輸機敏資訊 (Cleartext Transmission) | `core/remote_search.py` | GitHub API (`https://api.github.com`) 與 HuggingFace API (`https://huggingface.co`) 均強制使用 HTTPS TLS 加密連線。 | **安全** |

---

## 3. 機敏資訊與憑證外洩檢驗 (Secrets & Credential Scanning)

### 3.1 原始碼憑證掃描
- **掃描正規表達式**：`ghp_|hf_|sk-|BEGIN OPENSSH PRIVATE KEY|BEGIN RSA PRIVATE KEY|password\s*=`
- **掃描結果**：
  - `src/` 內 **0 處**硬編碼 API Token、金鑰或密碼（符合 **CWE-798** 規範）。
  - 遠端鑑權憑證僅自執行環境變數 `os.environ.get("GITHUB_TOKEN")` 與 `os.environ.get("HF_TOKEN")` 動態讀取，且不寫入日誌或標準輸出。

### 3.2 儲存庫與工作區機敏檔案檢查
- 先前誤置於工作區根目錄之 SSH 金鑰（`SkillManager`、`SkillManager.pub`）已確認移至系統標準安全目錄 `~/.ssh/`，工作區內無殘留私鑰。
- `.gitignore` 已完整配置忽略 `.env`、`.env.*`、`config.local.toml`、`*.tmp`，防止本地憑證誤提交。

---

## 4. 相依套件安全檢驗 (SCA — Software Composition Analysis)

檢視專案執行環境（`.venv`）之核心相依套件版本與已知 CVE 狀態：

| 套件名稱 | 安裝版本 | 用途 | 已知高/中危 CVE 狀態 |
| :--- | :--- | :--- | :--- |
| `pydantic` | `2.14.1` | 資料模型與嚴格型別驗證 | 0 已知漏洞 |
| `httpx` | `0.28.1` | 安全非同步/同步 HTTP 客戶端 | 0 已知漏洞 |
| `gitpython` | `3.2.1` | Git 儲存庫操作封裝 (已搭配 `_validate_git_ref` 防護) | 0 已知漏洞 |
| `pyyaml` | `6.0.3` | YAML 解析 (`safe_load` 模式) | 0 已知漏洞 |
| `huggingface-hub` | `2.2.0` | HuggingFace Hub 檢索整合 | 0 已知漏洞 |
| `typer` | `0.27.3` | CLI 介面框架 | 0 已知漏洞 |
| `rich` | `15.0.0` | 終端安全格式化渲染 | 0 已知漏洞 |

---

## 5. 安全加固回歸測試驗證 (Verification Log)

針對階段 4 新增之安全防禦邏輯（CWE-88 Git 參數注入攔截、CWE-22 路徑周遊攔截），已新增專屬安全測試案例 `test_security_cwe88_git_ref_injection_blocked` 並執行全量回歸測試：
- **測試指令**：`.venv\Scripts\pytest.exe -v`
- **執行結果**：**55 / 55 PASSED (100% 通過，0 失敗)**

---

## 6. 階段 4 檢核清單 (Security Gate Checklist)

- [x] **SAST 靜態分析**：無 SQLi、Command Injection、Path Traversal、Unsafe Deserialization 風險。
- [x] **機敏資訊掃描**：無硬編碼 API Key、Token 或私鑰檔案殘留。
- [x] **SCA 相依套件審計**：全數採用最新穩定版本，無已知高/中危 CVE。
- [x] **最小權限原則**：預設 `complete` 為 `dry_run=True` 唯讀預覽；`upgrade` 預設阻擋未提交變更覆寫。
- [x] **階段 4 檢核點**：資安審計通過，無高危弱點與明文機敏資料（**0 High/Medium Vulnerabilities**），核准放行至階段 5（環境容器化與部署）。

