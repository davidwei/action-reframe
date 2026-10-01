#!/usr/bin/env python3
"""Wait for an OpenAI-compatible model list before starting dependent services."""
import argparse
import json
import time
import urllib.error
import urllib.request


def wait(url, timeout):
    deadline = time.monotonic() + timeout
    endpoint = url.rstrip('/') + '/models'
    while True:
        try:
            with urllib.request.urlopen(endpoint, timeout=min(5, max(.1, deadline-time.monotonic()))) as response:
                models = json.load(response)['data']
            if not models:
                raise ValueError('model list is empty')
            print(f'Model ready: {models[0]["id"]}', flush=True)
            return
        except (OSError, ValueError, KeyError) as error:
            if time.monotonic() >= deadline:
                raise SystemExit(f'Model unavailable at {endpoint}: {error}')
            print(f'Waiting for model at {endpoint}: {error}', flush=True)
            time.sleep(min(5, max(0, deadline-time.monotonic())))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--api-url', required=True)
    parser.add_argument('--timeout', type=float, default=600)
    args = parser.parse_args()
    wait(args.api_url, args.timeout)
