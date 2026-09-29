"""Per-project description work status and cross-thread/process duplicate protection."""
import fcntl
import hashlib
import json
import time
import uuid
from pathlib import Path


def paths(batch,project):
    key=hashlib.sha256(str(batch.path(project).resolve()).encode()).hexdigest()
    folder=batch.folder/'description_jobs';folder.mkdir(parents=True,exist_ok=True)
    return folder/(key+'.lock'),folder/(key+'.json')


def save(path,value):
    temp=path.with_name(uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value));temp.replace(path)


def status(batch,project):
    lock,path=paths(batch,project)
    with lock.open('a') as stream:
        try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB);running=False
        except BlockingIOError:running=True
        data=json.loads(path.read_text()) if path.exists() else {}
        if running:return dict(data,status='running')
        if data.get('status')=='running':return dict(data,status='interrupted',error='Description work stopped before completion. You can retry.')
        return data


def run(batch,project,action,compute):
    lock,path=paths(batch,project)
    with lock.open('a') as stream:
        try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Description work is already running for this project. Wait for it to finish.')
        job=dict(id=uuid.uuid4().hex,action=action,status='running',started=time.time())
        save(path,job)
        try:
            result=compute()
        except BaseException as error:
            job.update(status='failed',finished=time.time(),error=str(error))
            if hasattr(error,'details'):job['model_error']=error.details
            save(path,job);raise
        job.update(status='succeeded',finished=time.time());save(path,job)
        return dict(result,job=job)
