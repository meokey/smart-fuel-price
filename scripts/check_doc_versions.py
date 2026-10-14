#!/usr/bin/env python3
"""Warn when hand-drawn docs lag behind the code version.

Docs that describe code behavior carry a marker like ``as of v2.5.6`` (see
docs/Architecture.md). This script compares each marker against
manifest.json and emits a GitHub ``::warning::`` when the code has moved
on -- it never fails, because docs reasonably lag a release or two.

Update the marker when you touch the doc; update the doc when the warning
shows up and the behavior actually changed.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MARKER_RE = re.compile(r"as of \*{0,2}v(\d+)\.(\d+)\.(\d+)\*{0,2}")


def _parse(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.split("."))


def main() -> int:
    manifest = json.loads(
        (REPO_ROOT / "custom_components" / "smart_fuel_price" / "manifest.json")
        .read_text(encoding="utf-8")
    )
    code_version = _parse(manifest["version"])
    warned = False
    for page in sorted((REPO_ROOT / "docs").glob("*.md")):
        for lineno, line in enumerate(
            page.read_text(encoding="utf-8").splitlines(), 1
        ):
            m = MARKER_RE.search(line)
            if m and _parse(".".join(m.groups())) < code_version:
                print(
                    f"::warning file=docs/{page.name},line={lineno}::"
                    f"doc tracks v{'.'.join(m.groups())} but code is "
                    f"v{manifest['version']} -- refresh the doc if behavior changed"
                )
                warned = True
    if not warned:
        print("doc version markers in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
