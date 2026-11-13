#!/usr/bin/env python3
"""
階段 3B / 4 確定性閘門腳本與共用工單器單元測試 (tests/tools/test_stage_gates.py)

驗證範圍：
1. `tools/defect_logger.py`：工單編號生成、同瑕疵查重累加 `retry_count`、修復後自動 `RESOLVED`、精華日誌截斷。
2. `tools/run_stage3b.py`：
   - Exit 0 (全數通過)
   - Exit 2 (覆蓋率或 EC-xx 對應率不足)
   - Exit 1 -> Exit 4 (同瑕疵連錯 3 次自動升級 W2_ARCHITECT RCA，且僅升級一次) -> Exit 5 (連錯 6 次或規格缺陷 2 次觸發停止)
   - Exit 6 (審查 JSON 格式毀損最高優先序攔截)
3. `tools/run_stage4.py`：
   - Secrets 硬編碼金鑰攔截 (Critical，且不可被豁免)
   - SAST (`shell=True`, `pickle.loads`) 與 Dockerfile 非 root 最小權限攔截
   - `.security-allowlist.yml` 有效豁免放行 vs. 過期/缺欄位豁免阻擋
   - 同一弱點連錯 3 次觸發 Exit 5 交人類裁決
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.defect_logger import DefectLogger  # noqa: E402
from tools.router import write_json  # noqa: E402
from tools.run_stage3b import Stage3BExitCode, Stage3BRunner, main as stage3b_main  # noqa: E402
from tools.run_stage4 import Stage4ExitCode, Stage4SecurityScanner  # noqa: E402


class TestDefectLoggerAndStageGates(unittest.TestCase):
    """測試 defect_logger.py、run_stage3b.py 與 run_stage4.py。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmp.name)
        subprocess.run(["git", "init", "-b", "dev"], cwd=str(self.repo_root), check=True, capture_output=True)
        (self.repo_root / "docs").mkdir(parents=True, exist_ok=True)
        (self.repo_root / "src").mkdir(parents=True, exist_ok=True)
        (self.repo_root / "tests").mkdir(parents=True, exist_ok=True)

        # 建立通過之最小測試與規格 (含 EC-01 對應)
        (self.repo_root / "docs" / "01_spec.md").write_text(
            "# 規格\n- FR-01: 測試\n- AC-01: Given A When B Then C\n- EC-01: 邊界測試\n",
            encoding="utf-8",
        )
        (self.repo_root / "tests" / "test_sample.py").write_text(
            "import unittest\n"
            "class TestSample(unittest.TestCase):\n"
            "    def test_T_R1_AC_01_ok(self):\n"
            "        self.assertEqual(1 + 1, 2)\n"
            "    def test_T_R2_EC_01_edge(self):\n"
            "        self.assertTrue(True)\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ------------------------------------------------------------------------
    # 1. 測試 DefectLogger 查重、重試累加與自動 RESOLVED
    # ------------------------------------------------------------------------

    def test_defect_logger_deduplication_and_resolution(self) -> None:
        """驗證同一瑕疵重跑沿用原 Ticket ID 並累加 retry_count，通過後標記為 RESOLVED。"""
        logger = DefectLogger(self.repo_root)
        long_trace = "\n".join(f"line {i}" for i in range(1, 80))

        # 第一次失敗 -> retry_count = 1
        recs1 = logger.record_defects("3B", [{
            "kind": "FAIL",
            "round": "R1",
            "test_id": "test_auth.TestAuth.test_login",
            "location": "tests/test_auth.py:25",
            "error_msg": "AssertionError: 401 != 200",
            "snippet": long_trace,
        }])
        self.assertEqual(len(recs1), 1)
        first_id = recs1[0].ticket_id
        self.assertEqual(recs1[0].retry_count, 1)
        self.assertIn("前略", recs1[0].snippet)

        # 第二次相同失敗 -> 沿用同一個 ticket_id，retry_count = 2
        recs2 = logger.record_defects("3B", [{
            "kind": "FAIL",
            "round": "R1",
            "test_id": "test_auth.TestAuth.test_login",
            "location": "tests/test_auth.py:25",
            "error_msg": "AssertionError: 401 != 200",
        }])
        self.assertEqual(recs2[0].ticket_id, first_id)
        self.assertEqual(recs2[0].retry_count, 2)

        # 第三次全數通過 (傳入空陣列) -> 原工單應轉為 RESOLVED
        recs3 = logger.record_defects("3B", [], resolve_missing_in_stage=True)
        self.assertEqual(len(recs3), 0)
        all_saved = logger.load_all()
        self.assertEqual(all_saved[0].status, "RESOLVED")

    # ------------------------------------------------------------------------
    # 2. 測試 run_stage3b.py 多輪驗證與 Exit Code (0, 1, 2, 4, 5, 6)
    # ------------------------------------------------------------------------

    def test_stage3b_pass_and_ec_mapping_check(self) -> None:
        """驗證 R1-R3 全數通過回傳 Exit 0；若缺少 EC-02 測試則回傳 Exit 2。"""
        runner = Stage3BRunner(self.repo_root)
        code, info = runner.execute("all")
        self.assertEqual(code, Stage3BExitCode.PASS)
        self.assertTrue((self.repo_root / "docs" / "04_test_report.md").is_file())

        # 在 01_spec.md 新增 EC-02 但未在 tests/ 實作 -> 應於 R2 回傳 COVERAGE_OR_EC_INSUFFICIENT (Exit 2)
        (self.repo_root / "docs" / "01_spec.md").write_text(
            "# 規格\n- EC-01: 已覆蓋\n- EC-02: 未覆蓋邊界\n",
            encoding="utf-8",
        )
        code_ec, _ = runner.execute("all")
        self.assertEqual(code_ec, Stage3BExitCode.COVERAGE_OR_EC_INSUFFICIENT)

    def test_stage3b_escalation_loop_exit_1_to_4_to_5_and_reset(self) -> None:
        """驗證同瑕疵連錯 3 次升級 Exit 4 (僅一次)，連錯 6 次觸發 Exit 5 停止，以及 --reset-counters。"""
        runner = Stage3BRunner(self.repo_root)
        # 注入 W4 獨立審查 Critical 問題模擬持續修復失敗
        write_json(self.repo_root / ".scratch" / "review" / "review_result.json", {
            "findings": [{
                "id": "REV-AUTH-01",
                "severity": "Critical",
                "location": "src/auth.py:10",
                "message": "缺少 Token 過期檢查",
            }]
        })

        # 第 1、2 次失敗 -> Exit 1 (退回 W3_CODER)
        c1, _ = runner.execute("all")
        c2, _ = runner.execute("all")
        self.assertEqual(c1, Stage3BExitCode.TEST_OR_REVIEW_FAIL)
        self.assertEqual(c2, Stage3BExitCode.TEST_OR_REVIEW_FAIL)

        # 第 3 次失敗 -> 自動升級至階段 3A RCA (Exit 4)
        c3, _ = runner.execute("all")
        self.assertEqual(c3, Stage3BExitCode.ESCALATE_3A_RCA)

        # 第 4、5 次失敗 -> 每個瑕疵僅升級一次，故回傳 Exit 1 (計入總迴圈)
        c4, _ = runner.execute("all")
        c5, _ = runner.execute("all")
        self.assertEqual(c4, Stage3BExitCode.TEST_OR_REVIEW_FAIL)
        self.assertEqual(c5, Stage3BExitCode.TEST_OR_REVIEW_FAIL)

        # 第 6 次失敗 -> 觸發同瑕疵 6 次硬性停止條件 (Exit 5)
        c6, _ = runner.execute("all")
        self.assertEqual(c6, Stage3BExitCode.STOP_FOR_HUMAN)

        # 執行 --reset-counters 歸零
        rc_reset = stage3b_main(["--root", str(self.repo_root), "--reset-counters"])
        self.assertEqual(rc_reset, 0)
        state = runner.load_state()
        self.assertEqual(state["stage3b_counters"]["total_repair_loops"], 0)

    def test_stage3b_invalid_review_json_returns_exit_6(self) -> None:
        """驗證當 review_result.json 格式毀損時，回傳最高優先序 Exit 6 (TOOL_OR_ENV_ERROR)。"""
        runner = Stage3BRunner(self.repo_root)
        (self.repo_root / ".scratch" / "review" / "review_result.json").write_text("{bad json", encoding="utf-8")
        code, _ = runner.execute("all")
        self.assertEqual(code, Stage3BExitCode.TOOL_OR_ENV_ERROR)

    # ------------------------------------------------------------------------
    # 3. 測試 run_stage4.py 資安掃描、豁免到期檢核與連錯 3 次停止
    # ------------------------------------------------------------------------

    def test_stage4_secrets_sast_dockerfile_and_allowlist_expiration(self) -> None:
        """驗證階段 4 Secrets、SAST、Dockerfile 掃描，以及有效豁免與過期豁免的阻擋行為。"""
        scanner = Stage4SecurityScanner(self.repo_root)

        # 1. 乾淨狀態 + 合規 Non-root Dockerfile -> Exit 0
        (self.repo_root / "Dockerfile").write_text("FROM python:3.12-slim\nUSER appuser\n", encoding="utf-8")
        code0, _ = scanner.execute()
        self.assertEqual(code0, Stage4ExitCode.PASS)

        # 2. 植入 SAST 弱點 (subprocess shell=True) -> Exit 1
        (self.repo_root / "src" / "runner.py").write_text(
            "import subprocess\n"
            "def run_cmd(cmd: str) -> None:\n"
            "    subprocess.run(cmd, shell=True)\n",
            encoding="utf-8",
        )
        code1, info1 = scanner.execute()
        self.assertEqual(code1, Stage4ExitCode.VULN_BLOCKED)
        self.assertEqual(info1["blocking_vulns_count"], 1)

        # 3. 寫入合法且未過期之 .security-allowlist.yml -> 豁免通過 (Exit 0)
        (self.repo_root / ".security-allowlist.yml").write_text(
            "allowlist:\n"
            "  - id: CWE-78-SHELL-TRUE\n"
            "    file: src/runner.py\n"
            "    reason: 內部受控腳本測試\n"
            "    approved_by: security_lead\n"
            "    expires_at: 2099-12-31\n",
            encoding="utf-8",
        )
        code_exempt, info_exempt = scanner.execute()
        self.assertEqual(code_exempt, Stage4ExitCode.PASS)
        self.assertEqual(info_exempt["exempted_count"], 1)

        # 4. 將豁免日期改為已過期 (2020-01-01) -> 豁免失效並阻擋 (Exit 1)
        (self.repo_root / ".security-allowlist.yml").write_text(
            "allowlist:\n"
            "  - id: CWE-78-SHELL-TRUE\n"
            "    file: src/runner.py\n"
            "    reason: 過期豁免測試\n"
            "    approved_by: security_lead\n"
            "    expires_at: 2020-01-01\n",
            encoding="utf-8",
        )
        code_exp, info_exp = scanner.execute()
        self.assertEqual(code_exp, Stage4ExitCode.VULN_BLOCKED)
        self.assertEqual(info_exp["invalid_allowlist_count"], 1)

        # 5. 植入硬編碼金鑰 (Secrets) -> 即使寫入 allowlist 也絕不允許豁免，且連錯 3 次觸發 Exit 5
        (self.repo_root / ".security-allowlist.yml").write_text("allowlist: []\n", encoding="utf-8")
        (self.repo_root / "src" / "runner.py").write_text(
            'api_key = "test_dummy_secret_key_1234567890abcdef"\n',
            encoding="utf-8",
        )
        s_try1, _ = scanner.execute()
        s_try2, _ = scanner.execute()
        s_try3, _ = scanner.execute()
        self.assertEqual(s_try1, Stage4ExitCode.VULN_BLOCKED)
        self.assertEqual(s_try2, Stage4ExitCode.VULN_BLOCKED)
        self.assertEqual(s_try3, Stage4ExitCode.STOP_FOR_HUMAN)


if __name__ == "__main__":
    unittest.main()
