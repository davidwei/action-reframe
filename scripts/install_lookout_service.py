#!/usr/bin/env python3
"""Install a user-level collector service; no machine-specific paths in the repo."""
import argparse
from pathlib import Path
import subprocess
import sys

parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True);parser.add_argument('--python',type=Path,default=Path(sys.executable));parser.add_argument('--install',action='store_true')
a=parser.parse_args();source=Path(__file__).resolve().parents[1]/'src'
def quoted(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
unit=f'''[Unit]
Description=Lookout local telemetry and daily reports
After=default.target

[Service]
Type=simple
WorkingDirectory={str(source).replace('%','%%')}
ExecStart={quoted(a.python.absolute())} -m lookout.daemon --workspace {quoted(a.workspace.resolve())}
Restart=on-failure
RestartSec=5
Nice=10
UMask=0077

[Install]
WantedBy=default.target
'''
if not a.install:print(unit)
else:
    path=Path.home()/'.config/systemd/user/action-reframe-lookout.service';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(unit)
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    subprocess.run(['systemctl','--user','enable',path.name],check=True)
    subprocess.run(['systemctl','--user','restart',path.name],check=True)
    print(path)
