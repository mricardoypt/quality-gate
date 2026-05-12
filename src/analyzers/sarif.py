"""Parses SARIF files produced by bandit, pip-audit, or any SARIF-emitting tool."""
import json
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

SEVERITY_RANK = {"error": 3, "warning": 2, "note": 1, "none": 0}


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
            return "No SARIF findings."
        return f"{self.error_count} error(s), {self.warning_count} warning(s) across {len(self.findings)} finding(s)."


def _parse_single(path: str) -> list[SarifFinding]:
    try:
        with open(path) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("Could not parse SARIF file: %s", path)
        return []

    findings: list[SarifFinding] = []

    for run in data.get("runs", []):
        tool_name = run.get("tool", {}).get("driver", {}).get("name", "unknown")
        for result in run.get("results", []):
            level = result.get("level", "warning")
            message = result.get("message", {}).get("text", "")
            rule_id = result.get("ruleId", "")
            locations = result.get("locations", [{}])
            loc = locations[0].get("physicalLocation", {}) if locations else {}
            file_path = loc.get("artifactLocation", {}).get("uri", "")
            line = loc.get("region", {}).get("startLine", 0)
            findings.append(
                SarifFinding(
                    tool=tool_name,
                    rule_id=rule_id,
                    message=message,
                    severity=level,
                    file=file_path,
                    line=line,
                )
            )

    return findings


def parse(sarif_paths: list[str]) -> Optional[SarifResult]:
    all_findings: list[SarifFinding] = []
    for path in sarif_paths:
        all_findings.extend(_parse_single(path))

    if not sarif_paths:
        return None

    return SarifResult(findings=all_findings)
