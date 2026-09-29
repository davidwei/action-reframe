#!/usr/bin/env python3
"""Read-only queue watch; records health every minute until the queue drains."""
import argparse
import datetime
import fcntl
import json
import re
import time
import urllib.request
from pathlib import Path


def lock_held(path):
    if not path.exists():
        return False
    with path.open('r') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    parser.add_argument('--interval', type=float, default=60)
    parser.add_argument('--stall-after', type=float, default=900,
                        help='Seconds without visible progress before a warning, not proof of a hang')
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--recover-all-failed', action='store_true',
                        help='Retry transient failures once if every watched job failed; never retry user stops')
    args = parser.parse_args()
    if args.interval <= 0 or args.stall_after <= 0:
        parser.error('Intervals must be positive')
    root = args.workspace.resolve()
    folder = root / '.batch' / 'monitor'
    folder.mkdir(parents=True, exist_ok=True)
    guard = (folder / 'monitor.lock').open('a')
    try:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        guard.close()
        raise SystemExit('Queue monitor is already running')
    seen, progress, offsets, failure_counts = set(), {}, {}, {}
    idle_checks = 0
    while True:
        started = time.monotonic()
        stamp = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
        alerts, rows = [], []
        drained = False
        try:
            with urllib.request.urlopen(args.url.rstrip('/') + '/api/batch', timeout=20) as response:
                state = json.load(response)
            active = [j for j in state['jobs'] if j['status'] in ('running', 'starting', 'queued')]
            seen.update(j['id'] for j in active)
            working = [j for j in active if j['status'] != 'queued']
            worker_alive = lock_held(root / '.batch' / 'worker.lock')
            if active and not state['paused'] and not worker_alive:
                alerts.append('Queue worker lock is not held; queue advancement may have stopped.')
            if state['paused'] and active:
                alerts.append('Queue is paused; waiting jobs will not advance.')
            for job in state['jobs']:
                if job['id'] not in seen:
                    continue
                jid, status = job['id'], job['status']
                out = (root / job['output_dir']).resolve()
                if not out.is_relative_to(root):
                    raise ValueError('Job output directory is outside the workspace')
                p = job.get('progress') or {}
                coverage = p.get('coverage', {})
                counts = {k: coverage[k].get('examined') for k in ('discovery', 'verification', 'optical') if k in coverage}
                row = dict(id=jid, project=job['project'], status=status, stage=p.get('stage'), coverage=counts)
                if job.get('error'):
                    row['error'] = job['error']
                if status in ('failed', 'interrupted'):
                    alerts.append(f"{jid}: {status}: {job.get('error') or 'see job log'}")
                if status in ('running', 'starting') and not lock_held(root / '.batch' / 'locks' / (jid + '.lock')):
                    alerts.append(f'{jid}: runner lock is not held (may be a brief startup/finish transition).')
                log = out / 'job.log'
                if log.exists():
                    size = log.stat().st_size
                    offset = offsets.get(jid, max(0, size - 65536))
                    if offset > size:
                        offset = 0
                    with log.open('rb') as stream:
                        stream.seek(max(offset, size - 1048576))
                        chunk = stream.read().decode('utf-8', errors='replace')
                    offsets[jid] = size
                    errors = [line[-1000:] for line in chunk.splitlines() if re.search(r'Traceback \(most recent call last\)|\b\w*(?:Error|Exception):|CUDA out of memory', line)]
                    alerts.extend(f'{jid}: {line}' for line in errors[-5:])
                failures = out / 'analysis_failures.json'
                if failures.exists():
                    count = len(json.loads(failures.read_text()))
                    row['frame_failures'] = count
                    if count > failure_counts.get(jid, 0):
                        alerts.append(f'{jid}: {count} frame failures recorded; inspect analysis_failures.json.')
                    failure_counts[jid] = count
                signature = json.dumps([p, offsets.get(jid)], sort_keys=True)
                old, changed = progress.get(jid, (None, started))
                if signature != old:
                    changed = started
                progress[jid] = signature, changed
                if status == 'running' and started - changed >= args.stall_after:
                    alerts.append(f'{jid}: no visible progress for {int(started-changed)}s; possible slow request/stall, not proof of failure.')
                rows.append(row)
            watched = [j for j in state['jobs'] if j['id'] in seen]
            marker = folder / 'automatic-recovery.json'
            if (args.recover_all_failed and watched and not active and not state['paused']
                    and all(j['status'] == 'failed' for j in watched) and not marker.exists()):
                # Write before mutation to prevent a restart from creating a retry loop.
                repair = dict(time=stamp, reason='All watched jobs failed', retried=[], needs_investigation=[])
                marker.write_text(json.dumps(repair, indent=2))
                for job in watched:
                    out = root / job['output_dir']
                    evidence = str(job.get('error') or '')
                    log = out / 'job.log'
                    if log.exists():
                        with log.open('rb') as stream:
                            stream.seek(max(0, log.stat().st_size-65536))
                            evidence += stream.read().decode('utf-8', errors='replace')
                    transient = re.search(r'timed? ?out|timeout|connection (?:reset|refused)|remote disconnected|'
                                          r'HTTP (?:Error )?(?:429|502|503|504)|output was truncated', evidence, re.I)
                    if not transient:
                        repair['needs_investigation'].append(job['id'])
                        continue
                    request = urllib.request.Request(args.url.rstrip('/')+'/api/batch/retry',
                        data=json.dumps({'id':job['id']}).encode(), headers={'Content-Type':'application/json'})
                    try:
                        with urllib.request.urlopen(request, timeout=20) as response:
                            json.load(response)
                        repair['retried'].append(job['id'])
                    except Exception as error:
                        repair['needs_investigation'].append(job['id'])
                        alerts.append(f"Recovery failed for {job['id']}: {error}")
                    marker.write_text(json.dumps(repair, indent=2))
                if repair['retried']:
                    request = urllib.request.Request(args.url.rstrip('/')+'/api/batch/start',
                        data=b'{}', headers={'Content-Type':'application/json'})
                    with urllib.request.urlopen(request, timeout=20) as response:
                        json.load(response)
                    # Wait for refreshed state before deciding the queue drained.
                    active = repair['retried']
                    alerts.append('All-job failure recovery: queued one retry for transient failures using saved inputs/caches.')
                if repair['needs_investigation']:
                    alerts.append('Automatic retry is not a fix for these errors; investigation required: '+', '.join(repair['needs_investigation']))
                marker.write_text(json.dumps(repair, indent=2))
            idle_checks = idle_checks + 1 if not active else 0
            drained = idle_checks >= 2
            record = dict(time=stamp, paused=state['paused'], worker_lock_held=worker_alive,
                          running=len(working), queued=len(active)-len(working), jobs=rows, alerts=alerts,
                          monitor_status='finished' if drained else 'watching')
        except Exception as error:
            record = dict(time=stamp, monitor_status='watching', jobs=rows,
                          alerts=alerts+[f'Health check failed: {type(error).__name__}: {error}'])
        with (folder / 'checks.jsonl').open('a') as stream:
            stream.write(json.dumps(record) + '\n')
        temp = folder / 'latest.tmp'
        temp.write_text(json.dumps(record, indent=2) + '\n')
        temp.replace(folder / 'latest.json')
        if record['alerts']:
            with (folder / 'alerts.jsonl').open('a') as stream:
                stream.write(json.dumps(record) + '\n')
        print(json.dumps(record), flush=True)
        if args.once or drained:
            guard.close()
            return
        time.sleep(max(0, args.interval - (time.monotonic() - started)))


if __name__ == '__main__':
    main()
