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


def _new_code_summary(report: AggregatedReport) -> str:
    if not report.is_pr_context or not report.static:
        return ""
    new = report.static.new_code_findings
    if not new:
        return "\n> **New code** introduced in this PR: no issues found.\n"
    bugs = sum(1 for f in new if f.category == "bug")
    vulns = sum(1 for f in new if f.category == "vulnerability")
    smells = sum(1 for f in new if f.category == "code_smell")
    return (
        f"\n> **New code** introduced in this PR: "
        f"{bugs} bug(s) · {vulns} vulnerability(ies) · {smells} code smell(s)\n"
    )


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
    debt_line = ""
    if report.debt:
        debt_line = f"\n**Technical debt:** {report.debt.formatted_total()} (ratio {report.debt.formatted_ratio()})\n"

    new_code_section = _new_code_summary(report)
    footer = f"\n> Full report and fix instructions → [Job Summary]({run_url})." if run_url else ""

    return header + table + debt_line + new_code_section + footer
