from emodul.api import ApiClient


class ScriptedApi(ApiClient):
    """ApiClient whose get_menu replays a fixed sequence of (duringChange, value)."""

    def __init__(self, states):
        super().__init__(base_url="http://test.invalid", token="t", user_id=1)
        self.states = list(states)

    def get_menu(self, udid, menu_type, pin_chain=None):
        during, value = self.states.pop(0)
        return {"data": {"elements": [{"id": 42, "duringChange": during, "params": {"value": value}}]}}


def test_settled_flag_with_stale_value_is_not_done() -> None:
    # Observed live: duringChange clears one poll before the new value appears.
    api = ScriptedApi([("t", 1), ("f", 1), ("f", 0)])
    assert api.wait_until_settled(lambda: api.is_menu_item_at("u", "MI", 42, 0), timeout=5, interval=0)
    assert api.states == []


def test_value_while_still_changing_is_not_done() -> None:
    api = ScriptedApi([("t", 0)])
    assert api.is_menu_item_at("u", "MI", 42, 0) is False


def test_old_settle_check_would_accept_stale_value() -> None:
    api = ScriptedApi([("f", 1)])
    assert api.is_menu_item_settled("u", "MI", 42) is True
