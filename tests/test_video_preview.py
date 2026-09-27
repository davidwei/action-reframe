import tempfile
import unittest
from pathlib import Path
import time
import av
import cv2
import numpy as np
from video_preview import preview

class VideoPreviewTests(unittest.TestCase):
    def test_cached_browser_video_has_changing_frames(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'moving.avi'
            writer=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*'MJPG'),10,(96,64))
            for i in range(12):
                frame=np.zeros((64,96,3),np.uint8);cv2.rectangle(frame,(i*4,10),(i*4+20,40),(0,255,0),-1);writer.write(frame)
            writer.release()
            result=preview(root,source,0)
            for _ in range(200):
                if result['status']!='processing':break
                time.sleep(.05);result=preview(root,source,0)
            self.assertEqual(result['status'],'ready',result)
            path=root/result['url'].removeprefix('/files/')
            with av.open(str(path)) as container:
                self.assertEqual(container.streams.video[0].codec_context.name,'h264')
                frames=[f.to_ndarray(format='rgb24') for f in container.decode(video=0)]
            self.assertGreater(len(frames),2)
            self.assertGreater(np.abs(frames[0].astype(float)-frames[-1]).mean(),1)
            mtime=path.stat().st_mtime_ns
            self.assertEqual(preview(root,source,.5)['url'],result['url'])
            self.assertEqual(path.stat().st_mtime_ns,mtime)
            for value in (-1,float('nan'),float('inf')):
                with self.assertRaises(ValueError):preview(root,source,value)
