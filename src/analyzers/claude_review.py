"""Calls the Anthropic API to review the PR diff against coding standards."""
import json
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

MAX_DIFF_CHARS = 120_000
MAX_GROUPS = 50

CATEGORY_LABELS = {
    "pyspark_classic": "⚡ PySpark — Classic Compute",
    "pyspark_performance": "🚀 PySpark — Performance",
    "python_fundamentals": "🐍 Python Fundamentals",
    "code_quality": "📝 Code Quality",
    "formatting": "🎨 Formatting & Style",
}

SEVERITY_ICON = {
    "critical": "🔴",
    "warning": "⚠️",
    "style": "💅",
}

CATEGORY_EMOJI = {
    "pyspark_classic": "⚡",
    "pyspark_performance": "🚀",
    "python_fundamentals": "🐍",
    "code_quality": "📝",
    "formatting": "🎨",
}

QUALITY_LABEL = {
    "good": "🟢 Good",
    "needs_work": "🟡 Needs Work",
    "poor": "🔴 Poor",
}

VERDICT_HEADER = {
    "FAIL": "# ❌ FAIL — Critical violations found. This PR is blocked from merging.",
    "NEEDS_CHANGES": "# ⚠️ NEEDS CHANGES — Issues found that should be addressed before merging.",
    "PASS": "# ✅ PASS — This PR meets the coding standards.",
}

_SYSTEM_PROMPT = """You are a senior data engineer performing a structured pull request code review
for a PySpark/Databricks retail analytics platform running on Classic (non-serverless) compute.

You MUST output ONLY a single valid JSON object — no prose, no markdown code fences, no explanation.
The JSON must exactly match the schema below.

JSON SCHEMA:
{
  "verdict": "FAIL" | "NEEDS_CHANGES" | "PASS",
  "summary": "<one sentence overall assessment>",
  "file_summaries": [
    {
      "file": "<exact path from the diff header>",
      "quality": "good" | "needs_work" | "poor",
      "issues": [
        {
          "type": "<short label for this category of problem, e.g. 'Debug output calls', 'Filter after join', 'SparkSession inside function'>",
          "severity": "critical" | "warning" | "style",
          "lines": [<list of integer line numbers where this problem type appears in this file>]
        }
      ]
    }
  ],
  "logical_groups": [
    {
      "id": "<e.g. LG1, LG2, ...>",
      "title": "<short descriptive title, max 10 words>",
      "category": "pyspark_classic" | "pyspark_performance" | "python_fundamentals" | "code_quality" | "formatting",
      "severity": "critical" | "warning" | "style",
      "file": "<exact path as shown in the diff header>",
      "problem": "<what is wrong and why it matters, max 200 chars>",
      "solution": "<complete description of how to fix this specific instance, max 200 chars>",
      "affected_lines": [
        {
          "line": <integer — [L:N] tag of the last line of this entry>,
          "start_line": <integer — [L:N] tag of the first line; include only when this entry spans multiple lines>,
          "role": "<brief label: 'definition', 'call site', 'filter after join', 'UDF declaration', etc., max 50 chars>",
          "current_code": "<exact verbatim lines from start_line to line>"
        }
      ]
    }
  ]
}

SEVERITY DEFINITIONS — apply these strictly, do not escalate:

CRITICAL — reserved exclusively for code that WILL or is VERY LIKELY to cause one of the following
in a production Spark job:
  • Out-of-memory failure on the driver or executor
    (e.g. collect(), toPandas(), for row in df.collect(), iterrows() on a large DataFrame)
  • Full DAG re-execution triggered in a production pipeline
    (e.g. show(), display(), count() called outside of test or debug files)
  • Application crash or broken Databricks session
    (e.g. SparkSession.builder.getOrCreate() called inside a function)
  • Unbounded data explosion that will make the job fail or run forever
    (e.g. crossJoin() without a restricting join condition)
  • Severe, proven performance degradation that makes the job impractical at scale
    (e.g. Python UDF — F.udf() — applied to a large DataFrame column)
  • Filter placed AFTER a join on production DataFrames, causing avoidable full shuffles

WARNING — for issues that are incorrect or risky but do not immediately crash or OOM:
  • print() / logging.error() without exc_info=True in production code
  • SELECT * / .select("*") in production pipelines (schema drift risk, memory waste)
  • Caching a DataFrame that is used only once (wasted memory)
  • Missing unpersist() after cache/persist
  • Defensive attribute checks: hasattr() or getattr() with defaults (hides bugs)
  • Functions that clearly do more than one thing (side effects + return value)
  • Ambiguous or misleading variable/function names in non-trivial contexts

STYLE — for clean-code conventions and team preferences:
  • Naming conventions (snake_case, descriptive names)
  • Parameter count (> 3 params is a style concern, never critical or warning alone)
  • Module-level mutable variables that are local config or constants in practice
  • Missing type hints
  • Import ordering or grouping

NEVER flag as CRITICAL:
  • Anything in test files (tests/**, *_test.py, test_*.py, conftest.py) — skip entirely
  • collect() or toPandas() in test files — expected and correct
  • Module-level mutable dicts or lists used as local config or caches
  • Functions with more than 3 parameters — this is STYLE at most
  • print() statements — WARNING at most, STYLE in most cases
  • Missing docstrings or comments
  • Convention preferences with no runtime impact

VERDICT RULES:
- FAIL: any critical logical group present
- NEEDS_CHANGES: no critical, but warning groups present
- PASS: only style groups or no groups

FILE QUALITY RULES:
- "poor": file has at least one critical group
- "needs_work": file has no critical groups but has two or more warning groups
- "good": file has at most one warning group and no critical groups

LINE NUMBER RULES (critical for correctness):
- Each added or context line in the diff is annotated with [L:N] where N is its exact line number in the new file
- ALL line/start_line values must come from [L:N] tags — never compute or guess
- Lines prefixed with "-" carry no [L:N] tag; they do not exist in the new file — never reference them
- Files matching tests/**, *_test.py, test_*.py, conftest.py must be completely skipped — produce no groups for them

LOGICAL GROUP RULES:
- Each individual OCCURRENCE of a problem = its own logical group.
  If df.show() appears 3 times in the same file, that is 3 separate groups, not one.
  If SparkSession.getOrCreate() is called in 2 functions, that is 2 separate groups.
- The affected_lines of a group are the lines that are INTERDEPENDENT for that specific occurrence.
  A single-statement problem (e.g., one df.show() call) has exactly one entry in affected_lines.
  A multi-statement problem (e.g., a filter placed after a join) lists both the join line and the
  filter line — because fixing one requires awareness of the other.
- NEVER merge multiple occurrences of the same problem type into one group.
- NEVER create a group for a line that is already covered by another group.

OUTPUT SIZE RULES (mandatory — JSON must fit in one response):
- Report at most 50 logical groups total; critical first, then warning, then style
- problem: max 200 characters
- solution: max 200 characters
- file_summaries issue type: max 60 characters
- file_summaries: one entry per file that appears in the diff"""

_STANDARDS = """
NAMING:
- Variables: must reveal intent. Flag: data, info, value, tmp, obj, df (unless scope trivially obvious).
- Functions: snake_case verb phrases only. CamelCase function names = violation.
- Avoid ambiguous names: process, handle, execute, manage, doTheThing.
- Classes: nouns with single responsibility. Avoid: Manager, Helper, Utils, Processor.

FUNCTIONS:
- Must do one thing only. Max 3 parameters (more → group into a value object).
- Must either DO something OR ANSWER something, never both.
- Never create empty stub methods (pass-only body with no actionable TODO comment).

LOGGING:
- WARNING: Prefer logger.xxx() over print() in production code. Use: logger = logging.getLogger(__name__).
- CRITICAL: Never display() or show() in production code (triggers full DAG re-execution).
- WARNING: Always include exc_info=True when logging errors.

ERROR HANDLING:
- WARNING: Never hasattr() or getattr() with defaults for defensive attribute checks.
- Object validity must be guaranteed at __init__ time.

STATE:
- WARNING: Never use the global keyword.
- STYLE: Module-level mutable variables used as local config or caches are acceptable.

OOP:
- Prefer classes over free-floating functions for stateful operations.
- Single responsibility per class. Composition over inheritance.

IMPORTS / SPARK SESSION:
- CRITICAL: Never call SparkSession.builder.getOrCreate() inside a function.
  The spark session is always available in Databricks as `spark`.

COLUMN SELECTION:
- WARNING: Avoid SELECT * or .select("*") in production code (schema drift, memory waste).
- Select only required columns before joins, aggregations, and window functions.

FILTER PLACEMENT:
- CRITICAL: Never filter AFTER a join on production DataFrames — avoidable full shuffles.
- Filter immediately after reading a table, BEFORE any joins or transforms.
- WARNING: No transformations inside filter conditions (no cast/rlike/trim in filters).

CACHING (Classic Compute):
- Use cache() or persist() when a DataFrame is reused in multiple downstream operations.
- WARNING: Do NOT cache DataFrames that are used only once — wasted memory.
- Prefer MEMORY_AND_DISK storage level for large DataFrames.
- WARNING: Always unpersist() when caching is no longer needed.

DRIVER-OVERLOADING OPERATIONS:
- CRITICAL: Never collect() or toPandas() in production — causes OOM.
- CRITICAL: Never Python for loops over collected DataFrame rows.
- CRITICAL: Never count()/show()/display() in production code (triggers full re-execution).

UDFs:
- CRITICAL: Never F.udf() at scale. Use built-in PySpark functions.
- Performance hierarchy: Built-in > Spark SQL > Pandas UDF > Python UDF.

CROSS JOINS:
- CRITICAL: Never crossJoin(). Refactor using F.lit(), F.explode(), or proper join conditions.

BROADCAST JOINS:
- Use F.broadcast() explicitly for lookup/dimension tables (< 500MB).

DEFENSIVE COLUMN CHECKS:
- Never `if "column" in df.columns` unless interfacing with uncontrolled external data.
- Column presence must be guaranteed by the pipeline contract.

GENERAL SPARK:
- Query order: Read → Filter → Select → Join → GroupBy/Window → Write.
- Never Python loops over DataFrames — use DataFrame operations.
"""


@dataclass
class ClaudeReviewResult:
    verdict: str             # "PASS" | "NEEDS_CHANGES" | "FAIL"
    summary_body: str        # pre-built markdown for the job summary
    groups_count: int
    groups_capped: bool
    critical_violations: int


def _annotate_diff_line_numbers(diff: str) -> str:
    """Prefix each added/context line with [L:N] — its actual line number in the new file."""
    result = []
    new_line = 0
    for raw in diff.split("\n"):
        if raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            if m:
                new_line = int(m.group(1)) - 1
            result.append(raw)
        elif raw.startswith("+") and not raw.startswith("+++"):
            new_line += 1
            result.append(f"[L:{new_line}]{raw}")
        elif raw.startswith("-") and not raw.startswith("---"):
            result.append(raw)
        else:
            new_line += 1
            result.append(f"[L:{new_line}]{raw}")
    return "\n".join(result)


def _call_claude(annotated_diff: str) -> dict:
    client = anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
    )
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    message = client.messages.create(
        model=model,
        max_tokens=16384,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Review the PR diff below against the standards provided.\n"
                    f"Output ONLY valid JSON — no markdown fences, no prose.\n\n"
                    f"CODING STANDARDS:\n{_STANDARDS}\n\n"
                    f"PULL REQUEST DIFF:\n{annotated_diff}"
                ),
            }
        ],
    )
    raw = message.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def _cap_groups(groups: list) -> tuple[list, bool]:
    _SEV = {"critical": 0, "warning": 1, "style": 2}
    sorted_groups = sorted(groups, key=lambda g: _SEV.get(g.get("severity", "style"), 2))
    was_truncated = len(sorted_groups) > MAX_GROUPS
    return sorted_groups[:MAX_GROUPS], was_truncated


def _build_markdown(data: dict) -> str:
    verdict = data.get("verdict", "FAIL")
    groups = data.get("logical_groups", [])
    file_summaries = data.get("file_summaries", [])
    groups_capped = data.get("groups_capped", False)

    lines = [VERDICT_HEADER.get(verdict, VERDICT_HEADER["FAIL"]), ""]
    lines += [f"> {data.get('summary', '')}", ""]

    if file_summaries:
        lines += ["## 📁 File Summary", ""]
        lines += ["| Quality | File | Issues |", "|:---:|:---|:---|"]
        for fs in file_summaries:
            quality = QUALITY_LABEL.get(fs.get("quality", "poor"), "🔴 Poor")
            basename = os.path.basename(fs["file"])
            bullets = []
            for issue in fs.get("issues", []):
                icon = SEVERITY_ICON.get(issue.get("severity", "style"), "💅")
                line_refs = " · ".join(f"`L{n}`" for n in issue.get("lines", []))
                suffix = f" — {line_refs}" if line_refs else ""
                bullets.append(f"{icon} {issue['type']}{suffix}")
            issues_cell = "<br>".join(bullets) if bullets else "—"
            lines.append(f"| {quality} | `{basename}` | {issues_cell} |")
        lines.append("")

    if groups:
        cat_counts: dict = {}
        for g in groups:
            cat = g["category"]
            sev = g["severity"]
            cat_counts.setdefault(cat, {"critical": 0, "warning": 0, "style": 0})
            cat_counts[cat][sev] += 1

        sev_totals = Counter(g["severity"] for g in groups)
        lines += ["## 📊 Issues by Category", ""]
        lines += [
            "| Category | 🔴 Critical | ⚠️ Warning | 💅 Style |",
            "|---|:---:|:---:|:---:|",
        ]
        for cat, label in CATEGORY_LABELS.items():
            counts = cat_counts.get(cat, {})
            c = counts.get("critical", 0)
            w = counts.get("warning", 0)
            s = counts.get("style", 0)
            if c + w + s > 0:
                lines.append(
                    f"| {label} | {'**' + str(c) + '**' if c else '—'} | {w or '—'} | {s or '—'} |"
                )
        tc = sev_totals.get("critical", 0)
        tw = sev_totals.get("warning", 0)
        ts = sev_totals.get("style", 0)
        lines += [f"| **Total** | **{tc}** | **{tw}** | **{ts}** |", ""]

        if groups_capped:
            lines += [
                "> [!WARNING]",
                f"> **Limit reached** — this review displays only the top **{MAX_GROUPS} issues** (critical-first priority)."
                " Additional issues may exist beyond this limit.",
                "",
            ]

        lines += ["## 🔎 Detailed Analysis", ""]

        seen_files: list = []
        groups_by_file: dict = {}
        for g in groups:
            f = g["file"]
            if f not in groups_by_file:
                seen_files.append(f)
                groups_by_file[f] = []
            groups_by_file[f].append(g)

        for i, file_path in enumerate(seen_files):
            if i > 0:
                lines += ["---", ""]
            n = len(groups_by_file[file_path])
            issue_word = "issue" if n == 1 else "issues"
            lines += [f"### 📄 `{file_path}` &nbsp; · &nbsp; _{n} {issue_word}_", ""]
            for g in groups_by_file[file_path]:
                icon = SEVERITY_ICON.get(g.get("severity", "style"), "")
                cat_emoji = CATEGORY_EMOJI.get(g.get("category", ""), "")

                lines.append("<details>")
                lines.append(
                    f"<summary>{icon} <strong>{g['id']}</strong> &nbsp;·&nbsp; {g['title']} &nbsp; {cat_emoji}</summary>"
                )
                lines.append("")
                lines.append("<br>")
                lines.append("")
                lines += [
                    "> **🐛 Problem**",
                    f"> {g.get('problem', '')}",
                    "",
                    "> **🛠️ Suggestion**",
                    f"> {g.get('solution', '')}",
                    "",
                ]

                affected = g.get("affected_lines", [])
                single = [al for al in affected if "\n" not in al.get("current_code", "")]
                multi = [al for al in affected if "\n" in al.get("current_code", "")]

                if affected:
                    lines.append("**📍 Affected Lines**")
                    lines.append("")

                if single:
                    lines += ["| Line | Role | Current Code |", "|:---:|---|---|"]
                    for al in single:
                        start = al.get("start_line")
                        end = al["line"]
                        loc = f"L{start}–{end}" if start and start != end else f"L{end}"
                        role = al.get("role", "")
                        code = al.get("current_code", "").strip()
                        lines.append(f"| `{loc}` | {role} | `{code}` |")
                    lines.append("")

                for al in multi:
                    start = al.get("start_line")
                    end = al["line"]
                    loc = f"L{start}–{end}" if start and start != end else f"L{end}"
                    role = al.get("role", "")
                    code = al.get("current_code", "").strip()
                    lines.append(f"**`{loc}`** — {role}")
                    lines.append("```python")
                    lines.append(code)
                    lines.append("```")
                    lines.append("")

                lines += ["</details>", ""]

    lines += [
        "---",
        "> ⚠️ **Disclaimer** — The suggestions above are generated by automated static analysis and serve as a guide only. "
        "Do not apply them blindly — always consider the broader project context, business logic, and runtime constraints "
        "before implementing any fix.",
        "",
        "_🤖 Reviewed by Claude — powered by the team's internal PySpark & clean code standards_",
    ]

    return "\n".join(lines)


def analyze(diff_text: str) -> Optional[ClaudeReviewResult]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning(
            "ANTHROPIC_API_KEY not set — skipping Claude PR review. "
            "Set ANTHROPIC_API_KEY (and optionally ANTHROPIC_BASE_URL, ANTHROPIC_MODEL) to enable."
        )
        return None

    if not diff_text.strip():
        logger.info("Empty diff — skipping Claude PR review.")
        return None

    if len(diff_text) > MAX_DIFF_CHARS:
        diff_text = diff_text[:MAX_DIFF_CHARS] + "\n\n[... diff truncated due to size ...]"

    annotated = _annotate_diff_line_numbers(diff_text)
    logger.info("Calling Claude API for PR review…")

    try:
        data = _call_claude(annotated)
    except json.JSONDecodeError as exc:
        logger.error("Claude returned invalid JSON: %s", exc, exc_info=True)
        return None

    data["logical_groups"], data["groups_capped"] = _cap_groups(data.get("logical_groups", []))
    groups_count = len(data["logical_groups"])
    critical_violations = sum(
        1 for g in data["logical_groups"] if g.get("severity") == "critical"
    )
    capped_note = f" (capped at {MAX_GROUPS})" if data["groups_capped"] else ""
    logger.info(
        "Claude review — verdict: %s, %d logical group(s)%s, %d critical",
        data.get("verdict"), groups_count, capped_note, critical_violations,
    )

    return ClaudeReviewResult(
        verdict=data.get("verdict", "FAIL"),
        summary_body=_build_markdown(data),
        groups_count=groups_count,
        groups_capped=data["groups_capped"],
        critical_violations=critical_violations,
    )
