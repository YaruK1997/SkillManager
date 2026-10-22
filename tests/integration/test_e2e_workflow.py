"""End-to-end integration workflow tests."""

import json
from typer.testing import CliRunner
from skill_manager.cli import app

runner = CliRunner()


def test_e2e_full_lifecycle(sample_incomplete_skill, sample_index_file, temp_dir):
    """E2E lifecycle: Scan -> Audit -> Complete -> Scan (JSON verification)."""
    # 1. Scan before completion
    res_scan1 = runner.invoke(app, ["scan", "--path", str(temp_dir), "--format", "json"])
    assert res_scan1.exit_code == 0
    data1 = json.loads(res_scan1.stdout)
    assert data1["summary"]["valid_skills"] >= 1

    # 2. Audit
    res_audit = runner.invoke(app, ["audit", "--target", str(sample_incomplete_skill), "--index", str(sample_index_file), "--format", "json"])
    assert res_audit.exit_code == 0
    audit_data = json.loads(res_audit.stdout)
    assert audit_data["is_compliant"] is False

    # 3. Complete
    res_comp = runner.invoke(app, ["complete", "--target", str(sample_incomplete_skill), "--index", str(sample_index_file), "--no-dry-run", "--format", "json"])
    assert res_comp.exit_code == 0
    comp_data = json.loads(res_comp.stdout)
    assert comp_data["success"] is True

    # 4. Audit again
    res_audit2 = runner.invoke(app, ["audit", "--target", str(sample_incomplete_skill), "--index", str(sample_index_file), "--format", "json"])
    assert res_audit2.exit_code == 0
    audit_data2 = json.loads(res_audit2.stdout)
    assert audit_data2["is_compliant"] is True

