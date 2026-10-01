#!/usr/bin/env python3
"""Install the persistent queue supervisor; preserves pause and failure states."""
import argparse
from pathlib import Path
import subprocess
import sys
import re
from install_review_service import quoted


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--python',type=Path,default=Path(sys.executable))
    parser.add_argument('--model-service',required=True)
    parser.add_argument('--expected-model',required=True)
    parser.add_argument('--api-url',default='http://127.0.0.1:8000/v1')
    parser.add_argument('--install',action='store_true')
    a=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.@-]+\.service',a.model_service):parser.error('Invalid model service')
    repo=Path(__file__).resolve().parents[1];python=quoted(a.python.absolute())
    unit=f'''[Unit]
Description=Action Reframe persistent queue and interruption recovery
Wants={a.model_service}
After={a.model_service}

[Service]
Type=simple
Environment={quoted('QWEN_API_URL='+a.api_url)}
ExecStartPre={python} {quoted(repo/'scripts/wait_for_model.py')} --api-url {quoted(a.api_url)} --expected-model {quoted(a.expected_model)} --timeout 600
ExecStart={python} {quoted(repo/'src/batch_workflow.py')} --workspace {quoted(a.workspace.resolve())} --supervise
TimeoutStartSec=660
Restart=always
RestartSec=10
KillMode=process
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
'''
    if not a.install:print(unit);return
    subprocess.run(['systemctl','--user','cat',a.model_service],stdout=subprocess.DEVNULL,check=True)
    path=Path.home()/'.config/systemd/user/action-reframe-queue.service';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(unit)
    for args in (['daemon-reload'],['enable',path.name],['restart','--no-block',path.name]):
        subprocess.run(['systemctl','--user',*args],check=True)
    print(path)


if __name__=='__main__':main()
