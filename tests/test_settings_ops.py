from emodul import _settings_ops as ops
from emodul._zone_settings import zones_from_module
from emodul.settings_map import SETTINGS_BY_NAME

from .conftest import menu_with

EMERGENCY = SETTINGS_BY_NAME["emergency-mode"]
SETPOINT = SETTINGS_BY_NAME["heating-setpoint"]
ANTIFREEZE = SETTINGS_BY_NAME["antifreeze"]


def _rows(module_snapshot, settings, values, mt="MI"):
    zones = zones_from_module(module_snapshot)
    return ops.evaluate(ops.targets_for(settings, zones), {mt: menu_with(values)})


def test_every_zone_is_audited_not_just_strefa_1(module_snapshot) -> None:
    # The original bug: only Strefa 1 (30 %) was read, zones 2-6 at 1 % went unseen.
    values = {3145755: 30, 3147803: 1, 3149851: 1, 3153947: 30, 3155995: 1}
    rows = _rows(module_snapshot, [EMERGENCY], values)
    bad = {r["zone"] for r in ops.findings(rows)}
    assert bad == {"Pokój Artur", "Łazienka", "Biuro"}


def test_missing_zone_ido_is_reported_not_skipped(module_snapshot) -> None:
    rows = _rows(module_snapshot, [EMERGENCY], {3145755: 30})
    missing = [r for r in rows if not r["present"]]
    assert {r["zone_no"] for r in missing} == {2, 3, 5, 6}
    assert all(r["display"] == "—" for r in missing)


def test_drift_between_zones(module_snapshot) -> None:
    rows = _rows(module_snapshot, [EMERGENCY], {3145755: 30, 3147803: 1, 3149851: 30, 3153947: 30, 3155995: 30})
    (d,) = ops.drift({"Dom, Piętro": rows}, [EMERGENCY])
    assert d["per_zone"]["Piętro / Pokój Artur"] == "1%"
    assert d["per_zone"]["Piętro / Biuro"] == "30%"


def test_setpoints_differing_per_zone_is_not_drift(module_snapshot) -> None:
    values = {5767171: 220, 5771267: 200, 5775363: 230, 5783555: 210, 5787651: 220}
    rows = _rows(module_snapshot, [SETPOINT], values)
    assert ops.drift({"Dom, Piętro": rows}, [SETPOINT]) == []


def test_module_wide_drift_across_modules(module_snapshot) -> None:
    a = _rows(module_snapshot, [ANTIFREEZE], {1059: 1}, mt="MS")
    b = _rows(module_snapshot, [ANTIFREEZE], {1059: 0}, mt="MS")
    (d,) = ops.drift({"Dom, Parter": a, "Dom, Piętro": b}, [ANTIFREEZE])
    assert d["per_module"] == {"Dom, Parter": "ON", "Dom, Piętro": "OFF"}
