"""Resolve nested defaults and retain the exact configuration of each execution."""
import copy
import json
import time
import uuid
from pathlib import Path


def merge(defaults, overrides):
    result=copy.deepcopy(defaults)
    for key,value in overrides.items():
        result[key]=merge(result[key],value) if isinstance(result.get(key),dict) and isinstance(value,dict) else copy.deepcopy(value)
    return result


def save(config, stage):
    from reframe import write_json
    from code_version import current
    out=Path(config['output_dir']);out.mkdir(parents=True,exist_ok=True)
    value={k:copy.deepcopy(v) for k,v in config.items() if not k.startswith('_')}
    folder=out/'execution_configs';folder.mkdir(exist_ok=True)
    record=dict(started_at=time.time(),stage=stage,code=current(),config=value)
    path=folder/(time.strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex+'.json')
    write_json(path,record)
    write_json(out/'effective_config.json',value)
    write_json(out/'effective_config_record.json',dict(record=str(path),stage=stage,started_at=record['started_at']))
    if stage in ('all','analyze'):write_json(out/'run_config.json',value)
    elif stage=='render':write_json(out/'render_config.json',value)
    return path
