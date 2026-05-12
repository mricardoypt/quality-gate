"""Posts GitHub Check Annotations (inline on the PR diff) via the Checks API."""
import logging
import os

import requests

from src.aggregator import AggregatedReport

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_MAX_ANNOTATIONS = 50  # GitHub API hard limit per request


def _build_annotations(report: AggregatedReport) -> list[dict]:
    annotations: list[dict] = []

    if report.complexity:
        for v in report.complexity.violations:
            annotations.append({
                "path": v.file,
                "start_line": v.lineno,
                "end_line": v.lineno,
                "annotation_level": "warning",
                "title": f"High cognitive complexity ({v.complexity})",
                "message": f"Function `{v.name}` has complexity {v.complexity}. Refactor into smaller, focused functions.",
            })

    if report.sarif:
        level_map = {"error": "failure", "warning": "warning", "note": "notice"}
        for finding in report.sarif.findings:
            if not finding.file or not finding.line:
                continue
            annotations.append({
                "path": finding.file,
                "start_line": finding.line,
                "end_line": finding.line,
                "annotation_level": level_map.get(finding.severity, "warning"),
                "title": f"[{finding.tool}] {finding.rule_id}",
                "message": finding.message,
            })

    return annotations[:_MAX_ANNOTATIONS]


def post(report: AggregatedReport, sha: str) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repository = os.environ.get("GITHUB_REPOSITORY")

    if not token or not repository:
        logger.warning("GITHUB_TOKEN or GITHUB_REPOSITORY not set; skipping annotations")
        return

    annotations = _build_annotations(report)
    if not annotations:
        return

    conclusion = "success" if report.gate_passed else "failure"
    title = "Quality Gate passed" if report.gate_passed else "Quality Gate failed"

    payload = {
        "name": "Quality Gate",
        "head_sha": sha,
        "status": "completed",
        "conclusion": conclusion,
        "output": {
            "title": title,
            "summary": f"{len(report.blocking_failures)} blocking failure(s), {len(report.warning_failures)} warning(s).",
            "annotations": annotations,
        },
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    response = requests.post(
        f"{_GITHUB_API}/repos/{repository}/check-runs",
        json=payload,
        headers=headers,
        timeout=15,
    )

    if not response.ok:
        logger.error("Failed to post check annotations: %s %s", response.status_code, response.text)
