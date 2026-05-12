"""Parses native JSON reports from bandit and pip-audit."""
import json
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_BANDIT_SEVERITY_MAP = {"HIGH": "error", "MEDIUM": "warning", "LOW": "note"}


@dataclass
class SarifFinding:
    tool: str
    rule_id: str
    message: str
    severity: str  # error | warning | note | none
    file: str
    line: int


@dataclass
class SarifResult:
    findings: list[SarifFinding]

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")

    def summary(self) -> str:
        if not self.findings:
            return "No security findings."
        return f"{self.error_count} error(s), {self.warning_count} warning(s) across {len(self.findings)} finding(s)."


def _parse_bandit(path: str) -> list[SarifFinding]:
    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("Could not parse bandit JSON: %s", path)
        return []

    findings = []
    for result in data.get("results", []):
        severity = _BANDIT_SEVERITY_MAP.get(result.get("issue_severity", "").upper(), "note")
        findings.append(
            SarifFinding(
                tool="bandit",
                rule_id=result.get("test_id", ""),
                message=result.get("issue_text", ""),
                severity=severity,
                file=result.get("filename", ""),
                line=result.get("line_number", 0),
            )
        )
    return findings


def _parse_pip_audit(path: str) -> list[SarifFinding]:
    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("Could not parse pip-audit JSON: %s", path)
        return []

    findings = []
    for package in data.get("dependencies", []):
        name = package.get("name", "")
        version = package.get("version", "")
        for vuln in package.get("vulns", []):
            findings.append(
                SarifFinding(
                    tool="pip-audit",
                    rule_id=vuln.get("id", ""),
                    message=f"{name}=={version}: {vuln.get('description', '')}",
                    severity="error",
                    file="requirements.txt",
                    line=0,
                )
            )
    return findings


def parse(bandit_path: Optional[str], pip_audit_path: Optional[str]) -> Optional[SarifResult]:
    if bandit_path is None and pip_audit_path is None:
        return None

    findings: list[SarifFinding] = []
    if bandit_path is not None:
        findings.extend(_parse_bandit(bandit_path))
    if pip_audit_path is not None:
        findings.extend(_parse_pip_audit(pip_audit_path))

    return SarifResult(findings=findings)
