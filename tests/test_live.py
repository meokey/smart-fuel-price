"""Live smoke tests -- hit the real websites. Run: pytest -m live -v

Coverage is derived from each provider's own get_supported_cities(), so
it automatically grows/shrinks as CITY_MAP entries are added or removed
-- no separate list to keep in sync by hand.
"""

import pytest

from sfp_providers.affordableenergy_ca import AffordableEnergyCaProvider
from sfp_providers.citynews_ca import CityNewsCaProvider

pytestmark = pytest.mark.live

# Known, currently-expected failures. Keep them here (not silently
# skipped) so a city that's genuinely still broken shows as an expected
# failure (xfail), while anything NEW that breaks still shows up as a
# real, attention-grabbing failure.
_KNOWN_FAILURES = {
    (CityNewsCaProvider, "calgary"): "GasBuddy widget chain parked, see citynews_ca.py",
}

_CITY_BASED_PROVIDERS = (CityNewsCaProvider, AffordableEnergyCaProvider)


def _cases():
    cases = []
    for provider_cls in _CITY_BASED_PROVIDERS:
        for city in provider_cls.get_supported_cities():
            marks = []
            reason = _KNOWN_FAILURES.get((provider_cls, city))
            if reason:
                marks.append(pytest.mark.xfail(reason=reason, strict=False))
            cases.append(
                pytest.param(provider_cls, city, id=f"{provider_cls.__name__}-{city}", marks=marks)
            )
    return cases


@pytest.mark.parametrize("provider_cls, city", _cases())
def test_live_provider_still_parses(provider_cls, city):
    data = provider_cls(city).fetch_data()
    assert data["is_valid"] is True, f"{provider_cls.__name__}/{city} markup may have changed"
    assert data["state"] is not None
    assert 50 < data["current_price"] < 300  # sanity check: cents per litre
