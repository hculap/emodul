"""Shared fixtures: a trimmed module snapshot + MI menu shaped like a real L-4X."""
from __future__ import annotations

import pytest


def _zone(index: int, name: str, state: str = "noAlarm") -> dict:
    return {
        "zone": {"id": 9002 + 17 * index, "index": index, "zoneState": state},
        "description": {"name": name},
    }


@pytest.fixture
def module_snapshot() -> dict:
    # Strefa 4 unused, one null slot, one unregistered — as seen on Piętro.
    return {
        "zones": {
            "elements": [
                _zone(0, "Pokój Karol"),
                _zone(1, "Pokój Artur"),
                _zone(2, "Łazienka"),
                None,
                _zone(4, "Sypialnia"),
                _zone(5, "Biuro"),
                _zone(6, "Strefa 7", state="zoneUnregistered"),
            ]
        }
    }


def menu_with(values: dict[int, int]) -> dict:
    """Minimal menu response containing the given ido → value items."""
    return {
        "data": {
            "elements": [
                {"id": ido, "access": True, "duringChange": "f", "params": {"value": v}}
                for ido, v in values.items()
            ]
        }
    }
