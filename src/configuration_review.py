"""Explain displayed-run settings without confusing overrides with stale results."""
import json
from pathlib import Path
from code_version import current, comparison


def flatten(value,prefix=''):
    result={}
    for key,item in value.items():
        name=f'{prefix}.{key}' if prefix else key
        if isinstance(item,dict):result.update(flatten(item,name))
        else:result[name]=item
    return result


def report(config,out,source=None):
    defaults=json.loads((Path(__file__).resolve().parent.parent/'configs/defaults.json').read_text())
    executed=Path(out)/'effective_config.json'
    displayed=json.loads(executed.read_text()) if config.get('batch_input_revision') and executed.exists() else config
    baseline=flatten(defaults);saved=flatten(displayed);latest=flatten(source or config)
    keys=set(baseline)|set(saved)|set(latest)
    excluded={'api_url','output_dir','video','ffmpeg','stage_store_dir','batch_input_revision','batch_stage'}
    rows=[]
    for key in sorted(keys):
        if key.startswith('_') or key in excluded:continue
        value=saved.get(key,baseline.get(key));wanted=latest.get(key,baseline.get(key))
        status='current';reason=''
        if key not in saved:
            status='unknown';reason='Not saved explicitly; shown value is today’s default, not proof of the historical setting.'
        elif source is not None and value!=wanted:
            status='outdated';reason='Differs from the current source project. Reprocess the affected stage to apply it.'
        elif key in baseline and value!=baseline[key]:
            status='override';reason='Project override; differing from the default alone does not make it outdated.'
        if key=='leveling_source' and value!='gyro':
            status='attention';reason='Gyro is not selected, contrary to the agreed gyro-first workflow. Confirm sensor availability before changing this. Anchor mode currently supplies no visual leveling estimates.'
        group=('Tracking and verification' if key.startswith(('tracking','verify','box_verification','anchor_tracking','backward','color_refinement')) else
               'Context and model' if key.startswith(('temporal','model','workers')) else
               'Leveling' if key.startswith('level') else
               'Sampling' if key in ('analysis_fps','sample_interval') else
               'Subject and references' if key.startswith(('target','approved_target','reference')) else 'Output and other settings')
        rows.append(dict(key=key,group=group,value=value,current=wanted,default=baseline.get(key),status=status,reason=reason))
    p=Path(out)/'code_version.json';versions=json.loads(p.read_text()) if p.exists() else {}
    code={stage:comparison(versions.get(stage),current()) for stage in ('analysis','render')}
    return dict(rows=rows,code=code,scope=('Executed configuration (includes settings for stages not run)' if executed.exists() else 'Saved batch configuration') if config.get('batch_input_revision') else 'Project configuration (may differ from an earlier rendered output)',
                outdated=sum(r['status']=='outdated' for r in rows),attention=sum(r['status']=='attention' for r in rows))
