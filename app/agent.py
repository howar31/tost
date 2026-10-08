"""launchd agent management for hourly background fetches."""

import os
import plistlib
import subprocess
import sys
from pathlib import Path

from app.transport import CLT_DIR, _clt_installed

LABEL = "local.tost"
DEFAULT_INTERVAL_MINUTES = 60


def plist_path():
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def build_plist(python_path, entry_path, log_path, interval_minutes=DEFAULT_INTERVAL_MINUTES,
                env=None):
    """Pure: returns the plist as bytes."""
    data = {
        "Label": LABEL,
        "ProgramArguments": [str(python_path), str(entry_path), "fetch", "--notify", "--quiet"],
        "StartInterval": interval_minutes * 60,
        "RunAtLoad": True,
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
        "WorkingDirectory": str(Path(entry_path).parent),
    }
    if env:
        data["EnvironmentVariables"] = dict(env)
    return plistlib.dumps(data)


def _domain():
    return f"gui/{os.getuid()}"


# The system python is Apple-signed, so its TCC identity survives OS and
# toolchain updates; the Automation grant for Messages (iMessage channel) stays
# valid. Homebrew's python is ad-hoc signed and every upgrade turns it into a
# new TCC subject whose Automation grant is lost and cannot be re-enabled in
# System Settings. /usr/bin/python3 is a stub without developer tools (running
# it pops an install dialog), so it is only picked when xcode-select resolves.
SYSTEM_PYTHON = "/usr/bin/python3"
# Homebrew's unversioned symlink survives python upgrades; sys.executable
# resolves to a versioned path (…/python@3.14/…) that dies on `brew cleanup`.
PYTHON_CANDIDATES = ["/opt/homebrew/bin/python3", "/usr/local/bin/python3"]


def pick_python(candidates=None, exists=os.path.exists, fallback=None,
                clt_installed=_clt_installed):
    if clt_installed() and exists(SYSTEM_PYTHON):
        return SYSTEM_PYTHON
    for candidate in candidates if candidates is not None else PYTHON_CANDIDATES:
        if exists(candidate):
            return candidate
    return fallback if fallback is not None else sys.executable


def agent_env(python_path, clt_dir=CLT_DIR, exists=Path.exists):
    """Pin the system python to the Command Line Tools toolchain: with
    xcode-select pointing at Xcode.app, /usr/bin/python3 refuses to run after
    every Xcode update until the license is accepted again."""
    if python_path == SYSTEM_PYTHON and exists(clt_dir / "usr" / "bin" / "python3"):
        return {"DEVELOPER_DIR": str(clt_dir)}
    return None


def ensure_log_dir(log_path):
    """Create the log file's missing parent dirs (mode 700 — they live inside
    data/). launchd does not create directories for StandardOutPath; without
    this a fresh install's job fails to spawn. Existing dirs are left as-is."""
    missing = []
    directory = Path(log_path).parent
    while not directory.exists():
        missing.append(directory)
        directory = directory.parent
    for directory in reversed(missing):
        directory.mkdir()
        os.chmod(directory, 0o700)


def install(entry_path, log_path, interval_minutes=DEFAULT_INTERVAL_MINUTES):
    ensure_log_dir(log_path)
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    python_path = pick_python()
    path.write_bytes(build_plist(python_path, entry_path, log_path, interval_minutes,
                                 env=agent_env(python_path)))
    subprocess.run(["launchctl", "bootout", f"{_domain()}/{LABEL}"],
                   capture_output=True)  # ignore "not loaded"
    result = subprocess.run(["launchctl", "bootstrap", _domain(), str(path)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"launchctl bootstrap failed: {result.stderr.strip()}")
    print(f"agent installed: {path} (every {interval_minutes} min)")


def uninstall():
    subprocess.run(["launchctl", "bootout", f"{_domain()}/{LABEL}"],
                   capture_output=True)
    path = plist_path()
    if path.exists():
        path.unlink()
    print("agent uninstalled")


def status():
    result = subprocess.run(["launchctl", "print", f"{_domain()}/{LABEL}"],
                            capture_output=True, text=True)
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith(("state", "last exit code", "runs")):
                print(line)
        print(f"plist: {plist_path()}")
        return 0
    print("agent not installed")
    return 1
