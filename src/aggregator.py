"""Combines all analysis results, applies threshold checks, and produces the final report."""
from dataclasses import dataclass, field
from typing import Optional

from src.analyzers.complexity import ComplexityResult
from src.analyzers.coverage import CoverageResult
from src.analyzers.cycles import CyclesResult
from src.analyzers.duplication import DuplicationResult
from src.analyzers.mutation import MutationResult
from src.analyzers.raw_metrics import RawMetricsResult
from src.analyzers.sarif import SarifResult
from src.analyzers.static_analysis import StaticAnalysisResult
from src.config import QualityGateConfig
from src.debt import TechnicalDebt, calculate as calculate_debt
from src.ratings import Ratings, compute as compute_ratings

_RATING_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}


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
    )
