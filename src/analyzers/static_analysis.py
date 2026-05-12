"""Runs ruff to detect bugs, vulnerabilities, and code smells."""
import json
import logging
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from src.diff import to_relative

logger = logging.getLogger(__name__)

# Rule prefix → category. Order matters: longer prefixes first to avoid mismatch.
_CATEGORY_MAP: list[tuple[str, str]] = [
    ("F8", "bug"),           # pyflakes: undefined name, unused import hiding a bug
    ("B",  "bug"),           # bugbear: likely bugs and design issues
    ("S",  "vulnerability"), # flake8-bandit: security
    ("F",  "code_smell"),    # remaining pyflakes (unused vars, etc.)
    ("E",  "code_smell"),    # pycodestyle errors
    ("W",  "code_smell"),    # pycodestyle warnings
    ("C",  "code_smell"),    # mccabe + conventions
    ("N",  "code_smell"),    # naming
    ("UP", "code_smell"),    # pyupgrade
    ("RUF","code_smell"),    # ruff-specific
]

_SEVERITY: dict[str, str] = {
    "bug": "error",
    "vulnerability": "error",
    "code_smell": "warning",
}


@dataclass
class StaticFinding:
    file: str
    line: int
    column: int
    rule: str
    message: str
    category: str   # bug | vulnerability | code_smell
    severity: str   # error | warning
    is_new_code: bool = False


@dataclass
class StaticAnalysisResult:
    findings: list[StaticFinding] = field(default_factory=list)

    @property
    def bugs(self) -> list[StaticFinding]:
        return [f for f in self.findings if f.category == "bug"]

    @property
    def vulnerabilities(self) -> list[StaticFinding]:
        return [f for f in self.findings if f.category == "vulnerability"]

    @property
    def code_smells(self) -> list[StaticFinding]:
        return [f for f in self.findings if f.category == "code_smell"]

    @property
    def new_code_findings(self) -> list[StaticFinding]:
        return [f for f in self.findings if f.is_new_code]

    def summary(self) -> str:
        return (
            f"{len(self.bugs)} bug(s), "
            f"{len(self.vulnerabilities)} vulnerability(ies), "
            f"{len(self.code_smells)} code smell(s)"
        )


def _categorize(rule_code: str) -> tuple[str, str]:
    for prefix, category in _CATEGORY_MAP:
        if rule_code.startswith(prefix):
            return category, _SEVERITY[category]
    return "code_smell", "warning"


def analyze(
    src_path: str,
    new_code_lines: Optional[dict[str, set[int]]] = None,
) -> Optional[StaticAnalysisResult]:
    try:
        proc = subprocess.run(
            [
                "ruff", "check",
                "--select", "F,B,E,W,C90,N,UP,RUF,S",
                "--output-format", "json",
                src_path,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        logger.error("ruff not found; skipping static analysis")
        return None
    except subprocess.TimeoutExpired:
        logger.error("ruff timed out", exc_info=True)
        return None

    try:
        raw = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        logger.error("ruff produced invalid JSON: %s", proc.stdout[:200])
        return None

    findings: list[StaticFinding] = []
    for item in raw:
        rule = item.get("code", "")
        category, severity = _categorize(rule)
        file_path = item.get("filename", "")
        line = item.get("location", {}).get("row", 0)
        rel_path = to_relative(file_path)
        is_new = new_code_lines is not None and line in new_code_lines.get(rel_path, set())
        findings.append(
            StaticFinding(
                file=file_path,
                line=line,
                column=item.get("location", {}).get("column", 0),
                rule=rule,
                message=item.get("message", ""),
                category=category,
                severity=severity,
                is_new_code=is_new,
            )
        )

    return StaticAnalysisResult(findings=findings)
