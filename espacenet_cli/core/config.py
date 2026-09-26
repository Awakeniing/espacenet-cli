"""Profile paths and Edge executable discovery.

The endpoint/lock file layout is byte-compatible with the prior Node.js CLI:
both CLIs can attach to the same persistent Edge session.
"""

import os
from pathlib import Path

from espacenet_cli.core.errors import CliError

ESPACENET_ORIGIN = "https://worldwide.espacenet.com"
CDP_HOST = "127.0.0.1"

_RESERVED_WINDOWS = ("con", "prn", "aux", "nul",
                     *(f"com{i}" for i in range(1, 10)),
                     *(f"lpt{i}" for i in range(1, 10)))


def validate_profile_name(value="default"):
    name = str(value or "").strip()
    lower = name.lower().split(".")[0]
    if (not name or name in {".", ".."} or "/" in name or "\\" in name
            or any(c in name for c in '<>:"|?*') or any(ord(c) < 32 for c in name)
            or lower in _RESERVED_WINDOWS):
        raise CliError("INVALID_PROFILE", f"Invalid profile name: {name or '(empty)'}", exit_code=2)
    return name


def get_config_root(env=None):
    env = env if env is not None else os.environ
    if env.get("ESPACENET_CLI_CONFIG_DIR"):
        return Path(env["ESPACENET_CLI_CONFIG_DIR"]).resolve()
    local_app_data = env.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(local_app_data) / "EspacenetCLI"


def get_profile_paths(profile="default", config_root=None, env=None):
    safe = validate_profile_name(profile)
    root = Path(config_root or get_config_root(env)).resolve()
    profile_root = (root / "profiles" / safe).resolve()
    expected_prefix = (root / "profiles").resolve()
    if not str(profile_root).startswith(str(expected_prefix)):
        raise CliError("INVALID_PROFILE", "Profile path escaped the Espacenet CLI config root.", exit_code=2)
    return {
        "config_root": root,
        "profile": safe,
        "profile_root": profile_root,
        "browser_profile_dir": profile_root / "edge-profile",
        "edge_endpoint_file": profile_root / "edge-endpoint.json",
        "lock_dir": root / "locks",
        "launch_lock_file": root / "locks" / f"{safe}.edge-launch.lock",
    }


def read_endpoint_file(path):
    """Shared-Edge endpoint file (compatible with the prior Node.js CLI)."""
    import json

    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    port = value.get("port")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        return None
    return {
        "host": CDP_HOST,
        "port": port,
        "pid": int(value.get("pid") or 0),
        "profile_dir": str(value.get("profileDir") or value.get("profile_dir") or ""),
        "mode": value.get("mode") or "visible",
        "updated_at": str(value.get("updatedAt") or value.get("updated_at") or ""),
    }


def find_edge_executables(env=None):
    """Candidate msedge.exe locations, ordered. Real-software hard dependency."""
    env = env if env is not None else os.environ
    candidates = [
        env.get("ESPACENET_EDGE_PATH"),
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    local = env.get("LOCALAPPDATA")
    if local:
        candidates.append(str(Path(local) / "Microsoft" / "Edge" / "Application" / "msedge.exe"))
    candidates += [
        "/usr/bin/microsoft-edge",
        "/usr/bin/microsoft-edge-stable",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    return [c for c in candidates if c]


def find_edge(env=None):
    """Return the first existing Edge executable or raise with install guidance."""
    for candidate in find_edge_executables(env):
        if Path(candidate).exists():
            return candidate
    raise CliError(
        "EDGE_NOT_FOUND",
        "Microsoft Edge was not found on this machine.",
        action="Install Microsoft Edge, or set ESPACENET_EDGE_PATH to the msedge executable.",
    )
