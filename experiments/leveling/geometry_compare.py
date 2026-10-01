"""Summarize coordinate-derived direction ablation and rotation consistency."""
import argparse,html,json,statistics
from pathlib import Path

def summarize(root,previous):
    report={}
    for model in ('qwen38','gemma4'):
        path=root/model/'results/results.json'
        if not path.exists():continue
        d=json.loads(path.read_text());rows=d['rows'];original=[r for r in rows if not r['sample']['rotation_degrees']]
        first=[r for r in original if r['repeat']==0]
        timings=[c['seconds'] for r in original for c in r['calls']]
        diffs=[r['gyro_absolute_difference_degrees'] for r in original if 'gyro_absolute_difference_degrees' in r]
        old=json.loads((previous/model/'results/results.json').read_text())['rows']
        result=dict(requests=sum(len(r['calls']) for r in rows),original_responses=len(original),first_repeat_valid=sum(r['result'].get('roll') is not None and r['result'].get('orientation_confidence',0)>0 for r in first),original_valid=sum(r['result'].get('roll') is not None and r['result'].get('orientation_confidence',0)>0 for r in original),errors=sum(bool(r['result'].get('error')) for r in rows),median_request_seconds=statistics.median(timings),mean_request_seconds=statistics.mean(timings),gyro_mean_absolute_difference=statistics.mean(diffs) if diffs else None,gyro_median_absolute_difference=statistics.median(diffs) if diffs else None,gyro_max_absolute_difference=max(diffs) if diffs else None,
                    old_accepted=sum(r['result'].get('roll') is not None and r['result'].get('orientation_confidence',0)>0 for r in old),old_accepted_without_direction_gate=sum(r['result'].get('roll') is not None and r['result'].get('confidence',0)>0 for r in old))
        paired=[]
        for row in rows:
            s=row['sample']
            if not s['rotation_degrees']:continue
            base=next((r for r in original if r['sample']['id']==s['base_id'] and r['repeat']==row['repeat']),None)
            if base and base['result'].get('roll') is not None and row['result'].get('roll') is not None:
                expected=base['result']['roll']-s['rotation_degrees'];error=abs(row['result']['roll']-expected)
                paired.append(dict(id=s['id'],base_id=s['base_id'],rotation=s['rotation_degrees'],repeat=row['repeat'],base_roll=base['result']['roll'],rotated_roll=row['result']['roll'],error_degrees=error))
        result['rotation_consistency']=dict(pairs=len(paired),mean_error=statistics.mean(p['error_degrees'] for p in paired) if paired else None,max_error=max((p['error_degrees'] for p in paired),default=None),within_2_degrees=sum(p['error_degrees']<=2 for p in paired),details=paired)
        repeat_deltas=[]
        for row in original:
            if row['repeat']==0:continue
            base=next(r for r in first if r['sample']['id']==row['sample']['id'])
            if base['result'].get('roll') is not None and row['result'].get('roll') is not None:repeat_deltas.append(abs(base['result']['roll']-row['result']['roll']))
        result['repeat_max_difference']=max(repeat_deltas,default=None)
        report[model]=result
    (root/'comparison.json').write_text(json.dumps(report,indent=2))
    cards=[]
    table=['<table><tr><th>Model</th><th>Median seconds</th><th>Valid originals</th><th>Mean gyro difference</th><th>Mean rotation error</th></tr>']
    for name,r in report.items():
        table.append(f"<tr><td>{name}</td><td>{r['median_request_seconds']:.2f}</td><td>{r['original_valid']}/{r['original_responses']}</td><td>{r['gyro_mean_absolute_difference']:.2f}°</td><td>{r['rotation_consistency']['mean_error']:.2f}°</td></tr>")
    table.append('</table>')
    for name,r in report.items():
        cards.append(f'<h2>{name}</h2><p><a href="{name}/report.html">Inspect selected reference lines</a></p><pre>'+html.escape(json.dumps(r,indent=2))+'</pre>')
    (root/'index.html').write_text('<meta charset="utf-8"><style>td,th{padding:12px;border:1px solid #ccc;text-align:left}table{border-collapse:collapse}body{font:17px sans-serif;margin:30px;max-width:1300px}pre{white-space:pre-wrap}</style><h1>Leveling: geometry-derived direction</h1><p>Identical original frames plus known ±10° rotations; two repeats. Valid response is not proof of correct horizon. Gyro is a provisional reference. Rotation consistency tests sensitivity to an artificial camera roll, not absolute gravity accuracy.</p>'+''.join(table)+''.join(cards))
    return report
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--previous',type=Path,required=True);a=p.parse_args();print(json.dumps(summarize(a.root,a.previous),indent=2))
