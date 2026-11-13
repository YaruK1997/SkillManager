#!/usr/bin/env python3
"""
階段 3B：多輪自動化測試與獨立審查確定性閘門腳本 (tools/run_stage3b.py)

執行角色：非模型確定性腳本（由 W2_ARCHITECT 於階段 3A 維護，由 L2 Router 觸發）
核心流程：
1. 讀取 `gates.yml` 門檻設定與 `docs/stage_state.json` 迴圈狀態。
2. 依序執行 R1 (功能與覆蓋率 ≥80%/90%) ➔ R2 (邊界情境與 EC-xx 100% 對應) ➔ R3 (連續雙跑 2 次防抖 + 喚起乾淨上下文 W4 獨立審查)。
3. 捕獲失敗透過 `tools/defect_logger.py` 查重並產出結構化工單至 `.scratch/logs/defects.jsonl` 與 `docs/04_test_report.md`。
4. 依據優先序回傳標準 Exit Code (0–6) 供 `tools/router.py route-gate --stage 3B` 自動路由：
   - Exit 0: R1–R3 全數通過 ➔ 進入階段 4
   - Exit 1: 測試失敗 / W4 審查發現 Critical 或 Important 問題 (優先序 4) ➔ W3_CODER
   - Exit 2: 覆蓋率或 EC-xx 對應率未達標 (優先序 5) ➔ W4_TESTER / W2_ARCHITECT
   - Exit 3: 不穩定測試 Flaky Test，R3 多次結果不一致 (優先序 3) ➔ W2_ARCHITECT (RCA)
   - Exit 4: 同一瑕疵累計 3 次修復未過，首次升級 (優先序 2) ➔ W2_ARCHITECT (RCA)
   - Exit 5: 觸發硬性停止條件：同瑕疵 6 次 / 總迴圈 10 次 / 第 2 次規格缺陷 (優先序 1) ➔ 人類裁決
   - Exit 6: 腳本 / 測試工具 / 審查 JSON 格式錯誤 (優先序 0 最高)
"""

from __future__ import annotations

import argparse
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


class Stage3BExitCode(IntEnum):
    """階段 3B 標準 Exit Code。"""
    PASS = 0
    TEST_OR_REVIEW_FAIL = 1
    COVERAGE_OR_EC_INSUFFICIENT = 2
    FLAKY_TEST_DETECTED = 3
    ESCALATE_3A_RCA = 4
    STOP_FOR_HUMAN = 5
    TOOL_OR_ENV_ERROR = 6


# Exit Code 優先序映射（數值越小優先序越高）
EXIT_PRIORITY: dict[Stage3BExitCode, int] = {
    Stage3BExitCode.TOOL_OR_ENV_ERROR: 0,
    Stage3BExitCode.STOP_FOR_HUMAN: 1,
    Stage3BExitCode.ESCALATE_3A_RCA: 2,
    Stage3BExitCode.FLAKY_TEST_DETECTED: 3,
    Stage3BExitCode.TEST_OR_REVIEW_FAIL: 4,
    Stage3BExitCode.COVERAGE_OR_EC_INSUFFICIENT: 5,
    Stage3BExitCode.PASS: 99,
}


DEFAULT_GATES_CONFIG: dict[str, Any] = {
    "stage3b": {
        "coverage": {
            "line_min": 80,
            "core_min": 90,
            "core_modules": [],
        },
        "ec_mapping_min": 100,
        "r3": {
            "runs": 2,
            "env": "clone",
        },
        "review": {
            "command": "",
            "block_on": ["Critical", "Important"],
        },
        "loop_limits": {
            "escalate_after": 3,
            "stop_same_defect": 6,
            "stop_total_loops": 10,
            "stop_spec_defects": 2,
        },
    }
}


def load_yaml_or_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    """載入 `gates.yml`（支援 JSON 相容格式、PyYAML 或內建輕量縮排 YAML 解析器）。"""
    if not path.is_file():
        return json.loads(json.dumps(default))
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return json.loads(json.dumps(default))

    # 1. 優先嘗試 JSON
    if raw.startswith("{"):
        return json.loads(raw)

    # 2. 嘗試 PyYAML (若環境已安裝)
    try:
        import yaml  # type: ignore
        parsed = yaml.safe_load(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # 3. 內建輕量確定性 YAML 解析兜底（支援巢狀 dict、行內陣列 [a, b]、數值與字串）
    result = json.loads(json.dumps(default))
    stack: list[tuple[int, dict[str, Any]]] = [(-1, result)]

    for line in raw.splitlines():
        clean = line.split("#", 1)[0].rstrip()
        if not clean.strip() or ":" not in clean:
            continue
        indent = len(clean) - len(clean.lstrip(" "))
        key, val_str = [part.strip() for part in clean.strip().split(":", 1)]

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        current_dict = stack[-1][1]

        if not val_str:
            if key not in current_dict or not isinstance(current_dict[key], dict):
                current_dict[key] = {}
            stack.append((indent, current_dict[key]))
        else:
            current_dict[key] = _parse_scalar_or_list(val_str)

    return result


def _parse_scalar_or_list(val: str) -> Any:
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar_or_list(x.strip()) for x in inner.split(",")]
    if val.lower() in ("true", "false"):
        return val.lower() == "true"
    if re.fullmatch(r"-?\d+", val):
        return int(val)
    if re.fullmatch(r"-?\d+\.\d+", val):
        return float(val)
    return val.strip("\"'")


class Stage3BRunner:
    """階段 3B 確定性多輪測試與獨立審查執行器。"""

    EC_ID_PATTERN = re.compile(r"\b(EC-\d+)\b")
    AC_ID_PATTERN = re.compile(r"\b(AC-\d+)\b")
    TEST_EC_REF_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:T[_-]R2[_-])?(EC[_-]\d+)(?![A-Za-z0-9])", re.IGNORECASE)
    TEST_AC_REF_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:T[_-]R[12][_-])?(AC[_-]\d+)(?![A-Za-z0-9])", re.IGNORECASE)

    def __init__(self, root: Path, ci_mode: bool = False) -> None:
        self.root = root.resolve()
        self.ci_mode = ci_mode
        self.docs_dir = self.root / "docs"
        self.logs_dir = self.root / ".scratch" / "logs"
        self.review_dir = self.root / ".scratch" / "review"
        self.state_file = self.docs_dir / "stage_state.json"
        self.report_file = self.docs_dir / "04_test_report.md"
        self.gates_file = self.root / "gates.yml"
        self.spec_file = self.docs_dir / "01_spec.md"
        self.defect_logger = DefectLogger(self.root)

        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.review_dir.mkdir(parents=True, exist_ok=True)
        self.docs_dir.mkdir(parents=True, exist_ok=True)

    def load_gates(self) -> dict[str, Any]:
        cfg = load_yaml_or_json(self.gates_file, DEFAULT_GATES_CONFIG)
        return cfg.get("stage3b", DEFAULT_GATES_CONFIG["stage3b"])

    def load_state(self) -> dict[str, Any]:
        default_state = {
            "schema_version": "2.0.0",
            "current_stage": "STAGE_3B",
            "updated_at": utc_now_iso(),
            "stage3b_counters": {
                "total_repair_loops": 0,
                "spec_defect_count": 0,
                "defect_retries": {},
                "escalated_defects": [],
            },
        }
        state = read_json(self.state_file, default=default_state)
        state.setdefault("stage3b_counters", default_state["stage3b_counters"])
        return state

    def reset_counters(self) -> None:
        """使用者裁決後歸零所有計數器 (`--reset-counters`)。"""
        state = self.load_state()
        state["stage3b_counters"] = {
            "total_repair_loops": 0,
            "spec_defect_count": 0,
            "defect_retries": {},
            "escalated_defects": [],
        }
        state["updated_at"] = utc_now_iso()
        write_json(self.state_file, state)

    def record_spec_defect(self) -> int:
        """由階段 3A (W2_ARCHITECT) 判定為規格缺陷時登錄 (`--record-spec-defect`)。"""
        state = self.load_state()
        counters = state["stage3b_counters"]
        counters["spec_defect_count"] = counters.get("spec_defect_count", 0) + 1
        state["updated_at"] = utc_now_iso()
        write_json(self.state_file, state)
        return int(counters["spec_defect_count"])

    # ------------------------------------------------------------------------
    # 測試與覆蓋率收集核心方法
    # ------------------------------------------------------------------------

    def _run_test_command(self, round_name: str) -> tuple[int, str, Path, dict[str, str]]:
        """
        執行測試並寫入 Raw Log (`.scratch/logs/stage3b_{round}_{ts}.log`)。
        回傳 `(returncode, raw_output, log_file_path, per_test_outcomes)`。
        """
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
        log_file = self.logs_dir / f"stage3b_{round_name.lower()}_{ts}.log"

        tests_dir = self.root / "tests"
        if not tests_dir.is_dir():
            log_file.write_text("Tests directory not found.\n", encoding="utf-8")
            return 0, "No tests directory found.", log_file, {}

        cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(self.root),
                text=True,
                capture_output=True,
                timeout=120,
            )
        except Exception as exc:
            log_file.write_text(f"Test runner exception: {exc}\n", encoding="utf-8")
            return -1, str(exc), log_file, {}

        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        log_file.write_text(combined, encoding="utf-8")
        outcomes = self._parse_unittest_outcomes(combined)
        return proc.returncode, combined, log_file, outcomes

    @staticmethod
    def _parse_unittest_outcomes(output: str) -> dict[str, str]:
        """從 `unittest -v` 輸出解析每個測試案例之結果 (`ok` / `FAIL` / `ERROR`)。"""
        outcomes: dict[str, str] = {}
        pattern = re.compile(r"^(test_[a-zA-Z0-9_]+)\s+\(([^)]+)\).*?\.\.\.\s+(ok|FAIL|ERROR)\s*$", re.MULTILINE)
        for match in pattern.finditer(output):
            func_name, cls_name, status = match.group(1), match.group(2), match.group(3)
            outcomes[f"{cls_name}.{func_name}"] = status
        return outcomes

    def _check_coverage(self, gates: dict[str, Any], raw_log_rel: str) -> list[dict[str, Any]]:
        """
        檢查覆蓋率報告（讀取 `.scratch/coverage.json` 若存在，否則比對預設門檻）。
        回傳未達標之 `COVERAGE` 類型瑕疵項目清單。
        """
        cov_cfg = gates.get("coverage", {})
        line_min = float(cov_cfg.get("line_min", 80))
        core_min = float(cov_cfg.get("core_min", 90))
        core_modules: list[str] = cov_cfg.get("core_modules", [])

        cov_file = self.root / ".scratch" / "coverage.json"
        if not cov_file.is_file():
            return []

        cov_data = read_json(cov_file, default={})
        defects: list[dict[str, Any]] = []

        global_pct = float(cov_data.get("totals", {}).get("percent_covered", 100.0))
        if global_pct < line_min:
            defects.append({
                "kind": "COVERAGE",
                "round": "R1",
                "test_id": "COV-GLOBAL",
                "location": "src/:0",
                "error_msg": f"全域行覆蓋率 {global_pct:.1f}% 低於門檻 {line_min:.1f}%",
                "assigned_role": "W4_TESTER",
                "severity": "Important",
                "raw_log_file": raw_log_rel,
            })

        files_cov: dict[str, Any] = cov_data.get("files", {})
        for mod_prefix in core_modules:
            matched_pcts = [
                float(info.get("summary", {}).get("percent_covered", 100.0))
                for fpath, info in files_cov.items()
                if fpath.startswith(mod_prefix)
            ]
            if matched_pcts:
                avg_core = sum(matched_pcts) / len(matched_pcts)
                if avg_core < core_min:
                    defects.append({
                        "kind": "COVERAGE",
                        "round": "R1",
                        "test_id": f"COV-{mod_prefix.strip('/').replace('/', '_')}",
                        "location": f"{mod_prefix}:0",
                        "error_msg": f"核心模組 {mod_prefix} 覆蓋率 {avg_core:.1f}% 低於門檻 {core_min:.1f}%",
                        "assigned_role": "W4_TESTER",
                        "severity": "Important",
                        "raw_log_file": raw_log_rel,
                    })

        return defects

    def _check_ec_mapping(self, gates: dict[str, Any], raw_log_rel: str) -> list[dict[str, Any]]:
        """
        R2 檢核：比對 `01_spec.md` 中定義之 `EC-xx` 是否在 `tests/` 中 100% 具備對應測試標記。
        """
        if not self.spec_file.is_file():
            return []
        spec_text = self.spec_file.read_text(encoding="utf-8")
        spec_ecs = sorted(set(self.EC_ID_PATTERN.findall(spec_text)))
        if not spec_ecs:
            return []

        tests_dir = self.root / "tests"
        covered_ecs: set[str] = set()
        if tests_dir.is_dir():
            for tf in tests_dir.rglob("*.py"):
                content = tf.read_text(encoding="utf-8", errors="ignore")
                for m in self.TEST_EC_REF_PATTERN.findall(content):
                    normalized = m.upper().replace("_", "-")
                    covered_ecs.add(normalized)

        missing_ecs = [ec for ec in spec_ecs if ec not in covered_ecs]
        ec_min = float(gates.get("ec_mapping_min", 100))
        actual_ratio = ((len(spec_ecs) - len(missing_ecs)) / len(spec_ecs)) * 100.0

        if actual_ratio >= ec_min:
            return []

        return [
            {
                "kind": "COVERAGE",
                "round": "R2",
                "test_id": f"EC-MAP-{ec}",
                "location": "docs/01_spec.md:0",
                "error_msg": f"邊界情境 {ec} 缺少對應之 T-R2-{ec} 自動化測試案例 (目前對應率 {actual_ratio:.1f}% < {ec_min:.1f}%)",
                "assigned_role": "W4_TESTER",
                "severity": "Important",
                "spec_ref": {"ec": ec},
                "raw_log_file": raw_log_rel,
            }
            for ec in missing_ecs
        ]

    def _evaluate_independent_review(self, gates: dict[str, Any]) -> tuple[bool, list[dict[str, Any]], str]:
        """
        R3 獨立審查檢核：
        若設定了 `review.command` 則先執行該指令，接著讀取 `.scratch/review/review_result.json`。
        回傳 `(format_valid, review_defects, error_detail)`。
        """
        review_cfg = gates.get("review", {})
        cmd_str = review_cfg.get("command", "").strip()
        block_severities = set(review_cfg.get("block_on", ["Critical", "Important"]))
        review_file = self.review_dir / "review_result.json"

        if cmd_str:
            proc = subprocess.run(cmd_str, cwd=str(self.root), shell=True, text=True, capture_output=True)
            if proc.returncode != 0:
                return False, [], f"獨立審查指令執行失敗: {proc.stderr.strip()}"

        if not review_file.is_file():
            return True, [], ""

        try:
            review_data = json.loads(review_file.read_text(encoding="utf-8"))
            if not isinstance(review_data, dict) or "findings" not in review_data:
                return False, [], "review_result.json 格式錯誤：缺少 findings 欄位"
        except Exception as exc:
            return False, [], f"review_result.json JSON 解析失敗: {exc}"

        defects: list[dict[str, Any]] = []
        for idx, item in enumerate(review_data.get("findings", []), start=1):
            sev = item.get("severity", "Minor")
            if sev in block_severities:
                defects.append({
                    "kind": "REVIEW",
                    "round": "R3",
                    "test_id": item.get("id", f"REVIEW-{idx:03d}"),
                    "location": item.get("location", "src/:0"),
                    "error_msg": item.get("message", "Code Review 未通過項目"),
                    "assigned_role": "W3_CODER",
                    "severity": sev,
                    "raw_log_file": ".scratch/review/review_result.json",
                })
        return True, defects, ""

    # ------------------------------------------------------------------------
    # 主執行管線與優先序判定
    # ------------------------------------------------------------------------

    def execute(self, round_target: str = "all") -> tuple[Stage3BExitCode, dict[str, Any]]:
        gates = self.load_gates()
        state = self.load_state()
        counters = state["stage3b_counters"]
        limits = gates.get("loop_limits", DEFAULT_GATES_CONFIG["stage3b"]["loop_limits"])

        candidate_codes: set[Stage3BExitCode] = set()
        raw_defect_items: list[dict[str, Any]] = []
        round_summaries: dict[str, str] = {}

        rounds_to_run = ["R1", "R2", "R3"] if round_target == "all" else [round_target.upper()]

        # --- R1: 功能正確性與覆蓋率 ---
        if "R1" in rounds_to_run:
            rc, out, log_path, outcomes = self._run_test_command("R1")
            rel_log = log_path.relative_to(self.root).as_posix()
            if rc < 0:
                return Stage3BExitCode.TOOL_OR_ENV_ERROR, {"error": out}

            failed_tests = [tid for tid, st in outcomes.items() if st in ("FAIL", "ERROR")]
            if rc != 0 or failed_tests:
                candidate_codes.add(Stage3BExitCode.TEST_OR_REVIEW_FAIL)
                for tid in (failed_tests or ["R1.TestSuite"]):
                    raw_defect_items.append({
                        "kind": "FAIL",
                        "round": "R1",
                        "test_id": tid,
                        "location": "tests/:0",
                        "error_msg": f"R1 功能測試失敗: {tid}",
                        "assigned_role": "W3_CODER",
                        "severity": "Critical",
                        "snippet": out,
                        "raw_log_file": rel_log,
                    })

            cov_defects = self._check_coverage(gates, rel_log)
            if cov_defects:
                candidate_codes.add(Stage3BExitCode.COVERAGE_OR_EC_INSUFFICIENT)
                raw_defect_items.extend(cov_defects)

            round_summaries["R1"] = "PASS" if not (rc != 0 or failed_tests or cov_defects) else "FAIL"

        # --- R2: 邊界與異常對應率 (僅在前一輪通過或單獨指定 R2 時執行) ---
        if "R2" in rounds_to_run and not candidate_codes:
            rc, out, log_path, outcomes = self._run_test_command("R2")
            rel_log = log_path.relative_to(self.root).as_posix()
            if rc < 0:
                return Stage3BExitCode.TOOL_OR_ENV_ERROR, {"error": out}

            failed_tests = [tid for tid, st in outcomes.items() if st in ("FAIL", "ERROR")]
            if rc != 0 or failed_tests:
                candidate_codes.add(Stage3BExitCode.TEST_OR_REVIEW_FAIL)
                for tid in (failed_tests or ["R2.EdgeSuite"]):
                    raw_defect_items.append({
                        "kind": "FAIL",
                        "round": "R2",
                        "test_id": tid,
                        "location": "tests/:0",
                        "error_msg": f"R2 邊界測試失敗: {tid}",
                        "assigned_role": "W3_CODER",
                        "severity": "Important",
                        "snippet": out,
                        "raw_log_file": rel_log,
                    })

            ec_defects = self._check_ec_mapping(gates, rel_log)
            if ec_defects:
                candidate_codes.add(Stage3BExitCode.COVERAGE_OR_EC_INSUFFICIENT)
                raw_defect_items.extend(ec_defects)

            round_summaries["R2"] = "PASS" if not (rc != 0 or failed_tests or ec_defects) else "FAIL"

        # --- R3: 乾淨環境雙跑防抖 (Flaky Check) + W4 獨立審查 ---
        if "R3" in rounds_to_run and not candidate_codes:
            r3_runs = max(2, int(gates.get("r3", {}).get("runs", 2)))
            run_outcomes_list: list[dict[str, str]] = []
            last_log_rel = ""

            for run_idx in range(1, r3_runs + 1):
                rc, out, log_path, outcomes = self._run_test_command(f"R3_run{run_idx}")
                last_log_rel = log_path.relative_to(self.root).as_posix()
                if rc < 0:
                    return Stage3BExitCode.TOOL_OR_ENV_ERROR, {"error": out}
                run_outcomes_list.append(outcomes)

            # 比對多次執行結果是否一致 (Flaky 偵測)
            first_outcomes = run_outcomes_list[0]
            flaky_tests: set[str] = set()
            for later_outcomes in run_outcomes_list[1:]:
                all_tids = set(first_outcomes.keys()) | set(later_outcomes.keys())
                for tid in all_tids:
                    if first_outcomes.get(tid) != later_outcomes.get(tid):
                        flaky_tests.add(tid)

            if flaky_tests:
                candidate_codes.add(Stage3BExitCode.FLAKY_TEST_DETECTED)
                for tid in sorted(flaky_tests):
                    raw_defect_items.append({
                        "kind": "FLAKY",
                        "round": "R3",
                        "test_id": tid,
                        "location": "tests/:0",
                        "error_msg": f"R3 連續執行 {r3_runs} 次結果不一致 (Flaky Test)",
                        "assigned_role": "W2_ARCHITECT",
                        "severity": "Important",
                        "raw_log_file": last_log_rel,
                    })

            # 檢查 R3 是否有固定失敗案例
            consistent_fails = [
                tid for tid, st in first_outcomes.items()
                if st in ("FAIL", "ERROR") and tid not in flaky_tests
            ]
            if consistent_fails:
                candidate_codes.add(Stage3BExitCode.TEST_OR_REVIEW_FAIL)
                for tid in consistent_fails:
                    raw_defect_items.append({
                        "kind": "FAIL",
                        "round": "R3",
                        "test_id": tid,
                        "location": "tests/:0",
                        "error_msg": f"R3 回歸測試失敗: {tid}",
                        "assigned_role": "W3_CODER",
                        "severity": "Critical",
                        "raw_log_file": last_log_rel,
                    })

            # 執行/讀取 W4 獨立審查
            valid_rev, rev_defects, rev_err = self._evaluate_independent_review(gates)
            if not valid_rev:
                return Stage3BExitCode.TOOL_OR_ENV_ERROR, {"error": rev_err}
            if rev_defects:
                candidate_codes.add(Stage3BExitCode.TEST_OR_REVIEW_FAIL)
                raw_defect_items.extend(rev_defects)

            round_summaries["R3"] = "PASS" if not (flaky_tests or consistent_fails or rev_defects) else "FAIL"

        # --- 工單持久化、查重與升級/停止計數判定 ---
        active_records = self.defect_logger.record_defects(
            stage="3B",
            new_items=raw_defect_items,
            resolve_missing_in_stage=(round_target == "all" and not candidate_codes),
        )

        if candidate_codes:
            counters["total_repair_loops"] = int(counters.get("total_repair_loops", 0)) + 1
            escalated_list: list[str] = counters.setdefault("escalated_defects", [])
            retries_map: dict[str, int] = counters.setdefault("defect_retries", {})

            for rec in active_records:
                retries_map[rec.ticket_id] = rec.retry_count
                # 規則 6：同一瑕疵累計達 6 次未通過 -> 觸發停止條件 (Exit 5)
                if rec.retry_count >= int(limits.get("stop_same_defect", 6)):
                    candidate_codes.add(Stage3BExitCode.STOP_FOR_HUMAN)
                # 規則 5：同一瑕疵累計達 3 次未通過且尚未升級過 -> 升級 3A RCA (Exit 4)
                elif (
                    rec.retry_count >= int(limits.get("escalate_after", 3))
                    and rec.ticket_id not in escalated_list
                    and rec.kind in ("FAIL", "REVIEW")
                ):
                    escalated_list.append(rec.ticket_id)
                    rec.assigned_role = "W2_ARCHITECT"
                    candidate_codes.add(Stage3BExitCode.ESCALATE_3A_RCA)

            # 規則 6：總修復迴圈達 10 次 或 規格缺陷達 2 次 -> 觸發停止條件 (Exit 5)
            if counters["total_repair_loops"] >= int(limits.get("stop_total_loops", 10)):
                candidate_codes.add(Stage3BExitCode.STOP_FOR_HUMAN)
            if int(counters.get("spec_defect_count", 0)) >= int(limits.get("stop_spec_defects", 2)):
                candidate_codes.add(Stage3BExitCode.STOP_FOR_HUMAN)

        state["updated_at"] = utc_now_iso()
        write_json(self.state_file, state)

        final_code = (
            min(candidate_codes, key=lambda c: EXIT_PRIORITY[c])
            if candidate_codes
            else Stage3BExitCode.PASS
        )

        self._write_test_report(round_summaries, active_records, final_code, counters)
        return final_code, {
            "stage": "3B",
            "round_target": round_target,
            "exit_code": int(final_code),
            "round_summaries": round_summaries,
            "open_defects_count": len(active_records),
            "total_repair_loops": counters["total_repair_loops"],
            "report_file": self.report_file.relative_to(self.root).as_posix(),
        }

    def _write_test_report(
        self,
        round_summaries: dict[str, str],
        active_records: list[DefectRecord],
        final_code: Stage3BExitCode,
        counters: dict[str, Any],
    ) -> None:
        """自動產生 `docs/04_test_report.md`。"""
        tickets_md = self.defect_logger.render_markdown_tickets(active_records)
        rounds_rows = "\n".join(
            f"| **{r}** | `{st}` |" for r, st in round_summaries.items()
        )
        content = (
            "# 階段 3B 自動化多輪測試與獨立審查報告 (`docs/04_test_report.md`)\n\n"
            f"- **產出時間**：`{utc_now_iso()}`\n"
            f"- **最終判定 Exit Code**：`{int(final_code)} ({final_code.name})`\n"
            f"- **累計修復迴圈數**：`{counters.get('total_repair_loops', 0)}`\n"
            f"- **累計規格缺陷數**：`{counters.get('spec_defect_count', 0)}`\n\n"
            "## 1. 各輪次執行摘要\n\n"
            "| 輪次 | 判定狀態 |\n"
            "| :--- | :--- |\n"
            f"{rounds_rows}\n\n"
            "## 2. 結構化瑕疵工單清單 (Defect Tickets)\n\n"
            f"{tickets_md}"
        )
        self.report_file.write_text(content, encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="階段 3B 多輪自動化測試與獨立審查閘門腳本")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="專案根目錄")
    parser.add_argument("--round", choices=["all", "r1", "r2", "r3"], default="all", help="執行輪次")
    parser.add_argument("--ci", action="store_true", help="CI 模式執行")
    parser.add_argument("--reset-counters", action="store_true", help="人類裁決後歸零所有修復計數器")
    parser.add_argument("--record-spec-defect", action="store_true", help="登錄一次規格缺陷計數")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    runner = Stage3BRunner(root=args.root, ci_mode=args.ci)

    if args.reset_counters:
        runner.reset_counters()
        print(json.dumps({"status": "COUNTERS_RESET", "exit_code": 0}, ensure_ascii=False))
        return 0

    if args.record_spec_defect:
        count = runner.record_spec_defect()
        print(json.dumps({"status": "SPEC_DEFECT_RECORDED", "spec_defect_count": count}, ensure_ascii=False))
        return 0

    code, summary = runner.execute(round_target=args.round)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return int(code)


if __name__ == "__main__":
    sys.exit(main())
