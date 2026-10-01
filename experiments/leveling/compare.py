"""Summarize completed model runs without treating self-confidence as accuracy."""
import argparse
import html
import json
import os
import statistics
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__);p.add_argument('runs',type=Path);p.add_argument('--extra-runs',type=Path);args=p.parse_args()
rows=[]
paths=list(args.runs.glob('*/results/results.json'))
if args.extra_runs:paths.extend(args.extra_runs.glob('*/results/results.json'))
for path in sorted(paths):
    data=json.loads(path.read_text());samples=data['rows']
    times=[c['seconds'] for row in samples for c in row['calls']]
    differences=[r['gyro_absolute_difference_degrees'] for r in samples if 'gyro_absolute_difference_degrees' in r]
    accepted=[r for r in samples if r['result'].get('roll') is not None and r['result'].get('orientation_confidence',0)>0 and not r['result'].get('error')]
    accepted_diffs=[r['gyro_absolute_difference_degrees'] for r in accepted if 'gyro_absolute_difference_degrees' in r]
    rows.append(dict(model=data['model'],label=path.parents[1].name,images=len(samples),max_tokens=data['max_tokens'],
                     truncated=sum(any(c.get('finish_reason')=='length' for c in r['calls']) for r in samples),
                     mean_seconds=statistics.mean(times) if times else None,
                     median_seconds=statistics.median(times) if times else None,
                     errors=sum(bool(r['result'].get('error')) for r in samples),
                     direction_rejections=sum(bool(r['result'].get('direction_mismatch')) for r in samples),
                     accepted=len(accepted),gyro_samples=len(differences),
                     mean_gyro_disagreement=statistics.mean(differences) if differences else None,
                     accepted_gyro_samples=len(accepted_diffs),
                     accepted_mean_gyro_disagreement=statistics.mean(accepted_diffs) if accepted_diffs else None,
                     report=os.path.relpath(path.parents[1]/'report.html',args.runs)))
(args.runs/'comparison.json').write_text(json.dumps(rows,indent=2))
headers=['Model','Output token budget','Mean seconds/image','Median seconds/image','Accepted / images','Direction rejections','Errors','Mean gyro disagreement (all / accepted)']
body=[]
for row in rows:
    fmt=lambda v:'N/A' if v is None else f'{v:.2f}'
    cells=[f'<a href="{html.escape(row["report"])}">{html.escape(row["model"])}</a>',str(row['max_tokens']),fmt(row['mean_seconds']),fmt(row['median_seconds']),f'{row["accepted"]}/{row["images"]}',str(row['direction_rejections']),str(row['errors']),f'{fmt(row["mean_gyro_disagreement"])}° / {fmt(row["accepted_mean_gyro_disagreement"])}°']
    body.append('<tr>'+''.join('<td>'+v+'</td>' for v in cells)+'</tr>')
(args.runs/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Leveling model comparison</title><style>body{font:16px system-ui;max-width:1400px;margin:40px auto;padding:20px}td,th{padding:12px;border-bottom:1px solid #ddd;text-align:left}table{border-collapse:collapse}</style><h1>Leveling model comparison</h1><p>12 sailing images; fixed prompt; serial requests; thinking disabled. Any extended-budget diagnostic is labeled separately in the table. Click a model to inspect its reference lines.</p><p>Accepted means it passed the existing direction-consistency check with nonzero orientation confidence. It does not mean the reference line is visually correct. Gyro mapping is provisional, so disagreement is not calibrated accuracy. Accepted-only disagreement can look better by rejecting difficult frames.</p><table><tr>'+''.join('<th>'+h+'</th>' for h in headers)+'</tr>'+''.join(body)+'</table>')
print(json.dumps(rows,indent=2))
