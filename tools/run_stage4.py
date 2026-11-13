#!/usr/bin/env python3
"""
階段 4：資訊安全阻擋性檢查確定性閘門腳本 (tools/run_stage4.py)

執行角色：非模型確定性腳本（由 W2_ARCHITECT 於階段 3A 維護，由 L2 Router 於階段 3B Exit 0 後觸發）
核心流程：
1. 讀取 `gates.yml` (`stage4.block_severity`) 與 `.security-allowlist.yml`（強制檢核 `id`, `file`, `reason`, `approved_by`, `expires_at`；過期或缺欄位視為無效並重新阻擋）。
2. 執行四類確定性掃描並正規化嚴重度 (`Critical / High / Medium / Low`)：
   - Secrets 掃描：解析 Gitleaks JSON 報告 + 內建硬編碼憑證正則掃描（一律視為 `Critical`）。
   - SAST 靜態原始碼掃描：解析 Bandit / Semgrep JSON 報告 + 內建危險語法 AST 掃描（`shell=True`、`pickle.loads`、`eval/exec`）。
   - SCA 相依套件掃描：解析 `pip-audit` / `trivy` JSON 報告之 CVE 漏洞。
   - 最小權限設定檢查：檢查 `Dockerfile` 是否含非 root `USER`、`.env` 是否被追蹤入 Git 版控。
3. 阻擋項透過 `tools/defect_logger.py` 轉為 `DEF-4-YYYYMMDD-XXX` (`VULN`) 工單，寫入 `docs/05_security_audit.md`。
4. 依據結果回傳標準 Exit Code (`0, 1, 5, 6`)：
   - Exit 0: 0 阻擋項且無過期豁免 ➔ 進入階段 5
   - Exit 1: 發現阻擋弱點 (CWE / Secrets / CVE) ➔ 路由至 W3_CODER 修補 (修補後須先過 3B 再重跑 4)
   - Exit 5: 同一弱點累計 3 次修補未過 ➔ 提請人類使用者裁決
   - Exit 6: 掃描工具或報告格式錯誤
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import re
import subprocess
import sys
from enum import IntEnum
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.defect_logger import DefectLogger, DefectRecord, utc_now_iso  # noqa: E402
from tools.router import read_json, write_json  # noqa: E402
from tools.run_stage3b import load_yaml_or_json  # noqa: E402


class Stage4ExitCode(IntEnum):
    """階段 4 標準 Exit Code。"""
    PASS = 0
    VULN_BLOCKED = 1
    STOP_FOR_HUMAN = 5
    TOOL_OR_ENV_ERROR = 6


DEFAULT_STAGE4_GATES: dict[str, Any] = {
    "stage4": {
        "block_severity": ["Critical", "High", "Medium"],
        "allowlist": ".security-allowlist.yml",
        "stop_same_vuln": 3,
    }
}

SECRET_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    ("SECRET-PRIVATE-KEY", "偵測到硬編碼私鑰標頭 (Private Key)", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("SECRET-AWS-AKIA", "偵測到硬編碼 AWS Access Key ID", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "SECRET-GENERIC-TOKEN",
        "偵測到疑似硬編碼機敏金鑰或 API Token",
        re.compile(r"""(?i)\b(?:api_key|secret_key|access_token|private_token)\s*=\s*['"][A-Za-z0-9_\-]{16,}['"]"""),
    ),
]


class Stage4SecurityScanner:
    """階段 4 確定性資安掃描與豁免檢核器。"""

    def __init__(self, root: Path, ci_mode: bool = False) -> None:
        self.root = root.resolve()
        self.ci_mode = ci_mode
        self.docs_dir = self.root / "docs"
        self.logs_dir = self.root / ".scratch" / "logs"
        self.state_file = self.docs_dir / "stage_state.json"
        self.audit_report_file = self.docs_dir / "05_security_audit.md"
        self.gates_file = self.root / "gates.yml"
        self.defect_logger = DefectLogger(self.root)

        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.docs_dir.mkdir(parents=True, exist_ok=True)

    def load_stage4_gates(self) -> dict[str, Any]:
        cfg = load_yaml_or_json(self.gates_file, DEFAULT_STAGE4_GATES)
        return cfg.get("stage4", DEFAULT_STAGE4_GATES["stage4"])

    def load_and_validate_allowlist(
        self,
        allowlist_rel_path: str,
    ) -> tuple[dict[tuple[str, str], dict[str, Any]], list[dict[str, Any]]]:
        """
        載入並驗證 `.security-allowlist.yml`：
        每筆豁免必須具備 `id`, `file`, `reason`, `approved_by`, `expires_at` (YYYY-MM-DD)。
        若欄位缺失或 `expires_at < 今日`，視為無效豁免並加入 `invalid_entries`。
        """
        path = self.root / allowlist_rel_path
        if not path.is_file():
            return {}, []

        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}, []

        entries: list[dict[str, Any]] = []
        if raw.startswith("{") or raw.startswith("["):
            parsed = json.loads(raw)
            entries = parsed if isinstance(parsed, list) else parsed.get("allowlist", [])
        else:
            try:
                import yaml  # type: ignore
                parsed = yaml.safe_load(raw)
                if isinstance(parsed, dict):
                    entries = parsed.get("allowlist", []) or []
                elif isinstance(parsed, list):
                    entries = parsed
            except Exception:
                entries = self._parse_simple_allowlist_yaml(raw)

        today_str = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        valid_map: dict[tuple[str, str], dict[str, Any]] = {}
        invalid_entries: list[dict[str, Any]] = []
        required_fields = ("id", "file", "reason", "approved_by", "expires_at")

        for item in entries:
            if not isinstance(item, dict):
                continue
            missing = [f for f in required_fields if not str(item.get(f, "")).strip()]
            expires = str(item.get("expires_at", "")).strip()
            is_expired = bool(expires and expires < today_str)

            if missing or is_expired:
                invalid_entries.append({
                    **item,
                    "invalid_reason": f"缺少欄位 {missing}" if missing else f"豁免已於 {expires} 到期",
                })
            else:
                key = (str(item["id"]).strip(), str(item["file"]).strip())
                valid_map[key] = item

        return valid_map, invalid_entries

    @staticmethod
    def _parse_simple_allowlist_yaml(raw: str) -> list[dict[str, Any]]:
        """無外部 PyYAML 時，解析 `- id: ...` 列表形式之 `.security-allowlist.yml`。"""
        items: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for line in raw.splitlines():
            clean = line.split("#", 1)[0].strip()
            if not clean or clean == "allowlist:" or clean == "allowlist: []":
                continue
            if clean.startswith("- "):
                if current:
                    items.append(current)
                current = {}
                clean = clean[2:].strip()
            if ":" in clean and current is not None:
                k, v = [p.strip().strip("\"'") for p in clean.split(":", 1)]
                current[k] = v
        if current:
            items.append(current)
        return items

    # ------------------------------------------------------------------------
    # 四大類確定性掃描 (Secrets / SAST / SCA / Config)
    # ------------------------------------------------------------------------

    def scan_secrets(self) -> list[dict[str, Any]]:
        """1. Secrets 掃描：檢查 `src/` 是否含硬編碼金鑰，並讀取外部 `gitleaks_report.json`（若存在）。"""
        findings: list[dict[str, Any]] = []
        src_dir = self.root / "src"
        if src_dir.is_dir():
            for fpath in sorted(src_dir.rglob("*")):
                if not fpath.is_file() or fpath.suffix in (".pyc", ".png", ".jpg"):
                    continue
                rel = fpath.relative_to(self.root).as_posix()
                text = fpath.read_text(encoding="utf-8", errors="ignore")
                for lineno, line in enumerate(text.splitlines(), start=1):
                    for rule_id, desc, regex in SECRET_PATTERNS:
                        if regex.search(line):
                            findings.append({
                                "kind": "VULN",
                                "round": "SECRETS",
                                "test_id": rule_id,
                                "file": rel,
                                "location": f"{rel}:{lineno}",
                                "error_msg": f"{desc}（修復時須同時撤銷/輪替憑證）",
                                "severity": "Critical",
                                "snippet": f"{rel}:{lineno}: {line.strip()[:80]}...",
                            })

        ext_gitleaks = self.logs_dir / "stage4_gitleaks.json"
        if ext_gitleaks.is_file():
            data = read_json(ext_gitleaks, default=[])
            for item in (data if isinstance(data, list) else []):
                rel = item.get("File", "unknown")
                lineno = item.get("StartLine", 1)
                rule_id = item.get("RuleID", "GITLEAKS-SECRET")
                findings.append({
                    "kind": "VULN",
                    "round": "SECRETS",
                    "test_id": rule_id,
                    "file": rel,
                    "location": f"{rel}:{lineno}",
                    "error_msg": f"Gitleaks 偵測到機敏憑證洩漏 ({rule_id})",
                    "severity": "Critical",
                    "snippet": item.get("Description", ""),
                })
        return findings

    def scan_sast(self) -> list[dict[str, Any]]:
        """2. SAST 靜態掃描：透過 Python AST 檢查 `src/` 內危險呼叫（`shell=True`、`pickle.loads`、`eval/exec`）。"""
        findings: list[dict[str, Any]] = []
        src_dir = self.root / "src"
        if src_dir.is_dir():
            for py_file in sorted(src_dir.rglob("*.py")):
                rel = py_file.relative_to(self.root).as_posix()
                source = py_file.read_text(encoding="utf-8", errors="ignore")
                try:
                    tree = ast.parse(source, filename=rel)
                except SyntaxError:
                    continue

                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        func_name = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
                        lineno = getattr(node, "lineno", 1)

                        # CWE-78: subprocess shell=True
                        if any(kw.arg == "shell" and getattr(kw.value, "value", False) is True for kw in node.keywords):
                            findings.append({
                                "kind": "VULN",
                                "round": "SAST",
                                "test_id": "CWE-78-SHELL-TRUE",
                                "file": rel,
                                "location": f"{rel}:{lineno}",
                                "error_msg": f"禁止使用 shell=True 執行子程序 ({func_name})，存在指令注入風險 (CWE-78)",
                                "severity": "High",
                                "snippet": f"{rel}:{lineno} -> {func_name}(..., shell=True)",
                            })

                        # CWE-502: pickle.loads / pickle.load
                        if func_name in ("pickle.loads", "pickle.load"):
                            findings.append({
                                "kind": "VULN",
                                "round": "SAST",
                                "test_id": "CWE-502-PICKLE",
                                "file": rel,
                                "location": f"{rel}:{lineno}",
                                "error_msg": "禁止反序列化不受信任之 pickle 資料 (CWE-502)",
                                "severity": "High",
                                "snippet": f"{rel}:{lineno} -> {func_name}(...)",
                            })

                        # CWE-95: eval / exec
                        if func_name in ("eval", "exec"):
                            findings.append({
                                "kind": "VULN",
                                "round": "SAST",
                                "test_id": "CWE-95-EVAL-EXEC",
                                "file": rel,
                                "location": f"{rel}:{lineno}",
                                "error_msg": f"禁止動態執行 {func_name}() (CWE-95)",
                                "severity": "High",
                                "snippet": f"{rel}:{lineno} -> {func_name}(...)",
                            })
        return findings

    def scan_sca(self) -> tuple[bool, list[dict[str, Any]], str]:
        """3. SCA 相依套件掃描：解析 `.scratch/logs/stage4_sca.json`（若存在）。"""
        sca_file = self.logs_dir / "stage4_sca.json"
        if not sca_file.is_file():
            return True, [], ""

        try:
            data = json.loads(sca_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "vulnerabilities" not in data:
                return False, [], "stage4_sca.json 格式錯誤：缺少 vulnerabilities 陣列"
        except Exception as exc:
            return False, [], f"stage4_sca.json 解析失敗: {exc}"

        findings: list[dict[str, Any]] = []
        for vuln in data.get("vulnerabilities", []):
            cve_id = vuln.get("id", "CVE-UNKNOWN")
            pkg = vuln.get("package", "requirements.txt")
            fix_ver = vuln.get("fix_version", "latest")
            sev = vuln.get("severity", "High")
            findings.append({
                "kind": "VULN",
                "round": "SCA",
                "test_id": cve_id,
                "file": "requirements.txt",
                "location": f"requirements.txt:0 ({pkg})",
                "error_msg": f"套件 {pkg} 存在已知漏洞 {cve_id}，建議升級至 {fix_ver}",
                "severity": sev,
                "snippet": json.dumps(vuln, ensure_ascii=False),
            })
        return True, findings, ""

    def scan_least_privilege_config(self) -> list[dict[str, Any]]:
        """4. 設定最小權限檢查：Dockerfile 非 root USER、`.env` 未入 Git 版控。"""
        findings: list[dict[str, Any]] = []
        dockerfile = self.root / "Dockerfile"
        if dockerfile.is_file():
            content = dockerfile.read_text(encoding="utf-8", errors="ignore")
            user_lines = [
                line.strip()
                for line in content.splitlines()
                if line.strip().upper().startswith("USER ")
            ]
            if not user_lines or user_lines[-1].split(None, 1)[-1].strip() in ("root", "0"):
                findings.append({
                    "kind": "VULN",
                    "round": "CONFIG",
                    "test_id": "CONFIG-DOCKER-NON-ROOT",
                    "file": "Dockerfile",
                    "location": "Dockerfile:1",
                    "error_msg": "Dockerfile 缺少非 root 之 USER 指令，違反容器最小權限原則",
                    "severity": "Medium",
                    "snippet": "Dockerfile must specify a non-root USER before ENTRYPOINT/CMD.",
                })

        # 檢查 .env 是否被追蹤入 Git
        env_check = subprocess.run(
            ["git", "ls-files", "--error-unmatch", ".env"],
            cwd=str(self.root),
            text=True,
            capture_output=True,
        )
        if env_check.returncode == 0:
            findings.append({
                "kind": "VULN",
                "round": "CONFIG",
                "test_id": "CONFIG-DOTENV-TRACKED",
                "file": ".env",
                "location": ".env:1",
                "error_msg": ".env 機敏環境變數檔已被納入 Git 版控，必須立即移除並加入 .gitignore",
                "severity": "Critical",
                "snippet": "git ls-files .env returned tracked status.",
            })

        return findings

    # ------------------------------------------------------------------------
    # 主執行管線與 Exit Code 判定
    # ------------------------------------------------------------------------

    def execute(self) -> tuple[Stage4ExitCode, dict[str, Any]]:
        gates = self.load_stage4_gates()
        block_severities = set(gates.get("block_severity", ["Critical", "High", "Medium"]))
        allowlist_rel = str(gates.get("allowlist", ".security-allowlist.yml"))
        stop_same_vuln = int(gates.get("stop_same_vuln", 3))

        try:
            valid_allowlist, invalid_allowlist = self.load_and_validate_allowlist(allowlist_rel)
        except Exception as exc:
            return Stage4ExitCode.TOOL_OR_ENV_ERROR, {"error": f"豁免清單解析失敗: {exc}"}

        sca_ok, sca_findings, sca_err = self.scan_sca()
        if not sca_ok:
            return Stage4ExitCode.TOOL_OR_ENV_ERROR, {"error": sca_err}

        all_findings = (
            self.scan_secrets()
            + self.scan_sast()
            + sca_findings
            + self.scan_least_privilege_config()
        )

        # 將原始掃描結果存檔至 .scratch/logs/stage4_combined_{ts}.json
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
        raw_log_path = self.logs_dir / f"stage4_scan_{ts}.json"
        write_json(raw_log_path, {"scanned_at": utc_now_iso(), "findings": all_findings})
        rel_log = raw_log_path.relative_to(self.root).as_posix()

        blocking_items: list[dict[str, Any]] = []
        exempted_items: list[dict[str, Any]] = []

        # 過期或缺欄位之豁免項目本身即構成阻擋項
        for inv in invalid_allowlist:
            blocking_items.append({
                "kind": "VULN",
                "round": "CONFIG",
                "test_id": f"ALLOWLIST-INVALID-{inv.get('id', 'UNKNOWN')}",
                "location": f"{allowlist_rel}:1",
                "error_msg": f"資安豁免項目無效或已過期：{inv.get('invalid_reason')}",
                "assigned_role": "W2_ARCHITECT",
                "severity": "High",
                "raw_log_file": rel_log,
            })

        for item in all_findings:
            rule_id = item["test_id"]
            file_path = item.get("file", item["location"].split(":")[0])
            sev = item.get("severity", "Medium")

            # Secrets 一律強制視為 Critical 且不可豁免
            if item["round"] == "SECRETS":
                sev = "Critical"

            if (rule_id, file_path) in valid_allowlist and item["round"] != "SECRETS":
                exempted_items.append({**item, "exemption": valid_allowlist[(rule_id, file_path)]})
                continue

            if sev in block_severities:
                blocking_items.append({
                    **item,
                    "severity": sev,
                    "assigned_role": "W3_CODER",
                    "raw_log_file": rel_log,
                })

        active_records = self.defect_logger.record_defects(
            stage="4",
            new_items=blocking_items,
            resolve_missing_in_stage=(len(blocking_items) == 0),
        )

        state = read_json(self.state_file, default={})
        s4_counters = state.setdefault("stage4_counters", {"vuln_retries": {}})
        retries_map: dict[str, int] = s4_counters.setdefault("vuln_retries", {})

        hit_stop_limit = False
        for rec in active_records:
            retries_map[rec.ticket_id] = rec.retry_count
            if rec.retry_count >= stop_same_vuln:
                hit_stop_limit = True

        state["updated_at"] = utc_now_iso()
        write_json(self.state_file, state)

        if not active_records:
            final_code = Stage4ExitCode.PASS
        elif hit_stop_limit:
            final_code = Stage4ExitCode.STOP_FOR_HUMAN
        else:
            final_code = Stage4ExitCode.VULN_BLOCKED

        self._write_security_report(active_records, exempted_items, invalid_allowlist, final_code)
        return final_code, {
            "stage": "4",
            "exit_code": int(final_code),
            "blocking_vulns_count": len(active_records),
            "exempted_count": len(exempted_items),
            "invalid_allowlist_count": len(invalid_allowlist),
            "report_file": self.audit_report_file.relative_to(self.root).as_posix(),
        }

    def _write_security_report(
        self,
        active_records: list[DefectRecord],
        exempted_items: list[dict[str, Any]],
        invalid_allowlist: list[dict[str, Any]],
        final_code: Stage4ExitCode,
    ) -> None:
        """自動產生 `docs/05_security_audit.md`。"""
        tickets_md = self.defect_logger.render_markdown_tickets(active_records)
        exempt_rows = "\n".join(
            f"| `{e['test_id']}` | `{e.get('file')}` | {e['exemption'].get('reason')} | "
            f"`{e['exemption'].get('approved_by')}` | `{e['exemption'].get('expires_at')}` |"
            for e in exempted_items
        ) or "| _無豁免項目_ | — | — | — | — |"

        content = (
            "# 階段 4 資訊安全合規與弱點掃描報告 (`docs/05_security_audit.md`)\n\n"
            f"- **掃描時間**：`{utc_now_iso()}`\n"
            f"- **最終判定 Exit Code**：`{int(final_code)} ({final_code.name})`\n"
            f"- **阻擋性弱點數量**：`{len(active_records)}`\n"
            f"- **過期或無效豁免數量**：`{len(invalid_allowlist)}`\n\n"
            "## 1. 有效豁免清單狀態 (`.security-allowlist.yml`)\n\n"
            "| 規則 / CVE ID | 檔案路徑 | 豁免理由 | 核可者 | 到期日 |\n"
            "| :--- | :--- | :--- | :--- | :--- |\n"
            f"{exempt_rows}\n\n"
            "## 2. 阻擋性資安弱點工單 (`VULN` Tickets)\n\n"
            f"{tickets_md}"
        )
        self.audit_report_file.write_text(content, encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="階段 4 資訊安全阻擋性掃描閘門腳本")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="專案根目錄")
    parser.add_argument("--ci", action="store_true", help="CI 模式執行")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    scanner = Stage4SecurityScanner(root=args.root, ci_mode=args.ci)
    code, summary = scanner.execute()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return int(code)


if __name__ == "__main__":
    sys.exit(main())
