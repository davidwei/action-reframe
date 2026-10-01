"""Aggregate task accuracy and timings without treating model confidence as truth."""
import argparse,html,json,statistics
from pathlib import Path

def aggregate(root):
 summaries={};links=[]
 for path in root.glob('*/results/results.json'):
  d=json.loads(path.read_text());m=json.loads(Path(d['manifest']).read_text());stats={}
  for stage in ('discovery','crop_description','crop_verification','text_comparison','shared_text_comparison'):
   rows=[r for r in d['rows'] if r['stage']==stage]
   if not rows:continue
   t=[r['wall_seconds'] for r in rows];s=dict(cases=len(rows),errors=sum('error' in r for r in rows),median_seconds=statistics.median(t),mean_seconds=statistics.mean(t),retry_requests=sum(max(0,len(r['calls'])-1) for r in rows),truncated_requests=sum(c.get('finish_reason')=='length' for r in rows for c in r['calls']))
   if stage=='discovery':
    s['paths']={}
    for name in sorted(set(r['path'] for r in rows)):
     rr=[r for r in rows if r['path']==name];pos=[r for r in rr if r['expected']];neg=[r for r in rr if not r['expected']]
     s['paths'][name]=dict(positives=len(pos),absent=len(neg),iou50=sum((r.get('result',{}).get('iou') or 0)>=.5 for r in pos),iou25=sum((r.get('result',{}).get('iou') or 0)>=.25 for r in pos),mean_iou=statistics.mean((r.get('result',{}).get('iou') or 0) for r in pos),false_positives=sum(r.get('result',{}).get('present',False) for r in neg),correct_absent=sum('result' in r and not r['result'].get('present') for r in neg))
   elif stage in ('crop_verification','text_comparison','shared_text_comparison'):
    tp=fp=tn=fn=0
    for r in rows:
     a=r.get('result',{});pred=a.get('target_present',False) and a.get('match_score',0)>=.5 and a.get('exclusion_check')!='contradicted'
     if 'error' in r:continue
     if r['expected']:
      if pred:tp+=1
      else:fn+=1
     elif pred:fp+=1
     else:tn+=1
    expected_total=len(m['crops']) if stage=='crop_verification' else len(rows)
    s.update(tp=tp,fp=fp,tn=tn,fn=fn,expected_cases=expected_total,correct=tp+tn,accuracy=(tp+tn)/expected_total,precision=tp/(tp+fp) if tp+fp else None,recall=tp/(sum(c['expected'] for c in m['crops']) if stage=='crop_verification' else sum(r['expected'] for r in rows)))
   stats[stage]=s
  descriptions={r.get('image'):r for r in d['rows'] if r['stage']=='crop_description'}
  paired=[r for r in d['rows'] if r['stage']=='crop_verification' and r.get('kind')!='cross_target_negative']
  end_to_end=[r['wall_seconds']+descriptions[r['image']]['wall_seconds'] for r in paired]
  if end_to_end:stats['end_to_end_crop_latency']=dict(cases=len(end_to_end),median_seconds=statistics.median(end_to_end),mean_seconds=statistics.mean(end_to_end))
  summaries[path.parents[1].name]=stats
  links.append(f'<p><a href="{path.parents[1].name}/report.html">{html.escape(d["model"])}</a></p>')
 (root/'comparison.json').write_text(json.dumps(summaries,indent=2))
 (root/'index.html').write_text('<meta charset="utf-8"><h1>Object discovery and verification comparison</h1>'+''.join(links)+'<pre>'+html.escape(json.dumps(summaries,indent=2))+'</pre>')
 return summaries
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();print(json.dumps(aggregate(a.root),indent=2))
