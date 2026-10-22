"""Test fixtures and mock helpers for SkillManager."""

import os
import stat
import shutil
import tempfile
from pathlib import Path
import git
import pytest


def _remove_readonly(func, path, exc_info):
    """Clear readonly bit on Windows and retry deletion."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


@pytest.fixture
def temp_dir():
    """Create a temporary directory and clean up after test."""
    temp_path = Path(tempfile.mkdtemp(prefix="test_skill_mgr_"))
    yield temp_path
    if temp_path.exists():
        shutil.rmtree(temp_path, onexc=_remove_readonly)


@pytest.fixture
def sample_valid_skill(temp_dir):
    """Create a valid skill structure with SKILL.md, scripts, and references."""
    skill_dir = temp_dir / "my-test-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "scripts").mkdir()
    (skill_dir / "references").mkdir()

    skill_md = skill_dir / "SKILL.md"
    content = """---
name: my-test-skill
description: A comprehensive test skill for unit testing
---

# my-test-skill

## Overview
Test overview.

## When to Use
Use when executing unit tests.

## Instructions
1. Run pytest.
2. Verify output.

## Examples
Example command.

## References
Reference links.
"""
    skill_md.write_text(content, encoding="utf-8")
    return skill_dir


@pytest.fixture
def sample_incomplete_skill(temp_dir):
    """Create an incomplete skill missing sections and subdirectories."""
    skill_dir = temp_dir / "incomplete-skill"
    skill_dir.mkdir(parents=True)

    skill_md = skill_dir / "SKILL.md"
    content = """---
name: incomplete-skill
description: Incomplete skill for testing
---

# Incomplete Skill

Some basic text without standard sections.
"""
    skill_md.write_text(content, encoding="utf-8")
    return skill_dir


@pytest.fixture
def sample_index_file(temp_dir):
    """Create a standard index.md specification file."""
    index_file = temp_dir / "index.md"
    content = """# Skills Specification Index

## Required Structure
Every skill must have a valid SKILL.md with YAML metadata and the following sections:

## When to Use
Instructions on when to invoke the skill.

## Instructions
Step by step guidance.

## Examples
Concrete examples.

## References
Reference materials.
"""
    index_file.write_text(content, encoding="utf-8")
    return index_file


@pytest.fixture
def git_repo_with_remote(temp_dir):
    """Create a local Git repo pointing to a bare remote repo to test versioning."""
    bare_remote_dir = temp_dir / "remote_repo.git"
    git.Repo.init(bare_remote_dir, bare=True, initial_branch="main")

    local_repo_dir = temp_dir / "local_skill"
    repo = git.Repo.clone_from(str(bare_remote_dir), str(local_repo_dir))

    # Add initial commit to main
    test_file = local_repo_dir / "SKILL.md"
    test_file.write_text("---\nname: local-skill\n---\n# Skill\n", encoding="utf-8")
    repo.index.add(["SKILL.md"])
    repo.index.commit("Initial commit")
    repo.git.branch("-M", "main")
    repo.git.push("-u", "origin", "main")

    return local_repo_dir, bare_remote_dir

