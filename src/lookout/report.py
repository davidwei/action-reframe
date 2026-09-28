"""Evidence-backed daily recommendations, without priority scores."""
from collections import Counter,defaultdict
from datetime import datetime,date,timedelta
import json
import time
from zoneinfo import ZoneInfo
from .store import connect,settings


def bounds(day,timezone):
    d=date.fromisoformat(day);tz=ZoneInfo(timezone)
    return datetime.combine(d,datetime.min.time(),tz).timestamp(),datetime.combine(d+timedelta(days=1),datetime.min.time(),tz).timestamp()


def build(root,day):
    config=settings(root);lo,hi=bounds(day,config['timezone'])
    with connect(root) as db:
        events=[json.loads(r[0]) for r in db.execute('SELECT body FROM events WHERE ts>=? AND ts<? ORDER BY ts',(lo,hi))]
        decisions={r['key']:dict(r) for r in db.execute('SELECT * FROM decisions')}
    counts=Counter(e['kind'] for e in events);ux=[];ops=[]
    def add(dest,key,problem,evidence,change,benefit,uncertainty,verification):
        if not evidence:return
        decision=decisions.get(key,{})
        if decision.get('state') in ('dismissed','selected'):return
        if decision.get('state')=='deferred' and (not decision.get('until_day') or decision['until_day']>day):return
        examples=[]
        for e in evidence[:5]:examples.append({k:e[k] for k in ('id','timestamp','kind','action','operation','stage','outcome','project','job','duration_ms','error_kind','source') if k in e})
        dest.append(dict(key=key,problem=problem,evidence_count=len(evidence),examples=examples,
            proposed_change=change,expected_benefit=benefit,uncertainty=uncertainty,verification=verification))
    requests=[e for e in events if e['kind']=='request']
    add(ux,'ux.failed_actions','User actions fail or require another attempt',[e for e in requests if e.get('outcome')=='error'],
        'Make recovery and save status explicit beside the affected control.', 'Reduce uncertainty and repeated input.',
        'A failed request does not prove lost work; inspect linked action outcomes.', 'Compare repeated actions and failed saves per completed workflow.')
    nav=[e for e in events if e['kind']=='navigation' and e.get('operation')=='scroll']
    add(ux,'ux.review_controls','Review sessions involve repeated scrolling',nav if len(nav)>=5 else [],
        'Keep labeling and approval controls beside the video while scrolling.', 'Reduce navigation during frame review.',
        'Scrolling may be intentional reading. Control visibility and a user review are needed to confirm placement friction.', 'Compare scroll intervals and active time per saved label on similar review tasks.')
    checks=[e for e in events if e['kind']=='action' and e.get('action') in ('folder.refresh','view.reload')]
    add(ux,'ux.progress_clarity','Users repeatedly refresh status',checks if len(checks)>=3 else [],
        'Show the current stage, last progress, and whether intervention is needed.', 'Reduce manual checking.',
        'Refreshes may be checking for newly added videos, not stalled processing.', 'Compare manual checks during equivalent job stages; verify progress remains truthful.')
    edits=[e for e in events if e['kind']=='edit' and e.get('saved') is False]
    add(ux,'ux.edit_feedback','Text edits end without a confirmed save',edits,
        'Make save state visible and keep recoverable drafts.', 'Reduce repeated description editing.',
        'Leaving a field is not proof of abandonment; later saves may not yet be linked.', 'Measure confirmed saves and repeated edits per description workflow.')
    slow=[e for e in requests if e.get('duration_ms',0)>3000]
    add(ux,'ux.wait_feedback','Interactive requests take more than three seconds',slow,
        'Show task-specific pending feedback and keep unrelated controls usable.', 'Reduce repeated clicks and uncertainty while waiting.',
        'Request latency is not all active human waiting; use visible activity intervals.', 'Compare repeated clicks while pending and visible waiting per completed action.')
    jobs=[e for e in events if e['kind']=='job']
    failures=[e for e in jobs if e.get('outcome') in ('failed','interrupted')]
    modelerrors=[e for e in events if e['kind']=='model' and (e.get('outcome')=='error' or e.get('finish_reason')=='length')]
    add(ops,'ops.model_recovery','Model or job failures can require intervention',failures+modelerrors,
        'Audit bounded recovery across every model request; route frame-local failures to review.', 'Avoid manual restarts while preserving valid evidence.',
        'Some interrupted jobs were intentionally stopped. Existing recovery fixes may already cover part of this evidence.', 'Compare manual restarts per completed batch and unresolved-frame quality before and after.')
    preparation=[e for e in jobs if e.get('stage')=='preparation' and e.get('duration_ms',0)>60000]
    add(ops,'ops.preparation','Long preparation delays the start of analysis',preparation,
        'Use sequential or on-demand decoding and report preparation progress.', 'Reduce waiting and checks before useful analysis begins.',
        'Historical snapshots measure time since the job status update, not a precise preparation span. No UI attention history is inferred.', 'Compare time to first analysis, repeated seeks, and human status checks on the same input.')
    recovery=[e for e in events if e['kind']=='action' and e.get('action') in ('job.retry','job.stop','queue.start')]
    add(ops,'ops.unattended_queue','Queue operation needs manual intervention',recovery,
        'Improve idle pickup, service recovery, and consolidated needs-attention reporting.', 'Reduce babysitting of overnight processing.',
        'Starting or stopping a queue may be intentional, not a reliability failure.', 'Compare unplanned interventions per completed overnight batch.')
    reused=[e for e in events if e['kind']=='counter' and e.get('operation')=='cache.miss']
    retryjobs=[e for e in jobs if e.get('retry',0)>0]
    add(ops,'ops.reuse','Retried jobs may repeat preparation or analysis',retryjobs,
        'Expose checkpoint compatibility and reused work before retrying.', 'Avoid investigating or repeating already completed work.',
        'A retry alone does not prove cache loss; inspect cache counters and invalidation reasons.', 'Compare reused work and time to recovery, keeping input and version differences explicit.')
    intervals={}
    for e in events:
        if e['kind']=='activity':
            key=int(e['timestamp']//30)
            intervals[key]=max(intervals.get(key,0),min(30,e.get('active_seconds',0)))
    stages=defaultdict(lambda:dict(calls=0,wall_ms=0,cpu_ms=0,errors=0))
    for e in events:
        if e['kind']=='stage' and e.get('operation')=='end':
            s=stages[e.get('stage','unknown')];s['calls']+=1;s['wall_ms']+=e.get('duration_ms',0);s['cpu_ms']+=e.get('cpu_ms',0);s['errors']+=e.get('outcome')=='error'
    resources={}
    for metric in {e.get('metric') for e in events if e['kind']=='resource'}:
        values=[e['value'] for e in events if e['kind']=='resource' and e.get('metric')==metric]
        if values:resources[metric]=dict(samples=len(values),minimum=min(values),maximum=max(values),mean=sum(values)/len(values))
    latencies=sorted(e['duration_ms'] for e in events if e['kind']=='model' and 'duration_ms' in e)
    model_latency=dict(p50_ms=latencies[len(latencies)//2],p95_ms=latencies[min(len(latencies)-1,int(len(latencies)*.95))]) if latencies else {}
    result=dict(day=day,timezone=config['timezone'],generated=time.time(),events=len(events),
        coverage=dict(first=min((e['timestamp'] for e in events),default=None),last=max((e['timestamp'] for e in events),default=None),
            historical_snapshots=sum(e.get('source')=='queue_snapshot' for e in events),
            dropped=sum(e.get('count',0) for e in events if e.get('operation') in ('producer.dropped','collector.dropped'))),
        summary=dict(event_counts=dict(counts),active_seconds_estimate=sum(intervals.values()),sessions=len({e['session'] for e in events if e.get('session')}),
            resources=resources,model_latency=model_latency,model_calls=counts['model'],model_errors=len(modelerrors),job_interruptions=len(failures),stages=dict(stages)),
        ux=ux[:3],operations=ops[:3],decisions=decisions,
        limitations=['Activity is an estimate, not a measure of frustration or necessary effort.',
            'Overlapping tabs use the maximum activity in each 30-second bucket; distinct simultaneous users cannot be distinguished.',
            'Stage spans may overlap; CPU deltas are process-wide. Do not add nested spans or assign GPU samples to individual requests.',
            'Queue snapshots are historical state evidence, not reconstructed user sessions.',
            'No automatic retention. Sparse data yields fewer suggestions. Missing telemetry is not proof of no activity.'])
    with connect(root) as db:db.execute('INSERT OR REPLACE INTO reports VALUES(?,?,?)',(day,json.dumps(result),time.time()))
    return result


def markdown(report):
    lines=[f"# Lookout — {report['day']}",f"Timezone: {report['timezone']}. Events: {report['events']}.", '']
    for key,title in [('ux','UX improvements'),('operations','Operational improvements')]:
        lines+=['## '+title,'']
        if not report[key]:lines+=['Not enough evidence for a recommendation.','']
        for item in report[key]:
            lines+=['### '+item['problem'],'',f"Evidence: {item['evidence_count']} events."]
            for field in ('proposed_change','expected_benefit','uncertainty','verification'):lines.append(f"- {field.replace('_',' ').capitalize()}: {item[field]}")
            lines+=['']
    lines+=['## Limitations','']+['- '+s for s in report['limitations']]
    return '\n'.join(lines)+'\n'
