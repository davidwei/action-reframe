"""Command-line interface for one standalone leveling job.

The CLI never starts or stops a model server. Use ``orchestrate.py`` for guarded
local model swapping, or use these stage commands with an already served model.
"""
import argparse
import json
from pathlib import Path

from .core import Job, load, lock
from .pipeline import export, motion_pass, prepare, refine_pass, visual_pass


def options(args):
    names=("base_fps","motion_fps","motion_width","chunk_seconds",
           "max_anchor_gap_seconds","primary_seconds","review_seconds","request_timeout","scene_hint")
    return {name:getattr(args,name) for name in names if getattr(args,name,None) is not None}


def open_job(args):
    job=Job(args.video,args.output,args.hours,options(args))
    if args.primary_model and args.review_model:
        job.set_models(args.primary_model,args.review_model)
    return job


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("init","prepare","primary","motion","refine","review","export","status"))
    parser.add_argument("--video",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--hours",type=float,required=True,help="Maximum charged processing time for this video")
    parser.add_argument("--api-url",default="http://127.0.0.1:8001/v1")
    parser.add_argument("--primary-model")
    parser.add_argument("--review-model")
    parser.add_argument("--base-fps",type=float)
    parser.add_argument("--motion-fps",type=float)
    parser.add_argument("--motion-width",type=int)
    parser.add_argument("--chunk-seconds",type=float)
    parser.add_argument("--max-anchor-gap-seconds",type=float)
    parser.add_argument("--primary-seconds",type=float)
    parser.add_argument("--review-seconds",type=float)
    parser.add_argument("--request-timeout",type=float)
    parser.add_argument("--scene-hint",default=None,
                        help="Short user description of reliable scene-level cues; never treated as measured geometry")
    args=parser.parse_args(argv)
    if args.command in ("primary","refine") and not args.primary_model:
        parser.error(f"{args.command} requires --primary-model")
    if args.command=="review" and not args.review_model:
        parser.error("review requires --review-model")
    with lock(args.output):
        job=open_job(args)
        if args.command=="init":job.status("job","initialized",budget_seconds=job.config["budget_seconds"])
        elif args.command=="prepare":prepare(job)
        elif args.command=="primary":visual_pass(job,args.api_url,args.primary_model)
        elif args.command=="motion":motion_pass(job)
        elif args.command=="refine":refine_pass(job,args.api_url,args.primary_model,"refine")
        elif args.command=="review":refine_pass(job,args.api_url,args.review_model,"review")
        elif args.command=="export":export(job)
        elif args.command=="status":print(json.dumps(dict(config=job.config,state=job.state,remaining_seconds=job.remaining(),leveling=load(job.out/'leveling.json')),indent=2))


if __name__=="__main__":main()
