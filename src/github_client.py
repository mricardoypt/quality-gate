"""GitHub API helpers — PR comments and diff-scoped file listing."""
import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"


def _headers() -> dict:
    token = os.environ.get("GITHUB_TOKEN", "")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


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


def get_changed_python_files() -> Optional[list[str]]:
    """Returns the list of .py files changed in the PR, or None if not in a PR context."""
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

    return [
        f["filename"]
        for f in response.json()
        if f["filename"].endswith(".py") and f["status"] != "removed"
    ]
