"""Dedicated R2 boundary, fault injection, and edge-case test suite (T-R2-*)."""

import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch
import git
import httpx
import pytest
import respx

from skill_manager.core.indexer import (
    audit_skill,
    complete_skill,
    parse_index_schema,
)
from skill_manager.core.remote_search import (
    RateLimitExceededError,
    RemoteSearchError,
    search_github,
    search_remote_skills,
)
from skill_manager.core.scanner import (
    inspect_single_skill,
    parse_yaml_frontmatter,
    scan_skills,
)
from skill_manager.core.versioning import (
    DirtyWorktreeError,
    GitVersionError,
    check_version_status,
    upgrade_skill,
)
from skill_manager.models import PlatformType, VersionStatus


# ==============================================================================
# FR-01 Boundary & Fault Injection Tests
# ==============================================================================

@pytest.mark.r2
def test_t_r2_ac_01_05_permission_denied(temp_dir, capsys):
    """T-R2-AC-01-05 / T-R2-EC-01-07 (Source: AC-01-05, EC-01-07): Handle permission denied on directory gracefully."""
    restricted_dir = temp_dir / "restricted"
    restricted_dir.mkdir()

    with patch("os.scandir", side_effect=PermissionError("Permission denied")):
        res = scan_skills(platform=PlatformType.UNIVERSAL, custom_paths=[str(restricted_dir)])
        captured = capsys.readouterr()
        assert "ACCESS_DENIED" in captured.err
        assert res.summary.valid_skills == 0


@pytest.mark.r2
def test_t_r2_ec_01_02_streaming_large_directory(temp_dir):
    """T-R2-EC-01-02 (Source: EC-01-02): Generator handles large directory count without memory balloon."""
    # Create 50 mock subdirectories to test generator performance
    base_dir = temp_dir / "large_skills"
    base_dir.mkdir()
    for i in range(50):
        s_dir = base_dir / f"skill_{i}"
        s_dir.mkdir()
        (s_dir / "SKILL.md").write_text(f"---\nname: skill_{i}\n---\n# Skill {i}\n", encoding="utf-8")

    res = scan_skills(platform=PlatformType.UNIVERSAL, custom_paths=[str(base_dir)])
    assert res.summary.valid_skills == 50


@pytest.mark.r2
def test_t_r2_ec_01_05_concurrent_file_deletion(temp_dir):
    """T-R2-EC-01-05 (Source: EC-01-05): Handle file disappearing between scandir and read."""
    skill_dir = temp_dir / "ghost_skill"
    skill_dir.mkdir()
    ghost_file = skill_dir / "SKILL.md"

    # Simulate FileNotFoundError during inspection
    with patch("pathlib.Path.stat", side_effect=FileNotFoundError("File removed concurrently")):
        meta, body = parse_yaml_frontmatter(ghost_file)
        assert meta == {}
        assert body == ""


# ==============================================================================
# FR-02 Boundary & Fault Injection Tests
# ==============================================================================

@pytest.mark.r2
def test_t_r2_ec_02_01_blank_query_validation():
    """T-R2-EC-02-01 (Source: EC-02-01): Blank or whitespace-only query rejected."""
    with pytest.raises(ValueError, match="VALIDATION_ERROR"):
        search_remote_skills(query="   ")


@pytest.mark.r2
@respx.mock
def test_t_r2_ec_02_03_invalid_json_response():
    """T-R2-EC-02-03 (Source: EC-02-03): Invalid HTML/non-JSON response raises RemoteSearchError."""
    respx.get("https://api.github.com/search/repositories").respond(
        status_code=200,
        text="<html><body>Cloudflare 502 Bad Gateway</body></html>",
    )

    with httpx.Client() as client:
        with pytest.raises(RemoteSearchError, match="ERR_REMOTE_RESPONSE_INVALID"):
            search_github(query="docker", client=client)


@pytest.mark.r2
@respx.mock
def test_t_r2_ec_02_04_network_timeout_retry():
    """T-R2-EC-02-04 (Source: EC-02-04): Network timeout after 3 exponential backoff attempts."""
    route = respx.get("https://api.github.com/search/repositories")
    route.side_effect = httpx.ConnectTimeout("Connection timed out")

    with httpx.Client() as client:
        with patch("time.sleep") as mock_sleep:
            with pytest.raises(RemoteSearchError, match="NETWORK_TIMEOUT"):
                search_github(query="docker", client=client)
            assert mock_sleep.call_count == 2  # retried twice with backoff


@pytest.mark.r2
@respx.mock
def test_t_r2_ec_02_07_auth_error_handling():
    """T-R2-EC-02-07 (Source: EC-02-07): Handle 401 unauthorized or invalid token."""
    respx.get("https://api.github.com/search/repositories").respond(
        status_code=401,
        json={"message": "Bad credentials"},
    )

    with httpx.Client() as client:
        items = search_github(query="docker", client=client)
        assert items == []


# ==============================================================================
# FR-03 Boundary & Fault Injection Tests
# ==============================================================================

@pytest.mark.r2
def test_t_r2_ec_03_02_large_file_size_guard(temp_dir):
    """T-R2-EC-03-02 (Source: EC-03-02): Skip SKILL.md larger than 50 MB to prevent memory overflow."""
    large_file = temp_dir / "large_skill.md"
    large_file.write_text("dummy", encoding="utf-8")

    # Mock stat().st_size to return 51 MB
    mock_stat = MagicMock()
    mock_stat.st_size = 52 * 1024 * 1024

    with patch("pathlib.Path.stat", return_value=mock_stat):
        meta, body = parse_yaml_frontmatter(large_file)
        assert meta == {}
        assert body == ""


@pytest.mark.r2
def test_t_r2_ec_03_03_yaml_syntax_error(temp_dir):
    """T-R2-EC-03-03 (Source: EC-03-03): Catch corrupted YAML syntax error without crash."""
    corrupt_skill = temp_dir / "corrupt_yaml"
    corrupt_skill.mkdir()
    (corrupt_skill / "SKILL.md").write_text("---\nkey: : [unbalanced\n---\n# Body\n", encoding="utf-8")

    meta, body = parse_yaml_frontmatter(corrupt_skill / "SKILL.md")
    assert meta == {}
    assert "Body" in body


@pytest.mark.r2
def test_t_r2_ec_03_05_atomic_file_write(temp_dir):
    """T-R2-EC-03-05 (Source: EC-03-05): Ensure atomic writing replaces SKILL.md cleanly."""
    skill_dir = temp_dir / "atomic_skill"
    skill_dir.mkdir()
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("---\nname: atomic\n---\n# Atomic\n", encoding="utf-8")

    success, diff, modified = complete_skill(skill_dir, dry_run=False)
    assert success is True
    assert str(skill_md) in modified
    # Ensure no leftover .tmp files
    tmp_files = list(skill_dir.glob("SKILL.md.tmp.*"))
    assert len(tmp_files) == 0


@pytest.mark.r2
def test_t_r2_ac_03_04_and_ec_03_07_write_permission_denied(temp_dir):
    """T-R2-AC-03-04 / T-R2-EC-03-07 (Source: AC-03-04, EC-03-07): Raise PermissionError when writing to read-only directory."""
    skill_dir = temp_dir / "readonly_skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: ro\n---\n# RO\n", encoding="utf-8")

    with patch("pathlib.Path.replace", side_effect=PermissionError("Permission Denied")):
        with pytest.raises(PermissionError, match="WRITE_PERMISSION_DENIED"):
            complete_skill(skill_dir, dry_run=False)


# ==============================================================================
# FR-04 Boundary & Fault Injection Tests
# ==============================================================================

@pytest.mark.r2
def test_t_r2_ec_04_03_corrupt_git_repo(temp_dir):
    """T-R2-EC-04-03 (Source: EC-04-03): Catch corrupted git repository without crashing."""
    corrupt_dir = temp_dir / "corrupt_git"
    corrupt_dir.mkdir()
    git_dir = corrupt_dir / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("invalid ref garbage", encoding="utf-8")

    with pytest.raises(GitVersionError, match="GIT_CORRUPT"):
        check_version_status(corrupt_dir)


@pytest.mark.r2
def test_t_r2_ac_04_05_git_fetch_timeout(git_repo_with_remote):
    """T-R2-AC-04-05 (Source: AC-04-05): Git fetch network timeout marked as NETWORK_TIMEOUT."""
    local_repo_dir, _ = git_repo_with_remote

    with patch("git.Remote.fetch", side_effect=git.exc.GitCommandError("fetch", 128, "timed out")):
        status = check_version_status(local_repo_dir, fetch_remote=True)
        assert status.version_status == VersionStatus.NETWORK_TIMEOUT


@pytest.mark.r2
def test_upgrade_detached_head_and_no_remote(git_repo_with_remote, temp_dir):
    """CRIT-01 & CRIT-02: Test upgrade_skill handles detached HEAD and missing remotes gracefully."""
    local_repo_dir, _ = git_repo_with_remote
    repo = git.Repo(local_repo_dir)

    # 1. Detached HEAD
    repo.head.reference = repo.head.commit
    repo.head.reset(index=True, working_tree=True)
    assert repo.head.is_detached
    res = upgrade_skill(local_repo_dir, force=True)
    assert res.version_status == VersionStatus.UP_TO_DATE

    # 2. No remotes
    plain_repo_dir = temp_dir / "repo_no_remote"
    plain_repo = git.Repo.init(plain_repo_dir)
    (plain_repo_dir / "A.txt").write_text("a", encoding="utf-8")
    plain_repo.index.add(["A.txt"])
    plain_repo.index.commit("Initial")

    with pytest.raises(GitVersionError, match="UNTRACKED"):
        upgrade_skill(plain_repo_dir, force=True)


@pytest.mark.r2
def test_t_r2_ec_04_05_zero_dataloss_dirty_upgrade(git_repo_with_remote):
    """T-R2-EC-04-05 (Source: EC-04-05): Refuse upgrade when dirty changes exist, preventing data loss."""
    local_repo_dir, _ = git_repo_with_remote
    (local_repo_dir / "important_work.py").write_text("# my uncommitted work\n", encoding="utf-8")

    with pytest.raises(DirtyWorktreeError, match="DIRTY_WORKTREE_DETECTED"):
        upgrade_skill(local_repo_dir, force=False)

    # Verify uncommitted file is completely intact
    assert (local_repo_dir / "important_work.py").exists()


@pytest.mark.r2
def test_security_cwe88_git_ref_injection_blocked(git_repo_with_remote):
    """T-R2-SEC-CWE88 (Source: FR-04 Security Guard): Block git argument injection in target_ref and tag_name."""
    local_repo_dir, _ = git_repo_with_remote

    with pytest.raises(GitVersionError, match="INVALID_GIT_REF"):
        upgrade_skill(local_repo_dir, target_ref="--upload-pack=evil", force=True)

    with pytest.raises(GitVersionError, match="INVALID_GIT_REF"):
        upgrade_skill(local_repo_dir, target_ref="../escape", force=True)


@pytest.mark.r2
def test_security_cwe22_path_traversal_blocked(temp_dir):
    """T-R2-SEC-CWE22: Path traversal guard blocks escaping skill directory during completion."""
    from skill_manager.models import AuditResult
    skill_dir = temp_dir / "my_skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# My Skill\n", encoding="utf-8")

    malicious_audit = AuditResult(
        is_compliant=False,
        missing_fields=[],
        missing_sections=["Actions"],
        missing_dirs=["../../escaped_dir"],
        diff_content=None,
    )

    with patch("skill_manager.core.indexer.audit_skill", return_value=malicious_audit):
        with pytest.raises(ValueError, match="PATH_TRAVERSAL_BLOCKED"):
            complete_skill(skill_dir, dry_run=False)


