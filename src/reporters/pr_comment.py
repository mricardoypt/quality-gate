"""Builds the compact PR comment body (≤ 20 lines)."""
from src.aggregator import AggregatedReport

_PASS = "✅"
_FAIL = "❌"
_WARN = "⚠️"


def _icon(check_passed: bool, blocking: bool) -> str:
    if check_passed:
        return _PASS
    return _FAIL if blocking else _WARN


def build(report: AggregatedReport, run_url: str) -> str:
    gate_icon = _PASS if report.gate_passed else _FAIL
    header = f"{gate_icon} **Quality Gate {'passed' if report.gate_passed else 'failed'}**\n\n"

    rows = ["| Check | Status | Value | Threshold |", "| --- | --- | --- | --- |"]
    for check in report.checks:
        icon = _icon(check.passed, check.blocking)
        label = "" if check.blocking else " _(non-blocking)_"
        rows.append(f"| {check.name}{label} | {icon} | {check.value} | {check.threshold} |")

    table = "\n".join(rows)
    footer = f"\n\n> Full report and fix instructions in the [Job Summary]({run_url})."

    return header + table + footer
