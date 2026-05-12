"""Runs mutmut and parses the mutation score. Opt-in only (slow)."""
import logging
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


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
            timeout=600,
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
            ["mutmut", "junitxml"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        logger.error("mutmut junitxml timed out")
        return None

    try:
        root = ET.fromstring(result.stdout)
    except ET.ParseError:
        logger.exception("Could not parse mutmut junitxml output")
        return None

    suite = root.find("testsuite") if root.tag == "testsuites" else root
    if suite is None:
        logger.error("No testsuite element found in mutmut junitxml output")
        return None

    total = int(suite.get("tests", 0))
    # In mutmut JUnit XML: a "failure" means the mutant survived (test didn't catch it)
    survived = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
    killed = total - survived

    if total == 0:
        return None

    return MutationResult(
        score=(killed / total) * 100,
        killed=killed,
        survived=survived,
        total=total,
    )
