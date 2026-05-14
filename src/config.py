"""Parses .qualitygate.yml from the consumer repo."""
from dataclasses import dataclass, field
from typing import Optional

import yaml


@dataclass
class MetricConfig:
    threshold: float
    blocking: bool


@dataclass
class QualityGateConfig:
    # Coverage
    coverage: MetricConfig = field(default_factory=lambda: MetricConfig(threshold=80.0, blocking=True))

    # Complexity
    cyclomatic_max: int = 10
    cognitive_max: int = 15
    complexity_blocking: bool = True

    # Code duplication
    duplication_threshold: float = 3.0   # max % of duplicated lines
    duplication_blocking: bool = False

    # File / function size
    max_file_sloc: int = 300
    max_function_lines: int = 30
    size_blocking: bool = False

    # Ratings
    min_reliability_rating: str = "A"
    min_security_rating: str = "A"
    min_maintainability_rating: str = "B"
    ratings_blocking: bool = True

    # Dependency cycles
    cycles_blocking: bool = False

    # SARIF (bandit, pip-audit)
    sarif_blocking: bool = False

    # Mutation testing (opt-in — slow)
    mutation_threshold: Optional[float] = None
    mutation_blocking: bool = False

    # Claude PR review (opt-in — requires ANTHROPIC_API_KEY)
    claude_review_enabled: bool = False


def load_config(path: str) -> QualityGateConfig:
    try:
        with open(path) as f:
            raw = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return QualityGateConfig()

    config = QualityGateConfig()

    if "coverage" in raw:
        cov = raw["coverage"]
        config.coverage = MetricConfig(
            threshold=float(cov.get("threshold", 80)),
            blocking=bool(cov.get("blocking", True)),
        )

    if "complexity" in raw:
        cx = raw["complexity"]
        config.cyclomatic_max = int(cx.get("max_cyclomatic", 10))
        config.cognitive_max = int(cx.get("max_cognitive", 15))
        config.complexity_blocking = bool(cx.get("blocking", True))

    if "duplication" in raw:
        dup = raw["duplication"]
        config.duplication_threshold = float(dup.get("threshold", 3.0))
        config.duplication_blocking = bool(dup.get("blocking", False))

    if "size" in raw:
        sz = raw["size"]
        config.max_file_sloc = int(sz.get("max_file_sloc", 300))
        config.max_function_lines = int(sz.get("max_function_lines", 30))
        config.size_blocking = bool(sz.get("blocking", False))

    if "ratings" in raw:
        rt = raw["ratings"]
        config.min_reliability_rating = rt.get("min_reliability", "A").upper()
        config.min_security_rating = rt.get("min_security", "A").upper()
        config.min_maintainability_rating = rt.get("min_maintainability", "B").upper()
        config.ratings_blocking = bool(rt.get("blocking", True))

    if "dependency_cycles" in raw:
        config.cycles_blocking = bool(raw["dependency_cycles"].get("blocking", False))

    if "sarif" in raw:
        config.sarif_blocking = bool(raw["sarif"].get("blocking", False))

    if "mutation_score" in raw:
        ms = raw["mutation_score"]
        config.mutation_threshold = float(ms.get("threshold", 70))
        config.mutation_blocking = bool(ms.get("blocking", False))

    if "claude_review" in raw:
        config.claude_review_enabled = bool(raw["claude_review"].get("enabled", False))

    return config
