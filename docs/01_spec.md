# 跨平台全域技能管理系統 (SkillManager) 軟體需求規格書 (SRS)

## 1. 系統概述與設計背景

### 1.1 系統目標
SkillManager 為一套跨平台（支援 Windows、macOS、Linux）全域 AI 技能與插件管理工具，支援各主流 AI Agent 與 Coding Assistant 環境（包含 Claude Code、OpenAI Codex / Copilot、Google Antigravity、Cursor）。
本系統提供本機全域技能庫探測追蹤、GitHub 與 HuggingFace 遠端技能搜尋、依據 `index.md` 索引規格進行技能結構審計與自動骨架補全，以及技能版本控制與上游更新追蹤。

### 1.2 系統邊界與跨平台標準架構
本系統將不同平台之技能統一抽象為標準技能單元（Skill Entity），包含元資料、操作手冊、腳本工具及參考資源：
```text
+-----------------------------------------------------------------------------------+
|                            SkillManager 跨平台管理核心架構                         |
+-----------------------------------------------------------------------------------+
|  [外部遠端來源]                                                                    |
|   ├── GitHub Repositories (Topic: agent-skills, claude-skills)                     |
|   └── HuggingFace Hub (Spaces / Models / Datasets 標籤: skills, tool-use)          |
|                                                                                   |
|  [SkillManager 核心引擎]                                                          |
|   ├── Scanner 模組: 多平台全域路徑探測 (Claude, Antigravity, Codex, Cursor)          |
|   ├── Indexer 模組: index.md 規範解析、審計校驗、骨架補全與 Diff 生成              |
|   ├── Search 模組: GitHub REST API + HuggingFace Hub API 搜尋檢索                  |
|   └── Versioning 模組: Git Commit / HF Commit 追蹤、差異比對、快照與升級回滾       |
|                                                                                   |
|  [本機各平台全域目錄對應 (Local Storage)]                                         |
|   ├── Claude:       ~/.claude/skills/                                             |
|   ├── Antigravity:  ~/.gemini/antigravity/skills/ & builtin/skills/               |
|   ├── Codex:        ~/.codex/skills/ 或 ~/.copilot/skills/                        |
|   └── Cursor:       ~/.cursor/skills/                                             |
+-----------------------------------------------------------------------------------+
```

---

## 2. 功能需求清單 (Functional Requirements, FR)

### FR-01: 跨平台本機全域技能目錄掃描與結構追蹤
- **功能描述**：掃描並列舉各平台預設或使用者自訂之全域技能目錄，解析技能元資料（YAML frontmatter 與檔案目錄結構），並產出標準化清單。
- **輸入項目**：
  - `platform`（字串，可選：`claude`、`antigravity`、`codex`、`cursor`、`all`，預設為 `all`）。
  - `custom_paths`（字串陣列，自訂額外掃描路徑清單）。
  - `max_depth`（整數，掃描目錄深度，範圍 1 至 5，預設為 3）。
- **輸出項目**：
  - `skills`（結構化陣列，每筆包含：`id`、`name`、`platform`、`path`、`has_skill_md`、`has_scripts`、`has_references`、`version`、`description`）。
  - `summary`（統計物件：`total_scanned`、`valid_skills`、`invalid_skills`）。

#### 驗收標準 (Acceptance Criteria, AC)
- **AC-01-01 (正常)**：
  - **Given**：本機存在符合規範之技能目錄，內含 `SKILL.md` 且具有 YAML frontmatter（包含 `name` 與 `description`）。
  - **When**：執行 `skill-manager scan --platform all`。
  - **Then**：系統回傳退出碼 0，JSON 陣列內包含該技能物件，`has_skill_md` 為 `true`，且 `name` 與 YAML frontmatter 數值完全一致。
- **AC-01-02 (正常)**：
  - **Given**：系統運行於 Windows 環境，使用者未指定任何路徑。
  - **When**：執行自動探測。
  - **Then**：掃描路徑自動解析環境變數 `%USERPROFILE%`，依序檢查 `%USERPROFILE%\.claude\skills` 與 `%USERPROFILE%\.gemini\antigravity\skills`，回傳合併後之技能清單。
- **AC-01-03 (正常)**：
  - **Given**：系統運行於 Linux 或 macOS 環境，使用者未指定任何路徑。
  - **When**：執行自動探測。
  - **Then**：掃描路徑自動解析環境變數 `$HOME`，依序檢查 `$HOME/.claude/skills` 與 `$HOME/.gemini/antigravity/skills`，回傳合併後之技能清單。
- **AC-01-04 (異常)**：
  - **Given**：使用者透過 `--custom_paths` 指定一個不存在之目錄路徑 `/path/to/not_exist`。
  - **When**：執行掃描。
  - **Then**：系統輸出警告訊息至 stderr 標記 `PATH_NOT_FOUND: /path/to/not_exist`，略過該路徑並繼續掃描其餘合法路徑，最終回傳退出碼 0。
- **AC-01-05 (異常)**：
  - **Given**：指定目錄因作業系統權限限制無法讀取（Permission Denied）。
  - **When**：執行掃描。
  - **Then**：系統輸出警告至 stderr 標記 `ACCESS_DENIED: <path>`，跳過該資料夾，不引發未捕捉之例外崩潰。

---

### FR-02: GitHub 與 HuggingFace 遠端技能搜尋與資訊檢視
- **功能描述**：串接 GitHub REST API 與 HuggingFace Hub API，依關鍵字搜尋社群發布之 Agent Skills、Plugins 與 Prompts，並提供下載安裝前之詳細資訊預覽。
- **輸入項目**：
  - `query`（字串，搜尋關鍵字，長度須介於 2 至 100 字元）。
  - `source`（字串，可選：`github`、`huggingface`、`all`，預設為 `all`）。
  - `sort_by`（字串，可選：`stars`、`updated`，預設為 `stars`）。
  - `limit`（整數，單次抓取筆數上限，範圍 1 至 50，預設為 20）。
  - `page`（整數，分頁碼，大於等於 1，預設為 1）。
- **輸出項目**：
  - `items`（陣列，每筆包含：`source`、`repo_id`、`url`、`description`、`stars_or_downloads`、`updated_at`、`tags`）。
  - `pagination`（物件：`current_page`、`limit`、`total_count`）。

#### 驗收標準 (Acceptance Criteria, AC)
- **AC-02-01 (正常)**：
  - **Given**：設定有效之 GitHub Token，使用者查詢關鍵字 `docker` 且 `source=github`。
  - **When**：調用 GitHub Search API 檢索 `docker topic:agent-skills,claude-skills`。
  - **Then**：回傳 HTTP 200，解析回傳結構，包含符合該關鍵字之倉庫清單，每筆均有 `repo_id` 與 `url`。
- **AC-02-02 (正常)**：
  - **Given**：使用者查詢關鍵字 `code-review` 且 `source=huggingface`。
  - **When**：調用 HuggingFace Hub API 檢索標籤含 `skills` 或 `tool-use` 之項目。
  - **Then**：回傳 HTTP 200，解析回傳結構，每筆包含 `repo_id`、`stars_or_downloads` 數值。
- **AC-02-03 (異常)**：
  - **Given**：使用者輸入關鍵字長度少於 2 字元（例如 `a`）或超過 100 字元。
  - **When**：發起搜尋請求。
  - **Then**：系統拒絕發出網路請求，回傳退出碼 2，stderr 輸出錯誤訊息 `VALIDATION_ERROR: query length must be between 2 and 100 characters`。
- **AC-02-04 (異常)**：
  - **Given**：未提供 Token 導致 GitHub API 回傳 HTTP 429（Rate Limit Exceeded）。
  - **When**：執行搜尋。
  - **Then**：系統攔截 429 狀態碼，回傳退出碼 4，輸出明確錯誤訊息 `RATE_LIMIT_EXCEEDED` 並顯示 API 標頭所指明之重置時間（Reset Timestamp）。

---

### FR-03: 依據 index.md 規範之技能結構審計與自動骨架補全
- **功能描述**：讀取技能根目錄之 `index.md` 索引定義文件（包含該生態系或專案所規範之技能目錄結構、必要 YAML 欄位與指定 Markdown 章節），對本機技能進行合規性審計；對於缺失部分產出補全範本或直接執行補全寫入。
- **輸入項目**：
  - `target_skill_dir`（字串，目標技能資料夾路徑）。
  - `index_file_path`（字串，規範參考 `index.md` 路徑，未提供時預設使用目標技能上層目錄之 `index.md` 或內建標準規格庫）。
  - `dry_run`（布林值，`true` 代表僅產出檢查報告與 Diff，不更動磁碟檔案；`false` 代表直接寫入，預設為 `true`）。
- **輸出項目**：
  - `audit_result`（物件：`is_compliant`、`missing_fields`、`missing_sections`、`missing_dirs`）。
  - `diff_content`（字串，Unified Diff 格式之預期補全變更內容）。
  - `modified_files`（字串陣列，實際被寫入或預計更動之檔案路徑清單）。

#### 驗收標準 (Acceptance Criteria, AC)
- **AC-03-01 (正常)**：
  - **Given**：目標技能之 `SKILL.md` 僅有標題，缺少必要章節 `## When to Use` 與 `## Instructions`，且缺少 `references/` 資料夾。
  - **When**：執行 `skill-manager audit --target ./my-skill --index ./index.md`。
  - **Then**：回傳 `is_compliant=false`，`missing_sections` 包含 `["When to Use", "Instructions"]`，`missing_dirs` 包含 `["references"]`。
- **AC-03-02 (正常)**：
  - **Given**：目標技能存在審計缺漏項目，且指令帶入 `--dry-run=false`。
  - **When**：執行補全指令 `skill-manager complete --target ./my-skill --index ./index.md --dry-run=false`。
  - **Then**：系統在保留既有內容前提下，於 `SKILL.md` 底部補齊缺失章節骨架，自動建立 `references/` 目錄，並回傳退出碼 0。
- **AC-03-03 (異常)**：
  - **Given**：指定之 `index.md` 內容為空或非有效 Markdown 標題結構（無法解析章節階層）。
  - **When**：執行審計或補全。
  - **Then**：系統拒絕處理，回傳退出碼 3，stderr 輸出 `INVALID_INDEX_SCHEMA: unable to parse section headers from index.md`。
- **AC-03-04 (異常)**：
  - **Given**：目標目錄內存在同名但唯讀（Read-Only）或權限不足之 `SKILL.md`。
  - **When**：執行寫入補全。
  - **Then**：系統終止寫入，不產生局部毀損檔案，回傳退出碼 5，stderr 輸出 `WRITE_PERMISSION_DENIED: <path>`。

---

### FR-04: 技能版本控制、遠端追蹤與更新差異比對
- **功能描述**：追蹤本機技能之上游來源（Git Repository 或 HuggingFace Repo），比對本機 Commit SHA 與遠端最新版本之差距，產出差異日誌；在升級時自動建立安全快照，並支援一鍵更新與回滾。
- **輸入項目**：
  - `skill_dir`（字串，目標技能本機目錄）。
  - `action`（字串，可選：`status`、`diff`、`upgrade`、`rollback`）。
  - `target_ref`（字串，指定升級之 Git Tag、Branch 或 Commit SHA，未提供則預設為遠端預設分支最新 Commit）。
- **輸出項目**：
  - `version_status`（字串，狀態值：`UP_TO_DATE`、`BEHIND`、`AHEAD`、`DIVERGED`、`UNTRACKED`）。
  - `local_commit`（字串，40 字元 SHA 或版本標籤）。
  - `remote_commit`（字串，40 字元 SHA 或版本標籤）。
  - `behind_count`（整數，落後 Commit 數量）。
  - `diff_summary`（字串，檔案異動增減統計）。

#### 驗收標準 (Acceptance Criteria, AC)
- **AC-04-01 (正常)**：
  - **Given**：技能目錄為 Git 倉庫且設定遠端 origin，遠端已推送 2 個新 Commit。
  - **When**：執行 `skill-manager track status --target ./my-skill`。
  - **Then**：系統回傳退出碼 0，`version_status` 為 `BEHIND`，`behind_count` 等於 2。
- **AC-04-02 (正常)**：
  - **Given**：本機技能處於 `BEHIND` 狀態，且本機工作區乾淨無未提交變更。
  - **When**：執行 `skill-manager track upgrade --target ./my-skill`。
  - **Then**：系統於升級前建立 Git 標籤 `backup-pre-upgrade-<timestamp>`，將代碼更新至遠端最新 Commit，回傳退出碼 0。
- **AC-04-03 (正常)**：
  - **Given**：剛執行過升級之技能目錄，存在前次備份標籤。
  - **When**：執行 `skill-manager track rollback --target ./my-skill`。
  - **Then**：系統自動還原至備份標籤所對應之 Commit，驗證本機 HEAD 與備份標籤一致，回傳退出碼 0。
- **AC-04-04 (異常)**：
  - **Given**：本機技能目錄包含未提交之修改檔案（Dirty Working Tree）。
  - **When**：未帶 `--force` 旗標直接執行升級。
  - **Then**：系統拒絕執行合併覆蓋，回傳退出碼 6，stderr 輸出 `DIRTY_WORKTREE_DETECTED: stash or commit local changes before upgrading`。
- **AC-04-05 (異常)**：
  - **Given**：遠端 Git 倉庫 URL 無法連線或連線逾時（> 10 秒）。
  - **When**：執行狀態檢查或更新。
  - **Then**：系統標記該狀態為 `NETWORK_TIMEOUT`，回傳退出碼 7，本機檔案保持不變。

---

### FR-05: 統一 CLI 命令列與跨平台設定檔管理
- **功能描述**：提供具備結構化 JSON 輸出旗標之 CLI 介面，支援設定檔（`config.toml`）管理各平台目錄自訂映射與 API 憑證。
- **輸入項目**：
  - 全域參數：`--format`（可選：`table`、`json`，預設為 `table`）、`--config`（設定檔路徑）。
  - 子指令：`scan`、`search`、`audit`、`complete`、`track`、`config`。
- **輸出項目**：
  - 終端控制台渲染表格，或標準 stdout 結構化 JSON 字串；執行狀態碼（0 為成功，非 0 為具體定義之錯誤碼）。

#### 驗收標準 (Acceptance Criteria, AC)
- **AC-05-01 (正常)**：
  - **Given**：執行任何查詢或操作子指令時附加 `--format json` 參數。
  - **When**：指令執行完成。
  - **Then**：stdout 輸出為合法的單一 JSON 字串，可被 `jq` 或 Python `json.loads` 解析，無任何 ANSI 彩色控制碼干擾。
- **AC-05-02 (正常)**：
  - **Given**：使用者於 `config.toml` 中配置自訂的 Claude 目錄 `D:\custom\claude\skills`。
  - **When**：執行 `skill-manager scan --platform claude`。
  - **Then**：掃描程序優先自該配置路徑讀取技能，覆蓋系統預設目錄。
- **AC-05-03 (異常)**：
  - **Given**：輸入未定義之子指令（例如 `skill-manager fly`）。
  - **When**：CLI 接收指令。
  - **Then**：回傳退出碼 2，輸出標準 Help 指引資訊至 stderr。

---

## 3. 非功能需求 (Non-Functional Requirements, NFR)

### 3.1 量化指標
- **NFR-01 (跨平台相容性)**：
  - 核心程式庫必須相容於 Windows 10/11 (PowerShell 7 / CMD)、macOS 12+ (Zsh / Bash)、Linux (Ubuntu 20.04+, Debian 11+)。所有檔案路徑解析須採用作業系統相容格式，禁止寫死 `/` 或 `\` 分隔符。
- **NFR-02 (掃描效能門檻)**：
  - 在本機 SSD 環境下，掃描包含 500 個技能資料夾、檔案總數 5000 個之目錄結構，整體掃描、解析元資料並輸出清單之耗時不得超過 1500 ms。
- **NFR-03 (網路連線與逾時重試)**：
  - GitHub REST API 與 HuggingFace Hub API 之連線建立逾時時間設定為 5 秒，封包傳輸逾時設定為 10 秒。
  - 面對 HTTP 500、502、503、504 或網路中斷，必須自動執行重試，重試次數上限為 3 次，採用指數退避間隔（1 秒、2 秒、4 秒）。
- **NFR-04 (測試覆蓋率門檻與核心模組清單)**：
  - 專案整體行覆蓋率（Line Coverage）必須達到 80% 以上。
  - **核心模組清單（門檻 ≥ 90%）**：
    1. `core.scanner`（多平台目錄遍歷與檔案過濾器）
    2. `core.indexer`（`index.md` 語法解析、規則審計器與模板渲染器）
    3. `core.versioning`（Git 狀態檢查器、快照備份器與回滾控制器）
    4. `core.remote_search`（GitHub 與 HuggingFace API 請求轉換與結果標準化解析器）
- **NFR-05 (資源消耗限制)**：
  - 執行批次掃描或版本更新時，系統常駐記憶體（RSS）峰值不得超過 128 MB。

---

## 4. 邊界與異常情境推演 (R2 邊界檢驗清單)

依據 7 類邊界測試情境（空值、極大值、非法格式、網路逾時、資料遺失、併發衝突、權限不足）進行全面推演：

| 邊界編號 | 歸屬需求 | 邊界類別 | 情境具體說明 | 預期行為 (拒絕 / 重試 / 降級 / 回報錯誤) |
| :--- | :--- | :--- | :--- | :--- |
| **EC-01-01** | FR-01 | 空值 | 指定掃描之路徑資料夾存在，但內部為完全空白無任何檔案 | **降級**：回傳空陣列 `[]`，統計數量為 0，回傳退出碼 0 |
| **EC-01-02** | FR-01 | 極大值 | 單一全域目錄內包含超過 10,000 個技能子資料夾 | **降級**：採串流讀取（Generator）分批載入，維持記憶體小於 128 MB，完成全部列舉 |
| **EC-01-03** | FR-01 | 非法格式 | 目錄內存在符號連結（Symlink）且形成循環迴圈（Circular Symlink） | **回報錯誤**：追蹤已存取之真實路徑 Inode/Realpath，偵測到迴圈即刻跳過並記錄警告，不陷入無窮迴圈 |
| **EC-01-04** | FR-01 | 網路逾時 | N/A | 本功能為純本機磁碟掃描，不涉及網路連線 |
| **EC-01-05** | FR-01 | 資料遺失 | 讀取過程中其他行程刪除正在讀取之檔案 | **降級**：攔截 `FileNotFoundError`，標記該項目為讀取失效，繼續掃描其餘項目 |
| **EC-01-06** | FR-01 | 併發衝突 | N/A | 本功能僅執行唯讀（Read-Only）檢視，無檔案鎖定衝突問題 |
| **EC-01-07** | FR-01 | 權限不足 | 系統管理員專屬目錄無法以一般使用者權限開啟 | **回報錯誤**：輸出 `ACCESS_DENIED` 警告至 stderr，跳過該節點，回傳其餘合法檔案 |
| **EC-02-01** | FR-02 | 空值 | 搜尋參數 `query` 僅包含空白鍵或長度為 0 | **拒絕**：驗證攔截，回報參數錯誤，不發起遠端連線 |
| **EC-02-02** | FR-02 | 極大值 | 請求分頁參數 `limit=9999` | **降級**：強制收斂限制數值至上限 50，回傳第 1 頁之 50 筆資料 |
| **EC-02-03** | FR-02 | 非法格式 | API 回傳不合法的非 JSON 內容（例如 Cloudflare HTML 攔截頁） | **回報錯誤**：解析器攔截 JSONDecodeError，封裝為 `ERR_REMOTE_RESPONSE_INVALID` 回傳退出碼 4 |
| **EC-02-04** | FR-02 | 網路逾時 | 連線 GitHub 或 HuggingFace 伺服器連續 3 次超過 10 秒無回應 | **重試後回報錯誤**：以 1s、2s、4s 間隔重試 3 次，若仍失敗回報 `NETWORK_TIMEOUT`，退出碼 7 |
| **EC-02-05** | FR-02 | 資料遺失 | N/A | 遠端搜尋為即時查詢，不持久化寫入本機資料 |
| **EC-02-06** | FR-02 | 併發衝突 | 頻繁連續觸發搜尋導致觸發 Client 端 Rate Limit | **降級**：內部佇列控制請求頻率，限制發起請求速率不大於每秒 5 次 |
| **EC-02-07** | FR-02 | 權限不足 | 未授權之私有倉庫搜尋或 Token 無效 | **回報錯誤**：攔截 HTTP 401/403，提示 `AUTH_REQUIRED: invalid token` |
| **EC-03-01** | FR-03 | 空值 | 目標技能資料夾內不存在任何檔案 | **拒絕**：無法審計空白目錄，提示 `TARGET_DIR_EMPTY` |
| **EC-03-02** | FR-03 | 極大值 | `SKILL.md` 檔案大小超過 50 MB | **拒絕**：AI 技能手冊常態規格大小應小於 5 MB，超過 50 MB 判定為異常二進位檔案，拒絕載入 |
| **EC-03-03** | FR-03 | 非法格式 | `SKILL.md` 之 YAML frontmatter 語法錯誤（冒號未加空格、無結尾） | **回報錯誤**：解析器回報具體行號語法錯誤，標記為 `INVALID_YAML_FRONTMATTER` |
| **EC-03-04** | FR-03 | 網路逾時 | N/A | 結構審計與骨架補全為本機檔案處理，無網路交互 |
| **EC-03-05** | FR-03 | 資料遺失 | 補全過程中系統斷電或磁碟已滿（Disk Full） | **回報錯誤**：採用原子寫入機制（先寫入暫存檔 `.tmp`，成功後再置換 Atomic Replace），防止檔案內容遺失 |
| **EC-03-06** | FR-03 | 併發衝突 | 兩個不同終端同時對同一個技能執行 `complete --dry-run=false` | **回報錯誤**：寫入前檢查檔案鎖（FileLock），取得失敗回傳 `RESOURCE_LOCKED` |
| **EC-03-07** | FR-03 | 權限不足 | 目標技能檔案為唯讀檔案系統或無寫入權限 | **回報錯誤**：寫入前檢查寫入權限，無權限則回傳退出碼 5 `WRITE_PERMISSION_DENIED` |
| **EC-04-01** | FR-04 | 空值 | 指定之目錄並非 Git 倉庫，且無任何上游來源記錄檔 | **拒絕**：回傳 `UNTRACKED: directory is not a git repository and has no upstream info` |
| **EC-04-02** | FR-04 | 極大值 | 遠端倉庫落後超過 1,000 個 Commits | **降級**：僅比對最新 HEAD Commit SHA 與顯示落後數量，不載入全量異動 Commit 內文 |
| **EC-04-03** | FR-04 | 非法格式 | 本機 `.git` 資料夾毀損（Git Repository Corrupt） | **回報錯誤**：攔截 GitCommandError，回報 `GIT_CORRUPT` 並建議修復方式 |
| **EC-04-04** | FR-04 | 網路逾時 | `git fetch` 執行超過 15 秒 | **重試後回報錯誤**：重試 1 次，失敗後回傳 `NETWORK_TIMEOUT`，本機代碼維持現狀 |
| **EC-04-05** | FR-04 | 資料遺失 | 升級過程遇到衝突覆蓋未備份檔案 | **拒絕**：未提交變更時拒絕執行，強制要求備份或暫存（Stash），確保 0 資料遺失 |
| **EC-04-06** | FR-04 | 併發衝突 | Git index.lock 正在被其他 Git 程序佔用 | **回報錯誤**：偵測到 `index.lock` 時暫停 500 ms，若仍佔用則回報 `GIT_INDEX_LOCKED` |
| **EC-04-07** | FR-04 | 權限不足 | 存取需 SSH Key 或 Private Token 之私有遠端倉庫 | **回報錯誤**：攔截驗證錯誤，提示 `REMOTE_AUTH_FAILED` |

---

## 5. FR × NFR 衝突分析矩陣

| 交叉比對項目 | NFR-01 (跨平台) | NFR-02 (掃描效能 ≤1.5s) | NFR-03 (網路逾時重試) | NFR-04 (測試覆蓋率 ≥80%/90%) | NFR-05 (記憶體 ≤128MB) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **FR-01 (本機目錄掃描)** | **已決**：採用 `pathlib.Path` 與規範化路徑分隔，適配 Windows 與 POSIX。 | **已決**：使用底層 `os.scandir` 串流走訪取代遞迴 `os.walk`，達成 500 個目錄小於 500 ms。 | **無衝突**：本機掃描不使用網路。 | **已決**：Scanner 模組屬於核心模組，單元測試覆蓋率門檻設定為 ≥ 90%。 | **已決**：使用產生器（Generator）惰性載入，避免一次性將所有檔案結構載入記憶體。 |
| **FR-02 (遠端搜尋)** | **已決**：使用統一 HTTP 客戶端（`httpx`），無平台相依問題。 | **無衝突**：搜尋走網路 I/O，不計入磁碟掃描效能。 | **已決**：設定 5 秒連線逾時、10 秒讀取逾時與 3 次指數退避重試。 | **已決**：Remote Search 模組屬於核心模組，透過 Mock API 達成 ≥ 90% 測試覆蓋率。 | **已決**：限制單次搜尋回傳筆數最大 50 筆，JSON 負載量小於 500 KB。 |
| **FR-03 (結構審計與補全)** | **已決**：統一採用 UTF-8 編碼與 LF/CRLF 自動相容解析。 | **已決**：僅解析 Markdown 標題層級與 YAML 頭部，不解析全文正文，維持極低運算耗時。 | **無衝突**：純本機檔案操作。 | **已決**：Indexer 模組屬於核心模組，覆蓋率門檻 ≥ 90%。 | **已決**：限制單一檔案大小小於 50 MB，讀取時採用逐行解析。 |
| **FR-04 (版本追蹤更新)** | **已決**：封裝標準 Git CLI 與 GitPython，相容各平台 Git 路徑。 | **已決**：僅抓取 Commit SHA 元數據，不抓取全量物件樹（Tree Object）。 | **已決**：Git Fetch 設定逾時門檻 15 秒，逾時後終止網路連線並重試 1 次。 | **已決**：Versioning 模組屬於核心模組，覆蓋率門檻 ≥ 90%。 | **已決**：Diff 比對使用串流比對，記憶體耗用小於 10 MB。 |
| **FR-05 (CLI 與配置)** | **已決**：CLI 引數採用標準 POSIX 相容語法，各平台解析一致。 | **無衝突**：CLI 框架啟動時間小於 100 ms。 | **無衝突**：配置管理為純本機讀寫。 | **已決**：CLI 介面層設定覆蓋率門檻 ≥ 80%。 | **已決**：Rich 渲染器於非 TTY 模式自動降級為純文字，避免渲染暫存區過大。 |

---

## 6. 技術選型建議與評估矩陣 (Tech Stack Recommendation)

為達成跨平台、輕量高效、易於整合各 AI Agent（Claude Code, Codex, Antigravity）與易於發布之目標，針對四種候選技術架構進行評估：

### 6.1 候選架構分析與權衡矩陣

| 評估維度 | 方案 A: Python 3.15+ (Typer + Pydantic + httpx + GitPython) | 方案 B: TypeScript / Node.js (Commander + Octokit + Zod + simple-git) | 方案 C: Rust (Clap + Tokio + Reqwest + Git2) | 方案 D: Go (Cobra + BubbleTea + go-git) |
| :--- | :--- | :--- | :--- | :--- |
| **開發速度與維護成本** | **極高** (語法簡潔、生態成熟) | **高** (型別完整、非同步健全) | **中** (生命週期與借用檢查開發週期長) | **高** (簡潔、標準函式庫豐富) |
| **AI 生態系與 HuggingFace 原生整合度** | **最高** (`huggingface_hub` 原生 SDK、直接調用模型) | **良好** (`@huggingface/hub` JS SDK) | **普通** (需自行封裝 REST API) | **普通** (需自行封裝 REST API) |
| **各平台 AI Agent 呼叫整合 (MCP / JSON)** | **極佳** (可直接透過 FastMCP 封裝為 MCP Server) | **極佳** (Model Context Protocol 官方原生 SDK 支援度最好) | **普通** (需額外整合非官方 MCP SDK) | **良好** (社群有 Go MCP 實作) |
| **跨平台執行檔案分發便捷性** | **良好** (支援 `uv` 一鍵執行 `uvx skill-manager`，或 PyInstaller 打包) | **極佳** (支援 `npx skill-manager` 零安裝即跑) | **最高** (編譯為單一靜態二進位檔，0 依賴) | **最高** (單一執行檔，跨平台交叉編譯極易) |
| **掃描效能與資源消耗** | 優秀 (SSD 500 個目錄 < 400ms，記憶體 ~35MB) | 優秀 (500 個目錄 < 350ms，記憶體 ~45MB) | 最極致 (500 個目錄 < 50ms，記憶體 ~12MB) | 極致 (500 個目錄 < 80ms，記憶體 ~18MB) |

### 6.2 推薦技術選型結論
**推薦採用「方案 A (Python 3.15+)」為主體實作，並具備封裝為 FastMCP Server 之擴充性**：
1. **核心技術組合**：
   - **CLI 框架**：`typer` + `rich`（提供直覺之命令列互動、表格渲染與進度條，兼具 `--format json` 結構化輸出）。
   - **資料校驗與模型定義**：`pydantic v2`（提供嚴格之設定檔、技能元資料與 API 回傳結構校驗）。
   - **遠端 API 請求**：`httpx`（具備非同步、連線池、重試與逾時控制）+ `huggingface_hub`（官方 Python Hub API）。
   - **Git 操作**：`gitpython` 與本機 fallback 呼叫系統 `git` CLI。
   - **分發機制**：使用現代 Python 套件管理器 `uv`，使用者無需手動建立虛擬環境，可直接以 `uvx --from . skill-manager` 或 `pip install -e .` 立即使用。
2. **未來 Phase 擴充性（MCP Server 整合）**：
   - 由於 Claude Code、Antigravity、Cursor 均深度支援 Model Context Protocol (MCP)，採用 Python 架構可藉由 `mcp` / `fastmcp` 將本工具無縫暴露出 `scan_skills`、`search_remote_skills`、`audit_skill` 等 MCP Tools，直接讓各大 AI Agent 在對話中呼叫。

---

## 7. 系統介面定義與資料流 (Data Flow & Interfaces)

### 7.1 本機技能元資料實體 (Skill Entity Schema)
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["id", "name", "platform", "path", "has_skill_md", "version_status"],
  "properties": {
    "id": { "type": "string" },
    "name": { "type": "string" },
    "description": { "type": "string" },
    "platform": { "type": "string", "enum": ["claude", "antigravity", "codex", "cursor", "universal"] },
    "path": { "type": "string" },
    "has_skill_md": { "type": "boolean" },
    "has_scripts": { "type": "boolean" },
    "has_references": { "type": "boolean" },
    "yaml_metadata": { "type": "object" },
    "version_status": { "type": "string", "enum": ["UP_TO_DATE", "BEHIND", "AHEAD", "DIVERGED", "UNTRACKED"] },
    "commit_sha": { "type": "string" },
    "upstream_url": { "type": "string" }
  }
}
```

### 7.2 資料流架構圖
```text
+------------------+         +--------------------+         +--------------------+
|  CLI / MCP 調用  | ------> | Config & Platform  | ------> |  Scanner Engine    |
| (scan / audit..) |         | Path Resolver      |         | (os.scandir / Pyd) |
+------------------+         +--------------------+         +--------------------+
                                                                      |
                                                                      v
+------------------+         +--------------------+         +--------------------+
| Formatted Output | <------ | Indexer / Version  | <------ | Skill Entity Store |
| (Rich / JSON)    |         | Compare & Auditor  |         | (In-Memory Cache)  |
+------------------+         +--------------------+         +--------------------+
                                       ^
                                       | (HTTP / Git fetch)
                             +--------------------+
                             | Remote Providers   |
                             | (GitHub / HF Hub)  |
                             +--------------------+
```

---

## 8. 需求與測試追溯矩陣 (Traceability Matrix)

| 功能需求編號 | 驗收標準 / 邊界編號 | 類型 | 實作任務標籤 (Phase 2) | 預定測試 ID |
| :--- | :--- | :--- | :--- | :--- |
| **FR-01** | AC-01-01 | 正常 | TASK-01-SCANNER-CORE | `T-R1-AC-01-01` |
| **FR-01** | AC-01-02 | 正常 | TASK-01-PATH-RESOLVER-WIN | `T-R1-AC-01-02` |
| **FR-01** | AC-01-03 | 正常 | TASK-01-PATH-RESOLVER-POSIX | `T-R1-AC-01-03` |
| **FR-01** | AC-01-04 | 異常 | TASK-01-SCANNER-ERROR-PATH | `T-R2-AC-01-04` |
| **FR-01** | AC-01-05 | 異常 | TASK-01-SCANNER-ERROR-PERM | `T-R2-AC-01-05` |
| **FR-01** | EC-01-01 | 異常 | TASK-01-SCANNER-EMPTY-DIR | `T-R2-EC-01-01` |
| **FR-01** | EC-01-02 | 異常 | TASK-01-SCANNER-STREAMING | `T-R2-EC-01-02` |
| **FR-01** | EC-01-03 | 異常 | TASK-01-SCANNER-SYMLOOP | `T-R2-EC-01-03` |
| **FR-01** | EC-01-05 | 異常 | TASK-01-SCANNER-CONCURRENT-DEL | `T-R2-EC-01-05` |
| **FR-01** | EC-01-07 | 異常 | TASK-01-SCANNER-ACCESS-DENIED | `T-R2-EC-01-07` |
| **FR-02** | AC-02-01 | 正常 | TASK-02-GITHUB-SEARCH-API | `T-R1-AC-02-01` |
| **FR-02** | AC-02-02 | 正常 | TASK-02-HF-SEARCH-API | `T-R1-AC-02-02` |
| **FR-02** | AC-02-03 | 異常 | TASK-02-QUERY-VALIDATOR | `T-R2-AC-02-03` |
| **FR-02** | AC-02-04 | 異常 | TASK-02-RATE-LIMIT-HANDLER | `T-R2-AC-02-04` |
| **FR-02** | EC-02-01 | 異常 | TASK-02-QUERY-BLANK-VALIDATOR | `T-R2-EC-02-01` |
| **FR-02** | EC-02-02 | 異常 | TASK-02-LIMIT-CAP-HANDLER | `T-R2-EC-02-02` |
| **FR-02** | EC-02-03 | 異常 | TASK-02-INVALID-JSON-HANDLER | `T-R2-EC-02-03` |
| **FR-02** | EC-02-04 | 異常 | TASK-02-RETRY-BACKOFF-CLIENT | `T-R2-EC-02-04` |
| **FR-02** | EC-02-06 | 異常 | TASK-02-CLIENT-RATE-LIMITER | `T-R2-EC-02-06` |
| **FR-02** | EC-02-07 | 異常 | TASK-02-AUTH-ERROR-HANDLER | `T-R2-EC-02-07` |
| **FR-03** | AC-03-01 | 正常 | TASK-03-INDEX-AUDITOR | `T-R1-AC-03-01` |
| **FR-03** | AC-03-02 | 正常 | TASK-03-SKILL-COMPLETER | `T-R1-AC-03-02` |
| **FR-03** | AC-03-03 | 異常 | TASK-03-INDEX-SCHEMA-VALIDATE | `T-R2-AC-03-03` |
| **FR-03** | AC-03-04 | 異常 | TASK-03-WRITE-PERM-GUARD | `T-R2-AC-03-04` |
| **FR-03** | EC-03-01 | 異常 | TASK-03-EMPTY-DIR-GUARD | `T-R2-EC-03-01` |
| **FR-03** | EC-03-02 | 異常 | TASK-03-MAX-FILE-SIZE-GUARD | `T-R2-EC-03-02` |
| **FR-03** | EC-03-03 | 異常 | TASK-03-YAML-SYNTAX-GUARD | `T-R2-EC-03-03` |
| **FR-03** | EC-03-05 | 異常 | TASK-03-ATOMIC-FILE-WRITER | `T-R2-EC-03-05` |
| **FR-03** | EC-03-06 | 異常 | TASK-03-FILE-LOCK-HANDLER | `T-R2-EC-03-06` |
| **FR-03** | EC-03-07 | 異常 | TASK-03-READONLY-FS-GUARD | `T-R2-EC-03-07` |
| **FR-04** | AC-04-01 | 正常 | TASK-04-GIT-STATUS-CHECKER | `T-R1-AC-04-01` |
| **FR-04** | AC-04-02 | 正常 | TASK-04-GIT-UPGRADE-BACKUP | `T-R1-AC-04-02` |
| **FR-04** | AC-04-03 | 正常 | TASK-04-GIT-ROLLBACK-EXEC | `T-R1-AC-04-03` |
| **FR-04** | AC-04-04 | 異常 | TASK-04-DIRTY-WORKTREE-GUARD | `T-R2-AC-04-04` |
| **FR-04** | AC-04-05 | 異常 | TASK-04-GIT-FETCH-TIMEOUT | `T-R2-AC-04-05` |
| **FR-04** | EC-04-01 | 異常 | TASK-04-UNTRACKED-DIR-GUARD | `T-R2-EC-04-01` |
| **FR-04** | EC-04-02 | 異常 | TASK-04-LARGE-COMMIT-CAP | `T-R2-EC-04-02` |
| **FR-04** | EC-04-03 | 異常 | TASK-04-GIT-CORRUPT-HANDLER | `T-R2-EC-04-03` |
| **FR-04** | EC-04-04 | 異常 | TASK-04-FETCH-TIMEOUT-RETRY | `T-R2-EC-04-04` |
| **FR-04** | EC-04-05 | 異常 | TASK-04-ZERO-DATALOSS-GUARD | `T-R2-EC-04-05` |
| **FR-04** | EC-04-06 | 異常 | TASK-04-INDEX-LOCK-RETRY | `T-R2-EC-04-06` |
| **FR-04** | EC-04-07 | 異常 | TASK-04-REMOTE-AUTH-GUARD | `T-R2-EC-04-07` |
| **FR-05** | AC-05-01 | 正常 | TASK-05-CLI-JSON-OUTPUT | `T-R1-AC-05-01` |
| **FR-05** | AC-05-02 | 正常 | TASK-05-CONFIG-PATH-MAPPING | `T-R1-AC-05-02` |
| **FR-05** | AC-05-03 | 異常 | TASK-05-CLI-SUBCOMMAND-ERROR | `T-R2-AC-05-03` |
