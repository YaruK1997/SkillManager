#!/usr/bin/env python3
"""
L2 Hybrid Router 調度與四層級快取引擎骨架 (tools/router.py)

職責：
1. 解析 L1 Brain 產出之 `docs/00_task_dag.json` 並維護 `docs/stage_state.json`。
2. 執行四層級快取機制 (C1 Prompt 前綴對齊、C2 0-Token 規格切片與 AST 符號索引、C3 增量驗證、C4 三溫層記憶壓縮)。
3. 強制管理階段 2/3B `W3_CODER` 獨立 Git Worktree 建立、白名單越界檢查、合併與專屬 `W3_MERGE_FIXER` 衝突消解任務生成。
4. 執行雙階軟性壓縮與熔斷機制（輸入 > 8,000 tokens 或摘要 > 300 tokens 先由輕量 Router Agent 軟壓縮，仍超標則升級回 L1 Brain 拆細任務）。
5. 確定性路由階段 3B (`run_stage3b.py`) 與階段 4 (`run_stage4.py`) 之 Exit Code (0–6)。
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any


# ============================================================================
# 1. 常數、Exit Code 與路徑配置
# ============================================================================

class RouterExitCode(IntEnum):
    """Router 標準 Exit Code 定義（供 CI 或上層 Orchestrator 判讀）。"""
    OK = 0                       # 成功完成當前調度動作或階段推進
    WORKER_DISPATCH_READY = 10   # 已生成任務或修復 Payload，待喚起對應 Sub-Agent Worker
    MERGE_CONFLICT_FIXER = 11    # Worktree 合併衝突，已自動生成 W3_MERGE_FIXER 任務
    SOFT_COMPACTION_NEEDED = 12  # 超過 Token 預算，請輕量 Router Agent 先執行軟性壓縮
    ESCALATE_TO_BRAIN = 20       # 升級至 L1 Brain / W2 Architect (RCA、介面矛盾、軟壓縮後仍超限)
    HUMAN_GATE_BLOCKED = 30      # 等待人類簽核閘門 (Gate 1 / Gate 2) 或觸發硬性停止條件
    BOUNDARY_VIOLATION = 40      # Worker 修改了 forbidden_paths，拒絕合併並退回
    ENV_OR_TOOL_ERROR = 50       # 腳本、Git 或環境執行異常


TOKEN_BUDGET_TASK_INPUT_MAX = 8000
TOKEN_BUDGET_SPEC_SLICE_MAX = 800
TOKEN_BUDGET_REPO_MAP_MAX = 1500
TOKEN_BUDGET_HANDOVER_SUMMARY_MAX = 300
TOKEN_BUDGET_STAGE_DIGEST_MAX = 1000

DEFAULT_FORBIDDEN_FOR_CODER = [
    "gates.yml",
    ".security-allowlist.yml",
    "tools/router.py",
    "tools/run_stage3b.py",
    "tools/run_stage4.py",
    "tools/defect_logger.py",
]

ROLE_STATIC_PROMPTS: dict[str, str] = {
    "L1_BRAIN": (
        "# Role: L1_BRAIN (Central Orchestrator & DAG Planner)\n"
        "Mandate: Align user intent, decompose tasks into docs/00_task_dag.json, preside over Human Gates 1 & 2, "
        "and resolve escalations (RouterExitCode 20). Read only docs/cache/stage*_digest.json; "
        "NEVER modify src/ directly or read raw logs.\n"
    ),
    "L2_ROUTER_AGENT": (
        "# Role: L2_ROUTER_AGENT (Lightweight Context Compactor & Schema Validator)\n"
        "Mandate: Perform soft compaction when RouterExitCode=12 (compress task input to <=8,000 tokens without "
        "altering AC/EC thresholds, rewrite handover_summary to <=300 tokens, or compact stage_digest to <=1,000 tokens). "
        "Escalate to L1_BRAIN if lossy compression would be required.\n"
    ),
    "W1_RESEARCHER": (
        "# Role: W1_RESEARCHER (Read-Only Codebase & Dependency Explorer)\n"
        "Mandate: Strictly read-only exploration. Consult Block 2 repo_symbol_map first and read only targeted line ranges "
        "(forbidden to read whole files >300 lines). Output symbol_refs (file:start-end) and handover_summary <=300 tokens.\n"
    ),
    "W2_ARCHITECT": (
        "# Role: W2_ARCHITECT (Specification, Gate Engineering & RCA Specialist)\n"
        "Mandate: Author docs/01_spec.md & 01_plan.md (R1/R2 self-tests, 7 edge-case categories, traceability matrix), "
        "author docs/03_test_plan.md, gates.yml & stage 3B/4 gate scripts, and perform RCA on Stage 3B Exit 3/4. "
        "Strictly FORBIDDEN from modifying src/ business code.\n"
    ),
    "W3_CODER": (
        "# Role: W3_CODER (Isolated Git Worktree Implementer & Defect Fixer)\n"
        "Mandate: Implement assigned spec_slice in isolated Git Worktree (.worktrees/<task_id>). "
        "Modify ONLY scope_boundary.allowed_paths; NEVER touch forbidden_paths (gates.yml, tools/, .security-allowlist.yml). "
        "Run required_self_check_cmd (Exit 0), prefix commits with [vX.Y.Z], and keep handover_summary <=300 tokens.\n"
    ),
    "W3_MERGE_FIXER": (
        "# Role: W3_MERGE_FIXER (Dedicated Parallel Branch Conflict Resolver)\n"
        "Mandate: Resolve Git merge conflicts between parallel W3_CODER branches while preserving all AC-xx and EC-xx logic "
        "from both sides. Run integration smoke tests for both modules. If conflict stems from incompatible cross-module "
        "interface assumptions, immediately return status=BLOCKED to escalate to L1_BRAIN / W2_ARCHITECT.\n"
    ),
    "W4_REVIEWER_TESTER": (
        "# Role: W4_REVIEWER_TESTER (Clean-Context Adversarial Reviewer & Tester)\n"
        "Mandate: Execute in 100% clean context (zero confirmation bias). Perform Stage 1 R3 cold-read review, "
        "Stage 3A R1/R2 test authoring (tests/), Stage 3B R3 independent code review (.scratch/review/review_result.json), "
        "and Stage 5 healthcheck verification. Strictly FORBIDDEN from modifying src/ or gates.yml.\n"
    ),
}


@dataclass(frozen=True)
class WorkspacePaths:
    """工作區標準目錄與檔案路徑映射。"""
    root: Path
    docs_dir: Path = field(init=False)
    shared_cache_dir: Path = field(init=False)
    scratch_dir: Path = field(init=False)
    local_cache_dir: Path = field(init=False)
    payloads_dir: Path = field(init=False)
    logs_dir: Path = field(init=False)
    review_dir: Path = field(init=False)
    worktrees_dir: Path = field(init=False)

    # 核心文件與快取檔案
    task_dag_file: Path = field(init=False)
    spec_file: Path = field(init=False)
    plan_file: Path = field(init=False)
    human_review_file: Path = field(init=False)
    stage_state_file: Path = field(init=False)
    gates_file: Path = field(init=False)

    repo_symbol_map_file: Path = field(init=False)
    cache_manifest_file: Path = field(init=False)
    spec_slices_file: Path = field(init=False)
    task_memo_file: Path = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "docs_dir", self.root / "docs")
        object.__setattr__(self, "shared_cache_dir", self.root / "docs" / "cache")
        object.__setattr__(self, "scratch_dir", self.root / ".scratch")
        object.__setattr__(self, "local_cache_dir", self.root / ".scratch" / "cache")
        object.__setattr__(self, "payloads_dir", self.root / ".scratch" / "payloads")
        object.__setattr__(self, "logs_dir", self.root / ".scratch" / "logs")
        object.__setattr__(self, "review_dir", self.root / ".scratch" / "review")
        object.__setattr__(self, "worktrees_dir", self.root / ".worktrees")

        object.__setattr__(self, "task_dag_file", self.docs_dir / "00_task_dag.json")
        object.__setattr__(self, "spec_file", self.docs_dir / "01_spec.md")
        object.__setattr__(self, "plan_file", self.docs_dir / "01_plan.md")
        object.__setattr__(self, "human_review_file", self.docs_dir / "02_human_review.md")
        object.__setattr__(self, "stage_state_file", self.docs_dir / "stage_state.json")
        object.__setattr__(self, "gates_file", self.root / "gates.yml")

        object.__setattr__(self, "repo_symbol_map_file", self.shared_cache_dir / "repo_symbol_map.json")
        object.__setattr__(self, "cache_manifest_file", self.local_cache_dir / "cache_manifest.json")
        object.__setattr__(self, "spec_slices_file", self.local_cache_dir / "spec_slices.json")
        object.__setattr__(self, "task_memo_file", self.local_cache_dir / "task_memo.json")

    def ensure_dirs(self) -> None:
        """確保所有必要目錄皆已建立。"""
        for d in (
            self.docs_dir,
            self.shared_cache_dir,
            self.local_cache_dir,
            self.payloads_dir,
            self.logs_dir,
            self.review_dir,
            self.worktrees_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


# ============================================================================
# 2. 共用工具函數 (雜湊、Token 估算、Git 指令封裝)
# ============================================================================

def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def estimate_tokens(text: str) -> int:
    """
    確定性輕量 Token 估算器（無須外部 tokenizer 依賴）：
    - ASCII / 程式碼字元約 4 chars ≈ 1 token
    - CJK 中文字元約 1 char ≈ 1.5 tokens
    """
    if not text:
        return 0
    cjk_count = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    non_cjk_count = len(text) - cjk_count
    return int(cjk_count * 1.5 + (non_cjk_count / 4.0)) + 1


def sha256_file(path: Path) -> str:
    """計算檔案之 SHA-256 雜湊值；若檔案不存在則回傳 'MISSING'。"""
    if not path.is_file():
        return "MISSING"
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def run_git(root: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    """於指定目錄執行 Git 子程序。"""
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        text=True,
        capture_output=True,
        check=check,
    )


def get_git_tree_hash(root: Path, ref: str = "HEAD") -> str:
    """取得指定 Git Ref 之 Tree Hash（用於 C3 增量快取鍵）。"""
    res = run_git(root, ["rev-parse", f"{ref}^{{tree}}"], check=False)
    if res.returncode != 0:
        return "git-tree:UNINITIALIZED"
    return f"git-tree:{res.stdout.strip()}"


def read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ============================================================================
# 3. 四層級快取與 Token 節流引擎 (CacheManager)
# ============================================================================

class CacheManager:
    """
    實作第 5 節「四層級上下文與 Token 快取機制」：
    - C1: LLM Prompt Prefix Cache 對齊組裝器
    - C2-A: 0-Token 規格切片快取 (`.scratch/cache/spec_slices.json`)
    - C2-B: 增量 AST 符號索引快取 (`docs/cache/repo_symbol_map.json`, 入版控)
    - C3: Content-Hash 任務增量快取 (`.scratch/cache/task_memo.json`)
    - C4: 跨階段壓縮摘要 (`docs/cache/stage{N}_digest.json`, 入版控) 與雙階軟壓縮檢查
    """

    ITEM_ID_PATTERN = re.compile(r"\b(FR-\d+|AC-\d+|EC-\d+|NFR-\d+)\b")

    def __init__(self, paths: WorkspacePaths) -> None:
        self.paths = paths

    def compute_current_hashes(self) -> dict[str, str]:
        return {
            "docs/01_spec.md": sha256_file(self.paths.spec_file),
            "docs/01_plan.md": sha256_file(self.paths.plan_file),
            "gates.yml": sha256_file(self.paths.gates_file),
            "dev_head_tree": get_git_tree_hash(self.paths.root, "HEAD"),
        }

    def sync_caches(self, force: bool = False) -> dict[str, Any]:
        """
        鐵律 1 (Hash 驅動即時失效)：
        比對 `cache_manifest.json` 與當前雜湊，自動重建失效之 `spec_slices.json`
        或增量更新 `docs/cache/repo_symbol_map.json`。
        """
        self.paths.ensure_dirs()
        manifest = read_json(self.paths.cache_manifest_file, default={})
        old_hashes = manifest.get("source_hashes", {})
        cur_hashes = self.compute_current_hashes()

        # 1. 檢查規格切片快取 (C2-A)
        spec_changed = (
            force
            or old_hashes.get("docs/01_spec.md") != cur_hashes["docs/01_spec.md"]
            or not self.paths.spec_slices_file.is_file()
        )
        if spec_changed and self.paths.spec_file.is_file():
            slices = self._build_spec_slices(self.paths.spec_file)
            write_json(self.paths.spec_slices_file, slices)
            spec_status = {
                "status": "VALID",
                "file": ".scratch/cache/spec_slices.json",
                "indexed_items": {k: len(v) for k, v in slices.get("items", {}).items()},
            }
        else:
            spec_status = manifest.get("spec_slice_cache", {"status": "MISSING"})

        # 2. 檢查 AST 符號索引快取 (C2-B - 納入 Git 版控)
        tree_changed = (
            force
            or old_hashes.get("dev_head_tree") != cur_hashes["dev_head_tree"]
            or not self.paths.repo_symbol_map_file.is_file()
        )
        if tree_changed:
            repo_map = self._update_repo_symbol_map_incrementally()
            repo_status = {
                "status": "VALID",
                "file": "docs/cache/repo_symbol_map.json",
                "tracked_files": len(repo_map.get("files", {})),
            }
        else:
            repo_status = manifest.get("repo_symbol_cache", {"status": "VALID"})

        new_manifest = {
            "manifest_version": "1.0",
            "updated_at": utc_now_iso(),
            "source_hashes": cur_hashes,
            "spec_slice_cache": spec_status,
            "repo_symbol_cache": repo_status,
            "stage_digests": manifest.get("stage_digests", {}),
            "review_baseline": manifest.get(
                "review_baseline",
                {"last_approved_commit_sha": None, "approved_at_round": None},
            ),
        }
        write_json(self.paths.cache_manifest_file, new_manifest)
        return new_manifest

    def _build_spec_slices(self, spec_path: Path) -> dict[str, Any]:
        """
        0-Token 規格切片解析器：
        依 Markdown 行與標題將 `FR-xx`, `AC-xx`, `EC-xx`, `NFR-xx` 抽取為字典。
        """
        content = spec_path.read_text(encoding="utf-8")
        items: dict[str, dict[str, str]] = {"FR": {}, "AC": {}, "EC": {}, "NFR": {}}

        lines = content.splitlines()
        current_ids: list[tuple[str, str]] = []
        buffer: list[str] = []

        def flush_buffer() -> None:
            if not current_ids or not buffer:
                return
            block_text = "\n".join(buffer).strip()
            for prefix, item_id in current_ids:
                existing = items[prefix].get(item_id, "")
                items[prefix][item_id] = f"{existing}\n{block_text}".strip() if existing else block_text

        for line in lines:
            matches = self.ITEM_ID_PATTERN.findall(line)
            if matches:
                flush_buffer()
                current_ids = [(m.split("-")[0], m) for m in set(matches)]
                buffer = [line]
            elif line.startswith("#") and current_ids:
                flush_buffer()
                current_ids = []
                buffer = []
            elif current_ids:
                buffer.append(line)

        flush_buffer()
        return {
            "spec_sha256": sha256_file(spec_path),
            "generated_at": utc_now_iso(),
            "items": items,
        }

    def get_task_spec_slice(self, spec_refs: dict[str, list[str]]) -> dict[str, Any]:
        """
        由 `.scratch/cache/spec_slices.json` 以 0 LLM Token 查表取出該任務所需之規格切片。
        """
        self.sync_caches(force=False)
        cache = read_json(self.paths.spec_slices_file, default={"items": {}})
        items = cache.get("items", {})

        result = {
            "functional_requirements": {
                fid: items.get("FR", {}).get(fid, f"[未索引 {fid}，請檢查 01_spec.md]")
                for fid in spec_refs.get("fr_ids", [])
            },
            "acceptance_criteria_gwt": {
                aid: items.get("AC", {}).get(aid, f"[未索引 {aid}，請檢查 01_spec.md]")
                for aid in spec_refs.get("ac_ids", [])
            },
            "edge_cases": {
                eid: items.get("EC", {}).get(eid, f"[未索引 {eid}，請檢查 01_spec.md]")
                for eid in spec_refs.get("ec_ids", [])
            },
        }
        return result

    def _update_repo_symbol_map_incrementally(self) -> dict[str, Any]:
        """
        C2-B: 增量掃描 `src/` 與 `tools/` 下之程式碼，透過 AST 提取類別與函數簽章及起訖行號。
        僅重新解析 `sha256` 改變之檔案，並將結果寫入 `docs/cache/repo_symbol_map.json`（入版控）。
        """
        existing_map = read_json(self.paths.repo_symbol_map_file, default={"files": {}})
        old_files: dict[str, Any] = existing_map.get("files", {})
        new_files: dict[str, Any] = {}

        scan_roots = [self.paths.root / "src"]
        for scan_root in scan_roots:
            if not scan_root.is_dir():
                continue
            for py_file in sorted(scan_root.rglob("*.py")):
                rel_path = py_file.relative_to(self.paths.root).as_posix()
                file_hash = sha256_file(py_file)
                if rel_path in old_files and old_files[rel_path].get("sha256") == file_hash:
                    new_files[rel_path] = old_files[rel_path]
                else:
                    new_files[rel_path] = {
                        "sha256": file_hash,
                        "symbols": self._extract_python_ast_symbols(py_file),
                    }

        updated_map = {
            "schema_version": "1.0",
            "updated_at": utc_now_iso(),
            "files": new_files,
        }
        write_json(self.paths.repo_symbol_map_file, updated_map)
        return updated_map

    @staticmethod
    def _extract_python_ast_symbols(py_file: Path) -> list[dict[str, Any]]:
        """解析單一 Python 檔案之 AST，回傳公開類別與函數之簽章與行號區間。"""
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except Exception as exc:
            return [{"kind": "parse_error", "error": str(exc)}]

        symbols: list[dict[str, Any]] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args_str = ast.unparse(node.args) if hasattr(ast, "unparse") else "..."
                ret_str = f" -> {ast.unparse(node.returns)}" if getattr(node, "returns", None) and hasattr(ast, "unparse") else ""
                doc = (ast.get_docstring(node) or "").splitlines()
                symbols.append({
                    "kind": "function",
                    "name": node.name,
                    "signature": f"def {node.name}({args_str}){ret_str}",
                    "lines": [node.lineno, getattr(node, "end_lineno", node.lineno)],
                    "doc_head": doc[0] if doc else "",
                })
            elif isinstance(node, ast.ClassDef):
                doc = (ast.get_docstring(node) or "").splitlines()
                methods = [
                    n.name for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                symbols.append({
                    "kind": "class",
                    "name": node.name,
                    "methods": methods,
                    "lines": [node.lineno, getattr(node, "end_lineno", node.lineno)],
                    "doc_head": doc[0] if doc else "",
                })
        return symbols

    def build_c1_aligned_prompt(
        self,
        worker_role: str,
        task_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        C1 Prompt Prefix Cache 對齊組裝器：
        強制維持 [Block 1: 固定角色與技能規範] -> [Block 2: 階段共享符號索引] -> [Block 3: 單一任務動態切片]
        不在 Block 1 & Block 2 插入任何動態時間戳或 UUID，確保平行 Worker 100% 命中底層 KV Cache。
        """
        repo_map = read_json(self.paths.repo_symbol_map_file, default={"files": {}})
        block1_static = ROLE_STATIC_PROMPTS.get(
            worker_role,
            (
                f"# Role: {worker_role}\n"
                "Constraints: Strictly follow scope_boundary, forbidden_paths, and Task Contract schema. "
                "Do not read entire files > 300 lines; use repo_symbol_map line ranges.\n"
            ),
        )
        compact_map = {
            f: [
                {
                    "name": s.get("name"),
                    "lines": s.get("lines"),
                    "sig": s.get("signature") or s.get("methods"),
                }
                for s in d.get("symbols", [])
            ]
            for f, d in repo_map.get("files", {}).items()
            if d.get("symbols")
        }
        block2_stage_shared = (
            "# Shared Repository Symbol Map (Read-Only Reference)\n"
            + json.dumps(compact_map, ensure_ascii=False, separators=(",", ":"))
        )
        block3_dynamic_task = (
            "# Task Specific Dispatch Payload\n"
            + json.dumps(task_payload, ensure_ascii=False, indent=2)
        )

        prefix_hash = hashlib.sha256(
            (block1_static + block2_stage_shared).encode("utf-8")
        ).hexdigest()[:16]

        total_tokens = estimate_tokens(block1_static + block2_stage_shared + block3_dynamic_task)
        return {
            "c1_prefix_cache_key": f"prefix:{worker_role}:{prefix_hash}",
            "estimated_input_tokens": total_tokens,
            "budget_max": TOKEN_BUDGET_TASK_INPUT_MAX,
            "prompt_blocks": {
                "block1_static_role": block1_static,
                "block2_stage_shared": block2_stage_shared,
                "block3_dynamic_task": block3_dynamic_task,
            },
        }

    def invalidate_on_spec_rollback(self) -> None:
        """鐵律 2 (規格回退連鎖清除)：當退回階段 1 修改規格時，清除切片與任務記憶快取。"""
        manifest = read_json(self.paths.cache_manifest_file, default={})
        if "spec_slice_cache" in manifest:
            manifest["spec_slice_cache"]["status"] = "INVALIDATED"
        write_json(self.paths.cache_manifest_file, manifest)
        if self.paths.task_memo_file.is_file():
            self.paths.task_memo_file.unlink()


# ============================================================================
# 4. 階段 2 平行 Git Worktree 隔離與專屬 Merge Fixer 管理 (WorktreeManager)
# ============================================================================

class WorktreeManager:
    """
    實作第 4 節「平行 Git Worktree 調度與專屬 Merge Fixer 機制」：
    - 建立 `.worktrees/{task_id}` 與分支 `wt/{task_id}`
    - 檢查 `forbidden_paths` 白名單越界
    - 合併分支至整合分支 (`dev`)；若衝突則自動封裝雙方 Diff 生成 `W3_MERGE_FIXER` 任務
    """

    def __init__(self, paths: WorkspacePaths) -> None:
        self.paths = paths

    def create_worktree(self, task_id: str, base_branch: str = "HEAD") -> tuple[Path, str]:
        wt_path = self.paths.worktrees_dir / task_id
        branch_name = f"wt/{task_id}"
        if wt_path.exists():
            return wt_path, branch_name

        res = run_git(
            self.paths.root,
            ["worktree", "add", "-B", branch_name, str(wt_path), base_branch],
            check=False,
        )
        if res.returncode != 0:
            raise RuntimeError(f"建立 Git Worktree 失敗 ({task_id}): {res.stderr.strip()}")
        return wt_path, branch_name

    def verify_scope_boundary(
        self,
        branch_name: str,
        base_branch: str,
        allowed_paths: list[str],
        forbidden_paths: list[str],
    ) -> tuple[bool, list[str]]:
        """
        Worktree 鐵律 2 (白名單越界攔截)：
        檢查 `git diff --name-only base...branch` 是否觸碰 `forbidden_paths` 或超出 `allowed_paths`。
        """
        res = run_git(
            self.paths.root,
            ["diff", "--name-only", f"{base_branch}...{branch_name}"],
            check=False,
        )
        changed_files = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        violations: list[str] = []

        all_forbidden = set(forbidden_paths) | set(DEFAULT_FORBIDDEN_FOR_CODER)
        for chg in changed_files:
            if any(chg == fb or chg.startswith(fb.rstrip("/") + "/") for fb in all_forbidden):
                violations.append(f"FORBIDDEN_TOUCHED:{chg}")
            elif allowed_paths and not any(
                chg == al or chg.startswith(al.rstrip("/") + "/") for al in allowed_paths
            ):
                violations.append(f"OUT_OF_ALLOWED_SCOPE:{chg}")

        return (len(violations) == 0), violations

    def merge_worktree_or_spawn_fixer(
        self,
        task_id: str,
        branch_name: str,
        task_spec_slice: dict[str, Any],
        handover_summary: str,
    ) -> tuple[RouterExitCode, dict[str, Any]]:
        """
        Worktree 鐵律 3 & 5：
        嘗試將 `wt/{task_id}` 合併入當前整合分支。
        - 成功：清理 Worktree 與分支，回傳 `RouterExitCode.OK`
        - 衝突：擷取衝突檔案與雙方 Diff，中止髒合併，生成專屬 `W3_MERGE_FIXER` 派發契約！
        """
        merge_res = run_git(
            self.paths.root,
            ["merge", "--no-ff", "--no-edit", branch_name],
            check=False,
        )
        if merge_res.returncode == 0:
            self.cleanup_worktree(task_id, branch_name)
            return RouterExitCode.OK, {"merged_branch": branch_name, "status": "MERGED"}

        # 發生合併衝突：擷取衝突清單與雙方 Diff，再執行 git merge --abort 保護主工作區乾淨
        conflict_files_res = run_git(
            self.paths.root,
            ["diff", "--name-only", "--diff-filter=U"],
            check=False,
        )
        conflict_files = [f.strip() for f in conflict_files_res.stdout.splitlines() if f.strip()]
        conflict_diff_res = run_git(self.paths.root, ["diff"], check=False)
        run_git(self.paths.root, ["merge", "--abort"], check=False)

        fixer_task_id = f"MERGE-FIX-{task_id}"
        fixer_payload = {
            "task_id": fixer_task_id,
            "worker_role": "W3_MERGE_FIXER",
            "target_branch_to_merge": branch_name,
            "conflicting_files": conflict_files,
            "conflict_diff_snippet": conflict_diff_res.stdout[:6000],
            "task_spec_slice": task_spec_slice,
            "incoming_handover_summary": handover_summary,
            "instructions": (
                "於整合 Worktree 中合併目標分支並消解 Git 衝突，保留雙方 AC/EC 邏輯，"
                "禁止修改 gates.yml，完成後執行整合冒煙測試。若屬跨模組介面定義矛盾，回傳 status=BLOCKED。"
            ),
        }
        fixer_in_file = self.paths.payloads_dir / f"{fixer_task_id}_in.json"
        write_json(fixer_in_file, fixer_payload)
        return RouterExitCode.MERGE_CONFLICT_FIXER, {
            "status": "CONFLICT_DETECTED",
            "fixer_task_id": fixer_task_id,
            "fixer_payload_file": str(fixer_in_file.relative_to(self.paths.root)),
            "conflicting_files": conflict_files,
        }

    def cleanup_worktree(self, task_id: str, branch_name: str) -> None:
        wt_path = self.paths.worktrees_dir / task_id
        if wt_path.exists():
            run_git(self.paths.root, ["worktree", "remove", "--force", str(wt_path)], check=False)
        run_git(self.paths.root, ["branch", "-D", branch_name], check=False)


# ============================================================================
# 5. DAG 狀態機、雙階軟性壓縮與階段 3B/4 Exit Code 路由器 (HybridRouter)
# ============================================================================

class HybridRouter:
    """L2 Hybrid Router 核心狀態機與協調器。"""

    def __init__(self, root: Path) -> None:
        self.paths = WorkspacePaths(root=root.resolve())
        self.cache = CacheManager(self.paths)
        self.worktrees = WorktreeManager(self.paths)

    def init_workspace(self) -> dict[str, Any]:
        """初始化目錄結構与 `docs/stage_state.json`。"""
        self.paths.ensure_dirs()
        if not self.paths.stage_state_file.is_file():
            initial_state = {
                "schema_version": "2.0.0",
                "current_stage": "STAGE_1",
                "updated_at": utc_now_iso(),
                "human_gates": {
                    "stage1_spec_dag_approved": False,
                    "stage2_impl_review_approved": False,
                },
                "task_states": {},
                "stage3b_counters": {
                    "total_repair_loops": 0,
                    "spec_defect_count": 0,
                    "defect_retries": {},
                    "escalated_defects": [],
                },
                "stage4_counters": {
                    "vuln_retries": {},
                },
            }
            write_json(self.paths.stage_state_file, initial_state)
        manifest = self.cache.sync_caches(force=True)
        return {"status": "INITIALIZED", "cache_manifest": manifest}

    def get_next_parallel_batch(self) -> tuple[RouterExitCode, dict[str, Any]]:
        """
        讀取 `docs/00_task_dag.json` 與 `docs/stage_state.json`：
        1. 檢查雙人工審核閘門 (Human Gate 1 & Gate 2)。
        2. 找出所有 `depends_on` 已完成 (`COMPLETED`) 之待執行任務批次。
        """
        dag = read_json(self.paths.task_dag_file)
        if not dag:
            return RouterExitCode.ESCALATE_TO_BRAIN, {
                "reason": "MISSING_TASK_DAG",
                "message": "尚未產生 docs/00_task_dag.json，請由 L1 Brain 先完成任務拆解。",
            }

        state = read_json(self.paths.stage_state_file, default={})
        gates = dag.get("human_gates", state.get("human_gates", {}))
        current_stage = dag.get("current_stage", state.get("current_stage", "STAGE_1"))

        if current_stage == "STAGE_2" and not gates.get("stage1_spec_dag_approved", False):
            return RouterExitCode.HUMAN_GATE_BLOCKED, {
                "gate": "HUMAN_GATE_1",
                "message": "階段 1 規格與 00_task_dag.json 尚未經人類確認，禁止啟動階段 2 平行 Worktree 編碼。",
            }

        if current_stage in ("STAGE_3A", "STAGE_3B") and not gates.get("stage2_impl_review_approved", False):
            return RouterExitCode.HUMAN_GATE_BLOCKED, {
                "gate": "HUMAN_GATE_2",
                "message": "階段 2 docs/02_human_review.md 尚未獲人類簽核 Approved，禁止進入階段 3。",
            }

        task_states: dict[str, str] = state.get("task_states", {})
        ready_tasks: list[dict[str, Any]] = []

        for task in dag.get("tasks", []):
            tid = task["task_id"]
            status = task_states.get(tid, "PENDING")
            if status != "PENDING":
                continue
            deps = task.get("depends_on", [])
            if all(task_states.get(dep) == "COMPLETED" for dep in deps):
                ready_tasks.append(task)

        return RouterExitCode.OK, {
            "current_stage": current_stage,
            "ready_count": len(ready_tasks),
            "ready_tasks": ready_tasks,
        }

    def prepare_task_dispatch(
        self,
        task_id: str,
        soft_compacted_slice: dict[str, Any] | None = None,
    ) -> tuple[RouterExitCode, dict[str, Any]]:
        """
        為單一任務建立 Git Worktree（若為 W3_CODER）、由 0-Token 快取提取 `spec_slice`、
        組裝 C1 對齊提示詞，並執行「雙階軟性壓縮 ➔ 退回 Brain 拆細」預算檢核。
        """
        dag = read_json(self.paths.task_dag_file, default={"tasks": []})
        task = next((t for t in dag.get("tasks", []) if t["task_id"] == task_id), None)
        if not task:
            return RouterExitCode.ENV_OR_TOOL_ERROR, {"error": f"找不到任務 ID: {task_id}"}

        worker_role = task.get("worker_role", "W3_CODER")
        isolation = task.get("isolation", {})
        wt_path_str = "."
        branch_name = "HEAD"

        # 階段 2/3B W3_CODER 強制建立獨立 Git Worktree
        if worker_role == "W3_CODER" or isolation.get("mode") == "GIT_WORKTREE":
            wt_path, branch_name = self.worktrees.create_worktree(task_id)
            wt_path_str = wt_path.relative_to(self.paths.root).as_posix()

        spec_slice = soft_compacted_slice or self.cache.get_task_spec_slice(task.get("spec_refs", {}))
        payload_in = {
            "task_id": task_id,
            "attempt": 1,
            "worker_role": worker_role,
            "worktree_path": wt_path_str,
            "branch_name": branch_name,
            "objective": task.get("title", ""),
            "scope_boundary": {
                "allowed_paths": isolation.get("allowed_paths", []),
                "forbidden_paths": list(
                    set(isolation.get("forbidden_paths", [])) | set(DEFAULT_FORBIDDEN_FOR_CODER)
                ),
            },
            "spec_slice": spec_slice,
            "required_self_check_cmd": task.get("verification_cmd", ""),
        }

        c1_bundle = self.cache.build_c1_aligned_prompt(worker_role, payload_in)
        est_tokens = c1_bundle["estimated_input_tokens"]

        # 鐵律 5：雙階軟性壓縮與熔斷機制 (8,000 tokens 上限)
        if est_tokens > TOKEN_BUDGET_TASK_INPUT_MAX:
            if soft_compacted_slice is None:
                # 第一階：喚起輕量 Router Agent 進行軟性壓縮
                return RouterExitCode.SOFT_COMPACTION_NEEDED, {
                    "task_id": task_id,
                    "reason": "INPUT_TOKEN_BUDGET_EXCEEDED",
                    "estimated_tokens": est_tokens,
                    "budget_max": TOKEN_BUDGET_TASK_INPUT_MAX,
                    "action": "請輕量 Router Agent 壓縮 spec_slice 與上游摘要後重新呼叫 dispatch。",
                }
            # 第二階：軟性壓縮後仍超過 8,000 tokens -> 升級回 L1 Brain 拆細任務顆粒度
            return RouterExitCode.ESCALATE_TO_BRAIN, {
                "task_id": task_id,
                "reason": "INPUT_EXCEEDS_BUDGET_AFTER_SOFT_COMPACTION",
                "estimated_tokens": est_tokens,
                "budget_max": TOKEN_BUDGET_TASK_INPUT_MAX,
                "action": "軟性壓縮後仍超過 8,000 tokens，請 L1 Brain 將該任務拆分為更小的 DAG 子節點。",
            }

        in_file = self.paths.payloads_dir / f"{task_id}_in.json"
        write_json(in_file, {**payload_in, "c1_prompt_metadata": {
            "c1_prefix_cache_key": c1_bundle["c1_prefix_cache_key"],
            "estimated_input_tokens": est_tokens,
        }})
        return RouterExitCode.WORKER_DISPATCH_READY, {
            "task_id": task_id,
            "worker_role": worker_role,
            "worktree_path": wt_path_str,
            "payload_in_file": in_file.relative_to(self.paths.root).as_posix(),
            "c1_prefix_cache_key": c1_bundle["c1_prefix_cache_key"],
            "estimated_input_tokens": est_tokens,
        }

    def collect_task_result(self, task_id: str, base_branch: str = "HEAD") -> tuple[RouterExitCode, dict[str, Any]]:
        """
        驗收 Worker 回傳之 `.scratch/payloads/{task_id}_out.json`：
        1. 檢查 `handover_summary` 是否超過 300 tokens（超標則觸發軟壓縮/重寫要求）。
        2. 檢查 Worktree 檔案變更是否違反 `forbidden_paths`。
        3. 自動合併 Worktree（遇衝突自動派發 `W3_MERGE_FIXER`）。
        4. 合併成功後強制增量刷新 `docs/cache/repo_symbol_map.json`（鐵律 4）。
        """
        out_file = self.paths.payloads_dir / f"{task_id}_out.json"
        in_file = self.paths.payloads_dir / f"{task_id}_in.json"
        result = read_json(out_file)
        dispatch_in = read_json(in_file, default={})

        if not result:
            return RouterExitCode.ENV_OR_TOOL_ERROR, {"error": f"找不到回傳契約: {out_file}"}

        status = result.get("status", "FAILED")
        if status in ("BLOCKED", "FAILED"):
            return RouterExitCode.ESCALATE_TO_BRAIN, {
                "task_id": task_id,
                "worker_status": status,
                "blockers": result.get("blockers_or_questions", []),
            }

        # 檢查 handover_summary 300 tokens 預算 (第一階軟性截斷/要求重寫)
        summary = result.get("handover_summary", "")
        summary_tokens = estimate_tokens(summary)
        if summary_tokens > TOKEN_BUDGET_HANDOVER_SUMMARY_MAX:
            return RouterExitCode.SOFT_COMPACTION_NEEDED, {
                "task_id": task_id,
                "reason": "HANDOVER_SUMMARY_TOO_LONG",
                "summary_tokens": summary_tokens,
                "budget_max": TOKEN_BUDGET_HANDOVER_SUMMARY_MAX,
                "action": "請輕量 Router Agent 將 handover_summary 軟性壓縮至 ≤ 300 tokens 後重新驗收。",
            }

        branch_name = dispatch_in.get("branch_name", f"wt/{task_id}")
        scope = dispatch_in.get("scope_boundary", {})

        if branch_name != "HEAD":
            ok, violations = self.worktrees.verify_scope_boundary(
                branch_name=branch_name,
                base_branch=base_branch,
                allowed_paths=scope.get("allowed_paths", []),
                forbidden_paths=scope.get("forbidden_paths", []),
            )
            if not ok:
                return RouterExitCode.BOUNDARY_VIOLATION, {
                    "task_id": task_id,
                    "violations": violations,
                    "action": "拒絕合併！Worker 觸碰了禁止修改路徑，退回 Worker 還原。",
                }

            merge_code, merge_info = self.worktrees.merge_worktree_or_spawn_fixer(
                task_id=task_id,
                branch_name=branch_name,
                task_spec_slice=dispatch_in.get("spec_slice", {}),
                handover_summary=summary,
            )
            if merge_code != RouterExitCode.OK:
                return merge_code, merge_info

        # 鐵律 4：合併成功後立即增量刷新 AST 符號索引快取並更新任務狀態
        self.cache.sync_caches(force=False)
        state = read_json(self.paths.stage_state_file, default={"task_states": {}})
        state.setdefault("task_states", {})[task_id] = "COMPLETED"
        state["updated_at"] = utc_now_iso()
        write_json(self.paths.stage_state_file, state)

        return RouterExitCode.OK, {
            "task_id": task_id,
            "status": "COMPLETED_AND_MERGED",
            "summary_tokens": summary_tokens,
        }

    def route_gate_exit_code(self, stage: str, exit_code: int) -> tuple[RouterExitCode, dict[str, Any]]:
        """
        階段 3B (`run_stage3b.py`) 與階段 4 (`run_stage4.py`) Exit Code (0–6) 確定性路由器。
        """
        stage_upper = stage.upper()
        if exit_code == 0:
            next_stage = "STAGE_4" if stage_upper == "3B" else "STAGE_5"
            return RouterExitCode.OK, {
                "stage": stage_upper,
                "gate_exit_code": 0,
                "route_to": next_stage,
                "action": f"階段 {stage_upper} 驗證全數通過，推進至 {next_stage}。",
            }

        if exit_code == 1:
            return RouterExitCode.WORKER_DISPATCH_READY, {
                "stage": stage_upper,
                "gate_exit_code": 1,
                "route_to": "W3_CODER",
                "action": "將結構化瑕疵/弱點工單 (25~50行精華日誌) 派發給 W3_CODER 於獨立 Worktree 修復。",
            }

        if stage_upper == "3B" and exit_code == 2:
            return RouterExitCode.WORKER_DISPATCH_READY, {
                "stage": "3B",
                "gate_exit_code": 2,
                "route_to": "W4_TESTER_AND_W2_ARCHITECT",
                "action": "覆蓋率或 EC 對應率不足，派發 W4_TESTER 補齊測試案例（若為死碼則由 W2 轉派 W3 移除）。",
            }

        if stage_upper == "3B" and exit_code in (3, 4):
            reason = "FLAKY_TEST_DETECTED" if exit_code == 3 else "SAME_DEFECT_3_FAILURES_RCA"
            return RouterExitCode.ESCALATE_TO_BRAIN, {
                "stage": "3B",
                "gate_exit_code": exit_code,
                "route_to": "W2_ARCHITECT_RCA",
                "reason": reason,
                "action": "派發 W2_ARCHITECT 執行 systematic-debugging 判定缺陷歸屬 (測試/實作/環境/規格)。",
            }

        if exit_code == 5:
            return RouterExitCode.HUMAN_GATE_BLOCKED, {
                "stage": stage_upper,
                "gate_exit_code": 5,
                "route_to": "HUMAN_USER",
                "action": "觸發硬性停止條件，暫停自動調度並提請人類使用者裁決。",
            }

        return RouterExitCode.ENV_OR_TOOL_ERROR, {
            "stage": stage_upper,
            "gate_exit_code": exit_code,
            "route_to": "RETRY_ONCE_THEN_W2",
            "action": "腳本或測試/掃描工具執行異常 (Exit 6)，請重跑一次；仍失敗則交 W2/人類排查環境。",
        }

    def compile_stage_digest(self, stage_id: str) -> tuple[RouterExitCode, dict[str, Any]]:
        """
        C4 Warm Cache：將該階段所有已完成任務之 `handover_summary` 彙整為
        `docs/cache/stage{N}_digest.json`（納入 Git 版控，嚴格控制在 ≤ 1,000 tokens）。
        """
        summaries: list[dict[str, str]] = []
        for out_file in sorted(self.paths.payloads_dir.glob("*_out.json")):
            data = read_json(out_file, default={})
            if data.get("status") == "SUCCESS":
                summaries.append({
                    "task_id": data.get("task_id", out_file.stem),
                    "summary": data.get("handover_summary", ""),
                    "modified_files": data.get("modified_files", []),
                })

        digest = {
            "stage_id": stage_id,
            "compiled_at": utc_now_iso(),
            "dev_head_tree": get_git_tree_hash(self.paths.root, "HEAD"),
            "completed_tasks": summaries,
        }
        digest_text = json.dumps(digest, ensure_ascii=False)
        digest_tokens = estimate_tokens(digest_text)

        if digest_tokens > TOKEN_BUDGET_STAGE_DIGEST_MAX:
            return RouterExitCode.SOFT_COMPACTION_NEEDED, {
                "stage_id": stage_id,
                "digest_tokens": digest_tokens,
                "budget_max": TOKEN_BUDGET_STAGE_DIGEST_MAX,
                "action": "階段摘要超過 1,000 tokens，請輕量 Router Agent 先合併壓縮各任務摘要。",
            }

        digest_file = self.paths.shared_cache_dir / f"{stage_id.lower()}_digest.json"
        write_json(digest_file, digest)
        return RouterExitCode.OK, {
            "stage_id": stage_id,
            "digest_file": digest_file.relative_to(self.paths.root).as_posix(),
            "digest_tokens": digest_tokens,
        }


# ============================================================================
# 6. CLI 介面定義
# ============================================================================

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="router.py",
        description="L2 Hybrid Router 調度器、Git Worktree 隔離管理與四層級快取引擎",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="專案根目錄路徑 (預設為當前目錄)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="初始化 .scratch/、docs/cache/ 與 docs/stage_state.json")

    p_sync = sub.add_parser("cache-sync", help="驗證檔案雜湊並增量更新 0-Token 規格切片與 AST 符號索引")
    p_sync.add_argument("--force", action="store_true", help="強制重建所有快取")

    sub.add_parser("next-batch", help="檢查人工閘門並計算下一批可平行派發之 DAG 任務節點")

    p_disp = sub.add_parser("dispatch", help="為指定任務建立 Worktree、組裝 C1 對齊提示詞與 _in.json")
    p_disp.add_argument("--task-id", required=True, help="目標任務 ID (例: T-S2-01-AUTH)")

    p_coll = sub.add_parser("collect", help="驗收 Worker _out.json、檢查越界、合併 Worktree 或生成 Merge Fixer")
    p_coll.add_argument("--task-id", required=True, help="目標任務 ID")
    p_coll.add_argument("--base-branch", default="HEAD", help="合併目標基準分支 (預設: HEAD / dev)")

    p_gate = sub.add_parser("route-gate", help="根據階段 3B / 4 閘門腳本之 Exit Code (0-6) 執行確定性路由")
    p_gate.add_argument("--stage", choices=["3B", "4"], required=True, help="階段代號 (3B 或 4)")
    p_gate.add_argument("--exit-code", type=int, required=True, help="閘門腳本回傳之 Exit Code (0-6)")

    p_dig = sub.add_parser("compact-stage", help="產出跨階段壓縮摘要 docs/cache/stage{N}_digest.json (≤1,000 tokens)")
    p_dig.add_argument("--stage", required=True, help="階段名稱 (例: STAGE_2)")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    router = HybridRouter(root=args.root)

    try:
        if args.command == "init":
            payload = router.init_workspace()
            code = RouterExitCode.OK
        elif args.command == "cache-sync":
            payload = router.cache.sync_caches(force=args.force)
            code = RouterExitCode.OK
        elif args.command == "next-batch":
            code, payload = router.get_next_parallel_batch()
        elif args.command == "dispatch":
            code, payload = router.prepare_task_dispatch(task_id=args.task_id)
        elif args.command == "collect":
            code, payload = router.collect_task_result(
                task_id=args.task_id,
                base_branch=args.base_branch,
            )
        elif args.command == "route-gate":
            code, payload = router.route_gate_exit_code(
                stage=args.stage,
                exit_code=args.exit_code,
            )
        elif args.command == "compact-stage":
            code, payload = router.compile_stage_digest(stage_id=args.stage)
        else:
            parser.print_help()
            return int(RouterExitCode.ENV_OR_TOOL_ERROR)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return int(RouterExitCode.ENV_OR_TOOL_ERROR)

    print(json.dumps({"router_exit_code": int(code), **payload}, ensure_ascii=False, indent=2))
    return int(code)


if __name__ == "__main__":
    sys.exit(main())
