"""Build a concise report linking detailed visual and fixed-text evidence."""
import argparse,html,json
from pathlib import Path
from compare import aggregate

def build(root):
 first=aggregate(root/'runs');second=aggregate(root/'shared_runs') if (root/'shared_runs').exists() else {}
 names={'baseline_same_runtime':'Qwen3-VL-32B control','qwen38':'Qwen3.8-27B','qwen36':'Qwen3.6-35B-A3B','gemma4':'Gemma-4-31B'}
 body=['<meta charset="utf-8"><title>Discovery model comparison</title><style>body{font:17px sans-serif;max-width:1300px;margin:35px auto;padding:20px}table{border-collapse:collapse}td,th{padding:12px;border:1px solid #ccc;text-align:left}p{line-height:1.5}</style><h1>Discovery and verification model comparison</h1><p>Same local hardware, prompts, examples, and output budgets. Counts below use human boxes and absent labels. Seconds are median wall time. This is a small sailing-specific experiment, not a general model ranking.</p><table><tr><th>Model</th><th>Raw discovery: box IoU ≥0.5</th><th>Absent false positives</th><th>Discovery seconds</th><th>Crop verification</th><th>Crop + comparison seconds</th><th>Identical-text comparison</th><th>Text seconds</th></tr>']
 for key,name in names.items():
  if key not in first:continue
  s=first[key];d=s['discovery'];r=d['paths']['raw_angle'];t=second.get(key,{}).get('shared_text_comparison',{})
  vals=[name,f"{r['iou50']}/{r['positives']}",f"{r['false_positives']}/{r['absent']}",f"{d['median_seconds']:.2f}",f"{s['crop_verification']['correct']}/32",f"{s['end_to_end_crop_latency']['median_seconds']:.2f}",f"{t.get('correct','pending')}/32",f"{t['median_seconds']:.2f}" if t else 'pending']
  body.append('<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in vals)+'</tr>')
 body.append('</table><p>Discovery timing includes raw and leveled calls; the box counts shown use the common raw-frame set. Crop verification includes each model’s own blind description plus text comparison. Identical-text comparison uses frozen control descriptions, excluding image-reading differences. Control comparison measurements are reused because the prompts are identical.</p><h2>Inspect the evidence</h2><p><a href="runs/index.html">Task metrics and visual reports</a> · <a href="shared_runs/index.html">Shared-description results</a></p>')
 for key,name in names.items():
  if key in first:body.append(f'<p><a href="runs/{key}/report.html">{name}: human boxes, predictions, crop descriptions, and responses</a></p>')
 body.append('<p>Production restoration records: <a href="runs/experiment.json">first pass</a>, <a href="shared_runs/experiment.json">shared-text pass</a>. Restoration is complete only when production_restored is true; live smoke response is stored separately.</p>')
 (root/'index.html').write_text('\n'.join(body))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();build(a.root)
