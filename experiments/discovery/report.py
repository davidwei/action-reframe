"""Self-contained per-model evidence report."""
import argparse,base64,html,json
from pathlib import Path
import cv2

def build(results,output):
 d=json.loads(results.read_text());m=json.loads(Path(d['manifest']).read_text());samples={s['id']:s for s in m['samples']}
 parts=['<meta charset="utf-8"><title>Discovery benchmark</title><style>body{font:16px sans-serif;margin:30px}img{max-width:100%}pre{white-space:pre-wrap}section{border-top:1px solid #bbb;padding:16px}</style>',f'<h1>{html.escape(d["model"])}</h1>','<p>White: human box. Magenta: independent prediction. Errors count as failures. Labels are held out from model references.</p>']
 for r in d['rows']:
  parts.append('<section><h2>'+html.escape(r['stage']+' '+r['id'])+'</h2>')
  if r['stage']=='discovery':
   s=samples[r['sample']];im=cv2.imread(s['image'])
   for box,color in [(s['bbox'],(255,255,255)),(r.get('result',{}).get('source_bbox'),(255,0,255))]:
    if box:
     x1,y1,x2,y2=map(round,box);cv2.rectangle(im,(x1,y1),(x2,y2),color,3)
   im=cv2.resize(im,(960,round(im.shape[0]*960/im.shape[1])));enc=cv2.imencode('.jpg',im)[1].tobytes()
   parts.append('<img src="data:image/jpeg;base64,'+base64.b64encode(enc).decode()+'">')
  elif r.get('image'):
   enc=Path(r['image']).read_bytes();parts.append('<img style="max-height:260px" src="data:image/png;base64,'+base64.b64encode(enc).decode()+'">')
  parts.append('<pre>'+html.escape(json.dumps(r,indent=2))+'</pre></section>')
 output.write_text('\n'.join(parts))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('results',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();build(a.results,a.output)
