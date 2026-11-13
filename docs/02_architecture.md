# SkillManager 系統架構與設計說明書 (docs/02_architecture.md)

**版本**：v0.3.0  
**定位**：跨平台本機 AI 技能與外掛程式管理工具（CLI + 現代化 Textual TUI + 全域常駐/特定時機調用切換開關）

---

## 1. 架構總覽與分層設計

本系統遵循高內聚、低耦合原則，採用五層模組架構（CLI 介面層、TUI 互動層、非同步適配層、核心領域模組層、實體與事件層），完全相容於 Python 3.15+ 環境與跨平台作業系統（macOS / Linux / Windows）。

```text
+-----------------------------------------------------------------------------------------+
|                               SkillManager v0.3.0 模組分層架構圖                         |
+-----------------------------------------------------------------------------------------+

  [ 介面與入口層 (Presentation & Entry Layer) ]
   ├── skill_manager.cli: Typer CLI 雙模入口 (scan, search, audit, complete, track, mode, tui)
   │    ├── sys.stdin.isatty() 狀態偵測與 --no-tui 安全降級
   │    ├── Table 格式化輸出 (Rich Console)
   │    └── 結構化 JSON 輸出 (供 AI Agent / CI/CD 直接調用)
   └── skill_manager.tui: Textual TUI 現代化儀表盤
        ├── app.SkillManagerApp: 雙欄響應式佈局 (Alternate Screen, Header, Tabs, Footer)
        ├── widgets.SkillTree: 帶狀態徽章 (🟢/🔴 與 📌/⚡) 之分類樹狀檢視
        ├── widgets.DiffViewer: 語法高亮之 Unified Diff 即時檢視器
        ├── widgets.GlobalSwitchModal: 全域策略切換對話框 (ALL_RESIDENT, ALL_ON_DEMAND, RESTORE_LAST)
        ├── widgets.WorkflowView: 工作流依賴矩陣與選擇性補全
        └── widgets.RemoteSearchView: 遠端市集動態搜尋 (300ms Debounce 與逾時防護)
              │
              ▼
  [ 配置與解析層 (Configuration & Path Layer) ]
   └── skill_manager.config:
        ├── 跨平台路徑解析器 (自動展開 %USERPROFILE% 與 $HOME)
        ├── 平台映射預設值 (Claude, Antigravity, Codex, Cursor, Universal)
        └── TOML 設定檔載入器與環境變數 (GITHUB_TOKEN, HF_TOKEN)
              │
              ▼
  [ 非同步適配與 Worker 層 (Async Adapter & Worker Bridge) ]
   └── skill_manager.core.async_adapter:
        ├── asyncio run_in_executor 非同步核心呼叫包裝
        ├── async_scan_skills, async_audit_skill, async_complete_skill
        ├── async_check_version, async_toggle_skill_mode, async_apply_global_policy
        ├── async_search_remote (具備 5s/10s 逾時中斷保護，EC-12)
        └── 主線程零凍結 (60 FPS 穩態渲染，NFR-06, NFR-07)
              │
              ▼
  [ 核心領域層 (Core Domain Layer) ]
   ├── core.mode_controller:  技能執行模式切換、全域策略批次套用、.tmp 原子替換、快照儲存與還原
   ├── core.platform_open:    跨平台原生檔案總管開啟 (macOS open, Windows explorer, Linux xdg-open)
   ├── core.scanner:          os.scandir 串流遍歷、YAML Frontmatter 執行模式自動識別、符號連結防護
   ├── core.indexer:          index.md 規範審計器、Unified Diff 生成器、骨架補全與原子寫入引擎
   ├── core.versioning:       GitPython 封裝、SHA 狀態比對、快照標籤備份、一鍵回滾
   ├── core.remote_search:     GitHub REST API 與 HuggingFace Hub 檢索 (指數退避重試)
   └── core.workflow_auditor: 工作流技能依賴解析、本機庫就緒審計與自動補全引擎
              │
              ▼
  [ 實體、模型與事件層 (Data, Entity & Event Layer) ]
   ├── skill_manager.models:
   │    ├── SkillExecutionMode (RESIDENT 📌 / ON_DEMAND ⚡)
   │    ├── GlobalPolicyMode (ALL_RESIDENT / ALL_ON_DEMAND / CUSTOM / RESTORE_LAST)
   │    ├── SkillEntity (擴充 execution_mode 欄位)
   │    ├── ScanResult, ScanSummary, SearchItem, SearchResult
   │    ├── AuditResult, TrackResult, PlatformType, VersionStatus
   │    └── WorkflowSkillRequirement, WorkflowSkillStatus, WorkflowAuditResult, WorkflowCompleteResult
   └── skill_manager.events:
        ├── ScanProgressEvent, SkillSelectedEvent
        ├── SkillModeChangedEvent, GlobalPolicyChangedEvent
        ├── AuditCompleteEvent, VersionUpdateEvent, LogEvent
```

---

## 2. 元件交互與資料流 (Component Interactions)

### 2.1 技能執行模式切換與全域開關資料流 (Mode Control Flow)

```text
User CLI (`mode`) / TUI (`[Space]`, `[M]`, `[G]`)
        │
        ▼
[mode_controller.toggle_skill_mode] / [apply_global_policy]
        │
        ├─► 讀取 SKILL.md Frontmatter (正則提取或 YAML 解析)
        │     └── 若無 Frontmatter ──► 自動生成最小結構 (EC-07)
        ├─► 變更 execution_mode 欄位 (resident <-> on_demand)
        ├─► 備份快照至 .skill_manager_policy_snapshot.json (供 RESTORE_LAST 還原)
        ├─► 寫入暫存檔 target_path.tmp.<pid>
        ├─► os.replace 原子替換原檔 (0 資料遺失，EC-08)
        │     └── 若批次寫入中斷 ──► 自動觸發 rollback 快照還原 (EC-09)
        ▼
[SkillModeChangedEvent] / [GlobalPolicyChangedEvent] ──► 回傳結果並更新 UI
```

### 2.2 Textual 雙欄響應式介面與非同步 Worker 資料流 (TUI & Async Worker Flow)

```text
Terminal Launch (`skill-manager tui` / `skill-manager`)
        │
        ▼ (isatty 檢查)
[SkillManagerApp] ──► on_mount / on_resize (EC-14 視窗小於 80x24 警示檢查)
        │
        ├─► [run_worker] ──► [async_adapter.async_scan_skills] (背景加載，不阻塞 Main Loop)
        │                          │
        │                          ▼
        │                   [scanner.scan_skills]
        │                          │
        │                          ▼
        │                   [_update_skill_list] (填充 SkillTree 與徽章)
        │
        ├─► 鍵盤互動:
        │     ├── `[A]` ──► [async_audit_skill] ──► [DiffViewer.show_diff]
        │     ├── `[C]` ──► [async_complete_skill] ──► 預覽/寫入 Unified Diff
        │     ├── `[Space]` ──► [async_toggle_skill_mode] ──► 更新 📌/⚡ 徽章
        │     ├── `[O]` ──► [platform_open.open_folder_in_file_manager]
        │     └── `[Q]` ──► 乾淨退出 Alternate Screen，無任何畫面殘留
```

### 2.3 跨平台原生檔案總管開啟資料流 (Platform Open Flow)

```text
TUI (`[O]` 鍵) / CLI
        │
        ▼
[platform_open.open_folder_in_file_manager(folder_path)]
        │
        ├─► Path(folder_path).resolve() (驗證路徑存在與型態)
        ├─► 防注入檢查：禁止 shell=True，採固定參數陣列 (EC-13)
        ├─► 平台分支判斷:
        │     ├── Darwin (macOS)  ──► subprocess.Popen(["open", str(path)])
        │     ├── Windows         ──► subprocess.Popen(["explorer", str(path)])
        │     └── Linux / 其他    ──► subprocess.Popen(["xdg-open", str(path)])
        ▼
回傳 True (成功喚起) / False (記錄警告至 stderr，主程序不中斷)
```

### 2.4 工作流矩陣選擇性補全與遠端市集防手震搜尋資料流 (Workflow & Remote Flow)

```text
[Tab 2: WorkflowView]
        │
        ├── 讀取 workflow.md ──► SelectionList 呈現技能矩陣 (🟢/🟡/🔴)
        └── 使用者勾選特定項目 ──► 按下 [C] ──► 僅補全所選技能 (其餘維持不變，AC-11)

[Tab 3: RemoteSearchView]
        │
        ├── 使用者鍵入關鍵字 ──► 300ms Debounce 防手震計時器 (NFR-07, AC-12)
        └── 觸發 [async_search_remote] (逾時 5s/10s 攔截保護，EC-12)
              │
              ├── 成功 ──► DataTable 呈現 GitHub / HuggingFace 結果
              └── 逾時 ──► 停止 Spinner 並顯示逾時警示，介面零卡頓
```

---

## 3. 模組隔離、非同步解耦與安全防禦邊界

1. **Textual 與核心邏輯 100% 解耦**：
   - 所有 UI 與業務邏輯的互動均經由 `async_adapter.py` 或發布標準事件（`events.py`）。
   - 核心領域函式（`scanner`, `mode_controller`, `indexer`, `versioning`）保持純同步無 UI 依賴，既可單獨於 CLI 執行，亦可供 TUI 非同步調用。
2. **三項核心安全防護 (Security Hardening)**：
   - **CWE-22 (Path Traversal 防護)**：補全與目錄建立時強制執行 `resolved.is_relative_to(root)` 檢驗，防止 `../../` 惡意路徑跳脫。
   - **CWE-88 (Git Argument Injection 防護)**：版本比對與標籤還原時嚴格正則過濾 `_SAFE_REF_PATTERN`，禁止以 `-` 起頭或包含 `..` 之參數。
   - **CWE-78 (Command Injection 防護)**：檔案總管開啟模組嚴禁使用 `shell=True`，所有參數皆以陣列形式傳入 `subprocess.Popen`。
3. **無 TTY 與管道安全降級 (EC-11, AC-13)**：
   - 在 Docker、CI/CD 或管線重導向環境（`| cat`, `| jq`）執行時，系統自動檢測 `sys.stdin.isatty()` 與 `--no-tui` 旗標，絕不初始化 Textual 終端驅動，自動降級為標準 CLI 輸出，避免拋出 `Inappropriate ioctl for device` 例外。
4. **極端尺寸邊界防禦 (EC-14)**：
   - 當終端視窗尺寸小於 80x24 字元時，TUI 介面即時隱藏主要雙欄面板並於畫面中央顯示警告提示，防止 Textual Grid 崩潰破版。
