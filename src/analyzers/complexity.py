"""
Cyclomatic complexity via radon cc.
Cognitive complexity via the cognitive-complexity package (AST-based, no subprocess).
"""
import ast
import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ComplexFunction:
    file: str
    name: str
    lineno: int
    cyclomatic: int
    cognitive: int


@dataclass
class ComplexityResult:
    all_functions: list[ComplexFunction] = field(default_factory=list)
    cyclomatic_max: int = 10
    cognitive_max: int = 15

    @property
    def cyclomatic_violations(self) -> list[ComplexFunction]:
        return [f for f in self.all_functions if f.cyclomatic > self.cyclomatic_max]

    @property
    def cognitive_violations(self) -> list[ComplexFunction]:
        return [f for f in self.all_functions if f.cognitive > self.cognitive_max]

    @property
    def max_cyclomatic_found(self) -> int:
        return max((f.cyclomatic for f in self.all_functions), default=0)

    @property
    def max_cognitive_found(self) -> int:
        return max((f.cognitive for f in self.all_functions), default=0)

    def summary(self) -> str:
        return (
            f"Cyclomatic: {len(self.cyclomatic_violations)} violation(s), max={self.max_cyclomatic_found}. "
            f"Cognitive: {len(self.cognitive_violations)} violation(s), max={self.max_cognitive_found}."
        )


def _cognitive_scores(src_path: str) -> dict[tuple[str, str, int], int]:
    """Returns {(filepath, func_name, lineno): cognitive_score} for all functions."""
    try:
        from cognitive_complexity.api import get_cognitive_complexity
    except ImportError:
        logger.warning("cognitive-complexity package not installed; cognitive scores will be 0")
        return {}

    scores: dict[tuple[str, str, int], int] = {}
    for py_file in Path(src_path).rglob("*.py"):
        try:
            source = py_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(py_file))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                try:
                    scores[(str(py_file), node.name, node.lineno)] = get_cognitive_complexity(node)
                except Exception:
                    pass
    return scores


def _cyclomatic_data(src_path: str) -> dict[str, list[dict]]:
    try:
        proc = subprocess.run(
            ["radon", "cc", src_path, "--json", "--min", "A"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return json.loads(proc.stdout or "{}")
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        logger.exception("radon cc failed")
        return {}


def analyze(src_path: str, cyclomatic_max: int = 10, cognitive_max: int = 15) -> Optional[ComplexityResult]:
    cyclomatic_map = _cyclomatic_data(src_path)
    cognitive_map = _cognitive_scores(src_path)

    functions: dict[tuple[str, str, int], ComplexFunction] = {}

    for filepath, fns in cyclomatic_map.items():
        for fn in fns:
            key = (filepath, fn.get("name", "?"), fn.get("lineno", 0))
            functions[key] = ComplexFunction(
                file=filepath,
                name=fn.get("name", "?"),
                lineno=fn.get("lineno", 0),
                cyclomatic=fn.get("complexity", 0),
                cognitive=0,
            )

    for (filepath, name, lineno), cog in cognitive_map.items():
        key = (filepath, name, lineno)
        if key in functions:
            functions[key].cognitive = cog
        else:
            functions[key] = ComplexFunction(
                file=filepath, name=name, lineno=lineno, cyclomatic=0, cognitive=cog,
            )

    return ComplexityResult(
        all_functions=list(functions.values()),
        cyclomatic_max=cyclomatic_max,
        cognitive_max=cognitive_max,
    )
