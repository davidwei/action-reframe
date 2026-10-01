"""Run an explicitly authorized temporary model swap, always restoring production.

A systemd transient service with ExecStopPost restoration is recommended as an
additional guard against process termination. Does not edit production units.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.request


def models(endpoint):
    with urllib.request.urlopen(endpoint.rstrip('/') + '/models', timeout=5) as response:
        return json.load(response)['data']


def wait_model(endpoint, expected, timeout, process=None):
    deadline = time.monotonic() + timeout
    last = 'not ready'
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(f'Server exited with code {process.returncode}')
        try:
            ids = [row['id'] for row in models(endpoint)]
            if expected in ids:
                return
            last = f'Unexpected model IDs: {ids}'
        except Exception as exc:
            last = str(exc)
        time.sleep(2)
    raise TimeoutError(last)


def stop(process):
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=45)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=15)


def run(plan_path):
    plan = json.loads(plan_path.read_text())
    output = Path(plan['output']); output.mkdir(parents=True, exist_ok=True)
    record = dict(plan=plan, started=time.time(), runs=[], production_restored=False)
    path = output/'experiment.json'
    def save():
        temp=path.with_suffix('.tmp');temp.write_text(json.dumps(record,indent=2));temp.replace(path)
    def service(action):
        subprocess.run(['systemctl','--user',action,plan['production_service']],check=True,timeout=180)
    process = None
    monitor = None
    # Reject missing input files before touching production.
    for candidate in plan['candidates']:
        if not Path(candidate['path'],'config.json').is_file():
            raise ValueError(f"Missing model: {candidate['path']}")
    wait_model(plan['production_endpoint'],plan['production_model'],30)
    save()
    try:
        service('stop')
        for candidate in plan['candidates']:
            label=candidate['label'];folder=output/label;folder.mkdir(exist_ok=True)
            row=dict(candidate=candidate,status='starting',started=time.time());record['runs'].append(row);save()
            command=[plan['vllm'],'serve',candidate['path'],'--served-model-name',candidate['model'],
                     '--host','127.0.0.1','--port',str(plan['port']),
                     '--tensor-parallel-size','2','--max-model-len','8192',
                     '--max-num-seqs','2','--gpu-memory-utilization','0.90','--enforce-eager',
                     '--limit-mm-per-prompt','{"image":2,"video":0}']+candidate.get('extra_args',[])
            row['command']=command
            env=os.environ.copy();env.update(plan.get('environment',{}))
            try:
                with (folder/'server.log').open('w') as server_log, (folder/'gpu.csv').open('w') as gpu_log:
                    process=subprocess.Popen(command,stdout=server_log,stderr=subprocess.STDOUT,
                                             env=env,start_new_session=True)
                    monitor=subprocess.Popen(['nvidia-smi','--query-gpu=timestamp,index,utilization.gpu,memory.used,power.draw',
                                              '--format=csv','-l','1'],stdout=gpu_log,stderr=subprocess.DEVNULL,start_new_session=True)
                    start=time.monotonic()
                    wait_model(plan['experiment_endpoint'],candidate['model'],plan.get('startup_timeout',900),process)
                    row['startup_seconds']=time.monotonic()-start;row['status']='benchmarking';save()
                    with (folder/'benchmark.log').open('w') as log:
                        subprocess.run([plan['benchmark_python'],str(Path(__file__).with_name('benchmark.py')),
                                        'run','--manifest',plan['manifest'],'--output',str(folder/'results'),
                                        '--endpoint',plan['experiment_endpoint'],'--model',candidate['model']],
                                       stdout=log,stderr=subprocess.STDOUT,check=True,timeout=1800)
                    subprocess.run([plan['benchmark_python'],str(Path(__file__).with_name('report.py')),
                                    str(folder/'results/results.json'),'--output',str(folder/'report.html')],check=True)
                    row['summary']=json.loads((folder/'results/summary.json').read_text());row['status']='completed'
            except Exception as exc:
                row.update(status='failed',error=f'{type(exc).__name__}: {exc}')
            finally:
                stop(process);process=None;stop(monitor);monitor=None
                row['ended']=time.time();save()
            print(json.dumps(row),flush=True)
    finally:
        stop(process);stop(monitor)
        service('start')
        wait_model(plan['production_endpoint'],plan['production_model'],900)
        record['production_restored']=True;record['ended']=time.time();save()
        print('Production model restored and verified',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('plan',type=Path)
    run(parser.parse_args().plan)
