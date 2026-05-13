"""Quality Gate entrypoint — reads config, runs all analyzers, posts outputs, exits 0 or 1."""
import logging
import os
import subprocess
import sys

from src import aggregator
from src.analyzers import complexity, coverage, cycles, mutation, sarif
from src.analyzers import duplication, raw_metrics, static_analysis
from src.config import load_config
from src import github_client
from src.reporters import job_summary, pr_comment

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


def main() -> int:
    config_path = os.path.join(REPO_PATH, ".qualitygate.yml")
    config = load_config(config_path)

    src_path = os.path.join(REPO_PATH, "src")
    tests_path = os.path.join(REPO_PATH, "tests")
    coverage_xml = os.path.join(REPO_PATH, "coverage.xml")
    bandit_json = os.path.join(REPO_PATH, "bandit.json")
    pip_audit_json = os.path.join(REPO_PATH, "pip-audit.json")
    bandit_path = bandit_json if os.path.exists(bandit_json) else None
    pip_audit_path = pip_audit_json if os.path.exists(pip_audit_json) else None

    _install_consumer_requirements()

    logger.info("Fetching PR diff for differential analysis…")
    new_code_lines = github_client.get_changed_lines_by_file()

    logger.info("Analyzing coverage…")
    coverage_result = coverage.parse(coverage_xml)

    logger.info("Running static analysis (bugs, vulnerabilities, code smells)…")
    static_result = static_analysis.analyze(src_path, new_code_lines)

    logger.info("Analyzing cyclomatic and cognitive complexity…")
    complexity_result = complexity.analyze(src_path, config.cyclomatic_max, config.cognitive_max)

    logger.info("Detecting code duplication…")
    total_lines = coverage_result.total_lines if coverage_result else 0
    duplication_result = duplication.analyze(src_path, total_lines)

    logger.info("Measuring file and function sizes…")
    raw_metrics_result = raw_metrics.analyze(src_path, config.max_function_lines, config.max_file_sloc)

    logger.info("Checking dependency cycles…")
    cycles_result = cycles.analyze(REPO_PATH)

    logger.info("Parsing security reports…")
    sarif_result = sarif.parse(bandit_path, pip_audit_path)

    mutation_result = None
    if config.mutation_threshold is not None and new_code_lines is None:
        logger.info("Running mutation testing (may take several minutes)…")
        mutation_result = mutation.analyze(REPO_PATH, src_path, tests_path)

    report = aggregator.aggregate(
        config=config,
        coverage=coverage_result,
        static=static_result,
        complexity=complexity_result,
        cycles=cycles_result,
        duplication=duplication_result,
        raw_metrics=raw_metrics_result,
        sarif=sarif_result,
        mutation=mutation_result,
        new_code_lines=new_code_lines,
    )

    run_id = os.environ.get("GITHUB_RUN_ID", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    run_url = f"https://github.com/{repository}/actions/runs/{run_id}" if repository else ""

    job_summary.write(report)

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
