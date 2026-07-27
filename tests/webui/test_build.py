from __future__ import annotations

import os
import tomllib
from pathlib import Path

import pytest

from nanobot.webui.build import (
    WEBUI_BUILD_METADATA_FILENAME,
    WebUIBuildBaseMismatchError,
    effective_webui_build_base,
    ensure_webui_bundle,
    inspect_webui_bundle,
    normalize_webui_base_path,
    pick_webui_build_runner,
    read_webui_build_base,
    validate_webui_bundle_base,
    write_webui_build_metadata,
)

_MTIME_BASE_NS = 1_700_000_000_000_000_000
_MTIME_STEP_NS = 5_000_000_000


def _touch(path: Path, *, mtime_ns: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(path.name, encoding="utf-8")
    if mtime_ns < 1_000_000_000_000_000:
        mtime_ns = _MTIME_BASE_NS + mtime_ns * _MTIME_STEP_NS
    os.utime(path, ns=(mtime_ns, mtime_ns))


def test_inspect_webui_bundle_ignores_packaged_install_without_source(tmp_path: Path) -> None:
    source = tmp_path / "site-packages" / "webui"
    dist = tmp_path / "site-packages" / "nanobot" / "web" / "dist"
    _touch(dist / "index.html", mtime_ns=20)

    status = inspect_webui_bundle(source_dir=source, dist_dir=dist)

    assert status.source_available is False
    assert status.stale is False
    assert status.reason == "no_source"


def test_inspect_webui_bundle_marks_missing_dist_stale(tmp_path: Path) -> None:
    source = tmp_path / "webui"
    dist = tmp_path / "nanobot" / "web" / "dist"
    _touch(source / "package.json", mtime_ns=10)

    status = inspect_webui_bundle(source_dir=source, dist_dir=dist)

    assert status.source_available is True
    assert status.dist_available is False
    assert status.stale is True
    assert status.reason == "missing_dist"


def test_inspect_webui_bundle_detects_source_newer_than_dist(tmp_path: Path) -> None:
    source = tmp_path / "webui"
    dist = tmp_path / "nanobot" / "web" / "dist"
    _touch(source / "package.json", mtime_ns=10)
    _touch(source / "src" / "App.tsx", mtime_ns=30)
    _touch(dist / "index.html", mtime_ns=20)

    status = inspect_webui_bundle(source_dir=source, dist_dir=dist)

    assert status.stale is True
    assert status.reason == "source_newer"
    assert status.newest_source == source / "src" / "App.tsx"


def test_inspect_webui_bundle_tracks_shared_base_path_source(tmp_path: Path) -> None:
    source = tmp_path / "webui"
    dist = tmp_path / "nanobot" / "web" / "dist"
    _touch(source / "package.json", mtime_ns=10)
    _touch(dist / "index.html", mtime_ns=20)
    _touch(source / "base-path.ts", mtime_ns=30)

    status = inspect_webui_bundle(source_dir=source, dist_dir=dist)

    assert status.stale is True
    assert status.reason == "source_newer"
    assert status.newest_source == source / "base-path.ts"


def test_inspect_webui_bundle_detects_channel_owned_ui_source(tmp_path: Path) -> None:
    source = tmp_path / "webui"
    dist = tmp_path / "nanobot" / "web" / "dist"
    channel_ui = tmp_path / "nanobot" / "channels" / "example" / "webui" / "index.tsx"
    _touch(source / "package.json", mtime_ns=10)
    _touch(dist / "index.html", mtime_ns=20)
    _touch(channel_ui, mtime_ns=30)

    status = inspect_webui_bundle(source_dir=source, dist_dir=dist)

    assert status.needs_build is True
    assert status.reason == "source_newer"
    assert status.newest_source == channel_ui


def test_channel_owned_ui_sources_are_included_in_distributions() -> None:
    project_root = Path(__file__).resolve().parents[2]
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))

    assert "nanobot/channels/*/webui/**/*" in pyproject["tool"]["hatch"]["build"]["include"]


def test_inspect_webui_bundle_accepts_fresh_dist(tmp_path: Path) -> None:
    source = tmp_path / "webui"
    dist = tmp_path / "nanobot" / "web" / "dist"
    _touch(source / "package.json", mtime_ns=10)
    _touch(source / "src" / "App.tsx", mtime_ns=20)
    _touch(dist / "index.html", mtime_ns=30)

    status = inspect_webui_bundle(source_dir=source, dist_dir=dist)

    assert status.stale is False
    assert status.reason == "fresh"


def test_ensure_webui_bundle_auto_builds_stale_dist(tmp_path: Path) -> None:
    source = tmp_path / "webui"
    dist = tmp_path / "nanobot" / "web" / "dist"
    _touch(source / "package.json", mtime_ns=10)
    _touch(source / "src" / "App.tsx", mtime_ns=30)
    _touch(dist / "index.html", mtime_ns=20)
    commands: list[tuple[str, ...]] = []

    def fake_run(command, *, cwd: Path, check: bool, env: dict[str, str]) -> None:
        commands.append(tuple(command))
        assert cwd == source
        assert check is True
        assert env["VITE_BASE_PATH"] == "/"
        if command == ["bun", "run", "build"]:
            _touch(dist / "index.html", mtime_ns=40)

    status = ensure_webui_bundle(
        mode="auto",
        source_dir=source,
        dist_dir=dist,
        runner="bun",
        subprocess_run=fake_run,
    )

    assert status.stale is False
    assert commands == [("bun", "install"), ("bun", "run", "build")]


def test_ensure_webui_bundle_builds_for_explicit_runtime_base(tmp_path: Path) -> None:
    source = tmp_path / "webui"
    dist = tmp_path / "nanobot" / "web" / "dist"
    _touch(source / "package.json", mtime_ns=10)
    _touch(dist / "index.html", mtime_ns=20)
    commands: list[tuple[str, ...]] = []

    def fake_run(command, *, cwd: Path, check: bool, env: dict[str, str]) -> None:
        commands.append(tuple(command))
        assert cwd == source
        assert check is True
        assert env["VITE_BASE_PATH"] == "/nanobot-a"
        if command == ["bun", "run", "build"]:
            _touch(dist / "index.html", mtime_ns=40)

    status = ensure_webui_bundle(
        mode="auto",
        source_dir=source,
        dist_dir=dist,
        runner="bun",
        subprocess_run=fake_run,
        expected_base="/nanobot-a",
    )

    assert status.stale is False
    assert status.build_base == "/nanobot-a"
    assert read_webui_build_base(dist) == "/nanobot-a"
    assert commands == [("bun", "install"), ("bun", "run", "build")]


def test_pick_webui_build_runner_returns_resolved_executable(monkeypatch) -> None:
    bun_shim = r"C:\tools\npm\bun.CMD"

    monkeypatch.setattr(
        "nanobot.webui.build.shutil.which",
        lambda candidate: bun_shim if candidate == "bun" else None,
    )

    assert pick_webui_build_runner() == bun_shim


def test_ensure_webui_bundle_warns_without_building(tmp_path: Path) -> None:
    source = tmp_path / "webui"
    dist = tmp_path / "nanobot" / "web" / "dist"
    _touch(source / "package.json", mtime_ns=10)
    _touch(source / "src" / "App.tsx", mtime_ns=30)
    _touch(dist / "index.html", mtime_ns=20)
    messages: list[str] = []

    status = ensure_webui_bundle(
        mode="warn",
        source_dir=source,
        dist_dir=dist,
        output=messages.append,
    )

    assert status.stale is True
    assert messages
    assert "Run `cd" in messages[0]


def test_normalize_webui_base_path_uses_runtime_canonical_form() -> None:
    assert normalize_webui_base_path(None) == "/"
    assert normalize_webui_base_path("/") == "/"
    assert normalize_webui_base_path("/nanobot/") == "/nanobot"
    assert normalize_webui_base_path("/team_a/nanobot-1") == "/team_a/nanobot-1"


@pytest.mark.parametrize(
    "value",
    ["nanobot", "//nanobot", "/nanobot//child", "/nanobot/..", "/nanobot?debug=1"],
)
def test_normalize_webui_base_path_rejects_invalid_values(value: str) -> None:
    with pytest.raises(Exception, match="VITE_BASE_PATH"):
        normalize_webui_base_path(value)


def test_effective_webui_build_base_uses_vite_production_env_precedence(
    tmp_path: Path,
) -> None:
    source = tmp_path / "webui"
    source.mkdir()
    (source / ".env").write_text("VITE_BASE_PATH=/from-env\n", encoding="utf-8")
    (source / ".env.local").write_text("VITE_BASE_PATH=/from-local\n", encoding="utf-8")
    (source / ".env.production").write_text(
        "VITE_BASE_PATH=/from-production\n",
        encoding="utf-8",
    )
    (source / ".env.production.local").write_text(
        "VITE_BASE_PATH=/from-production-local/\n",
        encoding="utf-8",
    )

    assert effective_webui_build_base(source, environ={}) == "/from-production-local"
    assert (
        effective_webui_build_base(
            source,
            environ={"VITE_BASE_PATH": "/from-process/"},
        )
        == "/from-process"
    )


def test_inspect_webui_bundle_detects_dotenv_newer_than_dist(tmp_path: Path) -> None:
    source = tmp_path / "webui"
    dist = tmp_path / "nanobot" / "web" / "dist"
    _touch(source / "package.json", mtime_ns=10)
    _touch(dist / "index.html", mtime_ns=20)
    write_webui_build_metadata(dist, "/nanobot")
    _touch(source / ".env.production", mtime_ns=30)
    (source / ".env.production").write_text("VITE_BASE_PATH=/nanobot\n", encoding="utf-8")
    os.utime(
        source / ".env.production",
        ns=(_MTIME_BASE_NS + 30 * _MTIME_STEP_NS,) * 2,
    )

    status = inspect_webui_bundle(source_dir=source, dist_dir=dist, environ={})

    assert status.stale is True
    assert status.reason == "source_newer"
    assert status.newest_source == source / ".env.production"


def test_inspect_webui_bundle_detects_environment_base_mismatch(tmp_path: Path) -> None:
    source = tmp_path / "webui"
    dist = tmp_path / "nanobot" / "web" / "dist"
    _touch(source / "package.json", mtime_ns=10)
    _touch(dist / "index.html", mtime_ns=20)
    write_webui_build_metadata(dist, "/nanobot-a")

    status = inspect_webui_bundle(
        source_dir=source,
        dist_dir=dist,
        environ={"VITE_BASE_PATH": "/nanobot-b"},
    )

    assert status.stale is True
    assert status.reason == "base_mismatch"
    assert status.build_base == "/nanobot-a"
    assert status.expected_base == "/nanobot-b"


def test_legacy_bundle_without_metadata_is_accepted_only_for_root(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    _touch(dist / "index.html", mtime_ns=20)

    assert validate_webui_bundle_base(dist_dir=dist, expected_base="/") == "/"
    with pytest.raises(WebUIBuildBaseMismatchError, match="legacy '/' build"):
        validate_webui_bundle_base(dist_dir=dist, expected_base="/nanobot")


def test_webui_build_metadata_round_trip(tmp_path: Path) -> None:
    dist = tmp_path / "dist"

    write_webui_build_metadata(dist, "/nanobot/")

    assert read_webui_build_base(dist) == "/nanobot"
    assert (
        (dist / WEBUI_BUILD_METADATA_FILENAME).read_text(encoding="utf-8")
        == '{"base":"/nanobot"}\n'
    )
