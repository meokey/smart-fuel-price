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
