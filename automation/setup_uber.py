#!/usr/bin/env python3
"""Generate absolute paths, optionally install/reload the user LaunchAgent."""
import argparse
import os
from pathlib import Path
import plistlib
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LABEL = 'com.careerpilot.uber'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--interval', type=int, default=7200)
parser.add_argument('--install', action='store_true')
parser.add_argument('--smoke-test', action='store_true', help='Schedule the local browser fixture instead of Uber')
args = parser.parse_args()
if args.interval < 60:
    parser.error('interval must be at least 60 seconds')
if sys.prefix == sys.base_prefix:
    parser.error('Run using .venv/bin/python (or your existing virtual environment)')
os.umask(0o077)
state = ROOT / '.automation/uber'
state.mkdir(parents=True, exist_ok=True, mode=0o700)
launcher = state / 'launch.sh'
launcher.write_text('#!/bin/sh\numask 077\ncd ' + shlex.quote(str(ROOT)) + '\nexec ' +
                    shlex.quote(sys.executable) + ' -u ' + shlex.quote(str(ROOT / 'automation/run_uber.py')) +
                    (' --smoke-test' if args.smoke_test else '') + '\n')
launcher.chmod(0o700)
config = dict(Label=LABEL, ProgramArguments=['/bin/sh', str(launcher)],
              WorkingDirectory=str(ROOT), RunAtLoad=True, StartInterval=args.interval,
              StandardOutPath=str(state / 'launchd.stdout.log'),
              StandardErrorPath=str(state / 'launchd.stderr.log'),
              ProcessType='Background', ExitTimeOut=20, AbandonProcessGroup=False,
              EnvironmentVariables={'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'PYTHONUNBUFFERED': '1'})
local = state / (LABEL + '.plist')
local.write_bytes(plistlib.dumps(config))
subprocess.run(['/usr/bin/plutil', '-lint', str(local)], check=True)
print('Generated', local)
if args.install:
    destination = Path.home() / 'Library/LaunchAgents' / local.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    domain = 'gui/' + str(os.getuid())
    subprocess.run(['/bin/launchctl', 'bootout', domain + '/' + LABEL], capture_output=True)
    destination.write_bytes(local.read_bytes())
    subprocess.run(['/bin/launchctl', 'enable', domain + '/' + LABEL], check=True)
    subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(destination)], check=True)
    print('Installed', destination, 'interval=', args.interval, 'smoke=', args.smoke_test)
