"""Compare all models on identical real crop descriptions frozen from baseline."""
import argparse,json,statistics,time
from pathlib import Path
from benchmark import request,save
from description_comparison import compare_descriptions

def run(manifest,out,endpoint,model):
 assert model in [v['id'] for v in request(endpoint+'/models')['data']]
 data=json.loads(manifest.read_text());out.mkdir(parents=True,exist_ok=True);rows=[]
 for case in data['text']:
  calls=[]
  def api(url,payload):
   payload['chat_template_kwargs']={'enable_thinking':False};start=time.perf_counter();answer=request(url,payload)
   calls.append(dict(seconds=time.perf_counter()-start,usage=answer.get('usage'),finish_reason=answer['choices'][0].get('finish_reason')));return answer
  start=time.perf_counter();row=dict(stage='shared_text_comparison',id=case['id'],expected=case['expected'],description=case['description'],target=case['target'])
  try:row['result']=compare_descriptions(case['target'],case['description'],model,endpoint,api,out/case['id']/'request.json',cache=False)
  except Exception as e:row['error']=str(e)
  row.update(calls=calls,wall_seconds=time.perf_counter()-start);rows.append(row)
  save(out/'results.json',dict(model=model,manifest=str(manifest),rows=rows));print(case['id'],row['wall_seconds'],row.get('error',''),flush=True)
 save(out/'summary.json',dict(cases=len(rows),errors=sum('error' in r for r in rows),median_seconds=statistics.median(r['wall_seconds'] for r in rows)))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('command');p.add_argument('--manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--endpoint',required=True);p.add_argument('--model',required=True);p.add_argument('--max-tokens');a=p.parse_args();run(a.manifest,a.output,a.endpoint,a.model)
