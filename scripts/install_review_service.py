#!/usr/bin/env python3
"""Generate/install a review service depending on an existing local model unit."""
import argparse
from pathlib import Path
import re
import subprocess
import sys


def quoted(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$') + '"'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--python', type=Path, default=Path(sys.executable))
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--model-service', required=True)
    parser.add_argument('--api-url', default='http://127.0.0.1:8000/v1')
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.@-]+\.service', args.model_service):
        parser.error('model-service must name an existing systemd user service')
    repo = Path(__file__).resolve().parents[1]
    python = quoted(args.python.absolute())
    unit = f'''[Unit]
Description=Action Reframe video review with model readiness
Wants={args.model_service}
After={args.model_service}

[Service]
Type=simple
Environment={quoted('QWEN_API_URL='+args.api_url)}
ExecStartPre={python} {quoted(repo/'scripts/wait_for_model.py')} --api-url {quoted(args.api_url)} --timeout 600
ExecStart={python} {quoted(repo/'src/review_server.py')} --workspace {quoted(args.workspace.resolve())} --port {args.port}
TimeoutStartSec=660
Restart=on-failure
RestartSec=10
# Queue workers are detached subprocesses; restarting the UI must leave them alive.
KillMode=process
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
'''
    if not args.install:
        print(unit)
        return
    subprocess.run(['systemctl', '--user', 'cat', args.model_service], check=True, stdout=subprocess.DEVNULL)
    path = Path.home()/'.config/systemd/user/action-reframe-review.service'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(unit)
    for command in (['daemon-reload'], ['enable', path.name], ['restart', '--no-block', path.name]):
        subprocess.run(['systemctl', '--user', *command], check=True)
    print(path)


if __name__ == '__main__':
    main()
