"""Unit tests for remote search module (FR-02)."""

import httpx
import pytest
import respx
from skill_manager.core.remote_search import (
    RateLimitExceededError,
    RemoteSearchError,
    search_github,
    search_huggingface,
    search_remote_skills,
)


@respx.mock
def test_t_r1_ac_02_01_github_search():
    """T-R1-AC-02-01: GitHub search returns parsed SearchItem objects."""
    respx.get("https://api.github.com/search/repositories").respond(
        status_code=200,
        json={
            "items": [
                {
                    "full_name": "test-owner/docker-skills",
                    "html_url": "https://github.com/test-owner/docker-skills",
                    "description": "Docker skills for agent",
                    "stargazers_count": 142,
                    "updated_at": "2026-10-01T12:00:00Z",
                    "topics": ["agent-skills", "docker"],
                }
            ]
        },
    )

    with httpx.Client() as client:
        items = search_github(query="docker", client=client)
        assert len(items) == 1
        assert items[0].repo_id == "test-owner/docker-skills"
        assert items[0].stars_or_downloads == 142
        assert items[0].source == "github"


@respx.mock
def test_t_r1_ac_02_02_huggingface_search():
    """T-R1-AC-02-02: HuggingFace search returns parsed items."""
    respx.get("https://huggingface.co/api/spaces").respond(
        status_code=200,
        json=[
            {
                "id": "agent-tools/code-reviewer",
                "likes": 58,
                "lastModified": "2026-09-15T08:00:00Z",
                "tags": ["skills", "code-review"],
            }
        ],
    )

    with httpx.Client() as client:
        items = search_huggingface(query="code-review", client=client)
        assert len(items) == 1
        assert items[0].repo_id == "agent-tools/code-reviewer"
        assert items[0].stars_or_downloads == 58
        assert items[0].source == "huggingface"


def test_t_r2_ac_02_03_query_validation():
    """T-R2-AC-02-03: Query with length < 2 or > 100 raises ValueError."""
    with pytest.raises(ValueError, match="VALIDATION_ERROR"):
        search_remote_skills(query="a")

    with pytest.raises(ValueError, match="VALIDATION_ERROR"):
        search_remote_skills(query="x" * 101)


@respx.mock
def test_t_r2_ac_02_04_rate_limit_exceeded():
    """T-R2-AC-02-04: HTTP 429 raises RateLimitExceededError with reset timestamp."""
    respx.get("https://api.github.com/search/repositories").respond(
        status_code=429,
        headers={"x-ratelimit-reset": "1730000000"},
    )

    with httpx.Client() as client:
        with pytest.raises(RateLimitExceededError) as exc_info:
            search_github(query="docker", client=client)
        assert "RATE_LIMIT_EXCEEDED" in str(exc_info.value)
        assert exc_info.value.reset_timestamp == 1730000000


@respx.mock
def test_t_r2_ec_02_02_limit_capping():
    """T-R2-EC-02-02: Search limit > 50 is clamped to 50."""
    respx.get("https://api.github.com/search/repositories").respond(
        status_code=200,
        json={"items": []},
    )

    with httpx.Client() as client:
        result = search_remote_skills(query="docker", limit=9999, source="github", client=client)
        assert result.limit == 50

