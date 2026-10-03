import json
from pathlib import Path
import sys
import tempfile
import unittest

import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))

from standalone.video_leveling.core import Job, decode, load, save
from standalone.video_leveling.motion import rotation
from standalone.video_leveling.pipeline import export, prepare, write_npz


def video(path,frames=30,fps=10):
    writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*"MJPG"),fps,(320,180))
    if not writer.isOpened():raise RuntimeError("Cannot create test video")
    for index in range(frames):
        image=np.zeros((180,320,3),np.uint8)
        cv2.line(image,(0,70+index//10),(319,70+index//10),(255,255,255),2)
        cv2.circle(image,(80+index,110),8,(255,255,255),-1)
        writer.write(image)
    writer.release()


class StandaloneLevelingTests(unittest.TestCase):
    def test_job_resume_decode_and_annotation_schema(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/"source.avi";video(source)
            job=Job(source,root/"output",.02,dict(base_fps=5,motion_fps=5,chunk_seconds=1,max_anchor_gap_seconds=30))
            job.set_models("primary-test","review-test");prepare(job)
            decoded=[index for index,_,_ in decode(job,10,20)]
            self.assertEqual(decoded,list(range(10,20)))
            samples=[json.loads(p.read_text())["samples"] for p in sorted((job.out/"samples").glob("*.json"))]
            self.assertTrue(any(samples))
            (job.out/"primary").mkdir()
            for frame,angle in ((0,2.0),(28,4.0)):
                save(job.out/"primary"/f"{frame:09d}_test.json",dict(frame=frame,time=frame/10,model="primary-test",stage="primary",key=f"key-{frame}",image=f"images/{frame:09d}.jpg",reference_line=[0,400,1000,420],angle=angle,quality=.8,cue="horizon",candidate_id=0,note="test",prompt_version=None))
            signature="test-motion";motion_folder=job.out/"motion"/signature;motion_folder.mkdir(parents=True)
            rows=np.array([[index,.14,.8,30] for index in range(0,30,2)],float)
            path=motion_folder/"000000000.npz";sha=write_npz(path,rows=rows)
            save(path.with_suffix(".json"),dict(sha256=sha,start=0,end=30,rows=len(rows)))
            save(job.out/"motion.json",dict(signature=signature,folder=str(motion_folder.relative_to(job.out))))
            manifest=export(job)
            self.assertEqual(manifest["schema"],"video-leveling-annotations/v1")
            self.assertEqual(manifest["counts"]["estimated"],30)
            rows=[]
            for shard in manifest["shards"]:
                rows.extend(json.loads(line) for line in (job.out/shard["path"]).read_text().splitlines())
            self.assertEqual([row["frame"] for row in rows],list(range(30)))
            self.assertTrue(all(row["correction_degrees_ccw"] is not None for row in rows))
            resumed=Job(source,root/"output",.02,dict(base_fps=5,motion_fps=5,chunk_seconds=1,max_anchor_gap_seconds=30))
            self.assertEqual(load(resumed.out/"models.json")["primary"],"primary-test")
            with self.assertRaisesRegex(ValueError,"different models"):
                resumed.set_models("another-primary","review-test")

    def test_background_rotation_has_quality_requirements(self):
        image=np.zeros((180,320),np.uint8)
        for y in range(20,130,20):
            for x in range(20,300,30):cv2.circle(image,(x,y),2,255,-1)
        matrix=cv2.getRotationMatrix2D((160,90),2,1)
        moved=cv2.warpAffine(image,matrix,(320,180))
        result=rotation(image,moved,dt=.2)
        self.assertGreater(result["quality"],0)
        self.assertAlmostEqual(result["delta"],-2,delta=.5)


if __name__=="__main__":unittest.main()
