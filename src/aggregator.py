"""Combines all analysis results and applies threshold checks."""
from dataclasses import dataclass, field
from typing import Optional

from src.analyzers.coverage import CoverageResult
from src.analyzers.complexity import ComplexityResult
from src.analyzers.cycles import CyclesResult
from src.analyzers.sarif import SarifResult
from src.analyzers.mutation import MutationResult
from src.config import QualityGateConfig


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
    complexity: Optional[ComplexityResult]
    cycles: Optional[CyclesResult]
    sarif: Optional[SarifResult]
    mutation: Optional[MutationResult]

    @property
    def gate_passed(self) -> bool:
        return all(c.passed for c in self.checks if c.blocking)

    @property
    def blocking_failures(self) -> list[GateCheck]:
        return [c for c in self.checks if c.blocking and not c.passed]

    @property
    def warning_failures(self) -> list[GateCheck]:
        return [c for c in self.checks if not c.blocking and not c.passed]


def aggregate(
    config: QualityGateConfig,
    coverage: Optional[CoverageResult],
    complexity: Optional[ComplexityResult],
    cycles: Optional[CyclesResult],
    sarif: Optional[SarifResult],
    mutation: Optional[MutationResult],
) -> AggregatedReport:
    checks: list[GateCheck] = []

    if coverage is not None:
        passed = coverage.line_rate >= config.coverage.threshold
        checks.append(
            GateCheck(
                name="Coverage",
                passed=passed,
                blocking=config.coverage.blocking,
                value=f"{coverage.line_rate:.1f}%",
                threshold=f">= {config.coverage.threshold:.0f}%",
            )
        )

    if complexity is not None:
        passed = len(complexity.violations) == 0
        checks.append(
            GateCheck(
                name="Cognitive Complexity",
                passed=passed,
                blocking=config.complexity_blocking,
                value=f"{len(complexity.violations)} violation(s), max={complexity.max_found}",
                threshold=f"max per function <= {config.complexity_max}",
            )
        )

    if cycles is not None:
        checks.append(
            GateCheck(
                name="Dependency Cycles",
                passed=not cycles.cycles_found,
                blocking=config.cycles_blocking,
                value="cycles detected" if cycles.cycles_found else "clean",
                threshold="no cycles",
            )
        )

    if sarif is not None:
        passed = sarif.error_count == 0
        checks.append(
            GateCheck(
                name="Security (SARIF)",
                passed=passed,
                blocking=config.sarif_blocking,
                value=sarif.summary(),
                threshold="0 errors",
            )
        )

    if mutation is not None and config.mutation_threshold is not None:
        passed = mutation.score >= config.mutation_threshold
        checks.append(
            GateCheck(
                name="Mutation Score",
                passed=passed,
                blocking=config.mutation_blocking,
                value=f"{mutation.score:.1f}%",
                threshold=f">= {config.mutation_threshold:.0f}%",
            )
        )

    return AggregatedReport(
        checks=checks,
        coverage=coverage,
        complexity=complexity,
        cycles=cycles,
        sarif=sarif,
        mutation=mutation,
    )
