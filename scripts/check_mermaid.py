#!/usr/bin/env python3
"""Structural lint for Mermaid flowchart blocks in docs/.

Catches the common breakages (unbalanced quotes, dangling edges,
duplicate node ids) without needing a renderer. Usage::

    python scripts/check_mermaid.py docs/

Exits nonzero on the first problem found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BLOCK_RE = re.compile(r"```mermaid\n(.*?)```", re.S)
NODE_RE = re.compile(r"(^|[\s;])([A-Za-z][A-Za-z0-9_]*)(?:\[|\(|\{)")


def check_block(text: str, label: str) -> list[str]:
    errors: list[str] = []
    lines = text.strip().splitlines()
    if not lines or not lines[0].strip().startswith("flowchart"):
        return [f"{label}: block does not start with a flowchart declaration"]
    seen: dict[str, int] = {}
    for lineno, line in enumerate(lines, 1):
        s = line.strip()
        if not s or s.startswith(("subgraph", "end", "direction")):
            continue
        if s.count('"') % 2:
            errors.append(f"{label}:{lineno}: unbalanced quotes: {s[:70]}")
        if re.search(r"-->\s*$", s):
            errors.append(f"{label}:{lineno}: edge with no target: {s[:70]}")
        for m in NODE_RE.finditer(s):
            nid = m.group(2)
            if nid in ("flowchart",):
                continue
            if nid in seen:
                errors.append(
                    f"{label}:{lineno}: node id '{nid}' redefined "
                    f"(first at line {seen[nid]})"
                )
            else:
                seen[nid] = lineno
    return errors


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("docs")
    errors: list[str] = []
    files = sorted(target.glob("*.md")) if target.is_dir() else [target]
    blocks = 0
    for page in files:
        for i, m in enumerate(
            BLOCK_RE.findall(page.read_text(encoding="utf-8"))
        ):
            blocks += 1
            errors.extend(check_block(m, f"{page.name}#{i}"))
    if errors:
        print("\n".join(errors))
        return 1
    print(f"{blocks} mermaid blocks OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
