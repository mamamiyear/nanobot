"""Helpers for keeping the bundled WebUI build in sync with source checkouts."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

BuildMode = Literal["auto", "prompt", "warn", "skip"]

_SOURCE_TOP_LEVEL_FILES = (
    "base-path.ts",
    "index.html",
    "package.json",
    "bun.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "vite.config.ts",
    "vite.config.js",
    "tailwind.config.ts",
    "tailwind.config.js",
    "postcss.config.ts",
    "postcss.config.js",
    "tsconfig.json",
    "tsconfig.build.json",
    "components.json",
)
_SOURCE_DIRS = ("src", "public")
_VITE_ENV_FILES = (
    ".env",
    ".env.local",
    ".env.production",
    ".env.production.local",
)
WEBUI_BUILD_METADATA_FILENAME = ".nanobot-webui-build.json"
_WEBUI_BASE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9._~-]+$")


class WebUIBuildError(RuntimeError):
    """Raised when the local WebUI bundle cannot be built."""


class WebUIBuildBaseMismatchError(WebUIBuildError):
    """Raised when bundled assets were built for a different WebUI base path."""


@dataclass(frozen=True)
class WebUIBundleStatus:
    """Freshness status for a source checkout's bundled WebUI assets."""

    source_dir: Path
    dist_dir: Path
    index_html: Path
    source_available: bool
    dist_available: bool
    stale: bool
    reason: str
    newest_source: Path | None = None
    newest_source_mtime_ns: int | None = None
    dist_mtime_ns: int | None = None
    expected_base: str = "/"
    build_base: str | None = None

    @property
    def needs_build(self) -> bool:
        return self.source_available and self.stale


def default_project_root() -> Path:
    """Return the repository root when running from a source checkout."""
    return Path(__file__).resolve().parents[2]


def default_webui_source_dir(project_root: Path | None = None) -> Path:
    """Return the conventional frontend source directory for a checkout."""
    root = project_root or default_project_root()
    return root / "webui"


def default_webui_dist_dir(project_root: Path | None = None) -> Path:
    """Return the bundled WebUI dist directory for the installed package."""
    try:
        import nanobot.web as web_pkg  # type: ignore[import-not-found]
    except ImportError:
        root = project_root or default_project_root()
        return root / "nanobot" / "web" / "dist"
    return Path(web_pkg.__file__).resolve().parent / "dist"


def iter_webui_source_files(source_dir: Path) -> list[Path]:
    """Return WebUI source files that should make the production bundle stale."""
    files: list[Path] = []
    for name in _SOURCE_TOP_LEVEL_FILES:
        candidate = source_dir / name
        if candidate.is_file():
            files.append(candidate)
    for name in _VITE_ENV_FILES:
        candidate = source_dir / name
        if candidate.is_file():
            files.append(candidate)
    for dirname in _SOURCE_DIRS:
        root = source_dir / dirname
        if not root.is_dir():
            continue
        files.extend(path for path in root.rglob("*") if path.is_file())
    channel_root = source_dir.parent / "nanobot" / "channels"
    if channel_root.is_dir():
        for channel_webui in channel_root.glob("*/webui"):
            files.extend(path for path in channel_webui.rglob("*") if path.is_file())
    return files


def normalize_webui_base_path(value: str | None) -> str:
    """Return the canonical WebUI mount path used by build metadata."""
    candidate = (value or "/").strip()
    if candidate == "/":
        return "/"
    if not candidate.startswith("/"):
        raise WebUIBuildError('VITE_BASE_PATH must be "/" or start with "/"')
    if candidate.endswith("/"):
        candidate = candidate.rstrip("/")
    segments = candidate[1:].split("/")
    if not segments or any(not segment for segment in segments):
        raise WebUIBuildError("VITE_BASE_PATH must not contain empty path segments")
    if any(
        segment in {".", ".."} or not _WEBUI_BASE_SEGMENT_RE.fullmatch(segment)
        for segment in segments
    ):
        raise WebUIBuildError(
            "VITE_BASE_PATH segments may contain only letters, digits, '.', '_', '~', or '-'"
        )
    return candidate


def effective_webui_build_base(
    source_dir: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> str:
    """Resolve VITE_BASE_PATH with Vite's production dotenv precedence."""
    values: dict[str, str] = {}
    for filename in _VITE_ENV_FILES:
        values.update(_read_dotenv_file(source_dir / filename))
    env = os.environ if environ is None else environ
    if "VITE_BASE_PATH" in env:
        values["VITE_BASE_PATH"] = env["VITE_BASE_PATH"]
    return normalize_webui_base_path(values.get("VITE_BASE_PATH"))


def read_webui_build_base(dist_dir: Path) -> str | None:
    """Read the canonical base path recorded by the Vite production build."""
    metadata_path = dist_dir / WEBUI_BUILD_METADATA_FILENAME
    if not metadata_path.is_file():
        return None
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        value = payload["base"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise WebUIBuildError(f"invalid WebUI build metadata at {metadata_path}") from exc
    if not isinstance(value, str):
        raise WebUIBuildError(f"invalid WebUI build metadata at {metadata_path}")
    return normalize_webui_base_path(value)


def write_webui_build_metadata(dist_dir: Path, base: str) -> None:
    """Record the mount path used to build a WebUI dist directory."""
    metadata_path = dist_dir / WEBUI_BUILD_METADATA_FILENAME
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(
        json.dumps({"base": normalize_webui_base_path(base)}, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def validate_webui_bundle_base(
    *,
    dist_dir: Path | None = None,
    expected_base: str,
) -> str:
    """Fail clearly when a bundled frontend cannot run at the configured base."""
    resolved_dist = dist_dir or default_webui_dist_dir()
    expected = normalize_webui_base_path(expected_base)
    try:
        actual = read_webui_build_base(resolved_dist)
    except WebUIBuildError as exc:
        raise WebUIBuildBaseMismatchError(str(exc)) from exc
    # Bundles created before base metadata existed were always root builds.
    actual_or_legacy = actual or "/"
    if actual_or_legacy != expected:
        metadata_note = (
            f"was built for {actual_or_legacy!r}"
            if actual is not None
            else "has no base metadata and is treated as a legacy '/' build"
        )
        raise WebUIBuildBaseMismatchError(
            f"Bundled WebUI {metadata_note}, but channels.websocket.base is "
            f"{expected!r}. Rebuild with VITE_BASE_PATH={expected}."
        )
    return actual_or_legacy


def inspect_webui_bundle(
    *,
    source_dir: Path | None = None,
    dist_dir: Path | None = None,
    expected_base: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> WebUIBundleStatus:
    """Inspect whether a checkout's WebUI source is newer than the bundled dist."""
    resolved_source = source_dir or default_webui_source_dir()
    resolved_dist = dist_dir or default_webui_dist_dir()
    index_html = resolved_dist / "index.html"
    resolved_expected_base = (
        normalize_webui_base_path(expected_base)
        if expected_base is not None
        else effective_webui_build_base(resolved_source, environ=environ)
    )

    if not (resolved_source / "package.json").is_file():
        return WebUIBundleStatus(
            source_dir=resolved_source,
            dist_dir=resolved_dist,
            index_html=index_html,
            source_available=False,
            dist_available=index_html.is_file(),
            stale=False,
            reason="no_source",
            expected_base=resolved_expected_base,
        )

    if not index_html.is_file():
        return WebUIBundleStatus(
            source_dir=resolved_source,
            dist_dir=resolved_dist,
            index_html=index_html,
            source_available=True,
            dist_available=False,
            stale=True,
            reason="missing_dist",
            expected_base=resolved_expected_base,
        )

    dist_mtime_ns = index_html.stat().st_mtime_ns
    try:
        build_base = read_webui_build_base(resolved_dist)
    except WebUIBuildError:
        return WebUIBundleStatus(
            source_dir=resolved_source,
            dist_dir=resolved_dist,
            index_html=index_html,
            source_available=True,
            dist_available=True,
            stale=True,
            reason="invalid_build_metadata",
            dist_mtime_ns=dist_mtime_ns,
            expected_base=resolved_expected_base,
        )
    if (build_base or "/") != resolved_expected_base:
        return WebUIBundleStatus(
            source_dir=resolved_source,
            dist_dir=resolved_dist,
            index_html=index_html,
            source_available=True,
            dist_available=True,
            stale=True,
            reason="base_mismatch" if build_base is not None else "missing_build_metadata",
            dist_mtime_ns=dist_mtime_ns,
            expected_base=resolved_expected_base,
            build_base=build_base,
        )

    newest_source: Path | None = None
    newest_source_mtime_ns: int | None = None
    for candidate in iter_webui_source_files(resolved_source):
        try:
            mtime_ns = candidate.stat().st_mtime_ns
        except OSError:
            continue
        if newest_source_mtime_ns is None or mtime_ns > newest_source_mtime_ns:
            newest_source = candidate
            newest_source_mtime_ns = mtime_ns

    if newest_source_mtime_ns is not None and newest_source_mtime_ns > dist_mtime_ns:
        return WebUIBundleStatus(
            source_dir=resolved_source,
            dist_dir=resolved_dist,
            index_html=index_html,
            source_available=True,
            dist_available=True,
            stale=True,
            reason="source_newer",
            newest_source=newest_source,
            newest_source_mtime_ns=newest_source_mtime_ns,
            dist_mtime_ns=dist_mtime_ns,
            expected_base=resolved_expected_base,
            build_base=build_base,
        )

    return WebUIBundleStatus(
        source_dir=resolved_source,
        dist_dir=resolved_dist,
        index_html=index_html,
        source_available=True,
        dist_available=True,
        stale=False,
        reason="fresh",
        newest_source=newest_source,
        newest_source_mtime_ns=newest_source_mtime_ns,
        dist_mtime_ns=dist_mtime_ns,
        expected_base=resolved_expected_base,
        build_base=build_base,
    )


def describe_webui_bundle_status(status: WebUIBundleStatus) -> str:
    """Return a short user-facing freshness message."""
    if status.reason == "missing_dist":
        return "Bundled WebUI build is missing."
    if status.reason == "source_newer":
        changed = _display_source_path(status)
        return f"WebUI source is newer than the bundled build ({changed})."
    if status.reason == "missing_build_metadata":
        return (
            "Bundled WebUI has no base metadata and is treated as a legacy '/' build, "
            f"but {status.expected_base!r} is required."
        )
    if status.reason == "base_mismatch":
        return (
            f"Bundled WebUI was built for {status.build_base!r}, "
            f"but {status.expected_base!r} is required."
        )
    if status.reason == "invalid_build_metadata":
        return "Bundled WebUI base metadata is invalid."
    if status.reason == "fresh":
        return "Bundled WebUI build is up to date."
    return "WebUI source tree was not found; using the bundled build."


def build_webui_bundle(
    *,
    source_dir: Path | None = None,
    dist_dir: Path | None = None,
    runner: str | None = None,
    subprocess_run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    output: Callable[[str], None] | None = None,
    expected_base: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> WebUIBundleStatus:
    """Install frontend dependencies and build the WebUI bundle."""
    resolved_source = source_dir or default_webui_source_dir()
    resolved_dist = dist_dir or default_webui_dist_dir()
    resolved_base = (
        normalize_webui_base_path(expected_base)
        if expected_base is not None
        else effective_webui_build_base(resolved_source, environ=environ)
    )
    command_runner = runner or pick_webui_build_runner()
    if command_runner is None:
        raise WebUIBuildError(
            "neither `bun` nor `npm` is available on PATH; install one or run "
            "`cd webui && bun run build` manually"
        )

    _emit(output, f"Building bundled WebUI with `{command_runner}`...")
    _run_frontend_command(
        [command_runner, "install"],
        cwd=resolved_source,
        subprocess_run=subprocess_run,
        environ=environ,
        vite_base=resolved_base,
    )
    _run_frontend_command(
        [command_runner, "run", "build"],
        cwd=resolved_source,
        subprocess_run=subprocess_run,
        environ=environ,
        vite_base=resolved_base,
    )
    write_webui_build_metadata(resolved_dist, resolved_base)
    return inspect_webui_bundle(
        source_dir=resolved_source,
        dist_dir=resolved_dist,
        expected_base=resolved_base,
        environ=environ,
    )


def ensure_webui_bundle(
    *,
    mode: BuildMode,
    source_dir: Path | None = None,
    dist_dir: Path | None = None,
    confirm: Callable[[str], bool] | None = None,
    output: Callable[[str], None] | None = None,
    runner: str | None = None,
    environ: Mapping[str, str] | None = None,
    subprocess_run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    expected_base: str | None = None,
) -> WebUIBundleStatus:
    """Ensure or warn about a stale WebUI bundle according to the selected mode."""
    env = os.environ if environ is None else environ
    status = inspect_webui_bundle(
        source_dir=source_dir,
        dist_dir=dist_dir,
        expected_base=expected_base,
        environ=env,
    )
    if not status.needs_build:
        return status

    detail = describe_webui_bundle_status(status)
    if env.get("NANOBOT_SKIP_WEBUI_BUILD") == "1" or mode == "skip":
        _emit(output, f"Warning: {detail} Skipping WebUI build.")
        return status

    if mode == "warn":
        _emit(
            output,
            f"Warning: {detail} Run `cd {status.source_dir} && bun run build` "
            "to refresh it.",
        )
        return status

    if mode == "prompt":
        if confirm is None:
            _emit(output, f"Warning: {detail} No interactive confirmation is available.")
            return status
        message = "Build WebUI now? This runs `cd webui && bun run build`."
        if not confirm(message):
            _emit(output, "Continuing with the existing bundled WebUI build.")
            return status

    try:
        return build_webui_bundle(
            source_dir=status.source_dir,
            dist_dir=status.dist_dir,
            runner=runner,
            subprocess_run=subprocess_run,
            output=output,
            expected_base=status.expected_base,
            environ=environ,
        )
    except WebUIBuildError as exc:
        raise WebUIBuildError(f"{detail} {exc}") from exc


def pick_webui_build_runner() -> str | None:
    """Pick the frontend package manager used to build the WebUI."""
    for candidate in ("bun", "npm"):
        if executable := shutil.which(candidate):
            return executable
    return None


def _run_frontend_command(
    command: list[str],
    *,
    cwd: Path,
    subprocess_run: Callable[..., subprocess.CompletedProcess],
    environ: Mapping[str, str] | None,
    vite_base: str,
) -> None:
    command_env = dict(os.environ)
    if environ is not None:
        command_env.update(environ)
    command_env["VITE_BASE_PATH"] = vite_base
    try:
        subprocess_run(command, cwd=cwd, check=True, env=command_env)
    except subprocess.CalledProcessError as exc:
        raise WebUIBuildError(
            f"command failed ({exc.returncode}): {' '.join(command)}"
        ) from exc
    except OSError as exc:
        raise WebUIBuildError(f"command failed: {' '.join(command)} ({exc})") from exc


def _display_source_path(status: WebUIBundleStatus) -> str:
    if status.newest_source is None:
        return "source files changed"
    with suppress(ValueError):
        return str(status.newest_source.relative_to(status.source_dir))
    return str(status.newest_source)


def _emit(output: Callable[[str], None] | None, message: str) -> None:
    if output is not None:
        output(message)


def _read_dotenv_file(path: Path) -> dict[str, str]:
    """Read the small dotenv subset needed for VITE_BASE_PATH freshness checks."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != "VITE_BASE_PATH":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        values["VITE_BASE_PATH"] = value
    return values
