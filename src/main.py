"""Quality Gate entrypoint — reads config, runs analysis, posts outputs, exits 0 or 1."""
import logging
import os
import subprocess
import sys

from src import aggregator
from src.analyzers import coverage, complexity, cycles, mutation, sarif
from src.config import load_config
from src import github_client
from src.reporters import annotations, job_summary, pr_comment

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

REPO_PATH = os.environ.get("REPO_PATH", "/repo")


def _install_consumer_requirements() -> None:
    req_path = os.path.join(REPO_PATH, "requirements.txt")
    if not os.path.exists(req_path):
        return
    logger.info("Installing consumer requirements from %s", req_path)
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "-r", req_path],
        check=True,
    )


def _run_mutation(config, src_path: str, tests_path: str):
    if config.mutation_threshold is None:
        return None
    logger.info("Running mutation testing (this may take several minutes)…")
    return mutation.analyze(REPO_PATH, src_path, tests_path)


def main() -> int:
    config_path = os.path.join(REPO_PATH, ".qualitygate.yml")
    config = load_config(config_path)

    src_path = os.path.join(REPO_PATH, "src")
    tests_path = os.path.join(REPO_PATH, "tests")
    coverage_xml = os.path.join(REPO_PATH, "coverage.xml")
    sarif_paths = [
        p for p in [
            os.path.join(REPO_PATH, "bandit.sarif"),
            os.path.join(REPO_PATH, "pip-audit.sarif"),
        ]
        if os.path.exists(p)
    ]

    _install_consumer_requirements()

    logger.info("Analyzing coverage…")
    coverage_result = coverage.parse(coverage_xml)

    logger.info("Analyzing cognitive complexity…")
    complexity_result = complexity.analyze(src_path, config.complexity_max)

    logger.info("Checking dependency cycles…")
    cycles_result = cycles.analyze(REPO_PATH)

    logger.info("Parsing SARIF reports…")
    sarif_result = sarif.parse(sarif_paths)

    mutation_result = _run_mutation(config, src_path, tests_path)

    report = aggregator.aggregate(
        config=config,
        coverage=coverage_result,
        complexity=complexity_result,
        cycles=cycles_result,
        sarif=sarif_result,
        mutation=mutation_result,
    )

    sha = os.environ.get("GITHUB_SHA", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    run_url = f"https://github.com/{repository}/actions/runs/{run_id}" if repository else ""

    job_summary.write(report)
    annotations.post(report, sha)

    comment_body = pr_comment.build(report, run_url)
    github_client.post_pr_comment(comment_body)

    if report.gate_passed:
        logger.info("Quality Gate PASSED")
        return 0

    failures = [c.name for c in report.blocking_failures]
    logger.error("Quality Gate FAILED — blocking checks: %s", ", ".join(failures))
    return 1


if __name__ == "__main__":
    sys.exit(main())
