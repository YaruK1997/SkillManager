"""GitHub and HuggingFace Hub remote skills search provider."""

import asyncio
import os
import sys
import time
from typing import Any, Dict, List, Optional
import httpx

from skill_manager.models import SearchItem, SearchResult


class RemoteSearchError(Exception):
    """Custom exception raised during remote search queries."""
    pass


class RateLimitExceededError(RemoteSearchError):
    """Raised when GitHub or HuggingFace rate limit is reached."""
    def __init__(self, message: str, reset_timestamp: Optional[int] = None):
        super().__init__(message)
        self.reset_timestamp = reset_timestamp


def _build_github_headers(token: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "SkillManager/0.1.0",
    }
    github_tok = token or os.environ.get("GITHUB_TOKEN")
    if github_tok:
        headers["Authorization"] = f"Bearer {github_tok}"
    return headers


def _build_hf_headers(token: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "User-Agent": "SkillManager/0.1.0",
    }
    hf_tok = token or os.environ.get("HF_TOKEN")
    if hf_tok:
        headers["Authorization"] = f"Bearer {hf_tok}"
    return headers


def _execute_request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    headers: Dict[str, str],
    params: Optional[Dict[str, Any]] = None,
    max_retries: int = 3,
) -> httpx.Response:
    """Execute HTTP request with exponential backoff (1s, 2s, 4s) on transient errors."""
    backoff = 1.0
    last_err: Optional[Exception] = None

    for attempt in range(max_retries):
        try:
            resp = client.request(method, url, headers=headers, params=params)

            # Check rate limiting
            if resp.status_code == 429 or (resp.status_code == 403 and resp.headers.get("x-ratelimit-remaining") == "0"):
                reset_ts = resp.headers.get("x-ratelimit-reset")
                reset_int = int(reset_ts) if reset_ts and reset_ts.isdigit() else None
                raise RateLimitExceededError(
                    f"RATE_LIMIT_EXCEEDED: API rate limit reached. Reset at {reset_ts}",
                    reset_timestamp=reset_int,
                )

            # Check if server side error warrants retry
            if resp.status_code in (500, 502, 503, 504):
                if attempt < max_retries - 1:
                    time.sleep(backoff)
                    backoff *= 2.0
                    continue

            return resp
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError) as exc:
            last_err = exc
            if attempt < max_retries - 1:
                time.sleep(backoff)
                backoff *= 2.0
            else:
                raise RemoteSearchError(f"NETWORK_TIMEOUT: Request timed out after {max_retries} attempts.") from exc
        except RateLimitExceededError:
            raise

    raise RemoteSearchError(f"NETWORK_ERROR: Request failed: {last_err}")


def search_github(
    query: str,
    sort_by: str = "stars",
    limit: int = 20,
    page: int = 1,
    token: Optional[str] = None,
    client: Optional[httpx.Client] = None,
) -> List[SearchItem]:
    """Search repositories on GitHub matching skill keywords and topics."""
    # Compose search query targeting agent-skills or topic keywords
    github_q = f"{query} in:name,description,topics"
    sort_param = "stars" if sort_by == "stars" else "updated"
    params = {
        "q": github_q,
        "sort": sort_param,
        "order": "desc",
        "per_page": limit,
        "page": page,
    }

    url = "https://api.github.com/search/repositories"
    headers = _build_github_headers(token)

    should_close = False
    if client is None:
        client = httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0))
        should_close = True

    try:
        resp = _execute_request_with_retry(client, "GET", url, headers=headers, params=params)
        if resp.status_code != 200:
            sys.stderr.write(f"[WARN] GitHub API returned status {resp.status_code}: {resp.text}\n")
            return []

        try:
            data = resp.json()
        except Exception as e:
            raise RemoteSearchError("ERR_REMOTE_RESPONSE_INVALID: Failed to parse GitHub JSON response.") from e

        items: List[SearchItem] = []
        for repo in data.get("items", []):
            items.append(
                SearchItem(
                    source="github",
                    repo_id=repo.get("full_name", ""),
                    url=repo.get("html_url", ""),
                    description=repo.get("description") or "",
                    stars_or_downloads=repo.get("stargazers_count", 0),
                    updated_at=repo.get("updated_at"),
                    tags=repo.get("topics", []),
                )
            )
        return items
    finally:
        if should_close:
            client.close()


def search_huggingface(
    query: str,
    limit: int = 20,
    token: Optional[str] = None,
    client: Optional[httpx.Client] = None,
) -> List[SearchItem]:
    """Search HuggingFace Spaces and Models related to tools and skills."""
    url = "https://huggingface.co/api/spaces"
    params = {
        "search": query,
        "limit": limit,
        "full": "false",
    }
    headers = _build_hf_headers(token)

    should_close = False
    if client is None:
        client = httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0))
        should_close = True

    try:
        resp = _execute_request_with_retry(client, "GET", url, headers=headers, params=params)
        if resp.status_code != 200:
            sys.stderr.write(f"[WARN] HuggingFace API returned status {resp.status_code}\n")
            return []

        try:
            data = resp.json()
        except Exception as e:
            raise RemoteSearchError("ERR_REMOTE_RESPONSE_INVALID: Failed to parse HuggingFace JSON response.") from e

        items: List[SearchItem] = []
        if isinstance(data, list):
            for space in data:
                space_id = space.get("id") or space.get("_id", "")
                items.append(
                    SearchItem(
                        source="huggingface",
                        repo_id=space_id,
                        url=f"https://huggingface.co/spaces/{space_id}",
                        description=f"HuggingFace Space: {space_id}",
                        stars_or_downloads=space.get("likes", 0),
                        updated_at=space.get("lastModified"),
                        tags=space.get("tags", []),
                    )
                )
        return items
    finally:
        if should_close:
            client.close()


def search_remote_skills(
    query: str,
    source: str = "all",
    sort_by: str = "stars",
    limit: int = 20,
    page: int = 1,
    github_token: Optional[str] = None,
    hf_token: Optional[str] = None,
    client: Optional[httpx.Client] = None,
) -> SearchResult:
    """Execute remote search on GitHub, HuggingFace, or both."""
    # Validation
    cleaned_query = query.strip()
    if len(cleaned_query) < 2 or len(cleaned_query) > 100:
        raise ValueError("VALIDATION_ERROR: query length must be between 2 and 100 characters")

    # Limit capping
    capped_limit = max(1, min(limit, 50))
    capped_page = max(1, page)

    results: List[SearchItem] = []

    if source in ("github", "all"):
        gh_items = search_github(
            query=cleaned_query,
            sort_by=sort_by,
            limit=capped_limit,
            page=capped_page,
            token=github_token,
            client=client,
        )
        results.extend(gh_items)

    if source in ("huggingface", "all"):
        hf_items = search_huggingface(
            query=cleaned_query,
            limit=capped_limit,
            token=hf_token,
            client=client,
        )
        results.extend(hf_items)

    # Sort aggregated items
    if sort_by == "stars":
        results.sort(key=lambda x: x.stars_or_downloads, reverse=True)

    return SearchResult(
        items=results[:capped_limit],
        total_count=len(results),
        current_page=capped_page,
        limit=capped_limit,
    )

