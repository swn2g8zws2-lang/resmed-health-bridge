from datetime import date

import pytest

from resmed_health_bridge.adapters.myair import UnavailableMyAirAdapter


def test_unofficial_adapter_does_not_guess_endpoints():
    with pytest.raises(NotImplementedError, match="unofficial"):
        UnavailableMyAirAdapter().fetch_range(date(2026, 1, 1), date(2026, 1, 2))
