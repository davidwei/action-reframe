"""Run several leveling jobs while loading each local model only when needed.

Use this under a transient systemd service with an independent ExecStopPost that
starts the production model service. The runner also restores production in its
own finally block and verifies its exact served model ID.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request


def read(url,timeout=5):
    with urllib.request.urlopen(url,timeout=timeout) as response:return json.load(response)


def wait_model(endpoint,expected,timeout,process=None):
    deadline=time.monotonic()+timeout;last="not ready"
    while time.monotonic()<deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"Model server exited with {process.returncode}")
        try:
            ids=[row["id"] for row in read(endpoint.rstrip('/')+'/models')["data"]]
            if expected in ids:return
            last=f"unexpected model IDs: {ids}"
        except Exception as error:last=str(error)
        time.sleep(2)
    raise TimeoutError(last)


def stop(process):
    if process is None:return
    try:os.killpg(process.pid,signal.SIGTERM)
    except ProcessLookupError:return
    try:process.wait(timeout=60)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=15)


def command(plan,job,stage,model=None):
    value=[plan["python"],"-m","standalone.video_leveling.cli",stage,
           "--video",job["video"],"--output",job["output"],"--hours",str(job["hours"]),
           "--primary-model",plan["primary"]["served_name"],
           "--review-model",plan["review"]["served_name"],
           "--api-url",plan["experiment_endpoint"]]
    for name,value_ in job.get("options",{}).items():value.extend(["--"+name.replace('_','-'),str(value_)])
    return value


def run_stage(plan,job,stage,log):
    with log.open("a") as handle:
        subprocess.run(command(plan,job,stage),cwd=plan["working_directory"],stdout=handle,
                       stderr=subprocess.STDOUT,check=True,timeout=plan.get("stage_timeout",25200))


def launch(plan,candidate,folder):
    cmd=[plan["vllm"],"serve",candidate["path"],"--served-model-name",candidate["served_name"],
         "--host","127.0.0.1","--port",str(plan["port"]),"--tensor-parallel-size","2",
         "--max-model-len",str(plan.get("max_model_len",8192)),"--max-num-seqs","2",
         "--gpu-memory-utilization","0.90","--enforce-eager","--limit-mm-per-prompt",'{"image":2,"video":0}']+candidate.get("extra_args",[])
    env=os.environ.copy();env.update(plan.get("environment",{}))
    return subprocess.Popen(cmd,cwd=plan["working_directory"],env=env,start_new_session=True,
                            stdout=(folder/f"{candidate['label']}.server.log").open("a"),stderr=subprocess.STDOUT)


def run(path):
    plan=json.loads(path.read_text());root=Path(plan["run_output"]);root.mkdir(parents=True,exist_ok=True)
    record=dict(plan=plan,started=time.time(),events=[],production_restored=False)
    record_path=root/"orchestration.json"
    def save():
        temp=record_path.with_suffix('.tmp');temp.write_text(json.dumps(record,indent=2));temp.replace(record_path)
    def service(action,name):subprocess.run(["systemctl","--user",action,name],check=True,timeout=180)
    for candidate in (plan["primary"],plan["review"]):
        if not Path(candidate["path"],"config.json").is_file():raise ValueError(f"Missing model weights: {candidate['path']}")
    wait_model(plan["production_endpoint"],plan["production_model"],300);save();process=None
    paused=[]
    try:
        for name in plan.get("pause_services",[]):
            active = subprocess.run(
                ["systemctl", "--user", "is-active", "--quiet", name]
            ).returncode == 0
            if active:service("stop",name);paused.append(name)
        service("stop",plan["production_service"])
        for job in plan["jobs"]:
            log=root/(Path(job["output"]).name+".log")
            for stage in ("init","prepare"):run_stage(plan,job,stage,log)
        process=launch(plan,plan["primary"],root);wait_model(plan["experiment_endpoint"],plan["primary"]["served_name"],900,process)
        for job in plan["jobs"]:
            log=root/(Path(job["output"]).name+".log")
            for stage in ("primary","motion","refine"):run_stage(plan,job,stage,log)
        stop(process);process=None
        process=launch(plan,plan["review"],root);wait_model(plan["experiment_endpoint"],plan["review"]["served_name"],900,process)
        for job in plan["jobs"]:run_stage(plan,job,"review",root/(Path(job["output"]).name+".log"))
        stop(process);process=None
        for job in plan["jobs"]:
            log=root/(Path(job["output"]).name+".log")
            for stage in ("motion","export"):run_stage(plan,job,stage,log)
        record["status"]="completed"
    except Exception as error:
        record.update(status="failed",error=f"{type(error).__name__}: {error}");raise
    finally:
        stop(process)
        try:
            service("start",plan["production_service"])
            wait_model(plan["production_endpoint"],plan["production_model"],900)
            record["production_restored"]=True
        finally:
            for name in reversed(paused):service("start",name)
            record["ended"]=time.time();save()


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("plan",type=Path);run(parser.parse_args().plan)
