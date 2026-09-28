"""Loopback-only Lookout API; browser events use a stricter allowlist."""
from datetime import datetime,timedelta,date
import json
from pathlib import Path
import time
from zoneinfo import ZoneInfo
from . import events
from .store import connect,folder,settings,status
from .report import build,markdown

BROWSER_KINDS={'view','activity','action','edit','navigation','playback','request','ui_error'}


def get(handler,root,path,query):
    if path=='/api/lookout/status':handler.json_response(status(root));return True
    if path in ('/api/lookout/report','/api/lookout/markdown'):
        day=query.get('day',[datetime.now(ZoneInfo(settings(root)['timezone'])).date().isoformat()])[0]
        date.fromisoformat(day)
        with connect(root) as db:row=db.execute('SELECT body FROM reports WHERE day=?',(day,)).fetchone()
        report=json.loads(row[0]) if row else build(root,day)
        if path.endswith('markdown'):
            data=markdown(report).encode();handler.send_response(200);handler.send_header('Content-Type','text/markdown; charset=utf-8');handler.send_header('Content-Length',str(len(data)));handler.end_headers();handler.wfile.write(data)
        else:handler.json_response(report)
        return True
    if path=='/api/lookout/export':
        handler.send_response(200);handler.send_header('Content-Type','application/x-ndjson');handler.send_header('Content-Disposition','attachment; filename="lookout-events.ndjson"');handler.end_headers()
        with connect(root) as db:
            for row in db.execute('SELECT body FROM events ORDER BY ts'):handler.wfile.write((row[0]+'\n').encode())
        return True
    if path=='/api/lookout/evidence':
        key=query.get('id',[''])[0]
        with connect(root) as db:row=db.execute('SELECT body FROM events WHERE id=?',(key,)).fetchone()
        handler.json_response(json.loads(row[0]) if row else {},200 if row else 404);return True
    return False


def post(root,action,data):
    if action=='events':
        batch=data.get('events')
        if not isinstance(batch,list) or len(batch)>50 or len(json.dumps(data))>65536:raise ValueError('Telemetry batch exceeds limits')
        clean=[]
        for item in batch:
            value=events.validate(item)
            if value['kind'] not in BROWSER_KINDS:raise ValueError('Not a browser event')
            if abs(value['timestamp']-time.time())>86400:raise ValueError('Invalid event timestamp')
            # Never accept paths or browser-provided resource/model telemetry.
            clean.append(value)
        if not settings(root)['enabled']:return {'accepted':0,'disabled':True}
        accepted=sum(events.emit(**e) for e in clean)
        return {'accepted':accepted,'dropped':len(clean)-accepted}
    if action=='settings':
        c=settings(root)
        if 'enabled' in data:
            if type(data['enabled']) is not bool:raise ValueError('enabled must be boolean')
            c['enabled']=data['enabled']
        if 'timezone' in data:ZoneInfo(data['timezone']);c['timezone']=data['timezone']
        if 'report_hour' in data:
            if type(data['report_hour']) is not int or not 0<=data['report_hour']<=23:raise ValueError('Invalid report hour')
            c['report_hour']=data['report_hour']
        p=folder(root)/'settings.json';tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(c));tmp.replace(p)
        events._last_config=0
        return c
    if action=='generate':return build(root,data['day'])
    if action=='decision':
        if data['key'] not in {'ux.failed_actions','ux.review_controls','ux.progress_clarity','ux.edit_feedback','ux.wait_feedback','ops.model_recovery','ops.preparation','ops.unattended_queue','ops.reuse'}:raise ValueError('Unknown opportunity')
        if data['state'] not in ('selected','deferred','dismissed','open'):raise ValueError('Invalid decision')
        until=data.get('until_day')
        if data['state']=='deferred':date.fromisoformat(until or '')
        with connect(root) as db:db.execute('INSERT OR REPLACE INTO decisions VALUES(?,?,?,?)',(data['key'],data['state'],until,time.time()))
        return {'saved':True}
    if action=='delete':
        health=status(root)
        if health['settings']['enabled'] or health['collector'].get('enabled',True):raise ValueError('Disable collection and wait for collector confirmation before deletion')
        with connect(root) as db:
            for table in ('events','reports','decisions'):db.execute('DELETE FROM '+table)
        for p in (folder(root)/'reports').glob('*.md'):p.unlink()
        return {'deleted':True}
    if action=='commentary':
        from batch_workflow import Batch
        if Batch(root).active():raise ValueError('Model commentary waits until video processing is idle')
        report=build(root,data['day'])
        from reframe import api
        from model_response import completion,discover_model
        from review_server import project_defaults
        url=project_defaults()['api_url'];audit=folder(root)/'commentary'/data['day'];audit.mkdir(parents=True,exist_ok=True)
        model=discover_model(api,url+'/models',audit/'model.json')
        # Only already aggregated suggestions, never raw event fields or user inputs.
        payload={'model':model,'max_tokens':800,'temperature':0,'messages':[{'role':'user','content':
            'Summarize these evidence-backed improvement suggestions in at most 120 words. Do not add scores, new facts, or recommendations. State uncertainty. Return JSON with commentary (string) and keys (list of existing suggestion keys). '+json.dumps({k:report[k] for k in ('ux','operations')})}]}
        allowed={r['key'] for k in ('ux','operations') for r in report[k]}
        def check(r):
            if not isinstance(r.get('commentary'),str) or not isinstance(r.get('keys'),list) or not all(k in allowed for k in r['keys']):raise ValueError('Invalid commentary evidence')
        result=completion(api,url+'/chat/completions',payload,audit/'request.json','Lookout commentary',check)
        report['commentary']=result['commentary']
        with connect(root) as db:db.execute('INSERT OR REPLACE INTO reports VALUES(?,?,?)',(data['day'],json.dumps(report),time.time()))
        return report
    raise ValueError('Unknown Lookout action')
