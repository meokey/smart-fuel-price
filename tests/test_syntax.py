"""Syntax validation for every Python file in the integration.

Unlike test_all_provider_modules_import_cleanly (which needs modules to
actually import successfully, and therefore can't cover config_flow.py,
sensor.py or __init__.py -- they import `homeassistant`, which isn't
installed here), this only parses each file's grammar via ast.parse().
That's enough to catch a SyntaxError/IndentationError without needing
any of the file's imports to resolve -- exactly the class of bug that
slipped past every other check (this repo's config_flow.py had exactly
this kind of bug ship silently).
"""

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPONENT_ROOT = REPO_ROOT / "custom_components" / "smart_fuel_price"


def _all_python_files():
    return sorted(COMPONENT_ROOT.rglob("*.py"))


@pytest.mark.parametrize(
    "path", _all_python_files(), ids=lambda p: str(p.relative_to(COMPONENT_ROOT))
)
def test_python_file_has_valid_syntax(path):
    source = path.read_text(encoding="utf-8")
    ast.parse(source, filename=str(path))  # raises SyntaxError if malformed


# HA APIs that were removed in recent versions. A syntax check cannot catch
# their use (attribute access is grammatically valid); this test scans the
# *code* tokens (comments and strings excluded) so a removed API can never
# ship silently again -- v2.3.19 did exactly that with the singular
# async_forward_entry_setup and took every sensor down to `unavailable`.
REMOVED_HA_APIS = [
    # (regex, why it's banned)
    (
        r"async_forward_entry_setup(?!s)\s*\(",
        "the singular async_forward_entry_setup was removed from HA; "
        "forward one platform at a time via async_forward_entry_setups(entry, [platform])",
    ),
]


def _code_text(path: Path) -> str:
    """Source with comments and string literals stripped (tokenize-based)."""
    import io
    import tokenize

    src = path.read_text(encoding="utf-8")
    keep = {
        tokenize.NAME, tokenize.NUMBER, tokenize.OP,
        tokenize.NEWLINE, tokenize.NL, tokenize.INDENT, tokenize.DEDENT,
    }
    return " ".join(
        tok.string
        for tok in tokenize.generate_tokens(io.StringIO(src).readline)
        if tok.type in keep
    )


def test_no_removed_ha_apis():
    import re

    offenders = []
    for path in _all_python_files():
        code = _code_text(path)
        for pattern, reason in REMOVED_HA_APIS:
            if re.search(pattern, code):
                offenders.append(f"{path.relative_to(COMPONENT_ROOT)}: {reason}")
    assert not offenders, "removed HA API(s) in use:\n" + "\n".join(offenders)
