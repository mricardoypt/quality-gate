"""Runs radon to compute cognitive and cyclomatic complexity."""
import json
import logging
import subprocess
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ComplexFunction:
    file: str
    name: str
    complexity: int
    lineno: int


@dataclass
class ComplexityResult:
    violations: list[ComplexFunction]
    max_found: int

    def summary(self) -> str:
        if not self.violations:
            return "No functions exceed the complexity threshold."
        names = ", ".join(f"{v.file}:{v.name}({v.complexity})" for v in self.violations[:5])
        suffix = f" (+{len(self.violations) - 5} more)" if len(self.violations) > 5 else ""
        return f"{len(self.violations)} violation(s): {names}{suffix}"


def analyze(src_path: str, threshold: int) -> Optional[ComplexityResult]:
    try:
        result = subprocess.run(
            ["radon", "cc", src_path, "--json", "--min", "A"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.error("radon failed", exc_info=True)
        return None

    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        logger.error("radon produced invalid JSON: %s", result.stdout)
        return None

    violations: list[ComplexFunction] = []
    max_found = 0

    for filepath, functions in data.items():
        for fn in functions:
            complexity = fn.get("complexity", 0)
            max_found = max(max_found, complexity)
            if complexity > threshold:
                violations.append(
                    ComplexFunction(
                        file=filepath,
                        name=fn.get("name", "?"),
                        complexity=complexity,
                        lineno=fn.get("lineno", 0),
                    )
                )

    return ComplexityResult(violations=violations, max_found=max_found)
