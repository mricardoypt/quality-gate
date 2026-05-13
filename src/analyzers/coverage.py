"""Parses coverage.xml produced by pytest-cov."""
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional

from src.diff import to_relative


@dataclass
class FileCoverage:
    path: str           # relative path as stored in coverage.xml
    line_rate: float    # 0–100
    branch_rate: float  # 0–100
    covered_lines: int
    total_lines: int


@dataclass
class CoverageResult:
    line_rate: float  # 0–100
    branch_rate: float  # 0–100
    covered_lines: int
    total_lines: int
    per_file: list[FileCoverage] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return True  # threshold applied by aggregator

    def summary(self) -> str:
        return f"{self.line_rate:.1f}% lines, {self.branch_rate:.1f}% branches ({self.covered_lines}/{self.total_lines})"


def _parse_file_coverage(root: ET.Element) -> list[FileCoverage]:
    files: list[FileCoverage] = []
    for cls in root.iter("class"):
        filename = cls.get("filename", "")
        if not filename:
            continue
        lines = cls.findall(".//line")
        total = len(lines)
        covered = sum(1 for ln in lines if int(ln.get("hits", 0)) > 0)
        files.append(FileCoverage(
            path=os.path.normpath(to_relative(filename)),
            line_rate=float(cls.get("line-rate", 0)) * 100,
            branch_rate=float(cls.get("branch-rate", 0)) * 100,
            covered_lines=covered,
            total_lines=total,
        ))
    return files


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
        per_file=_parse_file_coverage(root),
    )
