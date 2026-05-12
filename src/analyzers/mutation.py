"""Runs mutmut and parses the mutation score. Opt-in only (slow)."""
import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_SCORE_RE = re.compile(r"Survived:\s*(\d+).*?Killed:\s*(\d+)", re.DOTALL)


@dataclass
class MutationResult:
    score: float  # 0–100 (killed / total * 100)
    killed: int
    survived: int
    total: int

    def summary(self) -> str:
        return f"{self.score:.1f}% mutation score ({self.killed} killed / {self.total} total)"


def analyze(repo_path: str, src_path: str, tests_path: str) -> Optional[MutationResult]:
    try:
        subprocess.run(
            ["mutmut", "run", "--paths-to-mutate", src_path, "--tests-dir", tests_path],
            cwd=repo_path,
            timeout=600,  # mutation testing is slow; 10 min hard cap
            check=False,
        )
    except FileNotFoundError:
        logger.warning("mutmut not found; skipping mutation testing")
        return None
    except subprocess.TimeoutExpired:
        logger.error("mutmut timed out after 10 minutes")
        return None

    try:
        result = subprocess.run(
            ["mutmut", "results"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        logger.error("mutmut results timed out")
        return None

    output = result.stdout + result.stderr
    match = _SCORE_RE.search(output)
    if not match:
        logger.error("Could not parse mutmut results: %s", output)
        return None

    survived = int(match.group(1))
    killed = int(match.group(2))
    total = survived + killed

    if total == 0:
        return None

    return MutationResult(
        score=(killed / total) * 100,
        killed=killed,
        survived=survived,
        total=total,
    )
