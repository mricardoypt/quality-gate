"""Writes the full GitHub Job Summary (GITHUB_STEP_SUMMARY) with Claude instructions."""
import os

from src.aggregator import AggregatedReport

_PASS = "✅"
_FAIL = "❌"
_WARN = "⚠️"


def _icon(passed: bool, blocking: bool) -> str:
    if passed:
        return _PASS
    return _FAIL if blocking else _WARN


def _claude_instructions(report: AggregatedReport) -> str:
    if report.gate_passed and not report.warning_failures:
        return ""

    lines = [
        "---",
        "## Instructions for Claude",
        "",
        "The following issues were detected. Fix them before the gate passes.",
        "",
    ]

    for check in report.blocking_failures + report.warning_failures:
        priority = "**[BLOCKING]**" if check.blocking else "_[Non-blocking]_"
        lines.append(f"- {priority} **{check.name}**: {check.value} (threshold: {check.threshold})")

    if report.complexity and report.complexity.violations:
        lines += [
            "",
            "### Complexity violations to fix:",
        ]
        for v in report.complexity.violations:
            lines.append(f"- `{v.file}` → `{v.name}` (line {v.lineno}): complexity {v.complexity} — refactor into smaller functions.")

    if report.sarif and report.sarif.findings:
        lines += [
            "",
            "### Security findings to fix:",
        ]
        for finding in report.sarif.findings[:20]:
            lines.append(f"- `{finding.file}:{finding.line}` [{finding.tool}] `{finding.rule_id}`: {finding.message}")

    if report.cycles and report.cycles.cycles_found:
        lines += [
            "",
            "### Dependency cycle details:",
            f"```\n{report.cycles.details}\n```",
        ]

    return "\n".join(lines)


def write(report: AggregatedReport) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    gate_icon = _PASS if report.gate_passed else _FAIL
    lines = [
        f"# {gate_icon} Quality Gate Report",
        "",
        "## Summary",
        "",
        "| Check | Status | Value | Threshold |",
        "| --- | --- | --- | --- |",
    ]

    for check in report.checks:
        icon = _icon(check.passed, check.blocking)
        label = "" if check.blocking else " _(non-blocking)_"
        lines.append(f"| {check.name}{label} | {icon} | {check.value} | {check.threshold} |")

    if report.coverage:
        lines += [
            "",
            "## Coverage Detail",
            "",
            f"- Line coverage: **{report.coverage.line_rate:.1f}%**",
            f"- Branch coverage: **{report.coverage.branch_rate:.1f}%**",
            f"- Lines covered: {report.coverage.covered_lines} / {report.coverage.total_lines}",
        ]

    if report.complexity and report.complexity.violations:
        lines += [
            "",
            "## Complexity Violations",
            "",
            "| File | Function | Line | Complexity |",
            "| --- | --- | --- | --- |",
        ]
        for v in report.complexity.violations:
            lines.append(f"| `{v.file}` | `{v.name}` | {v.lineno} | {v.complexity} |")

    if report.sarif and report.sarif.findings:
        lines += [
            "",
            "## Security Findings",
            "",
            "| Tool | Rule | File | Line | Severity | Message |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for f in report.sarif.findings:
            lines.append(f"| {f.tool} | `{f.rule_id}` | `{f.file}` | {f.line} | {f.severity} | {f.message[:80]} |")

    if report.mutation:
        lines += [
            "",
            "## Mutation Testing",
            "",
            f"- Score: **{report.mutation.score:.1f}%**",
            f"- Killed: {report.mutation.killed} / {report.mutation.total}",
            f"- Survived: {report.mutation.survived}",
        ]

    lines.append(_claude_instructions(report))

    with open(summary_path, "w") as f:
        f.write("\n".join(lines))
