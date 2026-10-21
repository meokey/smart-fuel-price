"""Syntax/consistency checks for the integration's static asset files.

These need no network and no Home Assistant -- just json.load(). A
malformed translations/en.json takes down the ENTIRE integration at HA
startup (not just one sensor), so this is cheap insurance worth having.
"""

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS_PATH = REPO_ROOT / "custom_components/smart_fuel_price/translations/en.json"
MANIFEST_PATH = REPO_ROOT / "custom_components/smart_fuel_price/manifest.json"
HACS_JSON_PATH = REPO_ROOT / "hacs.json"


def _load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)  # raises json.JSONDecodeError on malformed JSON


def test_translations_en_json_is_valid():
    _load(TRANSLATIONS_PATH)


def test_manifest_json_is_valid():
    _load(MANIFEST_PATH)


def test_hacs_json_is_valid():
    _load(HACS_JSON_PATH)


def test_manifest_requirements_stay_empty():
    """manifest requirements must stay [] (#91).

    hassfest (validate_custom_requirements, HA 2026.10+) rejects any
    requirement that is itself a dependency of Home Assistant ("must
    not be listed in the manifest of a custom integration") -- this is
    why voluptuous was removed. voluptuous and requests are HA core
    dependencies, so they are importable at runtime without being
    listed. The standalone hassfest action cannot catch a regression
    (it builds its core-requirements list from the repo-root
    requirements.txt, which is empty of package names), so this test
    is the guard: if a real third-party dependency is ever needed,
    update this test deliberately in the same change.
    """
    assert _load(MANIFEST_PATH)["requirements"] == []


def test_translations_cover_every_config_flow_error_code():
    """Every errors["base"] = "..." value config_flow.py can set needs a
    matching translation, or HA shows the user the raw, untranslated key."""
    translations = _load(TRANSLATIONS_PATH)
    expected_errors = {
        "unsupported_city",
        "station_ids_required",
        "fuel_grade_required",
        "invalid_station_id",
        "unknown_provider",
    }
    assert expected_errors.issubset(translations["config"]["error"].keys())


def test_translations_cover_every_config_flow_step():
    """Every step_id passed to async_show_form() needs a matching step entry."""
    translations = _load(TRANSLATIONS_PATH)
    expected_steps = {"user", "details"}
    assert expected_steps.issubset(translations["config"]["step"].keys())
