"""Posts GitHub Check Annotations (inline on the PR diff) via the Checks API."""
import logging
import os

import requests

from src.aggregator import AggregatedReport

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_MAX_ANNOTATIONS = 50  # GitHub API hard limit per request
_REPO_PATH = os.environ.get("REPO_PATH", "/repo")


def _relative_path(absolute: str) -> str:
    prefix = _REPO_PATH.rstrip("/") + "/"
    return absolute[len(prefix):] if absolute.startswith(prefix) else absolute


def _in_pr_diff(path: str, line: int, new_code_lines: dict[str, set[int]]) -> bool:
    return line in new_code_lines.get(path, set())


def _build_annotations(report: AggregatedReport) -> list[dict]:
    diff = report.new_code_lines  # None when not a PR
    annotations: list[dict] = []

    if report.static:
        for finding in report.static.bugs + report.static.vulnerabilities:
            if not finding.file or not finding.line:
                continue
            path = _relative_path(finding.file)
            if diff is not None and not _in_pr_diff(path, finding.line, diff):
                continue
            annotations.append({
                "path": path,
                "start_line": finding.line,
                "end_line": finding.line,
                "annotation_level": "failure",
                "title": f"[{finding.category.replace('_', ' ').title()}] {finding.rule}",
                "message": finding.message,
            })

        for finding in report.static.code_smells:
            if not finding.file or not finding.line:
                continue
            path = _relative_path(finding.file)
            if diff is not None and not _in_pr_diff(path, finding.line, diff):
                continue
            annotations.append({
                "path": path,
                "start_line": finding.line,
                "end_line": finding.line,
                "annotation_level": "warning",
                "title": f"[Code Smell] {finding.rule}",
                "message": finding.message,
            })

    if report.complexity:
        for fn in report.complexity.cyclomatic_violations:
            path = _relative_path(fn.file)
            if diff is not None and not _in_pr_diff(path, fn.lineno, diff):
                continue
            annotations.append({
                "path": path,
                "start_line": fn.lineno,
                "end_line": fn.lineno,
                "annotation_level": "warning",
                "title": f"High cyclomatic complexity ({fn.cyclomatic})",
                "message": f"`{fn.name}` has cyclomatic complexity {fn.cyclomatic} (max {report.complexity.cyclomatic_max}). Refactor into smaller functions.",
            })
        for fn in report.complexity.cognitive_violations:
            path = _relative_path(fn.file)
            if diff is not None and not _in_pr_diff(path, fn.lineno, diff):
                continue
            annotations.append({
                "path": path,
                "start_line": fn.lineno,
                "end_line": fn.lineno,
                "annotation_level": "warning",
                "title": f"High cognitive complexity ({fn.cognitive})",
                "message": f"`{fn.name}` has cognitive complexity {fn.cognitive} (max {report.complexity.cognitive_max}). Reduce nesting and conditional chains.",
            })

    if report.sarif:
        level_map = {"error": "failure", "warning": "warning", "note": "notice"}
        for finding in report.sarif.findings:
            if not finding.file or not finding.line:
                continue
            path = _relative_path(finding.file)
            if diff is not None and not _in_pr_diff(path, finding.line, diff):
                continue
            annotations.append({
                "path": path,
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
    conclusion = "success" if report.gate_passed else "failure"
    blocking_count = len(report.blocking_failures)
    warning_count = len(report.warning_failures)

    payload = {
        "name": "Quality Gate",
        "head_sha": sha,
        "status": "completed",
        "conclusion": conclusion,
        "output": {
            "title": "Quality Gate passed" if report.gate_passed else "Quality Gate failed",
            "summary": f"{blocking_count} blocking failure(s), {warning_count} non-blocking warning(s).",
            "annotations": annotations,
        },
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    logger.info("Posting %d annotation(s) for sha=%s", len(annotations), sha)
    response = requests.post(
        f"{_GITHUB_API}/repos/{repository}/check-runs",
        json=payload,
        headers=headers,
        timeout=15,
    )
    if response.ok:
        logger.info("Check run created: %s", response.json().get("html_url", ""))
    else:
        logger.error("Failed to post check annotations: %s %s", response.status_code, response.text)
