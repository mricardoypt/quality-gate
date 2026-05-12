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
    coverage: MetricConfig = field(default_factory=lambda: MetricConfig(threshold=80.0, blocking=True))
    complexity_max: int = 15
    complexity_blocking: bool = True
    cycles_blocking: bool = False
    sarif_blocking: bool = False
    mutation_threshold: Optional[float] = None
    mutation_blocking: bool = False


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
        config.complexity_max = int(cx.get("max_cognitive", 15))
        config.complexity_blocking = bool(cx.get("blocking", True))

    if "dependency_cycles" in raw:
        config.cycles_blocking = bool(raw["dependency_cycles"].get("blocking", False))

    if "sarif" in raw:
        config.sarif_blocking = bool(raw["sarif"].get("blocking", False))

    if "mutation_score" in raw:
        ms = raw["mutation_score"]
        config.mutation_threshold = float(ms.get("threshold", 70))
        config.mutation_blocking = bool(ms.get("blocking", False))

    return config
