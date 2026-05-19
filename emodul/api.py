"""Thin httpx wrapper around the eModul.pl REST API.

Endpoints reverse-engineered from the Angular SPA bundle (see README for the map).
All temperatures on the wire are integer tenths of °C — this layer keeps them
as integers; conversion lives in `emodul.format`.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable

import httpx


def _is_changing(value: Any) -> bool:
    """TECH `duringChange` flag — sometimes bool, sometimes 't'/'f' string."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("t", "true", "1")
    return bool(value)


class EmodulApiError(RuntimeError):
    def __init__(self, status: int, body: Any, path: str) -> None:
        super().__init__(f"API {status} on {path}: {body!r}")
        self.status = status
        self.body = body
        self.path = path


class ApiClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        user_id: int | None = None,
        timeout: float = 30.0,
        refresher: Callable[["ApiClient"], None] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.user_id = user_id
        self.refresher = refresher
        self._refreshing = False  # guard against recursion during re-auth
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "User-Agent": "emodul-cli/0.1",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ApiClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        parse_json: bool = True,
    ) -> Any:
        r = self._client.request(method, path, headers=self._headers(), json=json_body)
        if (
            r.status_code == 401
            and self.refresher is not None
            and not self._refreshing
        ):
            self._refreshing = True
            try:
                self.refresher(self)  # mutates self.token on success; raises otherwise
            finally:
                self._refreshing = False
            r = self._client.request(
                method, path, headers=self._headers(), json=json_body
            )
        if r.status_code >= 400:
            try:
                body = r.json()
            except Exception:
                body = r.text
            raise EmodulApiError(r.status_code, body, path)
        if not parse_json:
            return r.text
        if "application/json" in r.headers.get("content-type", ""):
            return r.json()
        return r.text

    # -- shorthand --
    def get(self, path: str, **kw: Any) -> Any:
        return self._request("GET", path, **kw)

    def post(self, path: str, body: Any = None, **kw: Any) -> Any:
        return self._request("POST", path, json_body=body if body is not None else {}, **kw)

    def put(self, path: str, body: Any = None, **kw: Any) -> Any:
        return self._request("PUT", path, json_body=body if body is not None else {}, **kw)

    def delete(self, path: str, **kw: Any) -> Any:
        return self._request("DELETE", path, **kw)

    def options(self, path: str, **kw: Any) -> Any:
        # eModul uses OPTIONS as a CSV download verb (yes, really).
        r = self._client.request("OPTIONS", path, headers=self._headers())
        if r.status_code >= 400:
            try:
                body = r.json()
            except Exception:
                body = r.text
            raise EmodulApiError(r.status_code, body, path)
        return r.text

    # ---------------- Auth ----------------
    def authenticate(self, username: str, password: str, language_id: int = 18) -> dict:
        return self.post(
            "/api/v1/authentication",
            {
                "username": username,
                "password": password,
                "rememberMe": True,
                "languageId": language_id,
                "remote": False,
            },
        )

    # ---------------- User ----------------
    def user_info(self) -> dict:
        return self.get(f"/api/v1/users/{self.user_id}/info")

    def last_modification(self) -> str:
        return self.get(f"/api/v1/users/{self.user_id}/last_modification", parse_json=False)

    # ---------------- Modules ----------------
    def list_modules(self) -> list[dict]:
        return self.get(f"/api/v1/users/{self.user_id}/modules")

    def get_module(self, udid: str) -> dict:
        return self.get(f"/api/v1/users/{self.user_id}/modules/{udid}")

    def get_tiles(self, udid: str) -> dict:
        return self.get(f"/api/v1/users/{self.user_id}/modules/{udid}/tiles")

    def force_sync(self, udid: str) -> dict:
        return self.post(f"/api/v1/users/{self.user_id}/modules/{udid}/force_data_sync")

    def update_module_info(self, udid: str, name: str, additional_information: str = "") -> dict:
        return self.put(
            f"/api/v1/users/{self.user_id}/modules/{udid}/info/data",
            {"module_name": name, "additional_information": additional_information},
        )

    def set_tile_order(self, udid: str, order: str, type_: str = "tiles") -> dict:
        return self.post(
            f"/api/v1/users/{self.user_id}/modules/{udid}/tiles/order",
            {"order": order, "type": type_},
        )

    # ---------------- Zones ----------------
    def _zones_path(self, udid: str) -> str:
        return f"/api/v1/users/{self.user_id}/modules/{udid}/zones"

    def set_zone_constant_temp(
        self, udid: str, *, mode_id: int, zone_id: int, set_temperature_int10: int
    ) -> dict:
        return self.post(
            self._zones_path(udid),
            {
                "mode": {
                    "id": mode_id,
                    "parentId": zone_id,
                    "mode": "constantTemp",
                    "constTempTime": 60,
                    "setTemperature": set_temperature_int10,
                    "scheduleIndex": 0,
                }
            },
        )

    def set_zone_time_limit(
        self,
        udid: str,
        *,
        mode_id: int,
        zone_id: int,
        set_temperature_int10: int,
        minutes: int,
    ) -> dict:
        return self.post(
            self._zones_path(udid),
            {
                "mode": {
                    "id": mode_id,
                    "parentId": zone_id,
                    "mode": "timeLimit",
                    "constTempTime": minutes,
                    "setTemperature": set_temperature_int10,
                    "scheduleIndex": 0,
                }
            },
        )

    def attach_global_schedule(
        self,
        udid: str,
        *,
        zone_id: int,
        mode_id: int,
        schedule_element: dict,
    ) -> dict:
        """Switch a zone to a globalSchedule by re-POSTing the schedule with
        this zone in `setInZones`. Live-confirmed against the API (POST /zones
        with mode=globalSchedule returns 422 'Invalid JSON data'; this endpoint
        is the right one)."""
        p0 = [i for i in (schedule_element.get("p0Intervals") or []) if i.get("start", 9999) <= 1440]
        p1 = [i for i in (schedule_element.get("p1Intervals") or []) if i.get("start", 9999) <= 1440]
        body = {
            "modeId": mode_id,
            "schedule": {
                "id": schedule_element["id"],
                "index": schedule_element["index"],
                "p0Days": schedule_element.get("p0Days") or [],
                "p0Intervals": p0,
                "p0SetbackTemp": schedule_element.get("p0SetbackTemp", 200),
                "p1Days": schedule_element.get("p1Days") or [],
                "p1Intervals": p1,
                "p1SetbackTemp": schedule_element.get("p1SetbackTemp", 200),
            },
            "scheduleName": schedule_element.get("name") or "",
            "setInZones": [{"modeId": mode_id, "zoneId": zone_id}],
        }
        return self.post(f"{self._zones_path(udid)}/{zone_id}/global_schedule", body)


    def set_zone_state(self, udid: str, zone_id: int, state: str) -> dict:
        if state not in ("zoneOn", "zoneOff"):
            raise ValueError("state must be zoneOn or zoneOff")
        return self.post(self._zones_path(udid), {"zone": {"id": zone_id, "zoneState": state}})

    def rename_zone(
        self,
        udid: str,
        *,
        zone_id: int,
        description_id: int,
        name: str,
        icon_id: int = 0,
    ) -> dict:
        return self.put(
            f"{self._zones_path(udid)}/{zone_id}",
            {"description_id": description_id, "name": name, "icons_id": icon_id},
        )

    def set_local_schedule(
        self, udid: str, *, zone_id: int, mode_id: int, schedule: dict
    ) -> dict:
        return self.post(
            f"{self._zones_path(udid)}/{zone_id}/local_schedule",
            {"modeId": mode_id, "schedule": schedule},
        )

    def set_global_schedule(
        self,
        udid: str,
        *,
        zone_id: int,
        mode_id: int,
        schedule: dict,
        schedule_name: str,
        set_in_zones: list[dict],
    ) -> dict:
        return self.post(
            f"{self._zones_path(udid)}/{zone_id}/global_schedule",
            {
                "modeId": mode_id,
                "schedule": schedule,
                "scheduleName": schedule_name,
                "setInZones": set_in_zones,
            },
        )

    # ---------------- Menu (MU / MI / MS / MP) ----------------
    @staticmethod
    def _format_pin_chain(pin_chain: list[tuple[int, str]] | None) -> str:
        if not pin_chain:
            return ""
        return "/" + ",".join(f"{int(i)}:{p}" for i, p in pin_chain)

    def get_menu(
        self,
        udid: str,
        menu_type: str,
        pin_chain: list[tuple[int, str]] | None = None,
    ) -> dict:
        base = f"/api/v1/users/{self.user_id}/modules/{udid}/menu/{menu_type}"
        return self.get(base + self._format_pin_chain(pin_chain))

    def set_menu_param(self, udid: str, menu_type: str, ido: int, body: dict) -> dict:
        return self.post(
            f"/api/v1/users/{self.user_id}/modules/{udid}/menu/{menu_type}/ido/{ido}",
            body,
        )

    # ---------------- Statistics (no /users/ prefix!) ----------------
    def stats_available(self, udid: str) -> dict:
        return self.get(f"/api/v1/modules/{udid}/statistics/available")

    def stats_linear(
        self,
        udid: str,
        *,
        period: str = "day",
        month: int | None = None,
        year: int | None = None,
    ) -> dict:
        if month and year:
            return self.get(
                f"/api/v1/modules/{udid}/statistics/linear/range/month/{month}/year/{year}"
            )
        return self.get(f"/api/v1/modules/{udid}/statistics/linear/range/{period}")

    def stats_column(
        self,
        udid: str,
        *,
        state: str,
        period: str = "day",
        month: int | None = None,
        year: int | None = None,
    ) -> dict:
        if month and year:
            return self.get(
                f"/api/v1/modules/{udid}/statistics/{state}/range/month/{month}/year/{year}"
            )
        return self.get(f"/api/v1/modules/{udid}/statistics/{state}/range/{period}")

    def stats_csv(
        self,
        udid: str,
        *,
        state: str,
        period: str = "day",
        language: str = "pl",
        month: int | None = None,
        year: int | None = None,
    ) -> str:
        if month and year:
            path = (
                f"/api/v1/modules/{udid}/statistics/{state}/range/month/{month}/"
                f"year/{year}/language/{language}"
            )
        else:
            path = f"/api/v1/modules/{udid}/statistics/{state}/range/{period}/language/{language}"
        return self.options(path)

    # ---------------- Alarms ----------------
    def alarm_history(
        self, udid: str, *, from_date: str, to_date: str, alarm_type: str = "all"
    ) -> dict:
        return self.get(
            f"/api/v1/users/{self.user_id}/modules/{udid}"
            f"/alarm_history/from/{from_date}/to/{to_date}/type/{alarm_type}"
        )

    def acknowledge_alarm(self, udid: str, alarm_id: int) -> dict:
        return self.post(
            f"/api/v1/users/{self.user_id}/modules/{udid}/alarm_history",
            {"id": alarm_id},
        )

    # ---------------- I18n ----------------
    def i18n(self, lang: str = "pl") -> dict:
        return self.get(f"/api/v1/i18n/{lang}")

    # ---------------- Polling ----------------
    def update_data(
        self,
        udid: str,
        *,
        parents: list[str] | None = None,
        alarm_ids: list[int] | None = None,
        last_update: int | None = None,
    ) -> dict:
        parents_str = json.dumps(parents or [], separators=(",", ":"))
        alarms_str = json.dumps(alarm_ids or [], separators=(",", ":"))
        path = (
            f"/api/v1/users/{self.user_id}/modules/{udid}"
            f"/update/data/parents/{parents_str}/alarm_ids/{alarms_str}"
        )
        if last_update is not None:
            path += f"/last_update/{last_update}"
        return self.get(path)

    # ---------------- Notifications ----------------
    def get_notification_times(self, udid: str) -> dict:
        return self.get(f"/api/v1/users/{self.user_id}/modules/{udid}/notifications/time")

    def set_notification_time(
        self,
        udid: str,
        *,
        notification_type: str,
        start: str,
        end: str,
        enable: bool,
        id_: int,
    ) -> dict:
        return self.put(
            f"/api/v1/users/{self.user_id}/modules/{udid}/notifications/time",
            {
                "data": {
                    "notification_type": notification_type,
                    "start": start,
                    "end": end,
                    "enable": enable,
                    "id": id_,
                }
            },
        )

    # ---------------- Write-settle helpers (`duringChange:"t"` window) ----------------
    def wait_until_settled(
        self,
        check: Callable[[], bool],
        *,
        timeout: float = 30.0,
        interval: float = 2.0,
    ) -> bool:
        """Poll `check()` until it returns True (settled) or timeout elapses.

        Borrowed from HA tech-controllers issue #184: after any write the API
        keeps reporting the OLD value with `duringChange:"t"` for ~30s. Caller
        provides a closure that re-reads and decides "settled?" — typically by
        inspecting `duringChange` on the relevant zone/menu element.

        Returns True if settled, False on timeout.
        """
        deadline = time.monotonic() + timeout
        while True:
            try:
                if check():
                    return True
            except EmodulApiError:
                # Transient errors during settle are normal; just retry.
                pass
            if time.monotonic() >= deadline:
                return False
            time.sleep(interval)

    def is_menu_item_settled(
        self, udid: str, menu_type: str, ido: int, *, pin_chain=None
    ) -> bool:
        """True when `duringChange` on the menu element is no longer set."""
        from emodul.settings_map import find_item  # local import to avoid cycle

        menu = self.get_menu(udid, menu_type, pin_chain=pin_chain)
        item = find_item(menu, ido)
        if item is None:
            return True
        return not _is_changing(item.get("duringChange"))

    def is_zone_settled(self, udid: str, zone_id: int) -> bool:
        """True when zone/mode/description all report `duringChange` clear."""
        snap = self.get_module(udid)
        elements = (snap.get("zones") or {}).get("elements") or []
        for el in elements:
            if not el:
                continue
            zone = el.get("zone") or {}
            if zone.get("id") != zone_id:
                continue
            if _is_changing(zone.get("duringChange")):
                return False
            for sub in ("mode", "description", "schedule"):
                s = el.get(sub) or {}
                if _is_changing(s.get("duringChange")):
                    return False
            return True
        return True  # zone vanished — settled (or moved)
