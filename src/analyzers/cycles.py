"""Runs import-linter to detect dependency cycles."""
import logging
import subprocess
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CyclesResult:
    cycles_found: bool
    details: str

    def summary(self) -> str:
        if not self.cycles_found:
            return "No dependency cycles detected."
        return f"Dependency cycles found:\n{self.details}"


def analyze(repo_path: str) -> Optional[CyclesResult]:
    """Runs lint-imports; requires .importlinter config in repo_path."""
    try:
        result = subprocess.run(
            ["lint-imports"],
            capture_output=True,
            text=True,
            cwd=repo_path,
            timeout=60,
        )
    except FileNotFoundError:
        logger.warning("import-linter not found; skipping cycle detection")
        return None
    except subprocess.TimeoutExpired:
        logger.error("lint-imports timed out", exc_info=True)
        return None

    cycles_found = result.returncode != 0
    details = (result.stdout + result.stderr).strip()

    return CyclesResult(cycles_found=cycles_found, details=details)
