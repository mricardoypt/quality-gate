"""Measures function and file sizes via radon raw metrics."""
import json
import logging
import subprocess
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class FileMetrics:
    path: str
    loc: int    # total lines (including blanks and comments)
    sloc: int   # source lines (executable statements only)
    comments: int
    blank: int


@dataclass
class RawMetricsResult:
    files: list[FileMetrics] = field(default_factory=list)
    max_function_lines: int = 30
    max_file_sloc: int = 300

    @property
    def total_sloc(self) -> int:
        return sum(f.sloc for f in self.files)

    @property
    def large_files(self) -> list[FileMetrics]:
        return [f for f in self.files if f.sloc > self.max_file_sloc]

    def summary(self) -> str:
        large = len(self.large_files)
        base = f"{self.total_sloc} SLOC across {len(self.files)} file(s)"
        return base + (f", {large} file(s) exceed {self.max_file_sloc} SLOC" if large else "")


def analyze(src_path: str, max_function_lines: int = 30, max_file_sloc: int = 300) -> Optional[RawMetricsResult]:
    try:
        proc = subprocess.run(
            ["radon", "raw", src_path, "--json"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        logger.error("radon not found; skipping raw metrics")
        return None
    except subprocess.TimeoutExpired:
        logger.error("radon raw timed out", exc_info=True)
        return None

    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        logger.error("radon raw produced invalid JSON: %s", proc.stdout[:200])
        return None

    files = [
        FileMetrics(
            path=path,
            loc=m.get("loc", 0),
            sloc=m.get("sloc", 0),
            comments=m.get("comments", 0),
            blank=m.get("blank", 0),
        )
        for path, m in data.items()
    ]

    return RawMetricsResult(
        files=files,
        max_function_lines=max_function_lines,
        max_file_sloc=max_file_sloc,
    )
