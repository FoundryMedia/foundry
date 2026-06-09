"""GitHub API integration for Foundry CLI.

Provides token resolution, organization validation, and repository
discovery using the GitHub REST API v3.  Uses only :mod:`urllib` from
the standard library — no ``requests`` dependency needed.

Foundry never stores GitHub credentials — it reads from whatever the
developer (or CI runner) has configured locally:

Token resolution order (first match wins):

1. ``FOUNDRY_GITHUB_TOKEN`` environment variable
2. ``GITHUB_TOKEN`` environment variable  (CI/CD — automatic in GitHub Actions)
3. ``gh auth token`` (GitHub CLI — recommended for local dev)

No tokens are ever written to disk by Foundry.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from foundry_cli.core.errors import FoundryError

_API_BASE = "https://api.github.com"
_TOKEN_ENV_VARS = ("FOUNDRY_GITHUB_TOKEN", "GITHUB_TOKEN")


# ------------------------------------------------------------------
# Data classes
# ------------------------------------------------------------------

@dataclass(frozen=True)
class GitHubTokenResult:
    """Outcome of token resolution."""

    token: str | None
    source: str  # e.g. "env:GITHUB_TOKEN", "gh-cli", "config.yml", "none"

    @property
    def found(self) -> bool:
        return self.token is not None


@dataclass(frozen=True)
class GitHubCredentialStatus:
    """Summary of the detected GitHub credential state."""

    authenticated: bool
    login: str | None
    name: str | None
    source: str  # e.g. "env:GITHUB_TOKEN", "gh-cli", "none"
    error: str | None = None


@dataclass(frozen=True)
class GitHubOrg:
    """Minimal org info from the GitHub API."""

    login: str
    name: str | None
    url: str


@dataclass(frozen=True)
class GitHubRepo:
    """Minimal repo info from the GitHub API."""

    name: str
    full_name: str
    private: bool
    url: str
    default_branch: str


# ------------------------------------------------------------------
# Token resolution
# ------------------------------------------------------------------

def resolve_token() -> GitHubTokenResult:
    """Resolve a GitHub personal access token.

    Foundry never stores tokens — it reads from the developer's
    existing toolchain:

    1. ``FOUNDRY_GITHUB_TOKEN`` env var
    2. ``GITHUB_TOKEN`` env var  (automatic in GitHub Actions)
    3. ``gh auth token`` (GitHub CLI)
    """
    # 1 & 2 — environment variables
    for var in _TOKEN_ENV_VARS:
        val = os.environ.get(var)
        if val and val.strip():
            return GitHubTokenResult(token=val.strip(), source=f"env:{var}")

    # 3 — GitHub CLI
    token = _try_gh_cli()
    if token:
        return GitHubTokenResult(token=token, source="gh-cli")

    return GitHubTokenResult(token=None, source="none")


def _try_gh_cli() -> str | None:
    """Attempt to get a token from the GitHub CLI."""
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def detect_github_credentials() -> GitHubCredentialStatus:
    """Detect whether valid GitHub credentials are available.

    Non-throwing — returns a status object indicating success or failure.
    Used by ``foundry config --show`` to display toolchain status.
    """
    resolved = resolve_token()
    if not resolved.found:
        return GitHubCredentialStatus(
            authenticated=False,
            login=None,
            name=None,
            source="none",
            error="No GitHub token found. Sign in with: gh auth login",
        )
    try:
        user = validate_token(resolved.token)
        return GitHubCredentialStatus(
            authenticated=True,
            login=user.get("login"),
            name=user.get("name"),
            source=resolved.source,
        )
    except FoundryError as exc:
        return GitHubCredentialStatus(
            authenticated=False,
            login=None,
            name=None,
            source=resolved.source,
            error=str(exc),
        )


# ------------------------------------------------------------------
# API helpers
# ------------------------------------------------------------------

def _api_request(
    path: str,
    token: str,
    *,
    method: str = "GET",
    params: dict[str, str] | None = None,
) -> Any:
    """Make an authenticated request to the GitHub REST API.

    Returns parsed JSON.  Raises :class:`FoundryError` on failure.
    """
    url = f"{_API_BASE}{path}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"

    req = urllib.request.Request(
        url,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "foundry-cli",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        if exc.code == 401:
            raise FoundryError(
                "GitHub token is invalid or expired.\n"
                "  Regenerate at: https://github.com/settings/tokens"
            ) from exc
        if exc.code == 403:
            raise FoundryError(
                f"GitHub API forbidden (403). Check token scopes.\n  {body}"
            ) from exc
        if exc.code == 404:
            raise FoundryError(
                f"GitHub resource not found: {path}"
            ) from exc
        raise FoundryError(
            f"GitHub API error {exc.code}: {body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise FoundryError(
            f"Cannot reach GitHub API: {exc.reason}"
        ) from exc


# ------------------------------------------------------------------
# Public API operations
# ------------------------------------------------------------------

def validate_token(token: str) -> dict[str, Any]:
    """Validate a token by calling ``GET /user``.

    Returns the user data dict on success.
    """
    return _api_request("/user", token)


def get_org(org_login: str, token: str) -> GitHubOrg:
    """Fetch organisation details.  Raises on 404."""
    data = _api_request(f"/orgs/{org_login}", token)
    return GitHubOrg(
        login=data["login"],
        name=data.get("name"),
        url=data["html_url"],
    )


def list_org_repos(
    org_login: str,
    token: str,
    *,
    prefix: str | None = None,
    main_repo: str | None = None,
    per_page: int = 100,
) -> list[GitHubRepo]:
    """List repositories in an organisation, filtered to platform repos.

    A repo is included if it matches **any** of:

    - Its name equals *main_repo* (the primary platform repository).
    - Its name starts with ``{prefix}-`` (satellite / extracted repos).

    If neither *prefix* nor *main_repo* is given, all repos are returned.
    Fetches up to *per_page* repos (one page — sufficient for most platforms).
    """
    data = _api_request(
        f"/orgs/{org_login}/repos",
        token,
        params={"per_page": str(per_page), "sort": "name", "type": "all"},
    )
    has_filter = bool(prefix or main_repo)
    repos: list[GitHubRepo] = []
    for item in data:
        name: str = item["name"]
        if has_filter:
            is_main = main_repo and name == main_repo
            is_satellite = prefix and name.startswith(f"{prefix}-")
            if not is_main and not is_satellite:
                continue
        repos.append(GitHubRepo(
            name=name,
            full_name=item["full_name"],
            private=item["private"],
            url=item["html_url"],
            default_branch=item.get("default_branch", "main"),
        ))
    return repos


def check_repo_exists(org: str, repo: str, token: str) -> bool:
    """Return ``True`` if ``{org}/{repo}`` exists and is accessible."""
    try:
        _api_request(f"/repos/{org}/{repo}", token)
        return True
    except FoundryError:
        return False


# ------------------------------------------------------------------
# Config.yml helpers
# ------------------------------------------------------------------

__all__ = [
    "GitHubCredentialStatus",
    "GitHubOrg",
    "GitHubRepo",
    "GitHubTokenResult",
    "check_repo_exists",
    "detect_github_credentials",
    "get_org",
    "list_org_repos",
    "resolve_token",
    "validate_token",
]
