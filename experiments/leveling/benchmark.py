"""Isolated visual-leveling benchmark. Never changes production services/configuration."""
import argparse
import hashlib
import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from leveling import visual_observation


def request(url, payload=None):
    req = urllib.request.Request(url, data=json.dumps(payload).encode() if payload else None,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=240) as response:
        return json.load(response)


def prepare(spec_path, output):
    spec = json.loads(spec_path.read_text())
    output.mkdir(parents=True, exist_ok=True)
    (output / 'images').mkdir(exist_ok=True)
    samples = []
    for clip in spec['clips']:
        cap = cv2.VideoCapture(clip['video'])
        if not cap.isOpened():
            raise ValueError(f"Cannot open {clip['video']}")
        fps = cap.get(cv2.CAP_PROP_FPS)
        gyro = json.loads(Path(clip['gyro']).read_text()) if clip.get('gyro') else None
        for seconds in clip['times']:
            frame = round(seconds * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
            ok, image = cap.read()
            if not ok:
                raise ValueError(f"Cannot decode {clip['video']} frame {frame}")
            h, w = image.shape[:2]
            image = cv2.resize(image, (1280, round(h * 1280 / w)))
            index = len(samples)
            path = output / 'images' / f'{index:07d}.jpg'
            if not cv2.imwrite(str(path), image):
                raise IOError(path)
            samples.append(dict(id=index, clip=clip['name'], frame=frame, time=frame/fps,
                                image=str(path.resolve()), width=image.shape[1], height=image.shape[0],
                                gyro_roll=gyro['frames'][frame]['roll'] if gyro else None))
        cap.release()
    manifest = dict(samples=samples, source_spec=spec,
                    note='Gyro roll is a provisional reference, not calibrated ground truth.')
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(f'Prepared {len(samples)} images', flush=True)


def run(manifest_path, output, endpoint, expected_model, tokens):
    model = request(endpoint + '/models')['data'][0]['id']
    if model != expected_model:
        raise ValueError(f'Expected {expected_model}, server reports {model}')
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(manifest_path.read_text())
    rows = []
    start = time.perf_counter()
    for sample in manifest['samples']:
        i = sample['id']
        sample_out = output / str(i)
        sample_out.mkdir(exist_ok=True)
        calls = []
        def api(url, payload):
            payload['max_tokens'] = tokens
            payload['chat_template_kwargs'] = {'enable_thinking': False}
            started = time.perf_counter()
            answer = request(url, payload)
            calls.append(dict(seconds=time.perf_counter()-started, usage=answer.get('usage'),
                              finish_reason=answer['choices'][0].get('finish_reason'),
                              response=answer['choices'][0]['message']))
            return answer
        meta = dict(cache=str(Path(sample['image']).parent), width=sample['width'],
                    height=sample['height'], fps=1,
                    signature=hashlib.sha256(Path(sample['image']).read_bytes()).hexdigest())
        started = time.perf_counter()
        result = visual_observation(dict(output_dir=str(sample_out), api_url=endpoint), meta, i, model, api)
        row = dict(sample=sample, result=result, calls=calls, wall_seconds=time.perf_counter()-started,
                   cached=not bool(calls))
        if result.get('roll') is not None and sample['gyro_roll'] is not None:
            row['gyro_absolute_difference_degrees'] = abs((result['roll']-sample['gyro_roll']+180)%360-180)
        rows.append(row)
        (output / 'results.json').write_text(json.dumps(dict(model=model, max_tokens=tokens,
             workers=1, elapsed_seconds=time.perf_counter()-start, rows=rows), indent=2))
        print(json.dumps(dict(id=i, seconds=row['wall_seconds'], roll=result.get('roll'),
                              error=result.get('error'), confidence=result.get('orientation_confidence'))), flush=True)
    latencies = [r['calls'][0]['seconds'] for r in rows if r['calls']]
    differences = [r['gyro_absolute_difference_degrees'] for r in rows if 'gyro_absolute_difference_degrees' in r]
    summary = dict(model=model, images=len(rows), new_calls=len(latencies),
                   mean_request_seconds=statistics.mean(latencies) if latencies else None,
                   elapsed_seconds=time.perf_counter()-start,
                   errors=sum(bool(r['result'].get('error')) for r in rows),
                   usable=sum(r['result'].get('roll') is not None and r['result'].get('orientation_confidence',0)>0 for r in rows),
                   mean_gyro_difference=statistics.mean(differences) if differences else None,
                   caveat='Gyro difference is not calibrated accuracy; inspect reference-line placement separately.')
    (output / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare'); p.add_argument('--spec', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('run'); p.add_argument('--manifest', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--endpoint', required=True); p.add_argument('--model', required=True); p.add_argument('--max-tokens', type=int, default=400)
    args = parser.parse_args()
    if args.command == 'prepare': prepare(args.spec, args.output)
    else: run(args.manifest, args.output, args.endpoint.rstrip('/'), args.model, args.max_tokens)
