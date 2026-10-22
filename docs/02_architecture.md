# SkillManager 系統架構與設計說明書 (docs/02_architecture.md)

## 1. 架構總覽與分層設計

本系統遵循高內聚、低耦合原則，採用四層模組架構（CLI 介面層、設定與路徑解析層、核心領域模組層、資料模型層），完全相容於 Python 3.15+ 環境與跨平台作業系統（Windows / macOS / Linux）。

```text
+-------------------------------------------------------------------------------+
|                       SkillManager 模組分層架構圖                             |
+-------------------------------------------------------------------------------+

  [ 介面層 (Presentation Layer) ]
   └── skill_manager.cli: Typer CLI 入口 (scan, search, audit, complete, track)
        ├── Table 格式化輸出 (Rich Console)
        └── 結構化 JSON 輸出 (乾淨無 ANSI 色碼，供 AI Agent 直接調用)
              |
              v
  [ 配置與解析層 (Configuration & Path Layer) ]
   └── skill_manager.config:
        ├── 跨平台路徑解析器 (自動展開 %USERPROFILE% 與 $HOME)
        ├── 平台映射預設值 (Claude, Antigravity, Codex, Cursor, Universal)
        └── TOML 設定檔載入器與環境變數 (GITHUB_TOKEN, HF_TOKEN)
              |
              v
  [ 核心領域層 (Core Domain Layer) ]
   ├── core.scanner:      os.scandir 串流遍歷、YAML Frontmatter 解析、循環連結防護
   ├── core.remote_search: GitHub REST API 與 HuggingFace Hub 檢索 (指數退避重試)
   ├── core.indexer:      index.md 規範審計器、Unified Diff 生成器、原子寫入引擎
   └── core.versioning:   GitPython 封裝、SHA 狀態比對、快照標籤備份、一鍵回滾
              |
              v
  [ 實體與模型層 (Data & Entity Layer) ]
   └── skill_manager.models:
        ├── SkillEntity, ScanResult, ScanSummary
        ├── SearchItem, SearchResult
        ├── AuditResult, TrackResult
        └── PlatformType, VersionStatus (嚴格 Enum 列舉)
```

---

## 2. 元件交互與資料流 (Component Interactions)

### 2.1 本機技能掃描資料流 (Scan Flow)
```text
User / Agent CLI
     │
     ▼
[cli.scan] ────────► [config.resolve_platform_paths]
                            │ (展開平台目錄，例如 ~/.claude/skills)
                            ▼
                     [scanner.scan_directory_tree]
                            │ (os.scandir 串流走訪)
                            ├─► [scanner.parse_yaml_frontmatter] (解析 SKILL.md)
                            ├─► [git.Repo] (探測本機 commit 與 remote)
                            ▼
                     [SkillEntity] ──► [ScanResult] ──► JSON / Table Output
```

### 2.2 審計與原子補全資料流 (Audit & Complete Flow)
```text
Target Skill Dir
     │
     ▼
[indexer.audit_skill] ◄─── [indexer.parse_index_schema] (讀取 index.md 規範)
     │
     ├─► 比對 YAML Frontmatter (name, description)
     ├─► 比對必要章節 (When to Use, Instructions, Examples)
     ├─► 檢查子目錄 (scripts/, references/)
     ▼
[AuditResult] (含 Unified Diff)
     │
     ▼ (若指定 complete --no-dry-run)
[indexer.complete_skill]
     ├─► 建立缺失目錄與 .gitkeep
     ├─► 寫入暫存檔 SKILL.md.tmp.<pid>
     └─► 原子替換 (Atomic Replace) SKILL.md (0 資料遺失)
```

### 2.3 版本追蹤與安全更新資料流 (Version & Rollback Flow)
```text
Skill Git Repo
     │
     ▼
[versioning.check_version_status]
     ├─► git.fetch (逾時 15 秒保護)
     ├─► 比對 HEAD SHA 與 remote tracking branch SHA
     └─► 計算 behind / ahead commits 差額 (UP_TO_DATE / BEHIND / DIVERGED)
     │
     ▼ (若執行 track upgrade)
[versioning.upgrade_skill]
     ├─► 檢查 repo.is_dirty() (Dirty Worktree 拒絕保護)
     ├─► 建立快照標籤 backup-pre-upgrade-<timestamp>
     ├─► git.reset --hard origin/main
     └─► 回傳更新後狀態
     │
     ▼ (若需還原)
[versioning.rollback_skill] ──► 一鍵還原至前次快照標籤
```

---

## 3. 模組隔離與介面定義

1. **零平台相依**：所有磁碟操作均透過 `pathlib.Path` 與 Python 標準庫，禁止寫死 Windows `\` 或 Linux `/`。
2. **高容錯性**：遇到損毀的 YAML、循環符號連結或無權限目錄時，模組自動記錄警告至 stderr，主程序維持 0 崩潰並正常輸出已解析成功項目。
3. **擴充至 MCP (Model Context Protocol)**：核心模組全部採用標準型別標註（Type Hints）與 Pydantic 資料模型，未來可直接以 1 行程式碼包裝為 FastMCP Server 工具供 Claude / Antigravity / Cursor 在對話中呼叫。

