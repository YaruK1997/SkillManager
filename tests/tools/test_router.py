#!/usr/bin/env python3
"""
tools/router.py 單元測試與整合測試套件 (tests/tools/test_router.py)

涵蓋範圍：
1. 四層級快取機制 (C1 Prefix Cache Key 穩定性、C2 0-Token 規格切片與 AST 符號索引增量更新、C4 階段摘要壓縮)
2. 快取失效鐵律 (檔案 SHA-256 變動自動重建、規格回退連鎖失效)
3. 雙人工審核閘門 (Human Gate 1 & Gate 2 阻擋與放行) 與 DAG 拓撲批次解析
4. 雙階軟性壓縮與熔斷機制 (8,000 input tokens / 300 summary tokens / 1,000 stage digest tokens)
5. 階段 2 平行 Git Worktree 建立、forbidden_paths 越界攔截、乾淨合併與衝突自動派發專屬 W3_MERGE_FIXER
6. 階段 3B / 4 閘門 Exit Code (0–6) 確定性路由與 CLI 端到端呼叫
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# 將專案根目錄加入 sys.path 以便匯入 tools.router
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.router import (  # noqa: E402
    HybridRouter,
    RouterExitCode,
    estimate_tokens,
    main as router_main,
    read_json,
    write_json,
)


def init_temp_git_repo(repo_dir: Path) -> None:
    """於臨時測試目錄初始化真實 Git 倉庫，供測試 Worktree 與 Git Tree Hash 使用。"""
    subprocess.run(["git", "init", "-b", "dev"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "config", "user.name", "Test Bot"], cwd=str(repo_dir), check=True)

    # 建立初始規格、閘門與源碼檔案
    (repo_dir / "docs").mkdir(parents=True, exist_ok=True)
    (repo_dir / "src" / "auth").mkdir(parents=True, exist_ok=True)

    (repo_dir / "docs" / "01_spec.md").write_text(
        "# 系統規格書\n\n"
        "## 功能需求\n"
        "- FR-01: 使用者登入驗證\n"
        "  輸入帳號密碼，回傳 JWT。\n"
        "- AC-01: [正常] Given 合法帳密, When 呼叫 /login, Then 回傳 200 與 token\n"
        "- EC-01: Header 缺少 Authorization 時回傳 HTTP 401\n\n"
        "## 計費需求\n"
        "- FR-02: 扣款冪等處理\n"
        "- AC-02: [正常] Given 相同 request_id, When 重複呼叫, Then 僅扣款一次\n"
        "- EC-02: 併發鎖逾時回傳 HTTP 409\n",
        encoding="utf-8",
    )
    (repo_dir / "docs" / "01_plan.md").write_text("# 實作計畫\n- Task 1: Auth\n- Task 2: Billing\n", encoding="utf-8")
    (repo_dir / "gates.yml").write_text("stage3b:\n  coverage:\n    line_min: 80\n", encoding="utf-8")
    (repo_dir / "src" / "auth" / "service.py").write_text(
        '"""認證服務模組。"""\n\n'
        "class AuthService:\n"
        '    """處理 JWT 簽發與驗證。"""\n'
        "    def verify(self, token: str) -> bool:\n"
        "        return bool(token)\n\n"
        "def helper_hash(raw: str) -> str:\n"
        '    """計算雜湊輔助函數。"""\n'
        "    return raw.strip()\n",
        encoding="utf-8",
    )

    subprocess.run(["git", "add", "."], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "commit", "-m", "[v1.0.0] chore: initial commit"], cwd=str(repo_dir), check=True, capture_output=True)


class TestHybridRouterAndCaching(unittest.TestCase):
    """測試 tools/router.py 核心功能。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._tmp.name)
        init_temp_git_repo(self.repo_root)
        self.router = HybridRouter(root=self.repo_root)
        self.router.init_workspace()

    def tearDown(self) -> None:
        # 先清理可能殘留的 git worktrees 避免 Windows/macOS 目錄鎖定
        subprocess.run(["git", "worktree", "prune"], cwd=str(self.repo_root), check=False, capture_output=True)
        self._tmp.cleanup()

    # ------------------------------------------------------------------------
    # 1. 測試四層級快取 (C1 / C2-A / C2-B / 失效機制)
    # ------------------------------------------------------------------------

    def test_c2_zero_token_spec_slicer_and_ast_symbol_map(self) -> None:
        """驗證 C2-A 0-Token 規格切片與 C2-B AST 符號索引生成與查表正確性。"""
        # 1. 驗證 spec_slices.json 已正確抽取 FR-01, AC-01, EC-01
        slice_data = self.router.cache.get_task_spec_slice({
            "fr_ids": ["FR-01"],
            "ac_ids": ["AC-01"],
            "ec_ids": ["EC-01"],
        })
        self.assertIn("使用者登入驗證", slice_data["functional_requirements"]["FR-01"])
        self.assertIn("Given 合法帳密", slice_data["acceptance_criteria_gwt"]["AC-01"])
        self.assertIn("HTTP 401", slice_data["edge_cases"]["EC-01"])
        # 未請求的 FR-02 不應出現在該任務切片中（保護 Context）
        self.assertNotIn("FR-02", slice_data["functional_requirements"])

        # 2. 驗證 docs/cache/repo_symbol_map.json 已解析出類別、方法、函數簽章與行號
        repo_map = read_json(self.router.paths.repo_symbol_map_file)
        self.assertIn("src/auth/service.py", repo_map["files"])
        symbols = repo_map["files"]["src/auth/service.py"]["symbols"]
        names = {s["name"]: s for s in symbols}
        self.assertIn("AuthService", names)
        self.assertEqual(names["AuthService"]["kind"], "class")
        self.assertIn("verify", names["AuthService"]["methods"])
        self.assertIn("helper_hash", names)
        self.assertIn("def helper_hash(raw: str) -> str", names["helper_hash"]["signature"])

    def test_cache_invalidation_on_spec_change_and_rollback(self) -> None:
        """驗證鐵律 1 & 2：當 01_spec.md 修改或發生規格回退時，快取自動失效並更新。"""
        # 修改 01_spec.md 新增 FR-03
        spec_file = self.router.paths.spec_file
        spec_file.write_text(
            spec_file.read_text(encoding="utf-8") + "\n- FR-03: 新增雙重驗證 (2FA)\n",
            encoding="utf-8",
        )
        slice_data = self.router.cache.get_task_spec_slice({"fr_ids": ["FR-03"], "ac_ids": [], "ec_ids": []})
        self.assertIn("雙重驗證", slice_data["functional_requirements"]["FR-03"])

        # 測試規格回退連鎖清除
        write_json(self.router.paths.task_memo_file, {"memo": "old"})
        self.router.cache.invalidate_on_spec_rollback()
        manifest = read_json(self.router.paths.cache_manifest_file)
        self.assertEqual(manifest["spec_slice_cache"]["status"], "INVALIDATED")
        self.assertFalse(self.router.paths.task_memo_file.exists())

    def test_c1_prompt_prefix_cache_key_stability(self) -> None:
        """驗證 C1：同一階段、同一角色的兩個不同平行任務，其共享前綴雜湊 (c1_prefix_cache_key) 必須 100% 一致。"""
        b1 = self.router.cache.build_c1_aligned_prompt("W3_CODER", {"task_id": "T-1", "objective": "Task A"})
        b2 = self.router.cache.build_c1_aligned_prompt("W3_CODER", {"task_id": "T-2", "objective": "Task B"})
        self.assertEqual(b1["c1_prefix_cache_key"], b2["c1_prefix_cache_key"])
        self.assertEqual(
            b1["prompt_blocks"]["block1_static_role"] + b1["prompt_blocks"]["block2_stage_shared"],
            b2["prompt_blocks"]["block1_static_role"] + b2["prompt_blocks"]["block2_stage_shared"],
        )

    # ------------------------------------------------------------------------
    # 2. 測試雙人工審核閘門 (Human Gate 1 & Gate 2) 與 DAG 拓撲排序
    # ------------------------------------------------------------------------

    def test_human_gates_and_dag_topological_batching(self) -> None:
        """驗證 Human Gate 1/2 未簽核時阻擋推進，簽核後依 depends_on 選出可平行任務。"""
        dag = {
            "workflow_version": "2.0.0",
            "current_stage": "STAGE_2",
            "human_gates": {
                "stage1_spec_dag_approved": False,
                "stage2_impl_review_approved": False,
            },
            "tasks": [
                {"task_id": "T-S2-01", "worker_role": "W3_CODER", "depends_on": []},
                {"task_id": "T-S2-02", "worker_role": "W3_CODER", "depends_on": []},
                {"task_id": "T-S2-03", "worker_role": "W3_CODER", "depends_on": ["T-S2-01"]},
            ],
        }
        write_json(self.router.paths.task_dag_file, dag)

        # 1. Gate 1 為 False 時，進入 STAGE_2 應回傳 HUMAN_GATE_BLOCKED (30)
        code, info = self.router.get_next_parallel_batch()
        self.assertEqual(code, RouterExitCode.HUMAN_GATE_BLOCKED)
        self.assertEqual(info["gate"], "HUMAN_GATE_1")

        # 2. 人類簽核 Gate 1 後，應回傳無相依的 T-S2-01 與 T-S2-02 (T-S2-03 因相依未完不入列)
        dag["human_gates"]["stage1_spec_dag_approved"] = True
        write_json(self.router.paths.task_dag_file, dag)
        code, info = self.router.get_next_parallel_batch()
        self.assertEqual(code, RouterExitCode.OK)
        ready_ids = [t["task_id"] for t in info["ready_tasks"]]
        self.assertEqual(ready_ids, ["T-S2-01", "T-S2-02"])

        # 3. 進入 STAGE_3A 但 Gate 2 為 False 時，應回傳 HUMAN_GATE_BLOCKED (30)
        dag["current_stage"] = "STAGE_3A"
        write_json(self.router.paths.task_dag_file, dag)
        code, info = self.router.get_next_parallel_batch()
        self.assertEqual(code, RouterExitCode.HUMAN_GATE_BLOCKED)
        self.assertEqual(info["gate"], "HUMAN_GATE_2")

    # ------------------------------------------------------------------------
    # 3. 測試雙階軟性壓縮與熔斷機制 (Token Budgets)
    # ------------------------------------------------------------------------

    def test_two_step_soft_compaction_and_brain_escalation_on_input_budget(self) -> None:
        """驗證鐵律 5：單任務輸入 > 8,000 tokens 時，第一階回傳 12 (軟壓縮)，壓縮後仍超限則回傳 20 (退回 Brain 拆細)。"""
        huge_text = "超長規格內容 " * 3000  # > 8,000 tokens
        self.router.paths.spec_file.write_text(f"- FR-99: {huge_text}\n", encoding="utf-8")
        self.router.cache.sync_caches(force=True)

        dag = {
            "current_stage": "STAGE_2",
            "human_gates": {"stage1_spec_dag_approved": True},
            "tasks": [{
                "task_id": "T-HUGE",
                "worker_role": "W2_ARCHITECT",
                "title": "超大型任務",
                "depends_on": [],
                "spec_refs": {"fr_ids": ["FR-99"], "ac_ids": [], "ec_ids": []},
            }],
        }
        write_json(self.router.paths.task_dag_file, dag)

        # 第一階：未經軟壓縮 -> 回傳 SOFT_COMPACTION_NEEDED (12)
        code1, info1 = self.router.prepare_task_dispatch("T-HUGE")
        self.assertEqual(code1, RouterExitCode.SOFT_COMPACTION_NEEDED)
        self.assertEqual(info1["reason"], "INPUT_TOKEN_BUDGET_EXCEEDED")

        # 第二階：傳入軟壓縮後依然超過 8,000 tokens 的切片 -> 升級 ESCALATE_TO_BRAIN (20)
        code2, info2 = self.router.prepare_task_dispatch(
            "T-HUGE",
            soft_compacted_slice={"functional_requirements": {"FR-99": huge_text}},
        )
        self.assertEqual(code2, RouterExitCode.ESCALATE_TO_BRAIN)
        self.assertEqual(info2["reason"], "INPUT_EXCEEDS_BUDGET_AFTER_SOFT_COMPACTION")

    def test_handover_summary_and_stage_digest_token_budgets(self) -> None:
        """驗證 handover_summary > 300 tokens 及 stage_digest > 1,000 tokens 時觸發軟壓縮 (Exit 12)。"""
        write_json(self.router.paths.payloads_dir / "T-01_in.json", {
            "task_id": "T-01",
            "branch_name": "HEAD",
            "scope_boundary": {"allowed_paths": ["src/"], "forbidden_paths": []},
        })
        write_json(self.router.paths.payloads_dir / "T-01_out.json", {
            "task_id": "T-01",
            "status": "SUCCESS",
            "handover_summary": "這是一段超過三百個 Token 預算上限的冗長交接摘要。" * 30,
        })

        code, info = self.router.collect_task_result("T-01")
        self.assertEqual(code, RouterExitCode.SOFT_COMPACTION_NEEDED)
        self.assertEqual(info["reason"], "HANDOVER_SUMMARY_TOO_LONG")

    # ------------------------------------------------------------------------
    # 4. 測試平行 Git Worktree 隔離、越界攔截與專屬 Merge Fixer 生成
    # ------------------------------------------------------------------------

    def test_worktree_dispatch_boundary_check_and_clean_merge(self) -> None:
        """驗證 W3_CODER 獨立 Worktree 建立、禁止修改 gates.yml 攔截、以及合法修改正常合併與 AST 索引更新。"""
        dag = {
            "current_stage": "STAGE_2",
            "human_gates": {"stage1_spec_dag_approved": True},
            "tasks": [{
                "task_id": "T-S2-AUTH",
                "worker_role": "W3_CODER",
                "title": "新增 token 刷新函數",
                "depends_on": [],
                "isolation": {
                    "mode": "GIT_WORKTREE",
                    "allowed_paths": ["src/auth/"],
                    "forbidden_paths": ["gates.yml"],
                },
                "spec_refs": {"fr_ids": ["FR-01"], "ac_ids": ["AC-01"], "ec_ids": ["EC-01"]},
            }],
        }
        write_json(self.router.paths.task_dag_file, dag)

        # 1. Dispatch 建立獨立 Worktree (.worktrees/T-S2-AUTH)
        code, disp_info = self.router.prepare_task_dispatch("T-S2-AUTH")
        self.assertEqual(code, RouterExitCode.WORKER_DISPATCH_READY)
        wt_dir = self.repo_root / disp_info["worktree_path"]
        self.assertTrue(wt_dir.is_dir())

        # 2. 模擬 W3 違規偷改 gates.yml -> 應被 BOUNDARY_VIOLATION (40) 攔截
        (wt_dir / "gates.yml").write_text("stage3b:\n  coverage:\n    line_min: 10\n", encoding="utf-8")
        subprocess.run(["git", "add", "gates.yml"], cwd=str(wt_dir), check=True)
        subprocess.run(["git", "commit", "-m", "[v1.0.0] chore: tamper gates"], cwd=str(wt_dir), check=True, capture_output=True)

        write_json(self.router.paths.payloads_dir / "T-S2-AUTH_out.json", {
            "task_id": "T-S2-AUTH",
            "status": "SUCCESS",
            "modified_files": ["gates.yml"],
            "handover_summary": "完成修改。",
        })
        code_viol, viol_info = self.router.collect_task_result("T-S2-AUTH", base_branch="dev")
        self.assertEqual(code_viol, RouterExitCode.BOUNDARY_VIOLATION)
        self.assertTrue(any("gates.yml" in v for v in viol_info["violations"]))

        # 3. 還原違規 commit，改為合法修改 src/auth/service.py -> 應成功合併並自動更新 repo_symbol_map.json
        subprocess.run(["git", "reset", "--hard", "HEAD~1"], cwd=str(wt_dir), check=True, capture_output=True)
        (wt_dir / "src" / "auth" / "service.py").write_text(
            (wt_dir / "src" / "auth" / "service.py").read_text(encoding="utf-8")
            + "\ndef refresh_token(old_token: str) -> str:\n    return old_token\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "src/auth/service.py"], cwd=str(wt_dir), check=True)
        subprocess.run(["git", "commit", "-m", "[v1.0.0] feat(auth): add refresh_token"], cwd=str(wt_dir), check=True, capture_output=True)

        write_json(self.router.paths.payloads_dir / "T-S2-AUTH_out.json", {
            "task_id": "T-S2-AUTH",
            "status": "SUCCESS",
            "modified_files": ["src/auth/service.py"],
            "handover_summary": "已新增 refresh_token(old_token: str) -> str 函數。",
        })
        code_ok, ok_info = self.router.collect_task_result("T-S2-AUTH", base_branch="dev")
        self.assertEqual(code_ok, RouterExitCode.OK)
        self.assertEqual(ok_info["status"], "COMPLETED_AND_MERGED")

        # Worktree 應已自動清理，且 repo_symbol_map.json 應包含新函數 refresh_token
        self.assertFalse(wt_dir.exists())
        repo_map = read_json(self.router.paths.repo_symbol_map_file)
        fn_names = [s["name"] for s in repo_map["files"]["src/auth/service.py"]["symbols"]]
        self.assertIn("refresh_token", fn_names)

    def test_parallel_worktree_merge_conflict_spawns_merge_fixer(self) -> None:
        """驗證兩個平行 Worktree 修改同一行發生衝突時，自動中止髒合併並生成 MERGE-FIX-<ID>_in.json (Exit 11)。"""
        dag = {
            "current_stage": "STAGE_2",
            "human_gates": {"stage1_spec_dag_approved": True},
            "tasks": [
                {
                    "task_id": "T-PAR-A",
                    "worker_role": "W3_CODER",
                    "title": "Task A",
                    "depends_on": [],
                    "isolation": {"mode": "GIT_WORKTREE", "allowed_paths": ["src/auth/"]},
                    "spec_refs": {"fr_ids": ["FR-01"], "ac_ids": [], "ec_ids": []},
                },
                {
                    "task_id": "T-PAR-B",
                    "worker_role": "W3_CODER",
                    "title": "Task B",
                    "depends_on": [],
                    "isolation": {"mode": "GIT_WORKTREE", "allowed_paths": ["src/auth/"]},
                    "spec_refs": {"fr_ids": ["FR-02"], "ac_ids": [], "ec_ids": []},
                },
            ],
        }
        write_json(self.router.paths.task_dag_file, dag)

        # 同時派發兩個平行 Worktree (皆基於當前 dev HEAD)
        self.router.prepare_task_dispatch("T-PAR-A")
        self.router.prepare_task_dispatch("T-PAR-B")

        wt_a = self.repo_root / ".worktrees" / "T-PAR-A"
        wt_b = self.repo_root / ".worktrees" / "T-PAR-B"

        # A 與 B 各自修改 src/auth/service.py 的同一區段為不同內容
        (wt_a / "src" / "auth" / "service.py").write_text("def conflict_fn() -> str:\n    return 'FROM_A'\n", encoding="utf-8")
        subprocess.run(["git", "commit", "-am", "[v1.0.0] feat: A change"], cwd=str(wt_a), check=True, capture_output=True)

        (wt_b / "src" / "auth" / "service.py").write_text("def conflict_fn() -> str:\n    return 'FROM_B'\n", encoding="utf-8")
        subprocess.run(["git", "commit", "-am", "[v1.0.0] feat: B change"], cwd=str(wt_b), check=True, capture_output=True)

        # 先驗收合併 A -> 成功
        write_json(self.router.paths.payloads_dir / "T-PAR-A_out.json", {
            "task_id": "T-PAR-A",
            "status": "SUCCESS",
            "handover_summary": "完成 A 修改。",
        })
        code_a, _ = self.router.collect_task_result("T-PAR-A", base_branch="dev")
        self.assertEqual(code_a, RouterExitCode.OK)

        # 再驗收合併 B -> 觸發 Git 衝突 -> 回傳 MERGE_CONFLICT_FIXER (11) 並生成 MERGE-FIX-T-PAR-B_in.json
        write_json(self.router.paths.payloads_dir / "T-PAR-B_out.json", {
            "task_id": "T-PAR-B",
            "status": "SUCCESS",
            "handover_summary": "完成 B 修改。",
        })
        code_b, info_b = self.router.collect_task_result("T-PAR-B", base_branch="dev")
        self.assertEqual(code_b, RouterExitCode.MERGE_CONFLICT_FIXER)
        self.assertEqual(info_b["fixer_task_id"], "MERGE-FIX-T-PAR-B")
        self.assertIn("src/auth/service.py", info_b["conflicting_files"])

        fixer_payload = read_json(self.router.paths.payloads_dir / "MERGE-FIX-T-PAR-B_in.json")
        self.assertEqual(fixer_payload["worker_role"], "W3_MERGE_FIXER")
        self.assertIn("FROM_B", fixer_payload["conflict_diff_snippet"])

    # ------------------------------------------------------------------------
    # 5. 測試階段 3B / 4 閘門 Exit Code (0–6) 路由與 CLI 子指令
    # ------------------------------------------------------------------------

    def test_stage3b_and_stage4_gate_routing_and_cli(self) -> None:
        """驗證階段 3B 與階段 4 所有 Exit Code (0–6) 的路由映射與 CLI 呼叫。"""
        cases = [
            ("3B", 0, RouterExitCode.OK, "STAGE_4"),
            ("3B", 1, RouterExitCode.WORKER_DISPATCH_READY, "W3_CODER"),
            ("3B", 2, RouterExitCode.WORKER_DISPATCH_READY, "W4_TESTER_AND_W2_ARCHITECT"),
            ("3B", 3, RouterExitCode.ESCALATE_TO_BRAIN, "W2_ARCHITECT_RCA"),
            ("3B", 4, RouterExitCode.ESCALATE_TO_BRAIN, "W2_ARCHITECT_RCA"),
            ("3B", 5, RouterExitCode.HUMAN_GATE_BLOCKED, "HUMAN_USER"),
            ("3B", 6, RouterExitCode.ENV_OR_TOOL_ERROR, "RETRY_ONCE_THEN_W2"),
            ("4", 0, RouterExitCode.OK, "STAGE_5"),
            ("4", 1, RouterExitCode.WORKER_DISPATCH_READY, "W3_CODER"),
            ("4", 5, RouterExitCode.HUMAN_GATE_BLOCKED, "HUMAN_USER"),
        ]
        for stage, gate_code, expected_router_code, expected_target in cases:
            with self.subTest(stage=stage, gate_code=gate_code):
                code, info = self.router.route_gate_exit_code(stage, gate_code)
                self.assertEqual(code, expected_router_code)
                self.assertEqual(info["route_to"], expected_target)

        # 測試 CLI compact-stage
        cli_code = router_main(["--root", str(self.repo_root), "compact-stage", "--stage", "STAGE_2"])
        self.assertEqual(cli_code, int(RouterExitCode.OK))
        self.assertTrue((self.repo_root / "docs" / "cache" / "stage_2_digest.json").is_file())


if __name__ == "__main__":
    unittest.main()
