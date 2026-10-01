"""Create a standalone visual audit of one benchmark run."""
import argparse
import base64
import html
import json
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('results', type=Path)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
d = json.loads(a.results.read_text())
cards = []
for row in d['rows']:
    s, r = row['sample'], row['result']
    image = base64.b64encode(Path(s['image']).read_bytes()).decode()
    line = r.get('reference_line')
    overlay = ''
    if line:
        x1,y1,x2,y2 = line
        overlay = f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="magenta" stroke-width="4"/><circle cx="{x1}" cy="{y1}" r="7" fill="magenta"/><circle cx="{x2}" cy="{y2}" r="7" fill="magenta"/>'
    variant=(f" · input rotation {s.get('rotation_degrees',0):+g}° · repeat {row['repeat']+1}" if 'repeat' in row else '')
    cards.append(f'''<article><h2>{html.escape(s['clip'])} — {s['time']:.2f}s{variant}</h2>
    <svg viewBox="0 0 1000 1000" preserveAspectRatio="none" style="aspect-ratio:{s['width']}/{s['height']}">
    <image href="data:image/jpeg;base64,{image}" width="1000" height="1000" preserveAspectRatio="none"/>{overlay}</svg>
    <p>Roll: {r.get('roll')}° · gyro: {s.get('gyro_roll')}° · confidence: {r.get('orientation_confidence')} · wall: {row['wall_seconds']:.2f}s</p>
    <p>{html.escape(r.get('cue',''))}: {html.escape(r.get('note',''))}</p><p>{html.escape(r.get('error',''))}</p></article>''')
a.output.write_text(f'''<!doctype html><meta charset="utf-8"><title>Leveling benchmark</title>
<style>body{{font:16px system-ui;max-width:1400px;margin:auto;padding:20px;background:#151515;color:#eee}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(450px,1fr));gap:24px}}svg{{width:100%}}article{{border:1px solid #555;padding:12px}}h2{{font-size:18px}}</style>
<h1>{html.escape(d['model'])}</h1><p>Magenta: model-selected reference. Gyro is a provisional reference, not calibrated ground truth. Inspect reference placement; confidence is self-reported.</p><main>{''.join(cards)}</main>''')
print(a.output)
