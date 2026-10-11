"""High-level mapping: friendly name → (menu_type, ido, encoder, decoder, recommendation).

Lets the CLI talk in `emergency-mode 30%` instead of `MI 3145755 30`.
Recommendations are heuristic, tuned for Polish floor heating on a TECH L-4X WIFI.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Per-zone IDO layout on TECH L-4X: "Strefa N" items sit at the Strefa 1 IDO
# plus (N-1) * stride. Two blocks are known (verified on two L-4X WIFI 1.0.13):
ZONE_STRIDE_MI = 2048        # 0x300000 block: sensor, actuators, weather, presets…
ZONE_STRIDE_HEATCOOL = 4096  # 0x580000 block: Grzanie / Chłodzenie per zone


@dataclass(frozen=True)
class Setting:
    name: str           # CLI-friendly slug: "emergency-mode"
    pl_label: str       # "Tryb awaryjny"
    menu_type: str      # "MU" | "MI" | "MS"
    ido: int            # module-wide IDO, or the Strefa 1 IDO for zone-scoped settings
    kind: str           # "tenths_c" | "percent" | "bool" | "hhmm" | "minutes" | "seconds" | "raw"
    category: str       # "actuator" | "schedule" | "safety" | "diagnostic" | "ux"
    note: str = ""      # short PL description
    recommend: tuple[Any, ...] = ()  # acceptable values for audit
    bad: tuple[Any, ...] = ()        # known-bad values
    zone_stride: int | None = None   # set → one value per zone ("Strefa N")
    per_zone_differs: bool = False   # zones legitimately differ (setpoints) → no drift

    @property
    def zone_scoped(self) -> bool:
        return self.zone_stride is not None

    def ido_for(self, zone_no: int | None) -> int:
        """IDO for "Strefa <zone_no>" (1-based); module-wide settings ignore zone_no."""
        if self.zone_stride is None:
            return self.ido
        if zone_no is None or zone_no < 1:
            raise ValueError(f"{self.name} is zone-scoped; pass a zone number >= 1")
        return self.ido + (zone_no - 1) * self.zone_stride

    def encode(self, user_value: Any) -> int:
        if self.kind == "tenths_c":
            return int(round(float(user_value) * 10))
        if self.kind in ("percent", "minutes", "seconds"):
            return int(user_value)
        if self.kind == "bool":
            s = str(user_value).lower()
            if s in ("1", "true", "on", "yes", "tak"):
                return 1
            if s in ("0", "false", "off", "no", "nie"):
                return 0
            return int(user_value)
        if self.kind == "hhmm":
            # accept "hh:mm" or minutes int
            s = str(user_value)
            if ":" in s:
                h, m = s.split(":", 1)
                return int(h) * 60 + int(m)
            return int(s)
        if self.kind == "raw":
            return int(user_value)
        raise ValueError(f"unknown kind {self.kind}")

    def decode(self, wire_value: Any) -> str:
        if wire_value is None:
            return "—"
        if self.kind == "tenths_c":
            return f"{wire_value / 10:.1f} °C"
        if self.kind == "percent":
            return f"{wire_value}%"
        if self.kind == "bool":
            return "ON" if wire_value else "OFF"
        if self.kind == "hhmm":
            return f"{wire_value // 60:02d}:{wire_value % 60:02d}"
        if self.kind == "minutes":
            return f"{wire_value} min"
        if self.kind == "seconds":
            return f"{wire_value} s"
        return str(wire_value)

    def audit(self, wire_value: Any) -> tuple[str, str]:
        """Return (severity, message). Severity: 'ok' | 'warn' | 'bad' | 'info'."""
        if wire_value is None:
            return ("info", "brak odczytu")
        if self.bad and wire_value in self.bad:
            return ("bad", f"niezalecana wartość {self.decode(wire_value)}")
        if self.recommend and wire_value not in self.recommend:
            rec = "/".join(self.decode(v) for v in self.recommend)
            return ("warn", f"warto rozważyć: {rec}")
        return ("ok", "")


# All currently known settings worth surfacing.
# Recommendations are tuples of WIRE values (not display values).
SETTINGS: list[Setting] = [
    # ------- safety / actuator behaviour -------
    Setting(
        "emergency-mode", "Tryb awaryjny", "MI", 3145755, "percent", "safety",
        note="otwarcie siłownika gdy padnie czujnik (default fabryczny: 50%)",
        recommend=tuple(range(20, 51)),
        bad=tuple(range(0, 11)),
        zone_stride=ZONE_STRIDE_MI,
    ),
    Setting(
        "hysteresis", "Histereza", "MI", 3145776, "tenths_c", "actuator",
        note="szerokość strefy nieczułości regulatora",
        recommend=(3, 4, 5),  # 0.3 - 0.5 °C
        bad=(1, 2),
        zone_stride=ZONE_STRIDE_MI,
    ),
    Setting(
        "sigma-range", "SIGMA Zakres", "MI", 3145749, "tenths_c", "actuator",
        note="szerokość pasma proporcjonalnego dla SIGMA",
        recommend=tuple(range(20, 51)),  # 2.0 - 5.0 °C
        bad=(10,),  # 1.0 °C (minimum, agresywne)
        zone_stride=ZONE_STRIDE_MI,
    ),
    Setting(
        "actuator-min-open", "Minimalne otwarcie siłownika", "MI", 3145750, "percent",
        "actuator", note="minimalne uchylenie głowicy",
        zone_stride=ZONE_STRIDE_MI,
    ),
    Setting(
        "actuator-max-open", "Maksymalne otwarcie siłownika", "MI", 3145751, "percent",
        "actuator", note="maksymalne uchylenie głowicy",
        zone_stride=ZONE_STRIDE_MI,
    ),
    Setting(
        "actuator-protection", "Zabezpieczenie siłowników", "MI", 3145753, "bool", "safety",
        note="zabezpieczenie temperaturowe siłowników",
        recommend=(1,),
        zone_stride=ZONE_STRIDE_MI,
    ),
    Setting(
        "actuator-protection-range", "Zabezpieczenie siłowników — zakres", "MI", 3145754,
        "tenths_c", "safety",
        zone_stride=ZONE_STRIDE_MI,
    ),
    # ------- weather / cooling -------
    Setting(
        "weather-control", "Sterowanie pogodowe", "MI", 3145734, "bool", "actuator",
        note="krzywa grzewcza wg temperatury zewnętrznej — wymaga czujnika pogody",
        zone_stride=ZONE_STRIDE_MI,
    ),
    Setting(
        "cooling", "Chłodzenie strefy", "MI", 5769217, "bool", "schedule",
        note="tryb chłodzenia — włącz tylko gdy faktycznie sterujesz chłodzeniem",
        recommend=(0,),
        zone_stride=ZONE_STRIDE_HEATCOOL,
    ),
    Setting(
        "cooling-setpoint", "Chłodzenie — stała temp.", "MI", 5769219, "tenths_c", "schedule",
        zone_stride=ZONE_STRIDE_HEATCOOL, per_zone_differs=True,
    ),
    Setting(
        "heating", "Grzanie strefy", "MI", 5767169, "bool", "schedule",
        note="powinno być ON",
        recommend=(1,),
        zone_stride=ZONE_STRIDE_HEATCOOL,
    ),
    Setting(
        "heating-setpoint", "Grzanie — stała temp.", "MI", 5767171, "tenths_c", "schedule",
        zone_stride=ZONE_STRIDE_HEATCOOL, per_zone_differs=True,
    ),
    # ------- comfort presets -------
    Setting(
        "preset-holiday", "Tryb urlopowy", "MI", 3145738, "tenths_c", "schedule",
        note="setpoint dla trybu urlopowego",
        zone_stride=ZONE_STRIDE_MI, per_zone_differs=True,
    ),
    Setting(
        "preset-eco", "Tryb ekonomiczny", "MI", 3145739, "tenths_c", "schedule",
        zone_stride=ZONE_STRIDE_MI, per_zone_differs=True,
    ),
    Setting(
        "preset-comfort", "Tryb komfortowy", "MI", 3145740, "tenths_c", "schedule",
        zone_stride=ZONE_STRIDE_MI, per_zone_differs=True,
    ),
    # ------- optimum start -------
    Setting(
        "optimum-start", "Optimum start", "MI", 3145742, "bool", "actuator",
        note="włącz aby strefa osiągała setpoint o zaplanowanej godzinie",
        zone_stride=ZONE_STRIDE_MI,
    ),
    Setting(
        "optimum-min-time", "Optimum start — min czas", "MI", 3145743, "hhmm", "actuator",
        zone_stride=ZONE_STRIDE_MI,
    ),
    Setting(
        "optimum-max-time", "Optimum start — max czas", "MI", 3145744, "hhmm", "actuator",
        zone_stride=ZONE_STRIDE_MI,
    ),
    # ------- sensor -------
    Setting(
        "sensor-calibration", "Kalibracja czujnika", "MI", 3145777, "tenths_c", "actuator",
        note="korekta odczytu czujnika pokojowego (zwykle 0)",
        recommend=(0,),
        zone_stride=ZONE_STRIDE_MI, per_zone_differs=True,
    ),
    # ------- pump -------
    Setting(
        "pump-antistop", "Antystop pomp", "MI", 1045, "bool", "safety",
        note="okresowe uruchamianie pompy poza sezonem grzewczym",
        recommend=(1,),
    ),
    # ------- service menu (PIN 5162) -------
    Setting(
        "antifreeze", "Ochrona przeciwzamrożeniowa", "MS", 1059, "bool", "safety",
        note="włącza grzanie awaryjne przy ryzyku zamrożenia",
        recommend=(1,),
    ),
    Setting(
        "relay-delay", "Opóźnienie przekaźnika", "MS", 1056, "seconds", "actuator",
    ),
    Setting(
        "temp-max", "Maks. temperatura setpointu", "MS", 1057, "tenths_c", "safety",
    ),
    Setting(
        "temp-min", "Min. temperatura setpointu", "MS", 1058, "tenths_c", "safety",
    ),
    Setting(
        "diagnostic-file", "Plik diagnostyczny", "MS", 1054, "bool", "diagnostic",
        note="zostaw OFF po komisjonowaniu",
        recommend=(0,),
    ),
    Setting(
        "show-all", "Pokaż wszystko (serwisowe)", "MS", 1055, "bool", "diagnostic",
        recommend=(0,),
    ),
]


SETTINGS_BY_NAME: dict[str, Setting] = {s.name: s for s in SETTINGS}


def find_value(menu_data: dict, ido: int) -> Any:
    """Walk a menu response and return params.value (or top-level value) for an ido."""
    item = find_item(menu_data, ido)
    if item is None:
        return None
    p = item.get("params") or {}
    if "value" in p:
        return p["value"]
    return item.get("value")


def find_item(menu_data: dict, ido: int) -> dict | None:
    """Return the full menu element with given id, or None."""
    def walk(obj):
        if isinstance(obj, dict):
            if obj.get("id") == ido:
                return obj
            for v in obj.values():
                r = walk(v)
                if r is not None:
                    return r
        elif isinstance(obj, list):
            for x in obj:
                r = walk(x)
                if r is not None:
                    return r
        return None
    return walk(menu_data)


def is_accessible(item: dict | None) -> bool:
    """Whether the controller currently allows reading/writing this item.

    Borrowed from HA `switch.py:62` etc — TECH returns `access` as a per-item
    server-side gate; some items are temporarily locked (PIN, mode, season).
    Default to True if missing so unknown items don't get silently hidden.
    """
    if item is None:
        return False
    return item.get("access", True) is not False
