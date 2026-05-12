"""
A–E quality ratings modelled after SonarQube's rating system.

  Reliability  (bugs)          A=0  B=1-2  C=3-5  D=6-10  E=11+
  Security     (vulns)         A=0  B=1    C=2-3  D=4-10  E=11+
  Maintainability (debt ratio) A≤5% B≤10% C≤20%  D≤50%   E>50%
"""
from dataclasses import dataclass

from src.analyzers.static_analysis import StaticAnalysisResult
from src.debt import TechnicalDebt


@dataclass
class Ratings:
    reliability: str   # A–E
    security: str      # A–E
    maintainability: str  # A–E

    def worst(self) -> str:
        order = ["A", "B", "C", "D", "E"]
        return max(
            self.reliability, self.security, self.maintainability,
            key=order.index,
        )


def _reliability(bug_count: int) -> str:
    if bug_count == 0:
        return "A"
    if bug_count <= 2:
        return "B"
    if bug_count <= 5:
        return "C"
    if bug_count <= 10:
        return "D"
    return "E"


def _security(vuln_count: int) -> str:
    if vuln_count == 0:
        return "A"
    if vuln_count == 1:
        return "B"
    if vuln_count <= 3:
        return "C"
    if vuln_count <= 10:
        return "D"
    return "E"


def _maintainability(debt_ratio: float) -> str:
    if debt_ratio <= 0.05:
        return "A"
    if debt_ratio <= 0.10:
        return "B"
    if debt_ratio <= 0.20:
        return "C"
    if debt_ratio <= 0.50:
        return "D"
    return "E"


def compute(static: StaticAnalysisResult, debt: TechnicalDebt) -> Ratings:
    return Ratings(
        reliability=_reliability(len(static.bugs)),
        security=_security(len(static.vulnerabilities)),
        maintainability=_maintainability(debt.ratio),
    )
