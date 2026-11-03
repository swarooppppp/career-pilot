# Uber background automation (macOS)

This is Uber-only. It reuses `career portal scripts/fetch_uber_jobs.py` (async Playwright); it does not run `sync_jobs.py` or import listings into the application database. Successful results atomically replace `data/uber_jobs.json`. Other portals and their scheduling are unaffected.

## Setup and operation

Run commands from the repository root. This installation created `.venv` with `python3 -m venv --system-site-packages .venv` because no existing project environment was found. It reuses this Mac's installed Playwright and python-dotenv. For a self-contained environment instead, create a normal venv and install those two dependencies. Setup accepts any venv: run it using that environment's Python. Chromium must be installed for that Python (`.venv/bin/python -m playwright install chromium`).

```sh
# Generate the absolute-path shell launcher and plist without installing
.venv/bin/python automation/setup_uber.py
# One-minute browser fixture test (no Uber network requests)
.venv/bin/python automation/setup_uber.py --install --interval 60 --smoke-test
# Inspect after at least 70 seconds: history should show two successful smoke runs
/bin/launchctl print "gui/$(id -u)/com.careerpilot.uber"
tail -30 .automation/uber/history.log
# Switch to real Uber, every two hours; runs once immediately, and after login
.venv/bin/python automation/setup_uber.py --install
# Trigger manually through launchd (does not require keeping a terminal open)
/bin/launchctl kickstart "gui/$(id -u)/com.careerpilot.uber"
# Direct run with the same lock/profile and default 300-second overall timeout
.venv/bin/python automation/run_uber.py
# Direct deterministic headed browser smoke test
.venv/bin/python automation/run_uber.py --smoke-test
# Stop/unload (also prevents future launches until bootstrap/login)
/bin/launchctl bootout "gui/$(id -u)/com.careerpilot.uber"
# Start/reload; also regenerates paths if the project moved
.venv/bin/python automation/setup_uber.py --install
# Restart a running execution (SIGTERM cleanup, followed by a new execution)
/bin/launchctl kickstart -k "gui/$(id -u)/com.careerpilot.uber"
# Permanently disable across login; setup --install enables again
/bin/launchctl disable "gui/$(id -u)/com.careerpilot.uber"
/bin/launchctl bootout "gui/$(id -u)/com.careerpilot.uber"
# Uninstall after unloading
rm "$HOME/Library/LaunchAgents/com.careerpilot.uber.plist"
```

Generated files are `.automation/uber/launch.sh` and `.automation/uber/com.careerpilot.uber.plist`; the installer copies the plist into `~/Library/LaunchAgents/`. They use absolute paths, `StartInterval=7200`, `RunAtLoad=true`, and separate launchd stdout/stderr logs. No shell activation, interactive shell configuration, Terminal or VS Code is required. The scheduler runs only in the logged-in GUI session. macOS's current `man launchd.plist` says interval firings while asleep are **missed**; it does not wake the Mac or promise an immediate catch-up on wake. Later intervals resume while awake. In-flight timeouts can be delayed by sleep. There is no KeepAlive retry loop.

## macOS permissions and visibility

**Observed blocker on this Mac:** launchd's shell cannot read the repository under Desktop (`Operation not permitted`, exit 126). Terminal access does not imply launchd access. Preferred fix: move the project to an unprotected directory such as `~/Projects/Resume JD matcher`, recreate the venv there, and rerun setup. Alternatively grant the relevant shell/Python executable the necessary access in System Settings → Privacy & Security (Files and Folders, or Full Disk Access where needed), then reinstall. Full Disk Access is broad; macOS controls these grants and the scripts do not change them. Inherited system packages currently live outside Desktop.

Hiding uses `/usr/bin/osascript` and System Events, selecting **only Unix PIDs whose main Chromium command uses this automation's exact dedicated profile**. It never hides an application by name and never selects your usual Chrome/Chromium profile. macOS may ask for Automation permission to control System Events, and Accessibility permission for the responsible Python executable/launch context. Grant permissions only through System Settings, then rerun the one-minute fixture. Permission denial is logged; fetching continues. A zero AppleScript status means the command succeeded, not proof the window was never visible. Launching can briefly show or focus Chromium before the first hide attempt; completely invisible headed execution and zero focus stealing cannot be guaranteed on macOS. We do not forcibly refocus your previous application, which could interrupt work again.

Check actual desktop behavior manually while typing in another app. Close Terminal and VS Code, wait at least 70 seconds in test mode, reopen and check new success timestamps. This proves execution is independent of those apps. Reboot/login and sleep/wake behavior also require manual verification. Do not grant permissions to unrelated apps just to hide Chromium.

## Sessions, safety, and manual verification

The dedicated persistent profile is `.automation/uber/profile` (test profile: `smoke-profile`). Only this runner may use it. It retains browser-supported cookies/local storage, subject to site expiration and browser session-cookie behavior; it never copies your personal browser cookies. `flock` prevents direct and scheduled runners overlapping, including fixture runs; the lock is kernel-released on crash and is never deleted. A stale PID written inside the lock file does not block a run. Do not remove the lock file or manually open the profile while a run is active. Existing normal sync uses a separate temporary context, so it cannot corrupt this profile.

The supervisor bounds runtime to 300 seconds, handles SIGINT/SIGTERM, asks the worker to unwind its context `finally`, waits up to ten seconds, and escalates to killing its process group. Playwright launches Chromium in its own group, so cleanup also checks exact-profile main browser groups, including leftovers recovered on the next run. No broad `killall` or process-name matching is used. SIGKILL/power failure cannot run Python cleanup; next-run recovery is best effort. Chromium's own singleton locking provides another guard; the runner does not delete browser singleton files.

Cloudflare verification is detected and logged as `MANUAL_VERIFICATION_REQUIRED`, and the run stops. It does not solve challenges, install stealth patches, or retry to defeat verification. A human can review the screenshot and, if authorized, use a separate interactive session with the dedicated profile after unloading the agent and ensuring no runner is active. No automated cookie transfer or bypass is provided. `--show-browser` disables hiding for diagnosis; it still stops on verification.

## Logs and debugging

- `.automation/uber/history.log`: timestamped start/end, duration, status, hiding results, overlap skips; rotates at 2 MB with three backups.
- `.automation/uber/launchd.stdout.log` and `launchd.stderr.log`: scheduler output and startup failures. These do not auto-rotate; archive/truncate periodically while unloaded.
- `.automation/uber/diagnostics/<UTC-run-id>/status.json`, `worker.log`, and `failure.png` where possible. Screenshots can contain personal data. Files are private (umask 077) and git-ignored; delete old run directories periodically.

Logs intentionally omit the configured URL, cookies, credentials, raw page HTML, and Playwright exception messages (which can embed sensitive URLs). Failure diagnostics record exception type and stack locations; screenshot capture is best effort and can fail if browser launch fails or the page closes. The `.env` file is parsed as data, never sourced by a shell. Only `UBER_JOBS_URL`, `UBER_MAX_PAGES`, `UBER_MAX_JOBS`, and `UBER_TIMEOUT` are read. Environment overrides `.env`.

For startup errors use `launchctl print`, `plutil -lint .automation/uber/com.careerpilot.uber.plist`, and the stderr log. For a fetch failure, inspect the latest private diagnostics, then run `automation/run_uber.py --show-browser`. For hiding failures, check the `browser_hide` status and Automation/Accessibility settings; rerun the fixture rather than repeatedly hitting Uber. `status=skipped` is expected when another runner holds the lock. Missing Playwright/Chromium requires installing it using the same venv interpreter configured by setup. The fixture exercises real headed persistent Chromium, navigation, selector waiting, in-page API fetch and close using routed local responses, so it does not establish that Uber will accept the session.

## Verification on this Mac

- Real Uber fetch succeeded and wrote 8 normalized listings using headed persistent Chromium.
- Real headed browser fixture passed; PID-specific AppleScript hiding returned status 0 during timeout testing. Visual absence/focus behavior still needs manual observation.
- A 2-second fixture timeout returned failure with `status=timeout`; no dedicated Chromium browser groups remained afterward.
- Two process-safety tests passed (exact-profile targeting and kernel lock recovery after a killed lock holder); three existing Uber tests passed. A direct overlapping runner skipped correctly.
- The one-minute LaunchAgent fired twice independently, but both runs exited 126 because macOS denied access to Desktop. It was then replaced with the real Uber configuration at 7,200 seconds. The agent is installed but scheduled fetching remains blocked until the Desktop privacy restriction is resolved.
- Terminal-closed successful execution, reboot/login, sleep/wake timing, and uninterrupted desktop behavior cannot be confirmed until folder permissions are fixed and manually observed.
