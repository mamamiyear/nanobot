import json
import socket
from unittest.mock import patch

import pytest

from nanobot.config.loader import load_config, save_config
from nanobot.security.network import validate_url_target


def _fake_resolve(host: str, results: list[str]):
    """Return a getaddrinfo mock that maps the given host to fake IP results."""
    def _resolver(hostname, port, family=0, type_=0):
        if hostname == host:
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0)) for ip in results]
        raise socket.gaierror(f"cannot resolve {hostname}")
    return _resolver


def test_onboard_refresh_backfills_missing_channel_fields(tmp_path, monkeypatch) -> None:
    from nanobot.channels.plugin import load_channel_package

    config_path = tmp_path / "config.json"
    workspace = tmp_path / "workspace"
    config_path.write_text(
        json.dumps(
            {
                "channels": {
                    "qq": {
                        "enabled": False,
                        "appId": "",
                        "secret": "",
                        "allowFrom": [],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("nanobot.config.loader.get_config_path", lambda: config_path)
    monkeypatch.setattr("nanobot.cli.commands.get_workspace_path", lambda _workspace=None: workspace)
    monkeypatch.setattr(
        "nanobot.channels.registry.discover_plugins",
        lambda: {"qq": load_channel_package("qq")},
    )
    monkeypatch.setattr(
        "nanobot.channels.registry.discover_all",
        lambda: pytest.fail("onboarding must not import channel runtimes"),
    )

    from typer.testing import CliRunner

    from nanobot.cli.commands import app
    runner = CliRunner()
    result = runner.invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["channels"]["qq"]["msgFormat"] == "plain"


@pytest.fixture
def onboard_channel_config(tmp_path, monkeypatch):
    from nanobot.channels.registry import load_channel_plugin

    config_path = tmp_path / "config.json"
    monkeypatch.setattr("nanobot.config.loader.get_config_path", lambda: config_path)
    monkeypatch.setattr(
        "nanobot.cli.commands.get_workspace_path", lambda _workspace=None: tmp_path / "workspace"
    )
    plugins = {name: load_channel_plugin(name) for name in ("slack", "feishu")}
    monkeypatch.setattr("nanobot.channels.registry.discover_plugins", lambda _names=None: plugins)
    monkeypatch.setattr(
        "nanobot.channels.registry.discover_all",
        lambda: pytest.fail("onboarding must not import channel runtimes"),
    )
    return config_path


@pytest.mark.parametrize("existing_config", [False, True], ids=["new-file", "new-channel"])
def test_onboard_creates_feishu_instance_defaults(onboard_channel_config, existing_config):
    from typer.testing import CliRunner

    from nanobot.cli.commands import app

    config_path = onboard_channel_config
    if existing_config:
        config_path.write_text(json.dumps({"channels": {"slack": {"dm": {"replyInThread": True}}}}))

    result = CliRunner().invoke(app, ["onboard", "--refresh"])

    assert result.exit_code == 0, result.output
    channels = json.loads(config_path.read_text())["channels"]
    assert channels["slack"]["dm"]["replyInThread"] is existing_config
    assert set(channels["feishu"]) == {"instances"}
    [instance] = channels["feishu"]["instances"]
    assert instance["id"] == "default"
    assert instance["enabled"] is False
    assert instance["dmReplyInThread"] is False


@pytest.mark.parametrize("configured", [None, False, True], ids=["missing", "off", "on"])
def test_onboard_refresh_backfills_slack_dm_reply_setting(onboard_channel_config, configured):
    from typer.testing import CliRunner

    from nanobot.cli.commands import app

    dm = {"enabled": True, "policy": "allowlist", "allowFrom": ["U_KEEP"]}
    if configured is not None:
        dm["replyInThread"] = configured
    config_path = onboard_channel_config
    config_path.write_text(json.dumps({"channels": {"slack": {
        "replyInThread": False, "botToken": "saved-token", "dm": dm,
    }}}))

    result = CliRunner().invoke(app, ["onboard", "--refresh"])

    assert result.exit_code == 0, result.output
    saved = json.loads(config_path.read_text())["channels"]["slack"]
    assert saved["dm"] == {**dm, "replyInThread": bool(configured)}
    assert saved["replyInThread"] is False
    assert saved["botToken"] == "saved-token"


@pytest.mark.parametrize("inherited", [False, True], ids=["default-off", "inherited-on"])
def test_onboard_refresh_backfills_each_feishu_instance(onboard_channel_config, inherited):
    from typer.testing import CliRunner

    from nanobot.channels.contracts import channel_instance_specs
    from nanobot.channels.registry import load_channel_plugin
    from nanobot.cli.commands import app

    config_path = onboard_channel_config
    original = {
        "enabled": True,
        "allowFrom": ["shared-user"],
        "instances": [
            {"id": "default", "appId": "cli_one", "appSecret": "${FEISHU_SECRET}", "dmReplyInThread": True},
            {"id": "support", "enabled": False, "dmReplyInThread": False, "allowFrom": []},
            {"id": "sales", "appId": "cli_sales", "name": "Sales", "customSetting": "keep"},
        ],
    }
    if inherited:
        original["dmReplyInThread"] = True
    config_path.write_text(json.dumps({"channels": {"feishu": original}}))
    runner = CliRunner()

    result = runner.invoke(app, ["onboard", "--refresh"])

    assert result.exit_code == 0, result.output
    saved = json.loads(config_path.read_text())["channels"]["feishu"]
    assert saved["enabled"] is True
    assert saved["allowFrom"] == ["shared-user"]
    assert [item["dmReplyInThread"] for item in saved["instances"]] == [True, False, inherited]
    assert [item["enabled"] for item in saved["instances"]] == [True, False, True]
    for before, after in zip(original["instances"], saved["instances"], strict=True):
        assert before.items() <= after.items()

    specs = channel_instance_specs(load_channel_plugin("feishu"), saved)
    assert [(spec.instance_id, spec.config["dmReplyInThread"]) for spec in specs] == [
        ("default", True), ("sales", inherited)
    ]
    assert runner.invoke(app, ["onboard", "--refresh"]).exit_code == 0
    assert json.loads(config_path.read_text())["channels"]["feishu"] == saved


@pytest.mark.parametrize("configured", [None, False, True], ids=["missing", "off", "on"])
def test_onboard_refresh_preserves_legacy_feishu_config(onboard_channel_config, configured):
    from typer.testing import CliRunner

    from nanobot.cli.commands import app

    original = {"enabled": True, "appId": "cli_legacy", "appSecret": "saved", "allowFrom": ["user"]}
    if configured is not None:
        original["dmReplyInThread"] = configured
    config_path = onboard_channel_config
    config_path.write_text(json.dumps({"channels": {"feishu": original}}))

    result = CliRunner().invoke(app, ["onboard"], input="n\n")

    assert result.exit_code == 0, result.output
    saved = json.loads(config_path.read_text())["channels"]["feishu"]
    assert "instances" not in saved
    assert saved["dmReplyInThread"] is bool(configured)
    assert original.items() <= saved.items()


def test_onboard_refresh_preserves_empty_feishu_instances(onboard_channel_config):
    from typer.testing import CliRunner

    from nanobot.cli.commands import app

    config_path = onboard_channel_config
    config_path.write_text(json.dumps({"channels": {"feishu": {"instances": []}}}))

    result = CliRunner().invoke(app, ["onboard", "--refresh"])

    assert result.exit_code == 0, result.output
    assert json.loads(config_path.read_text())["channels"]["feishu"] == {"instances": []}


@pytest.mark.parametrize(
    "instances",
    ["invalid", [{"id": "same", "appId": "one"}, {"id": "same", "appId": "two"}]],
    ids=["invalid-list", "duplicate-id"],
)
def test_onboard_plugin_refresh_keeps_invalid_feishu_config_intact(onboard_channel_config, instances):
    from nanobot.cli.commands import _onboard_plugins

    config_path = onboard_channel_config
    original = json.dumps({"channels": {"feishu": {"instances": instances}}})
    config_path.write_text(original)

    with pytest.raises(ValueError, match="instances must be a list|duplicate Feishu instance id"):
        _onboard_plugins(config_path)

    assert config_path.read_text() == original


def test_save_config_rewrites_legacy_my_tool_keys(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "tools": {
                    "myEnabled": False,
                    "mySet": True,
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)
    assert config.tools.my.enable is False
    assert config.tools.my.allow_set is True
    save_config(config, config_path)
    saved = json.loads(config_path.read_text(encoding="utf-8"))

    tools = saved["tools"]
    assert "myEnabled" not in tools
    assert "mySet" not in tools
    assert tools["my"] == {"enable": False, "allowSet": True}


def test_new_my_tool_keys_take_precedence_over_legacy(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "tools": {
                    "myEnabled": False,
                    "mySet": False,
                    "my": {"enable": True, "allowSet": True},
                }
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.tools.my.enable is True
    assert config.tools.my.allow_set is True


def test_load_config_resets_ssrf_whitelist_when_next_config_is_empty(tmp_path) -> None:
    whitelisted = tmp_path / "whitelisted.json"
    whitelisted.write_text(
        json.dumps({"tools": {"ssrfWhitelist": ["100.64.0.0/10"]}}),
        encoding="utf-8",
    )
    defaulted = tmp_path / "defaulted.json"
    defaulted.write_text(json.dumps({}), encoding="utf-8")

    load_config(whitelisted)
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve("ts.local", ["100.100.1.1"])):
        ok, err = validate_url_target("http://ts.local/api")
        assert ok, err

    load_config(defaulted)
    with patch("nanobot.security.network.socket.getaddrinfo", _fake_resolve("ts.local", ["100.100.1.1"])):
        ok, _ = validate_url_target("http://ts.local/api")
        assert not ok


def test_load_config_defaults_local_service_access_to_enabled(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"tools": {}}), encoding="utf-8")

    config = load_config(config_path)

    assert config.tools.webui_allow_local_service_access is True


def test_load_config_accepts_legacy_local_preview_access(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"tools": {"allowLocalPreviewAccess": False}}),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.tools.webui_allow_local_service_access is False


def test_load_config_defaults_remote_package_install_to_disabled(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"tools": {}}), encoding="utf-8")

    config = load_config(config_path)

    assert config.tools.webui_allow_remote_package_install is False


def test_load_config_accepts_remote_package_install_aliases(tmp_path) -> None:
    camel_path = tmp_path / "camel.json"
    camel_path.write_text(
        json.dumps({"tools": {"webuiAllowRemotePackageInstall": True}}),
        encoding="utf-8",
    )
    snake_path = tmp_path / "snake.json"
    snake_path.write_text(
        json.dumps({"tools": {"webui_allow_remote_package_install": True}}),
        encoding="utf-8",
    )

    assert load_config(camel_path).tools.webui_allow_remote_package_install is True
    assert load_config(snake_path).tools.webui_allow_remote_package_install is True
