import pytest

from emodul._zone_settings import ZoneRef, expand, select_zones, zones_from_module
from emodul.settings_map import SETTINGS_BY_NAME


def test_zones_from_module_maps_index_to_strefa(module_snapshot: dict) -> None:
    zones = zones_from_module(module_snapshot)
    assert [(z.no, z.name) for z in zones] == [
        (1, "Pokój Karol"),
        (2, "Pokój Artur"),
        (3, "Łazienka"),
        (5, "Sypialnia"),
        (6, "Biuro"),
    ]


def test_select_by_number_and_name(module_snapshot: dict) -> None:
    zones = zones_from_module(module_snapshot)
    assert select_zones(zones, "5") == [ZoneRef(5, "Sypialnia")]
    assert select_zones(zones, "artur") == [ZoneRef(2, "Pokój Artur")]


def test_exact_name_beats_substring() -> None:
    zones = [ZoneRef(1, "Łazienka"), ZoneRef(2, "Łazienka dolna")]
    assert select_zones(zones, "Łazienka") == [ZoneRef(1, "Łazienka")]


@pytest.mark.parametrize(("query", "msg"), [("Pokój", "ambiguous"), ("4", "no zone"), ("Garaż", "no zone")])
def test_select_rejects_ambiguous_or_missing(module_snapshot: dict, query: str, msg: str) -> None:
    with pytest.raises(ValueError, match=msg):
        select_zones(zones_from_module(module_snapshot), query)


def test_expand(module_snapshot: dict) -> None:
    zones = zones_from_module(module_snapshot)
    per_zone = expand(SETTINGS_BY_NAME["emergency-mode"], zones)
    assert [(t.zone.no, t.ido) for t in per_zone] == [
        (1, 3145755), (2, 3147803), (3, 3149851), (5, 3153947), (6, 3155995)
    ]
    module_wide = expand(SETTINGS_BY_NAME["antifreeze"], zones)
    assert [(t.zone, t.ido) for t in module_wide] == [(None, 1059)]
