"""Writes the full GitHub Job Summary (GITHUB_STEP_SUMMARY) including Claude fix instructions."""
import os

from src.aggregator import AggregatedReport

_RATING_EMOJI = {"A": "🟢", "B": "🟡", "C": "🟠", "D": "🔴", "E": "🔴"}


def _icon(passed: bool, blocking: bool) -> str:
    if passed:
        return "✅"
    return "❌" if blocking else "⚠️"


def _ratings_section(report: AggregatedReport) -> list[str]:
    if not report.ratings:
        return []
    r = report.ratings
    lines = [
        "",
        "## Quality Ratings",
        "",
        "| Dimension | Rating | Meaning |",
        "| --- | --- | --- |",
    ]
    descriptions = {
        "A": "No issues detected",
        "B": "Minor issues",
        "C": "Moderate issues",
        "D": "Serious issues",
        "E": "Critical issues",
    }
    for label, value in [
        ("Reliability", r.reliability),
        ("Security", r.security),
        ("Maintainability", r.maintainability),
    ]:
        emoji = _RATING_EMOJI.get(value, "")
        lines.append(f"| {label} | {emoji} **{value}** | {descriptions.get(value, '')} |")
    return lines


def _debt_section(report: AggregatedReport) -> list[str]:
    if not report.debt:
        return []
    d = report.debt
    bd = d.breakdown
    lines = [
        "",
        "## Technical Debt",
        "",
        f"**Total:** {d.formatted_total()} (ratio {d.formatted_ratio()} of estimated development cost)",
        "",
        "| Category | Debt |",
        "| --- | --- |",
        f"| Bugs | {bd.bugs_minutes}min |",
        f"| Vulnerabilities | {bd.vulnerabilities_minutes}min |",
        f"| Code Smells | {bd.code_smells_minutes}min |",
        f"| Complexity Violations | {bd.complexity_minutes}min |",
        f"| Duplication | {bd.duplication_minutes}min |",
        f"| Oversized Files | {bd.size_minutes}min |",
        f"| **Total** | **{d.formatted_total()}** |",
    ]
    return lines


def _coverage_section(report: AggregatedReport) -> list[str]:
    if not report.coverage:
        return []
    c = report.coverage
    return [
        "",
        "## Coverage",
        "",
        f"- Line coverage: **{c.line_rate:.1f}%**",
        f"- Branch coverage: **{c.branch_rate:.1f}%**",
        f"- Lines covered: {c.covered_lines} / {c.total_lines}",
    ]


def _static_section(report: AggregatedReport) -> list[str]:
    if not report.static or not report.static.findings:
        return []
    lines = ["", "## Static Analysis Findings", ""]

    bugs = report.static.bugs
    if bugs:
        lines += ["### Bugs", "", "| File | Line | Rule | Message |", "| --- | --- | --- | --- |"]
        for f in bugs[:20]:
            new_tag = " 🆕" if f.is_new_code else ""
            lines.append(f"| `{f.file}` | {f.line} | `{f.rule}` | {f.message[:80]}{new_tag} |")

    vulns = report.static.vulnerabilities
    if vulns:
        lines += ["", "### Vulnerabilities", "", "| File | Line | Rule | Message |", "| --- | --- | --- | --- |"]
        for f in vulns[:20]:
            new_tag = " 🆕" if f.is_new_code else ""
            lines.append(f"| `{f.file}` | {f.line} | `{f.rule}` | {f.message[:80]}{new_tag} |")

    smells = report.static.code_smells
    if smells:
        lines += [
            "",
            f"### Code Smells ({len(smells)} total — showing first 20)",
            "",
            "| File | Line | Rule | Message |",
            "| --- | --- | --- | --- |",
        ]
        for f in smells[:20]:
            new_tag = " 🆕" if f.is_new_code else ""
            lines.append(f"| `{f.file}` | {f.line} | `{f.rule}` | {f.message[:80]}{new_tag} |")

    return lines


def _complexity_section(report: AggregatedReport) -> list[str]:
    if not report.complexity:
        return []
    c = report.complexity
    if not c.cyclomatic_violations and not c.cognitive_violations:
        return []
    lines = [
        "",
        "## Complexity Violations",
        "",
        "| File | Function | Line | Cyclomatic | Cognitive |",
        "| --- | --- | --- | --- | --- |",
    ]
    violating = {
        (f.file, f.name, f.lineno)
        for f in c.cyclomatic_violations + c.cognitive_violations
    }
    for fn in c.all_functions:
        if (fn.file, fn.name, fn.lineno) in violating:
            cyc = f"**{fn.cyclomatic}** ❌" if fn.cyclomatic > c.cyclomatic_max else str(fn.cyclomatic)
            cog = f"**{fn.cognitive}** ❌" if fn.cognitive > c.cognitive_max else str(fn.cognitive)
            lines.append(f"| `{fn.file}` | `{fn.name}` | {fn.lineno} | {cyc} | {cog} |")
    return lines


def _duplication_section(report: AggregatedReport) -> list[str]:
    if not report.duplication or not report.duplication.blocks:
        return []
    d = report.duplication
    lines = [
        "",
        f"## Code Duplication — {d.percentage:.1f}%",
        "",
        "| File A | Line A | File B | Line B | Lines |",
        "| --- | --- | --- | --- | --- |",
    ]
    for block in d.blocks[:15]:
        lines.append(
            f"| `{block.file_a}` | {block.line_a} | `{block.file_b}` | {block.line_b} | {block.line_count} |"
        )
    return lines


def _size_section(report: AggregatedReport) -> list[str]:
    if not report.raw_metrics or not report.raw_metrics.large_files:
        return []
    rm = report.raw_metrics
    lines = [
        "",
        f"## Oversized Files (> {rm.max_file_sloc} SLOC)",
        "",
        "| File | SLOC | LOC |",
        "| --- | --- | --- |",
    ]
    for f in rm.large_files:
        lines.append(f"| `{f.path}` | **{f.sloc}** | {f.loc} |")
    return lines


def _differential_section(report: AggregatedReport) -> list[str]:
    if not report.is_pr_context or not report.static:
        return []
    new = report.static.new_code_findings
    existing = [f for f in report.static.findings if not f.is_new_code]
    lines = [
        "",
        "## Differential: New Code vs Existing Code",
        "",
        "| | New Code | Existing Code |",
        "| --- | --- | --- |",
        f"| Bugs | {sum(1 for f in new if f.category == 'bug')} | {sum(1 for f in existing if f.category == 'bug')} |",
        f"| Vulnerabilities | {sum(1 for f in new if f.category == 'vulnerability')} | {sum(1 for f in existing if f.category == 'vulnerability')} |",
        f"| Code Smells | {sum(1 for f in new if f.category == 'code_smell')} | {sum(1 for f in existing if f.category == 'code_smell')} |",
    ]
    return lines


def _claude_instructions(report: AggregatedReport) -> list[str]:
    if report.gate_passed and not report.warning_failures:
        return []
    lines = [
        "",
        "---",
        "## Instructions for Claude",
        "",
        "The following issues must be resolved before the Quality Gate passes.",
        "",
    ]
    for check in report.blocking_failures + report.warning_failures:
        priority = "**[BLOCKING]**" if check.blocking else "_[Non-blocking]_"
        lines.append(f"- {priority} **{check.name}**: {check.value} (threshold: {check.threshold})")

    if report.complexity and (report.complexity.cyclomatic_violations or report.complexity.cognitive_violations):
        lines += ["", "### Functions to refactor (split into smaller, focused functions):"]
        seen = set()
        for fn in report.complexity.cyclomatic_violations + report.complexity.cognitive_violations:
            key = (fn.file, fn.name, fn.lineno)
            if key not in seen:
                seen.add(key)
                lines.append(f"- `{fn.file}:{fn.lineno}` → `{fn.name}()` (cyclomatic={fn.cyclomatic}, cognitive={fn.cognitive})")

    if report.static and report.static.bugs:
        lines += ["", "### Bugs to fix:"]
        for f in report.static.bugs[:10]:
            lines.append(f"- `{f.file}:{f.line}` [`{f.rule}`] {f.message}")

    if report.static and report.static.vulnerabilities:
        lines += ["", "### Vulnerabilities to fix:"]
        for f in report.static.vulnerabilities[:10]:
            lines.append(f"- `{f.file}:{f.line}` [`{f.rule}`] {f.message}")

    if report.duplication and report.duplication.blocks:
        lines += ["", "### Duplicate code blocks to consolidate:"]
        for block in report.duplication.blocks[:5]:
            lines.append(f"- `{block.file_a}:{block.line_a}` duplicates `{block.file_b}:{block.line_b}` ({block.line_count} lines)")

    if report.sarif and report.sarif.findings:
        lines += ["", "### Security findings (SARIF):"]
        for finding in report.sarif.findings[:10]:
            lines.append(f"- `{finding.file}:{finding.line}` [{finding.tool}] `{finding.rule_id}`: {finding.message}")

    return lines


def write(report: AggregatedReport) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    gate_icon = "✅" if report.gate_passed else "❌"
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

    lines += _ratings_section(report)
    lines += _debt_section(report)
    lines += _coverage_section(report)
    lines += _complexity_section(report)
    lines += _static_section(report)
    lines += _duplication_section(report)
    lines += _size_section(report)
    lines += _differential_section(report)
    lines += _claude_instructions(report)

    if report.mutation:
        lines += [
            "",
            "## Mutation Testing",
            "",
            f"- Score: **{report.mutation.score:.1f}%**",
            f"- Killed: {report.mutation.killed} / {report.mutation.total}",
            f"- Survived: {report.mutation.survived}",
        ]

    try:
        with open(summary_path, "w") as f:
            f.write("\n".join(lines))
    except OSError:
        logger.warning(
            "Could not write job summary to %s — mount the runner temp dir in Docker "
            "(-v $(dirname \"$GITHUB_STEP_SUMMARY\"):$(dirname \"$GITHUB_STEP_SUMMARY\"))",
            summary_path,
        )
