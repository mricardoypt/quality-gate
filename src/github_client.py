"""GitHub API helpers — PR comments, diff-scoped file listing, changed-line mapping."""
import logging
import os
from typing import Optional

import requests

from src.diff import parse_added_lines

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"


def _headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _pr_files() -> Optional[list[dict]]:
    repository = os.environ.get("GITHUB_REPOSITORY")
    pr_number = os.environ.get("PR_NUMBER")
    if not repository or not pr_number:
        return None

    response = requests.get(
        f"{_GITHUB_API}/repos/{repository}/pulls/{pr_number}/files",
        headers=_headers(),
        timeout=15,
    )
    if not response.ok:
        logger.error("Failed to fetch PR files: %s %s", response.status_code, response.text)
        return None

    return response.json()


def post_pr_comment(body: str) -> None:
    repository = os.environ.get("GITHUB_REPOSITORY")
    pr_number = os.environ.get("PR_NUMBER")
    if not repository or not pr_number:
        logger.warning("GITHUB_REPOSITORY or PR_NUMBER not set; skipping PR comment")
        return

    response = requests.post(
        f"{_GITHUB_API}/repos/{repository}/issues/{pr_number}/comments",
        json={"body": body},
        headers=_headers(),
        timeout=15,
    )
    if not response.ok:
        logger.error("Failed to post PR comment: %s %s", response.status_code, response.text)


def get_changed_lines_by_file() -> Optional[dict[str, set[int]]]:
    """
    Returns {filepath: {added_line_numbers}} for every .py file in the PR.
    Returns None when not running in a PR context.
    """
    files = _pr_files()
    if files is None:
        return None

    return {
        f["filename"]: parse_added_lines(f.get("patch", ""))
        for f in files
        if f["filename"].endswith(".py") and f["status"] != "removed"
    }
