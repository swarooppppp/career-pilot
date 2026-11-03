#!/usr/bin/env python3
"""Manage the personal macOS Career Pilot LaunchAgent."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
LABEL = "com.careerpilot.local"
PLIST = Path.home() / "Library" / "LaunchAgents" / (LABEL + ".plist")
LOG = ROOT / "data" / "logs" / "local-service.log"
DOMAIN = f"gui/{os.getuid()}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "start", "stop", "status", "logs", "uninstall"])
    args = parser.parse_args()
    if args.action == "install":
        LOG.parent.mkdir(parents=True, exist_ok=True)
        PLIST.parent.mkdir(parents=True, exist_ok=True)
        document = {"Label": LABEL, "ProgramArguments": [str(ROOT / ".venv" / "bin" / "python"), str(ROOT / "run_local.py")],
                    "WorkingDirectory": str(ROOT), "RunAtLoad": True, "KeepAlive": True,
                    "ThrottleInterval": 30, "StandardOutPath": str(LOG), "StandardErrorPath": str(LOG),
                    "EnvironmentVariables": {"PATH": str(ROOT / ".venv" / "bin") + ":/opt/homebrew/bin:/Library/TeX/texbin:/usr/local/bin:/usr/bin:/bin", "PYTHONUNBUFFERED": "1", "HOST": "127.0.0.1", "PORTAL_SCHEDULER_ENABLED": "true"}}
        with PLIST.open("wb") as handle:
            plistlib.dump(document, handle)
        subprocess.run(["launchctl", "bootout", DOMAIN + "/" + LABEL], capture_output=True)
        subprocess.run(["launchctl", "bootstrap", DOMAIN, str(PLIST)], check=True)
        time.sleep(2)
        try:
            with urlopen("http://127.0.0.1:8000/health", timeout=3) as response:
                assert response.status == 200
            print("Installed and started: http://127.0.0.1:8000")
        except Exception:
            print("LaunchAgent installed, but startup failed. Inspect: " + str(LOG))
            print("If macOS denies Desktop access, grant the Python interpreter access in System Settings > Privacy & Security, then start again.")
            raise SystemExit(1)
    elif args.action == "start":
        subprocess.run(["launchctl", "bootstrap", DOMAIN, str(PLIST)], capture_output=True)
        subprocess.run(["launchctl", "kickstart", DOMAIN + "/" + LABEL], check=True)
    elif args.action in {"stop", "uninstall"}:
        subprocess.run(["launchctl", "bootout", DOMAIN + "/" + LABEL], check=False)
        if args.action == "uninstall":
            PLIST.unlink(missing_ok=True)
    elif args.action == "status":
        subprocess.run(["launchctl", "print", DOMAIN + "/" + LABEL], check=False)
    else:
        subprocess.run(["tail", "-n", "80", "-f", str(LOG)], check=False)


if __name__ == "__main__":
    main()
