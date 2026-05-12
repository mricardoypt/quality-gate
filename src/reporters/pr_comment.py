"""Builds the compact PR comment body (≤ ~30 lines)."""
from src.aggregator import AggregatedReport

_ICONS = {True: "✅", False: "❌"}
_WARN = "⚠️"
_RATING_EMOJI = {"A": "🟢", "B": "🟡", "C": "🟠", "D": "🔴", "E": "🔴"}


def _status_icon(passed: bool, blocking: bool) -> str:
    if passed:
        return "✅"
    return "❌" if blocking else _WARN


def _ratings_row(report: AggregatedReport) -> str:
    if not report.ratings:
        return ""
    r = report.ratings
    rel = f"{_RATING_EMOJI.get(r.reliability, '')} {r.reliability}"
    sec = f"{_RATING_EMOJI.get(r.security, '')} {r.security}"
    mnt = f"{_RATING_EMOJI.get(r.maintainability, '')} {r.maintainability}"
    return f"| Ratings | — | Reliability {rel} · Security {sec} · Maintainability {mnt} | — |\n"


def _issue_parts(d) -> list[str]:
    parts = []
    if d.new_bugs:
        parts.append(f"**{d.new_bugs} bug(s)**")
    if d.new_vulnerabilities:
        parts.append(f"**{d.new_vulnerabilities} vulnerability(ies)**")
    if d.new_code_smells:
        parts.append(f"{d.new_code_smells} code smell(s)")
    if d.new_complexity_violations:
        parts.append(f"{d.new_complexity_violations} complexity violation(s)")
    if d.new_security_findings:
        parts.append(f"{d.new_security_findings} security finding(s)")
    if d.new_large_files:
        parts.append(f"{d.new_large_files} large file(s)")
    if d.new_duplication_blocks:
        parts.append(f"{d.new_duplication_blocks} duplication block(s)")
    return parts


def _diff_section(report: AggregatedReport) -> str:
    if not report.is_pr_context or not report.diff_summary:
        return ""
    d = report.diff_summary
    lines: list[str] = []

    if d.diff_line_rate is not None:
        branch_str = f" / **{d.diff_branch_rate:.1f}%** branches" if d.diff_branch_rate is not None else ""
        lines.append(f"Coverage (diff): **{d.diff_line_rate:.1f}%** lines{branch_str} ({d.diff_covered_lines}/{d.diff_total_lines})")

    parts = _issue_parts(d)
    if parts:
        lines.append(f"Issues: {', '.join(parts)}")
    elif not lines:
        return "\n> **New code in this PR:** no issues found.\n"

    return "\n> **New code in this PR:**\n" + "".join(f"> - {ln}\n" for ln in lines)


def build(report: AggregatedReport, run_url: str) -> str:
    gate_icon = "✅" if report.gate_passed else "❌"
    header = f"{gate_icon} **Quality Gate {'passed' if report.gate_passed else 'failed'}**\n\n"

    rows = ["| Check | Status | Value | Threshold |", "| --- | --- | --- | --- |"]
    for check in report.checks:
        icon = _status_icon(check.passed, check.blocking)
        label = "" if check.blocking else " _(non-blocking)_"
        rows.append(f"| {check.name}{label} | {icon} | {check.value} | {check.threshold} |")

    if report.ratings:
        rows.append(_ratings_row(report).strip())

    table = "\n".join(rows)
    footer = f"\n> Full report and fix instructions → [Job Summary]({run_url})." if run_url else ""

    return header + table + _diff_section(report) + footer
