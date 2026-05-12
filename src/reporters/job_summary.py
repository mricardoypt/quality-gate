"""Writes the full GitHub Job Summary (GITHUB_STEP_SUMMARY) including Claude fix instructions."""
import logging
import os

from src.aggregator import AggregatedReport

logger = logging.getLogger(__name__)

_RATING_EMOJI = {"A": "🟢", "B": "🟡", "C": "🟠", "D": "🔴", "E": "🔴"}

_HDR_FILE_LINE_RULE_MSG = "| File | Line | Rule | Message |"
_SEP_4 = "| --- | --- | --- | --- |"
_HDR_FILE_LINE_RULE_MSG_WITH_SEP = [_HDR_FILE_LINE_RULE_MSG, _SEP_4]

_HDR_COMPLEXITY = "| File | Function | Line | Cyclomatic | Cognitive |"
_SEP_5 = "| --- | --- | --- | --- | --- |"

_HDR_DUP = "| File A | Line A | File B | Line B | Lines |"

_SEP_3 = "| --- | --- | --- |"


def _icon(passed: bool, blocking: bool) -> str:
    if passed:
        return "✅"
    return "❌" if blocking else "⚠️"


# ---------------------------------------------------------------------------
# PR-context sections (diff-scoped)
# ---------------------------------------------------------------------------

def _diff_coverage_section(report: AggregatedReport) -> list[str]:
    if not report.diff_summary:
        return []
    d = report.diff_summary
    if d.diff_line_rate is None:
        return []
    branch_str = f" / **{d.diff_branch_rate:.1f}%** branches" if d.diff_branch_rate is not None else ""
    return [
        "",
        "## Coverage (diff files)",
        "",
        f"- Line coverage: **{d.diff_line_rate:.1f}%**{branch_str}",
        f"- Lines covered: {d.diff_covered_lines} / {d.diff_total_lines}",
    ]


def _finding_rows(findings: list, limit: int = 20) -> list[str]:
    return [
        f"| `{f.file}` | {f.line} | `{f.rule}` | {f.message[:80]} |"
        for f in findings[:limit]
    ]


def _diff_findings_section(report: AggregatedReport) -> list[str]:
    if not report.diff_summary:
        return []
    d = report.diff_summary
    if not d.bugs and not d.vulnerabilities and not d.code_smells:
        return ["", "## Static Analysis (diff files)", "", "> No bugs, vulnerabilities, or code smells in the changed files."]

    lines: list[str] = ["", "## Static Analysis (diff files)", ""]

    if d.bugs:
        lines += ["### Bugs", ""] + _HDR_FILE_LINE_RULE_MSG_WITH_SEP + _finding_rows(d.bugs)

    if d.vulnerabilities:
        lines += ["", "### Vulnerabilities", ""] + _HDR_FILE_LINE_RULE_MSG_WITH_SEP + _finding_rows(d.vulnerabilities)

    if d.code_smells:
        lines += [
            "",
            f"### Code Smells ({len(d.code_smells)} total — showing first 20)",
            "",
        ] + _HDR_FILE_LINE_RULE_MSG_WITH_SEP + _finding_rows(d.code_smells)

    return lines


def _diff_complexity_section(report: AggregatedReport) -> list[str]:
    if not report.diff_summary or not report.diff_summary.complexity_violations:
        return []
    d = report.diff_summary
    c = report.complexity
    lines = ["", "## Complexity Violations (diff files)", "", _HDR_COMPLEXITY, _SEP_5]
    for fn in d.complexity_violations:
        cyc = f"**{fn.cyclomatic}** ❌" if c and fn.cyclomatic > c.cyclomatic_max else str(fn.cyclomatic)
        cog = f"**{fn.cognitive}** ❌" if c and fn.cognitive > c.cognitive_max else str(fn.cognitive)
        lines.append(f"| `{fn.file}` | `{fn.name}` | {fn.lineno} | {cyc} | {cog} |")
    return lines


def _diff_security_section(report: AggregatedReport) -> list[str]:
    if not report.diff_summary or not report.diff_summary.security_findings:
        return []
    d = report.diff_summary
    lines = [
        "",
        "## Security Findings (diff files)",
        "",
        "| File | Line | Tool | Rule | Message |",
        _SEP_5,
    ]
    for f in d.security_findings[:20]:
        lines.append(f"| `{f.file}` | {f.line} | {f.tool} | `{f.rule_id}` | {f.message[:80]} |")
    return lines


def _diff_size_section(report: AggregatedReport) -> list[str]:
    if not report.diff_summary or not report.diff_summary.large_files:
        return []
    d = report.diff_summary
    rm = report.raw_metrics
    sloc_limit = rm.max_file_sloc if rm else "?"
    lines = ["", f"## Oversized Files in PR (> {sloc_limit} SLOC)", "", "| File | SLOC | LOC |", _SEP_3]
    for f in d.large_files:
        lines.append(f"| `{f.path}` | **{f.sloc}** | {f.loc} |")
    return lines


def _diff_duplication_section(report: AggregatedReport) -> list[str]:
    if not report.diff_summary or not report.diff_summary.duplication_blocks:
        return []
    d = report.diff_summary
    lines = ["", "## Code Duplication (diff files)", "", _HDR_DUP, _SEP_5]
    for block in d.duplication_blocks[:15]:
        lines.append(
            f"| `{block.file_a}` | {block.line_a} | `{block.file_b}` | {block.line_b} | {block.line_count} |"
        )
    return lines


def _full_repo_condensed_section(report: AggregatedReport) -> list[str]:
    """Ratings, dependency cycles, and mutation — always full-repo, shown compact in PR context."""
    lines: list[str] = []

    if report.ratings:
        r = report.ratings
        descriptions = {
            "A": "No issues", "B": "Minor issues", "C": "Moderate issues",
            "D": "Serious issues", "E": "Critical issues",
        }
        lines += ["", "## Quality Ratings (full repo)", "", "| Dimension | Rating |", "| --- | --- |"]
        for label, value in [("Reliability", r.reliability), ("Security", r.security), ("Maintainability", r.maintainability)]:
            emoji = _RATING_EMOJI.get(value, "")
            lines.append(f"| {label} | {emoji} **{value}** — {descriptions.get(value, '')} |")

    if report.cycles:
        status = "⚠️ Cycles detected" if report.cycles.cycles_found else "✅ Clean"
        lines += ["", f"**Dependency Cycles (full repo):** {status}"]

    if report.mutation:
        m = report.mutation
        lines += ["", f"**Mutation Score (full repo):** {m.score:.1f}% ({m.killed} killed / {m.total} total)"]

    return lines


# ---------------------------------------------------------------------------
# Full-repo sections (main push)
# ---------------------------------------------------------------------------

def _ratings_section(report: AggregatedReport) -> list[str]:
    if not report.ratings:
        return []
    r = report.ratings
    descriptions = {
        "A": "No issues detected", "B": "Minor issues", "C": "Moderate issues",
        "D": "Serious issues", "E": "Critical issues",
    }
    lines = ["", "## Quality Ratings", "", "| Dimension | Rating | Meaning |", "| --- | --- | --- |"]
    for label, value in [("Reliability", r.reliability), ("Security", r.security), ("Maintainability", r.maintainability)]:
        emoji = _RATING_EMOJI.get(value, "")
        lines.append(f"| {label} | {emoji} **{value}** | {descriptions.get(value, '')} |")
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


def _tagged_finding_rows(findings: list, limit: int = 20) -> list[str]:
    return [
        f"| `{f.file}` | {f.line} | `{f.rule}` | {f.message[:80]}{' 🆕' if f.is_new_code else ''} |"
        for f in findings[:limit]
    ]


def _static_bugs_block(bugs: list) -> list[str]:
    if not bugs:
        return []
    return ["### Bugs", ""] + _HDR_FILE_LINE_RULE_MSG_WITH_SEP + _tagged_finding_rows(bugs)


def _static_vulns_block(vulns: list) -> list[str]:
    if not vulns:
        return []
    return ["", "### Vulnerabilities", ""] + _HDR_FILE_LINE_RULE_MSG_WITH_SEP + _tagged_finding_rows(vulns)


def _static_smells_block(smells: list) -> list[str]:
    if not smells:
        return []
    return [
        "",
        f"### Code Smells ({len(smells)} total — showing first 20)",
        "",
    ] + _HDR_FILE_LINE_RULE_MSG_WITH_SEP + _tagged_finding_rows(smells)


def _static_section(report: AggregatedReport) -> list[str]:
    if not report.static or not report.static.findings:
        return []
    return (
        ["", "## Static Analysis Findings", ""]
        + _static_bugs_block(report.static.bugs)
        + _static_vulns_block(report.static.vulnerabilities)
        + _static_smells_block(report.static.code_smells)
    )


def _complexity_section(report: AggregatedReport) -> list[str]:
    if not report.complexity:
        return []
    c = report.complexity
    if not c.cyclomatic_violations and not c.cognitive_violations:
        return []
    lines = ["", "## Complexity Violations", "", _HDR_COMPLEXITY, _SEP_5]
    violating = {(f.file, f.name, f.lineno) for f in c.cyclomatic_violations + c.cognitive_violations}
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
    lines = ["", f"## Code Duplication — {d.percentage:.1f}%", "", _HDR_DUP, _SEP_5]
    for block in d.blocks[:15]:
        lines.append(
            f"| `{block.file_a}` | {block.line_a} | `{block.file_b}` | {block.line_b} | {block.line_count} |"
        )
    return lines


def _size_section(report: AggregatedReport) -> list[str]:
    if not report.raw_metrics or not report.raw_metrics.large_files:
        return []
    rm = report.raw_metrics
    lines = ["", f"## Oversized Files (> {rm.max_file_sloc} SLOC)", "", "| File | SLOC | LOC |", _SEP_3]
    for f in rm.large_files:
        lines.append(f"| `{f.path}` | **{f.sloc}** | {f.loc} |")
    return lines


def _mutation_section(report: AggregatedReport) -> list[str]:
    if not report.mutation:
        return []
    m = report.mutation
    return [
        "",
        "## Mutation Testing",
        "",
        f"- Score: **{m.score:.1f}%**",
        f"- Killed: {m.killed} / {m.total}",
        f"- Survived: {m.survived}",
    ]


# ---------------------------------------------------------------------------
# Section assemblers
# ---------------------------------------------------------------------------

def _pr_sections(report: AggregatedReport) -> list[str]:
    return (
        _diff_coverage_section(report)
        + _diff_findings_section(report)
        + _diff_complexity_section(report)
        + _diff_security_section(report)
        + _diff_size_section(report)
        + _diff_duplication_section(report)
        + _full_repo_condensed_section(report)
    )


def _full_repo_sections(report: AggregatedReport) -> list[str]:
    return (
        _ratings_section(report)
        + _coverage_section(report)
        + _complexity_section(report)
        + _static_section(report)
        + _duplication_section(report)
        + _size_section(report)
        + _mutation_section(report)
    )


# ---------------------------------------------------------------------------
# Claude instructions — bullet helpers (no loops in callers)
# ---------------------------------------------------------------------------

def _complexity_bullets(violations: list) -> list[str]:
    return [
        f"- `{fn.file}:{fn.lineno}` → `{fn.name}()` (cyclomatic={fn.cyclomatic}, cognitive={fn.cognitive})"
        for fn in violations
    ]


def _static_finding_bullets(findings: list, limit: int = 10) -> list[str]:
    return [f"- `{f.file}:{f.line}` [`{f.rule}`] {f.message}" for f in findings[:limit]]


def _dup_bullets(blocks: list, limit: int = 5) -> list[str]:
    return [
        f"- `{b.file_a}:{b.line_a}` duplicates `{b.file_b}:{b.line_b}` ({b.line_count} lines)"
        for b in blocks[:limit]
    ]


def _security_bullets(findings: list, limit: int = 10) -> list[str]:
    return [
        f"- `{f.file}:{f.line}` [{f.tool}] `{f.rule_id}`: {f.message}"
        for f in findings[:limit]
    ]


def _deduped_complexity_bullets(complexity) -> list[str]:
    seen: set[tuple] = set()
    bullets: list[str] = []
    for fn in complexity.cyclomatic_violations + complexity.cognitive_violations:
        key = (fn.file, fn.name, fn.lineno)
        if key not in seen:
            seen.add(key)
            bullets.append(f"- `{fn.file}:{fn.lineno}` → `{fn.name}()` (cyclomatic={fn.cyclomatic}, cognitive={fn.cognitive})")
    return bullets


# ---------------------------------------------------------------------------
# Claude instructions
# ---------------------------------------------------------------------------

def _pr_claude_detail(report: AggregatedReport) -> list[str]:
    d = report.diff_summary
    if not d:
        return []
    lines: list[str] = []
    if d.complexity_violations:
        lines += ["", "### Functions to refactor (in this PR):"] + _complexity_bullets(d.complexity_violations)
    if d.bugs:
        lines += ["", "### Bugs to fix (in this PR):"] + _static_finding_bullets(d.bugs)
    if d.vulnerabilities:
        lines += ["", "### Vulnerabilities to fix (in this PR):"] + _static_finding_bullets(d.vulnerabilities)
    if d.duplication_blocks:
        lines += ["", "### Duplicate code blocks to consolidate (in this PR):"] + _dup_bullets(d.duplication_blocks)
    if d.security_findings:
        lines += ["", "### Security findings (in this PR):"] + _security_bullets(d.security_findings)
    return lines


def _full_repo_claude_detail(report: AggregatedReport) -> list[str]:
    lines: list[str] = []
    c = report.complexity
    if c and (c.cyclomatic_violations or c.cognitive_violations):
        lines += ["", "### Functions to refactor (split into smaller, focused functions):"] + _deduped_complexity_bullets(c)
    if report.static and report.static.bugs:
        lines += ["", "### Bugs to fix:"] + _static_finding_bullets(report.static.bugs)
    if report.static and report.static.vulnerabilities:
        lines += ["", "### Vulnerabilities to fix:"] + _static_finding_bullets(report.static.vulnerabilities)
    if report.duplication and report.duplication.blocks:
        lines += ["", "### Duplicate code blocks to consolidate:"] + _dup_bullets(report.duplication.blocks)
    if report.sarif and report.sarif.findings:
        lines += ["", "### Security findings (SARIF):"] + _security_bullets(report.sarif.findings)
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

    if report.is_pr_context:
        lines += _pr_claude_detail(report)
    else:
        lines += _full_repo_claude_detail(report)

    return lines


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

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
        _SEP_4,
    ]
    for check in report.checks:
        icon = _icon(check.passed, check.blocking)
        label = "" if check.blocking else " _(non-blocking)_"
        lines.append(f"| {check.name}{label} | {icon} | {check.value} | {check.threshold} |")

    if report.is_pr_context:
        lines += _pr_sections(report)
    else:
        lines += _full_repo_sections(report)

    lines += _claude_instructions(report)

    try:
        with open(summary_path, "w") as f:
            f.write("\n".join(lines))
    except OSError:
        logger.warning(
            "Could not write job summary to %s — mount the runner temp dir in Docker "
            "(-v $(dirname \"$GITHUB_STEP_SUMMARY\"):$(dirname \"$GITHUB_STEP_SUMMARY\"))",
            summary_path,
        )
