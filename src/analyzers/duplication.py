"""Detects copy-paste code duplication via pylint's R0801 (duplicate-code) check."""
import logging
import re
import subprocess
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Matches the "Similar lines in N files" header emitted by pylint R0801
_BLOCK_RE = re.compile(
    r"Similar lines in \d+ files\s*((?:==[^\n]+\n)+)",
    re.MULTILINE,
)
_FILE_RE = re.compile(r"==([^:]+):(\d+)")
_LINE_COUNT_RE = re.compile(r"R0801.*?Similar lines in \d+ files", re.DOTALL)


@dataclass
class DuplicateBlock:
    file_a: str
    line_a: int
    file_b: str
    line_b: int
    line_count: int


@dataclass
class DuplicationResult:
    blocks: list[DuplicateBlock] = field(default_factory=list)
    total_duplicated_lines: int = 0
    total_lines: int = 0

    @property
    def percentage(self) -> float:
        if self.total_lines == 0:
            return 0.0
        return (self.total_duplicated_lines / self.total_lines) * 100

    def summary(self) -> str:
        if not self.blocks:
            return "No code duplication detected."
        return (
            f"{len(self.blocks)} duplicate block(s), "
            f"{self.total_duplicated_lines} duplicated lines "
            f"({self.percentage:.1f}%)"
        )


def _count_block_lines(raw_section: str) -> int:
    """Counts non-header lines in a pylint duplication block (the actual duplicated code)."""
    code_lines = [
        ln for ln in raw_section.split("\n")
        if ln and not ln.startswith("==") and not ln.startswith("Similar")
    ]
    return len(code_lines)


def _parse(output: str) -> list[DuplicateBlock]:
    blocks: list[DuplicateBlock] = []
    # Split on each R0801 report line, then parse the following block
    for match in _BLOCK_RE.finditer(output):
        file_matches = _FILE_RE.findall(match.group(1))
        if len(file_matches) < 2:
            continue
        # Count the duplicated code lines that follow the == headers
        start = match.end()
        next_block = output.find("Similar lines in", start)
        section = output[start:next_block] if next_block != -1 else output[start:]
        line_count = _count_block_lines(section)
        blocks.append(
            DuplicateBlock(
                file_a=file_matches[0][0].strip().replace(".", "/") + ".py",
                line_a=int(file_matches[0][1]),
                file_b=file_matches[1][0].strip().replace(".", "/") + ".py",
                line_b=int(file_matches[1][1]),
                line_count=max(line_count, 6),  # pylint default min is 4-6 lines
            )
        )
    return blocks


def analyze(src_path: str, total_lines: int = 0) -> Optional[DuplicationResult]:
    try:
        proc = subprocess.run(
            [
                "pylint",
                "--disable=all",
                "--enable=duplicate-code",
                "--min-similarity-lines=6",
                src_path,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        logger.error("pylint not found; skipping duplication check")
        return None
    except subprocess.TimeoutExpired:
        logger.error("pylint duplicate-code timed out", exc_info=True)
        return None

    blocks = _parse(proc.stdout + proc.stderr)
    duplicated = sum(b.line_count for b in blocks)

    return DuplicationResult(
        blocks=blocks,
        total_duplicated_lines=duplicated,
        total_lines=total_lines,
    )
