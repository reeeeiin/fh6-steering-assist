# -*- coding: utf-8 -*-
"""Print the build id for the version string.

The number is how many commits are behind this build, so it only ever goes
up and it points at exactly one state of the source. A side branch adds its
letter, which is how a trial build is told apart from the release line.
"""
import re
import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000


def _git(cwd, *args) -> str:
    try:
        out = subprocess.run(("git",) + args, capture_output=True, text=True,
                             timeout=10, cwd=cwd or None,
                             creationflags=CREATE_NO_WINDOW
                             if sys.platform == "win32" else 0)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def branch_mark(branch: str) -> str:
    """v2 is the release line and adds nothing. v2b and the like are trials
    and carry their letter, so a trial build can never be mistaken for one."""
    m = re.match(r"^v\d+(?:\.\d+)?([a-z]+)$", branch or "")
    return m.group(1) if m else ""


def series_start(cwd: str = "") -> str:
    """The commit that last set APP_SERIES.

    Everything after it is a build of that series, so the number resets
    when a new one opens. Counted across the whole history instead, the
    first build of 2.1 came out as 2.1.172 and read as though a hundred
    and seventy-two patches had been and gone.
    """
    return _git(cwd, "log", "-1", "--format=%H", "-G", 'APP_SERIES = "',
                "--", "forza_assist_lite.py")


def build_id(cwd: str = "") -> str:
    since = series_start(cwd)
    # no history to read - a shallow copy, or no git at all - so fall back
    # to counting everything, which is wrong by a lot but never repeats
    span = ("%s..HEAD" % since) if since else "HEAD"
    count = _git(cwd, "rev-list", "--count", span)
    if not count.isdigit():
        return "dev"
    return count + branch_mark(_git(cwd, "rev-parse", "--abbrev-ref", "HEAD"))


if __name__ == "__main__":
    print(build_id())
