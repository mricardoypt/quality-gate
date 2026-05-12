"""Parses coverage.xml produced by pytest-cov."""
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional


@dataclass
class CoverageResult:
    line_rate: float  # 0–100
    branch_rate: float  # 0–100
    covered_lines: int
    total_lines: int

    @property
    def passed(self) -> bool:
        return True  # threshold applied by aggregator

    def summary(self) -> str:
        return f"{self.line_rate:.1f}% lines, {self.branch_rate:.1f}% branches ({self.covered_lines}/{self.total_lines})"


def parse(coverage_xml_path: str) -> Optional[CoverageResult]:
    try:
        root = ET.parse(coverage_xml_path).getroot()
    except (FileNotFoundError, ET.ParseError):
        return None

    return CoverageResult(
        line_rate=float(root.get("line-rate", 0)) * 100,
        branch_rate=float(root.get("branch-rate", 0)) * 100,
        covered_lines=int(root.get("lines-covered", 0)),
        total_lines=int(root.get("lines-valid", 0)),
    )
