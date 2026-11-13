#!/usr/bin/env python3
"""
共用結構化日誌解析、瑕疵查重與工單生成器 (tools/defect_logger.py)

職責：
1. 接收階段 3B (`run_stage3b.py`) 與階段 4 (`run_stage4.py`) 捕獲之失敗項目與原始日誌路徑。
2. 擷取關鍵錯誤前後 25~50 行精華診斷日誌 (Diagnostic Snippet)，保護 Worker Context Window。
3. 執行瑕疵查重 (Deduplication)：
   - 階段 3B 以 `(test_id, error_signature)` 為唯一鍵
   - 階段 4 以 `(rule_or_cve_id, location)` 為唯一鍵
   - 若既有工單仍為 `OPEN` / `IN_PROGRESS`，沿用原 `ticket_id` 並將 `retry_count + 1`
   - 若為全新瑕疵，核發新工單編號 `DEF-{3B|4}-YYYYMMDD-XXX` (`retry_count = 1`)
4. 寫入 `.scratch/logs/defects.jsonl` 並渲染標準 Markdown 工單區塊供 `04_test_report.md` 與 `05_security_audit.md` 嵌入。
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def today_yyyymmdd() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")


@dataclass
class DefectRecord:
    """結構化瑕疵工單資料模型 (對應規範 7.2 JSONL Schema)。"""
    ticket_id: str
    kind: str                          # FAIL | ERROR | COVERAGE | FLAKY | REVIEW | VULN
    stage: str                         # "3B" | "4"
    round: str                         # "R1" | "R2" | "R3" | "SAST" | "SECRETS" | "SCA" | "CONFIG"
    test_id: str                       # 測試 ID (T-R1-AC-01) 或 資安規則/CVE 編號 (CWE-79 / CVE-2026-XXXX)
    location: str                      # 檔案路徑:行號
    error_msg: str                     # 精簡錯誤訊息或斷言差異
    assigned_role: str                 # W3_CODER | W4_TESTER | W2_ARCHITECT
    severity: str                      # Critical | Important | Medium | Minor
    status: str = "OPEN"               # OPEN | IN_PROGRESS | RESOLVED | CLOSED
    retry_count: int = 1
    spec_ref: dict[str, str] = field(default_factory=dict)
    reproduce_cmd: str = ""
    snippet: str = ""
    raw_log_file: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def dedup_key(self) -> str:
        """
        計算同一瑕疵認定鍵：
        - 階段 3B：以 `stage + test_id + 正規化錯誤首行` 為準
        - 階段 4：以 `stage + test_id (規則/CVE) + location` 為準
        """
        if self.stage == "4":
            return f"4::{self.test_id}::{self.location}"
        err_head = self.error_msg.strip().splitlines()[0] if self.error_msg.strip() else "UNKNOWN"
        return f"3B::{self.test_id}::{err_head}"


class DefectLogger:
    """管理 `.scratch/logs/defects.jsonl` 之讀寫、查重、狀態更新與 Markdown 渲染。"""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.logs_dir = self.root / ".scratch" / "logs"
        self.defects_file = self.logs_dir / "defects.jsonl"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def extract_diagnostic_snippet(raw_text: str, max_lines: int = 40) -> str:
        """
        從原始輸出擷取最後 25~50 行精華診斷日誌 (Diagnostic Snippet)，
        避免將完整終端機輸出塞入 LLM Context。
        """
        if not raw_text:
            return ""
        lines = [line.rstrip() for line in raw_text.strip().splitlines()]
        if len(lines) <= max_lines:
            return "\n".join(lines)
        return "... (前略，完整日誌請見 raw_log_file) ...\n" + "\n".join(lines[-max_lines:])

    def load_all(self) -> list[DefectRecord]:
        """載入 `defects.jsonl` 中所有工單紀錄。"""
        if not self.defects_file.is_file():
            return []
        records: list[DefectRecord] = []
        with self.defects_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                records.append(DefectRecord(**data))
        return records

    def save_all(self, records: list[DefectRecord]) -> None:
        """將工單清單覆寫回 `defects.jsonl`。"""
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        with self.defects_file.open("w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")

    def _next_ticket_id(self, stage: str, existing: list[DefectRecord]) -> str:
        date_str = today_yyyymmdd()
        prefix = f"DEF-{stage}-{date_str}-"
        max_seq = 0
        for rec in existing:
            if rec.ticket_id.startswith(prefix):
                try:
                    seq = int(rec.ticket_id.split("-")[-1])
                    max_seq = max(max_seq, seq)
                except ValueError:
                    pass
        return f"{prefix}{max_seq + 1:03d}"

    def record_defects(
        self,
        stage: str,
        new_items: list[dict[str, Any]],
        resolve_missing_in_stage: bool = True,
    ) -> list[DefectRecord]:
        """
        批次登錄本次執行捕獲之瑕疵項目：
        1. 若與既有 `OPEN`/`IN_PROGRESS` 工單具有相同 `dedup_key`，則沿用原 `ticket_id` 且 `retry_count + 1`。
        2. 若為新瑕疵，分配新 `ticket_id` (`retry_count = 1`)。
        3. 若 `resolve_missing_in_stage=True`，同階段中本次未再出現之既有 OPEN 工單自動標記為 `RESOLVED`。
        """
        existing = self.load_all()
        active_by_key: dict[str, DefectRecord] = {
            r.dedup_key(): r
            for r in existing
            if r.stage == stage and r.status in ("OPEN", "IN_PROGRESS")
        }

        current_active_records: list[DefectRecord] = []
        seen_keys: set[str] = set()

        for item in new_items:
            snippet = self.extract_diagnostic_snippet(item.get("snippet", ""))
            candidate = DefectRecord(
                ticket_id="TEMP",
                kind=item.get("kind", "FAIL"),
                stage=stage,
                round=item.get("round", "R1"),
                test_id=item["test_id"],
                location=item.get("location", "unknown:0"),
                error_msg=item.get("error_msg", ""),
                assigned_role=item.get("assigned_role", "W3_CODER"),
                severity=item.get("severity", "Important"),
                status="OPEN",
                retry_count=1,
                spec_ref=item.get("spec_ref", {}),
                reproduce_cmd=item.get("reproduce_cmd", ""),
                snippet=snippet,
                raw_log_file=item.get("raw_log_file", ""),
            )
            key = candidate.dedup_key()
            seen_keys.add(key)

            if key in active_by_key:
                prev = active_by_key[key]
                prev.retry_count += 1
                prev.updated_at = utc_now_iso()
                prev.error_msg = candidate.error_msg
                prev.location = candidate.location
                prev.snippet = candidate.snippet or prev.snippet
                prev.raw_log_file = candidate.raw_log_file or prev.raw_log_file
                current_active_records.append(prev)
            else:
                candidate.ticket_id = self._next_ticket_id(stage, existing)
                existing.append(candidate)
                active_by_key[key] = candidate
                current_active_records.append(candidate)

        if resolve_missing_in_stage:
            for rec in existing:
                if rec.stage == stage and rec.status in ("OPEN", "IN_PROGRESS"):
                    if rec.dedup_key() not in seen_keys:
                        rec.status = "RESOLVED"
                        rec.updated_at = utc_now_iso()

        self.save_all(existing)
        return current_active_records

    @staticmethod
    def render_markdown_tickets(records: list[DefectRecord]) -> str:
        """將工單清單渲染為規範 7.3 定義之標準 Markdown 格式。"""
        if not records:
            return "_本次執行無未解決之瑕疵工單（0 Open Defects）。_\n"

        blocks: list[str] = []
        for rec in records:
            stage_label = "階段 3B 測試執行" if rec.stage == "3B" else "階段 4 資安審查"
            repro = rec.reproduce_cmd or f"pytest {rec.location.split(':')[0]} -k {rec.test_id}"
            snippet_block = rec.snippet or "(無額外 Traceback 摘要)"
            blocks.append(
                f"### 工單編號：`{rec.ticket_id}` ({rec.kind})\n"
                f"- **所屬階段**：{stage_label} ({rec.round})\n"
                f"- **測試/規則項目**：`{rec.test_id}`\n"
                f"- **失敗位置**：`{rec.location}`\n"
                f"- **失敗原因**：`{rec.error_msg}`\n"
                f"- **指派修復角色**：`{rec.assigned_role}`\n"
                f"- **嚴重度分級**：`{rec.severity}`\n"
                f"- **處理狀態**：`{rec.status}` (累計重試次數：`{rec.retry_count}`)\n"
                f"- **原始日誌路徑**：`{rec.raw_log_file}`\n"
                f"- **重現指令**：\n"
                f"  ```bash\n"
                f"  {repro}\n"
                f"  ```\n"
                f"- **精華診斷日誌 (Snippet)**：\n"
                f"  ```text\n"
                f"  {snippet_block}\n"
                f"  ```\n"
            )
        return "\n".join(blocks)
