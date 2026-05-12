"""Parses GitHub PR patch hunks to identify which lines belong to new (added) code."""
import re

_HUNK_HEADER_RE = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def parse_added_lines(patch: str) -> set[int]:
    """Returns the set of line numbers (1-based) that were added in the patch."""
    added: set[int] = set()
    current_line = 0

    for line in patch.split("\n"):
        hunk_match = _HUNK_HEADER_RE.match(line)
        if hunk_match:
            current_line = int(hunk_match.group(1)) - 1
        elif line.startswith("+++"):
            pass  # file header — skip
        elif line.startswith("+"):
            current_line += 1
            added.add(current_line)
        elif line.startswith("-"):
            pass  # deleted line — does not advance the new-file counter
        else:
            current_line += 1  # context line

    return added
