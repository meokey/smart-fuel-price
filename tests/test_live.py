"""Live smoke tests -- hit the real websites. Run: pytest -m live -v"""

import pytest

from sfp_providers.affordableenergy_ca import AffordableEnergyCaProvider
from sfp_providers.citynews_ca import CityNewsCaProvider

pytestmark = pytest.mark.live


@pytest.mark.parametrize(
    "provider_cls, city",
    [
        (CityNewsCaProvider, "toronto"),
        (CityNewsCaProvider, "ottawa"),
        (CityNewsCaProvider, "kitchener"),
        (AffordableEnergyCaProvider, "toronto"),
    ],
)
def test_live_provider_still_parses(provider_cls, city):
    data = provider_cls(city).fetch_data()
    assert data["is_valid"] is True, f"{provider_cls.__name__}/{city} markup may have changed"
    assert data["state"] is not None
    assert 50 < data["current_price"] < 300  # sanity check: cents per litre
