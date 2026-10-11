import pytest
from click.testing import CliRunner

from emodul.cli import cli


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("EMODUL_CONFIG_DIR", str(tmp_path))


@pytest.mark.parametrize(
    ("args", "msg"),
    [
        (["settings", "set", "emergency-mode", "30"], "set per zone"),
        (["settings", "set", "emergency-mode", "30", "--zone", "1", "--all-zones"], "not both"),
        (["settings", "set", "antifreeze", "on", "--zone", "1"], "module-wide"),
    ],
)
def test_set_rejects_ambiguous_scope_before_any_request(args, msg) -> None:
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 2
    assert msg in result.output


def test_list_reports_scope() -> None:
    import json

    result = CliRunner().invoke(cli, ["--json", "settings", "list"])
    scopes = {s["name"]: s["scope"] for s in json.loads(result.output)}
    assert scopes["emergency-mode"] == "zone"
    assert scopes["pump-antistop"] == "module"
