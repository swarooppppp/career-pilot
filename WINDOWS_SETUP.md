# Career Pilot on your Windows laptop

You will install the app once, restore your existing data, and keep it running after sign-in. **Fetching jobs stays manual:** click **Fetch jobs now**. Background matching still submits new eligible jobs and checks batch results hourly.

These instructions use **Windows 11, 64-bit, Python 3.12**, native Windows (not WSL). Your browser dashboard remains **http://127.0.0.1:8000**. Keep the laptop awake and signed in while fetching; sleep pauses work and shutdown stops it. The app does not wake the laptop.

## 1. Install four programs

Use the official installers:

1. **Git for Windows:** https://git-scm.com/download/win — default options are fine.
2. **Python 3.12 (64-bit):** https://www.python.org/downloads/windows/ — choose a Python 3.12 Windows installer. Enable **Add python.exe to PATH** and the **Python Launcher** (`py`). Do not copy Python or `.venv` from the Mac.
3. **Google Chrome:** https://www.google.com/chrome/ — normal installation for your Windows account.
4. **MiKTeX:** https://miktex.org/howto/install-miktex — install for your current user. Open **MiKTeX Console**, check/install updates, and set **Settings → General → Install missing packages on-the-fly → Always**. Resume generation needs `pdflatex` and the packages in `main.tex`. If a package download fails, fix it in MiKTeX Console before continuing.

Close any old PowerShell windows after installing these programs, then open a new **Windows PowerShell** from Start. You do not need to run it as Administrator.

## 2. Download the code

Copy each line into PowerShell and press Enter:

```powershell
New-Item -ItemType Directory -Force "$HOME\Projects"
Set-Location "$HOME\Projects"
git clone https://github.com/swarooppppp/career-pilot.git
Set-Location career-pilot
```

If GitHub asks you to sign in, use your personal `swarooppppp` account and complete the browser sign-in yourself. Do not paste a token into a command. Keep this project outside OneDrive-synced folders so the database is not synced while it is open.

## 3. Set up the Windows environment

From that same PowerShell window:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows.ps1 setup
```

This creates `.venv`, installs Python dependencies with the checked-in version constraints, installs Chromium, and tests Chrome, Chromium, the India timezone and PDF compilation. It does **not** fetch jobs or call OpenAI.

The execution-policy argument applies only to this invocation; it does not change your permanent system policy. If your organization enforces a script policy, follow it rather than changing security settings.

If setup reports a missing LaTeX package, install it through MiKTeX Console and rerun the same command. If `pdflatex` is missing, close/reopen PowerShell after installing MiKTeX, return to the project directory, and retry. A successful check ends with `Ready: Chrome, Chromium, India timezone and resume PDF compilation passed`.

## 4. Transfer your private files from the Mac

The Mac implementation creates `migration-private/`. Transfer these **two files privately** using a USB drive or another private transfer method:

- The `career-pilot-<timestamp>.migration.zip` archive.
- The `.env` file beside it. This contains your existing credentials; never upload it to GitHub or share it in chat.

Do not start the Windows app before restoring. Do not restart the Mac app after the final migration snapshot; Windows is now the only machine that runs matching and owns the database.

On Windows:

1. Copy `.env` into `$HOME\Projects\career-pilot` — alongside `run_local.py`, **not** inside `.venv`.
2. In File Explorer choose **View → Show → File name extensions**. Ensure the file is named `.env`, not `.env.txt`.
3. Open it locally in Notepad and confirm these settings (preserve the existing keys and model names):

   ```dotenv
   DATABASE_URL="sqlite:///data/career_pilot.db"
   PORTAL_SCHEDULER_ENABLED="false"
   MATCH_EXECUTION_MODE="batch"
   OPENAI_BATCH_SUBMIT_INTERVAL_MINUTES="60"
   OPENAI_BATCH_POLL_INTERVAL_MINUTES="60"
   OPENAI_BATCH_SUBMIT_LIMIT="100"
   ```

   If you see Mac-specific absolute file paths, stop and adjust them for this clone; the normal local database setting above is relative and works unchanged.
4. Put the migration zip in your **Downloads** folder. Run this command, replacing the example filename with the actual one:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\windows.ps1 restore "$HOME\Downloads\career-pilot-YYYYMMDD_HHMMSS.migration.zip"
   ```

   You can drag the file into PowerShell to insert its full path. Keep quotes around paths with spaces.

Restore checks every file checksum, SQLite integrity and table/job-state counts before installing the database. It also restores generated PDFs, matching caches, adapter caches and collection history. It does not restore browser profiles or the Mac virtual environment.

**If it says “Database already exists”:** do not overwrite it blindly. First run the backup command in section 9, check which database you want to retain, then use `-Replace` only when intentionally replacing it. A replacement also overwrites archived local profile/history files.

## 5. Check and start

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows.ps1 check
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows.ps1 start
```

Open **http://127.0.0.1:8000** in Chrome.

Check:

- Your jobs and matching scores appear.
- **Saved jobs** contains your saved roles.
- Applied/deleted jobs remain hidden.
- An existing generated resume downloads.
- Collection status says **manual collection only**.

Startup resumes monitoring existing OpenAI batches and may submit eligible pending jobs from your restored database using your existing key. It does not submit jobs that already have unchanged matching results.

## 6. Keep the app running after Windows sign-in

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows.ps1 install
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows.ps1 status
```

This registers **CareerPilotLocal** in Task Scheduler for your own signed-in account and starts it now. It restarts after a crash, runs on battery, and prevents duplicate service instances. It does not store a Windows password or require Administrator access. It does not open a console window or run any fetching schedule.

The app starts about 15 seconds after **sign-in**, not before you sign in. This is necessary for Uber's headed browser to run in your desktop session. It stays available while your session is locked, but sleep/shutdown still pause/stop execution.

You may now close PowerShell. Bookmark http://127.0.0.1:8000.

## 7. Test fetching and resume generation on Windows

First test one headless adapter and Uber separately, without importing to the dashboard:

```powershell
.\.venv\Scripts\python.exe -X utf8 local_career_portals\run.py rubrik --max-jobs 5
.\.venv\Scripts\python.exe -X utf8 local_career_portals\run.py uber --max-jobs 5
```

Uber should use its dedicated minimized headed browser. A browser can appear briefly before minimization. Access restrictions such as 403/429 can still happen; a new operating system does not guarantee every portal accepts automation.

Then click **Fetch jobs now** once. It runs all available company adapters, three at a time, up to 50 jobs each. Jobs appear as companies finish. Watch source results for failures. Do not start a second full collection; overlap is blocked.

For an eligible job, verify **pending matching → score → Generate resume → Download resume**. The downloaded PDF is named **Swaroop_Software_Engineer.pdf**. Verify **Save job → Saved jobs → Unsave**, and that Applied/Delete hide a job.

These live checks must happen on your Windows laptop. Mac tests and automated Windows CI do not prove that your Windows network or every career portal will accept fetching.

## 8. Pull future changes from the Mac

On the Mac, make code changes, test, commit and push to `main` as usual. Keep the Mac app stopped. Never commit `.env`, the SQLite database, migration files, or generated PDFs.

On Windows, open PowerShell and run:

```powershell
Set-Location "$HOME\Projects\career-pilot"
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows.ps1 update
```

The updater refuses to proceed if fetching/resume generation is active or there are local code changes. Otherwise it gracefully stops the app, makes a private database/artifact backup, pulls with `--ff-only`, updates dependencies and Chromium, checks readiness, and restarts if the app was running.

If an update fails, the app stays stopped and the backup remains in `data\backups`. Fix the displayed error, then use **start**. Code updates preserve Windows credentials, job states and local data. Database changes are applied by existing startup migrations; do not restore the old Mac snapshot after every pull.

## 9. Everyday commands

Run these from the repository folder:

```powershell
# Check whether the app is running
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows.ps1 status

# Show recent logs
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows.ps1 logs

# Stop gracefully (wait until fetching/resume generation completes first)
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows.ps1 stop

# Start again
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows.ps1 start

# Make a private backup while stopped; choose a new filename each time
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows.ps1 backup "$HOME\Downloads\career-pilot-backup.migration.zip"

# Remove automatic app startup and stop it; this does not delete data
powershell -NoProfile -ExecutionPolicy Bypass -File .\windows.ps1 uninstall
```

Logs are in `data\logs\windows-service.log`. Task Scheduler should show **CareerPilotLocal** running after login. If the browser says connection refused, run status/logs, then start. If another server occupies port 8000, stop that duplicate before starting this one.

If networking fails with VPN connected, compare one fetch with VPN disconnected. The application does not change your VPN, firewall, or endpoint-security settings.

## Mac cutover / another final backup

The final archive prepared during implementation is the initial migration snapshot. If you deliberately run the Mac app again and change jobs afterward, create a new final snapshot before restoring Windows:

```sh
.venv/bin/python automation/local_service.py stop
.venv/bin/python automation/migrate_local.py backup migration-private/career-pilot-NEW-TIMESTAMP.migration.zip
```

Keep `.env` separate and private. Never run both copies against independent databases and expect them to merge: Git synchronizes code, not your database.
