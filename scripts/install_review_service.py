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
    parser.add_argument('--model-service')
    parser.add_argument('--expected-model', help='Exact expected served model ID')
    parser.add_argument('--model-optional', action='store_true', help='Start the CPU review UI without starting or validating a model service')
    parser.add_argument('--api-url', default='http://127.0.0.1:8000/v1')
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    if not args.model_optional and (not args.model_service or not args.expected_model):
        parser.error('--model-service and --expected-model are required unless --model-optional is used')
    if args.model_service and not re.fullmatch(r'[A-Za-z0-9_.@-]+\.service', args.model_service):
        parser.error('model-service must name an existing systemd user service')
    repo = Path(__file__).resolve().parents[1]
    python = quoted(args.python.absolute())
    dependency = '' if args.model_optional else f'Wants={args.model_service}\nAfter={args.model_service}\n'
    readiness = '' if args.model_optional else f'ExecStartPre={python} {quoted(repo/"scripts/wait_for_model.py")} --api-url {quoted(args.api_url)} --timeout 600 --expected-model {quoted(args.expected_model)}\n'
    unit = f'''[Unit]
Description=Action Reframe CPU review UI{' (model optional)' if args.model_optional else ' with model readiness'}
{dependency}

[Service]
Type=simple
Environment={quoted('QWEN_API_URL='+args.api_url)}
{readiness}ExecStart={python} {quoted(repo/'src/review_server.py')} --workspace {quoted(args.workspace.resolve())} --port {args.port}
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
    if not args.model_optional:
        subprocess.run(['systemctl', '--user', 'cat', args.model_service], check=True, stdout=subprocess.DEVNULL)
    path = Path.home()/'.config/systemd/user/action-reframe-review.service'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(unit)
    for command in (['daemon-reload'], ['enable', path.name], ['restart', '--no-block', path.name]):
        subprocess.run(['systemctl', '--user', *command], check=True)
    print(path)


if __name__ == '__main__':
    main()
