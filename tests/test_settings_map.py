import pytest

from emodul.settings_map import SETTINGS_BY_NAME


@pytest.mark.parametrize(
    ("name", "zone_no", "ido"),
    [
        # IDOs read from a live L-4X WIFI 1.0.13 MI menu.
        ("emergency-mode", 1, 3145755),
        ("emergency-mode", 2, 3147803),
        ("emergency-mode", 6, 3155995),
        ("sigma-range", 3, 3149845),
        ("weather-control", 5, 3153926),
        ("hysteresis", 2, 3147824),
        ("heating", 2, 5771265),
        ("heating-setpoint", 5, 5783555),
    ],
)
def test_ido_for_zone(name: str, zone_no: int, ido: int) -> None:
    assert SETTINGS_BY_NAME[name].ido_for(zone_no) == ido


def test_module_wide_ignores_zone() -> None:
    s = SETTINGS_BY_NAME["antifreeze"]
    assert not s.zone_scoped
    assert s.ido_for(None) == s.ido == 1059
    assert s.ido_for(3) == 1059


def test_zone_scoped_requires_zone() -> None:
    with pytest.raises(ValueError, match="zone-scoped"):
        SETTINGS_BY_NAME["emergency-mode"].ido_for(None)


def test_relay_delay_is_seconds() -> None:
    s = SETTINGS_BY_NAME["relay-delay"]
    assert s.decode(3) == "3 s"
    assert s.encode("5") == 5
