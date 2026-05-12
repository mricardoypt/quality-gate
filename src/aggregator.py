"""Combines all analysis results, applies threshold checks, and produces the final report."""
from dataclasses import dataclass, field
from typing import Optional

from src.analyzers.complexity import ComplexFunction, ComplexityResult
from src.analyzers.coverage import CoverageResult
from src.analyzers.cycles import CyclesResult
from src.analyzers.duplication import DuplicateBlock, DuplicationResult
from src.analyzers.mutation import MutationResult
from src.analyzers.raw_metrics import FileMetrics, RawMetricsResult
from src.analyzers.sarif import SarifFinding, SarifResult
from src.analyzers.static_analysis import StaticFinding, StaticAnalysisResult
from src.config import QualityGateConfig
from src.debt import TechnicalDebt, calculate as calculate_debt
from src.diff import to_relative
from src.ratings import Ratings, compute as compute_ratings

_RATING_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}


@dataclass
class DiffSummary:
    bugs: list[StaticFinding]
    vulnerabilities: list[StaticFinding]
    code_smells: list[StaticFinding]
    complexity_violations: list[ComplexFunction]
    security_findings: list[SarifFinding]
    large_files: list[FileMetrics]
    duplication_blocks: list[DuplicateBlock]
    diff_line_rate: Optional[float]
    diff_branch_rate: Optional[float]
    diff_covered_lines: int
    diff_total_lines: int

    @property
    def new_bugs(self) -> int:
        return len(self.bugs)

    @property
    def new_vulnerabilities(self) -> int:
        return len(self.vulnerabilities)

    @property
    def new_code_smells(self) -> int:
        return len(self.code_smells)

    @property
    def new_complexity_violations(self) -> int:
        return len(self.complexity_violations)

    @property
    def new_security_findings(self) -> int:
        return len(self.security_findings)

    @property
    def new_large_files(self) -> int:
        return len(self.large_files)

    @property
    def new_duplication_blocks(self) -> int:
        return len(self.duplication_blocks)


@dataclass
class GateCheck:
    name: str
    passed: bool
    blocking: bool
    value: str
    threshold: str


@dataclass
class AggregatedReport:
    checks: list[GateCheck]
    coverage: Optional[CoverageResult]
    static: Optional[StaticAnalysisResult]
    complexity: Optional[ComplexityResult]
    cycles: Optional[CyclesResult]
    duplication: Optional[DuplicationResult]
    raw_metrics: Optional[RawMetricsResult]
    sarif: Optional[SarifResult]
    mutation: Optional[MutationResult]
    debt: Optional[TechnicalDebt]
    ratings: Optional[Ratings]
    new_code_lines: Optional[dict[str, set[int]]] = field(default=None)
    diff_summary: Optional[DiffSummary] = field(default=None)

    @property
    def gate_passed(self) -> bool:
        return all(c.passed for c in self.checks if c.blocking)

    @property
    def blocking_failures(self) -> list[GateCheck]:
        return [c for c in self.checks if c.blocking and not c.passed]

    @property
    def warning_failures(self) -> list[GateCheck]:
        return [c for c in self.checks if not c.blocking and not c.passed]

    @property
    def is_pr_context(self) -> bool:
        return self.new_code_lines is not None


def _line_in_diff(new_code_lines: dict[str, set[int]], abs_path: str, line: int) -> bool:
    return line in new_code_lines.get(to_relative(abs_path), set())


def _file_in_diff(new_code_lines: dict[str, set[int]], path: str) -> bool:
    return to_relative(path) in new_code_lines


def _filter_static_in_diff(
    static: Optional[StaticAnalysisResult], new_code_lines: dict[str, set[int]]
) -> tuple[list[StaticFinding], list[StaticFinding], list[StaticFinding]]:
    bugs: list[StaticFinding] = []
    vulns: list[StaticFinding] = []
    smells: list[StaticFinding] = []
    if not static:
        return bugs, vulns, smells
    for f in static.findings:
        if not _line_in_diff(new_code_lines, f.file, f.line):
            continue
        if f.category == "bug":
            bugs.append(f)
        elif f.category == "vulnerability":
            vulns.append(f)
        else:
            smells.append(f)
    return bugs, vulns, smells


def _filter_complexity_in_diff(
    complexity: Optional[ComplexityResult], new_code_lines: dict[str, set[int]]
) -> list[ComplexFunction]:
    if not complexity:
        return []
    seen: set[tuple] = set()
    result: list[ComplexFunction] = []
    for fn in complexity.cyclomatic_violations + complexity.cognitive_violations:
        key = (fn.file, fn.name, fn.lineno)
        if key not in seen and _line_in_diff(new_code_lines, fn.file, fn.lineno):
            seen.add(key)
            result.append(fn)
    return result


def _filter_security_in_diff(
    sarif: Optional[SarifResult], new_code_lines: dict[str, set[int]]
) -> list[SarifFinding]:
    if not sarif:
        return []
    return [
        f for f in sarif.findings
        if (f.line and _line_in_diff(new_code_lines, f.file, f.line))
        or (not f.line and _file_in_diff(new_code_lines, f.file))
    ]


def _filter_large_files_in_diff(
    raw_metrics: Optional[RawMetricsResult], new_code_lines: dict[str, set[int]]
) -> list[FileMetrics]:
    if not raw_metrics:
        return []
    return [f for f in raw_metrics.large_files if _file_in_diff(new_code_lines, f.path)]


def _filter_duplication_in_diff(
    duplication: Optional[DuplicationResult], new_code_lines: dict[str, set[int]]
) -> list[DuplicateBlock]:
    # DuplicateBlock paths are already relative
    if not duplication:
        return []
    return [
        b for b in duplication.blocks
        if b.file_a in new_code_lines or b.file_b in new_code_lines
    ]


def _aggregate_diff_coverage(
    coverage: Optional[CoverageResult], new_code_lines: dict[str, set[int]]
) -> tuple[Optional[float], Optional[float], int, int]:
    if not coverage or not coverage.per_file:
        return None, None, 0, 0
    matched = [f for f in coverage.per_file if f.path in new_code_lines]
    if not matched:
        return None, None, 0, 0
    total = sum(f.total_lines for f in matched)
    covered = sum(f.covered_lines for f in matched)
    if total == 0:
        return None, None, 0, 0
    # Weighted average of branch rates
    branch_covered = sum(f.branch_rate * f.total_lines for f in matched)
    return (covered / total) * 100, branch_covered / total, covered, total


def _compute_diff_summary(
    new_code_lines: dict[str, set[int]],
    coverage: Optional[CoverageResult],
    static: Optional[StaticAnalysisResult],
    complexity: Optional[ComplexityResult],
    sarif: Optional[SarifResult],
    raw_metrics: Optional[RawMetricsResult],
    duplication: Optional[DuplicationResult],
) -> DiffSummary:
    bugs, vulns, smells = _filter_static_in_diff(static, new_code_lines)
    line_rate, branch_rate, covered, total = _aggregate_diff_coverage(coverage, new_code_lines)
    return DiffSummary(
        bugs=bugs,
        vulnerabilities=vulns,
        code_smells=smells,
        complexity_violations=_filter_complexity_in_diff(complexity, new_code_lines),
        security_findings=_filter_security_in_diff(sarif, new_code_lines),
        large_files=_filter_large_files_in_diff(raw_metrics, new_code_lines),
        duplication_blocks=_filter_duplication_in_diff(duplication, new_code_lines),
        diff_line_rate=line_rate,
        diff_branch_rate=branch_rate,
        diff_covered_lines=covered,
        diff_total_lines=total,
    )


def _rating_passes(actual: str, minimum: str) -> bool:
    return _RATING_ORDER.get(actual, 4) <= _RATING_ORDER.get(minimum, 4)


def aggregate(
    config: QualityGateConfig,
    coverage: Optional[CoverageResult],
    static: Optional[StaticAnalysisResult],
    complexity: Optional[ComplexityResult],
    cycles: Optional[CyclesResult],
    duplication: Optional[DuplicationResult],
    raw_metrics: Optional[RawMetricsResult],
    sarif: Optional[SarifResult],
    mutation: Optional[MutationResult],
    new_code_lines: Optional[dict[str, set[int]]] = None,
) -> AggregatedReport:
    checks: list[GateCheck] = []

    if coverage is not None:
        checks.append(GateCheck(
            name="Coverage",
            passed=coverage.line_rate >= config.coverage.threshold,
            blocking=config.coverage.blocking,
            value=f"{coverage.line_rate:.1f}% lines / {coverage.branch_rate:.1f}% branches",
            threshold=f">= {config.coverage.threshold:.0f}%",
        ))

    if static is not None:
        checks.append(GateCheck(
            name="Bugs",
            passed=len(static.bugs) == 0,
            blocking=True,
            value=str(len(static.bugs)),
            threshold="0",
        ))
        checks.append(GateCheck(
            name="Vulnerabilities",
            passed=len(static.vulnerabilities) == 0,
            blocking=True,
            value=str(len(static.vulnerabilities)),
            threshold="0",
        ))
        checks.append(GateCheck(
            name="Code Smells",
            passed=True,  # informational by default — gate via ratings instead
            blocking=False,
            value=str(len(static.code_smells)),
            threshold="—",
        ))

    if static is not None and new_code_lines is not None:
        new_findings = static.new_code_findings
        new_bugs = [f for f in new_findings if f.category == "bug"]
        new_vulns = [f for f in new_findings if f.category == "vulnerability"]
        checks.append(GateCheck(
            name="New Code: Bugs",
            passed=len(new_bugs) == 0,
            blocking=True,
            value=str(len(new_bugs)),
            threshold="0",
        ))
        checks.append(GateCheck(
            name="New Code: Vulnerabilities",
            passed=len(new_vulns) == 0,
            blocking=True,
            value=str(len(new_vulns)),
            threshold="0",
        ))

    if complexity is not None:
        cyc_ok = len(complexity.cyclomatic_violations) == 0
        cog_ok = len(complexity.cognitive_violations) == 0
        checks.append(GateCheck(
            name="Cyclomatic Complexity",
            passed=cyc_ok,
            blocking=config.complexity_blocking,
            value=f"{len(complexity.cyclomatic_violations)} violation(s), max={complexity.max_cyclomatic_found}",
            threshold=f"max <= {config.cyclomatic_max}",
        ))
        checks.append(GateCheck(
            name="Cognitive Complexity",
            passed=cog_ok,
            blocking=config.complexity_blocking,
            value=f"{len(complexity.cognitive_violations)} violation(s), max={complexity.max_cognitive_found}",
            threshold=f"max <= {config.cognitive_max}",
        ))

    if duplication is not None:
        checks.append(GateCheck(
            name="Duplication",
            passed=duplication.percentage <= config.duplication_threshold,
            blocking=config.duplication_blocking,
            value=f"{duplication.percentage:.1f}% ({len(duplication.blocks)} block(s))",
            threshold=f"<= {config.duplication_threshold:.0f}%",
        ))

    if raw_metrics is not None:
        checks.append(GateCheck(
            name="File Size",
            passed=len(raw_metrics.large_files) == 0,
            blocking=config.size_blocking,
            value=f"{len(raw_metrics.large_files)} large file(s) > {config.max_file_sloc} SLOC",
            threshold=f"<= {config.max_file_sloc} SLOC",
        ))

    if cycles is not None:
        checks.append(GateCheck(
            name="Dependency Cycles",
            passed=not cycles.cycles_found,
            blocking=config.cycles_blocking,
            value="cycles detected" if cycles.cycles_found else "clean",
            threshold="no cycles",
        ))

    if sarif is not None:
        checks.append(GateCheck(
            name="Security (SARIF)",
            passed=sarif.error_count == 0,
            blocking=config.sarif_blocking,
            value=sarif.summary(),
            threshold="0 errors",
        ))

    debt = calculate_debt(static, complexity, duplication, raw_metrics)

    ratings: Optional[Ratings] = None
    if static is not None:
        ratings = compute_ratings(static, debt)
        checks.append(GateCheck(
            name="Reliability Rating",
            passed=_rating_passes(ratings.reliability, config.min_reliability_rating),
            blocking=config.ratings_blocking,
            value=ratings.reliability,
            threshold=f">= {config.min_reliability_rating}",
        ))
        checks.append(GateCheck(
            name="Security Rating",
            passed=_rating_passes(ratings.security, config.min_security_rating),
            blocking=config.ratings_blocking,
            value=ratings.security,
            threshold=f">= {config.min_security_rating}",
        ))
        checks.append(GateCheck(
            name="Maintainability Rating",
            passed=_rating_passes(ratings.maintainability, config.min_maintainability_rating),
            blocking=config.ratings_blocking,
            value=f"{ratings.maintainability} (debt {debt.formatted_total()}, ratio {debt.formatted_ratio()})",
            threshold=f">= {config.min_maintainability_rating}",
        ))

    if mutation is not None and config.mutation_threshold is not None:
        checks.append(GateCheck(
            name="Mutation Score",
            passed=mutation.score >= config.mutation_threshold,
            blocking=config.mutation_blocking,
            value=f"{mutation.score:.1f}%",
            threshold=f">= {config.mutation_threshold:.0f}%",
        ))

    diff_summary = (
        _compute_diff_summary(new_code_lines, coverage, static, complexity, sarif, raw_metrics, duplication)
        if new_code_lines is not None
        else None
    )

    return AggregatedReport(
        checks=checks,
        coverage=coverage,
        static=static,
        complexity=complexity,
        cycles=cycles,
        duplication=duplication,
        raw_metrics=raw_metrics,
        sarif=sarif,
        mutation=mutation,
        debt=debt,
        ratings=ratings,
        new_code_lines=new_code_lines,
        diff_summary=diff_summary,
    )
