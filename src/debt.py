"""
Estimates technical debt following the SQALE model used by SonarQube.

Remediation cost per issue type (in minutes):
  - Bug: 30 min
  - Vulnerability: 60 min
  - Code smell: 5 min
  - Cyclomatic complexity violation: 30 min per function
  - Cognitive complexity violation: 30 min per function
  - Duplication block: 15 min per block
  - Large file: 60 min per file

Development cost baseline: 30 min per SLOC (0.5h/SLOC is a conservative industry estimate).
Debt ratio = total_remediation_minutes / development_cost_minutes.
"""
from dataclasses import dataclass, field
from typing import Optional

from src.analyzers.complexity import ComplexityResult
from src.analyzers.duplication import DuplicationResult
from src.analyzers.raw_metrics import RawMetricsResult
from src.analyzers.static_analysis import StaticAnalysisResult

_REMEDIATION_MINUTES: dict[str, int] = {
    "bug": 30,
    "vulnerability": 60,
    "code_smell": 5,
    "complexity_violation": 30,
    "duplication_block": 15,
    "large_file": 60,
}

_DEV_MINUTES_PER_SLOC = 30


@dataclass
class DebtBreakdown:
    bugs_minutes: int = 0
    vulnerabilities_minutes: int = 0
    code_smells_minutes: int = 0
    complexity_minutes: int = 0
    duplication_minutes: int = 0
    size_minutes: int = 0

    @property
    def total_minutes(self) -> int:
        return (
            self.bugs_minutes
            + self.vulnerabilities_minutes
            + self.code_smells_minutes
            + self.complexity_minutes
            + self.duplication_minutes
            + self.size_minutes
        )


@dataclass
class TechnicalDebt:
    breakdown: DebtBreakdown
    total_sloc: int
    ratio: float  # 0.0–1.0+

    def formatted_total(self) -> str:
        minutes = self.breakdown.total_minutes
        if minutes < 60:
            return f"{minutes}min"
        hours = minutes // 60
        remaining = minutes % 60
        if hours < 8:
            return f"{hours}h {remaining}min" if remaining else f"{hours}h"
        days = hours // 8
        remaining_hours = hours % 8
        return f"{days}d {remaining_hours}h" if remaining_hours else f"{days}d"

    def formatted_ratio(self) -> str:
        return f"{self.ratio * 100:.1f}%"


def calculate(
    static: Optional[StaticAnalysisResult],
    complexity: Optional[ComplexityResult],
    duplication: Optional[DuplicationResult],
    raw_metrics: Optional[RawMetricsResult],
) -> TechnicalDebt:
    bd = DebtBreakdown()

    if static:
        bd.bugs_minutes = len(static.bugs) * _REMEDIATION_MINUTES["bug"]
        bd.vulnerabilities_minutes = len(static.vulnerabilities) * _REMEDIATION_MINUTES["vulnerability"]
        bd.code_smells_minutes = len(static.code_smells) * _REMEDIATION_MINUTES["code_smell"]

    if complexity:
        # Deduplicate: a function violating both cyclomatic and cognitive counts once
        violating = {
            (f.file, f.name, f.lineno)
            for f in complexity.cyclomatic_violations + complexity.cognitive_violations
        }
        bd.complexity_minutes = len(violating) * _REMEDIATION_MINUTES["complexity_violation"]

    if duplication:
        bd.duplication_minutes = len(duplication.blocks) * _REMEDIATION_MINUTES["duplication_block"]

    if raw_metrics:
        bd.size_minutes = len(raw_metrics.large_files) * _REMEDIATION_MINUTES["large_file"]

    total_sloc = raw_metrics.total_sloc if raw_metrics else 0
    dev_cost = max(total_sloc * _DEV_MINUTES_PER_SLOC, 1)
    ratio = bd.total_minutes / dev_cost

    return TechnicalDebt(breakdown=bd, total_sloc=total_sloc, ratio=ratio)
