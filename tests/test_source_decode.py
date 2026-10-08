import tempfile
from pathlib import Path
import unittest

import numpy as np

from source_decode import record_repairs, repaired_frames, repair_timeline, timeline

import cv2


class SourceDecodeTests(unittest.TestCase):
    def test_timeline_uses_timestamp_cadence_and_duration(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.avi'
            writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),10,(16,16))
            self.assertTrue(writer.isOpened())
            for value in range(30):writer.write(np.full((16,16,3),value,np.uint8))
            writer.release()
            result=timeline(path)
            self.assertAlmostEqual(result['fps'],10,places=3)
            self.assertEqual(result['frames'],30)

    def test_sparse_decode_preserves_positions_and_uses_nearest_frame(self):
        images={index:np.full((2,2,3),index,np.uint8) for index in (0,1,5)}
        rows=list(repair_timeline([(i,images[i]) for i in (0,1,5)],0,7))
        self.assertEqual([row.index for row in rows],list(range(7)))
        self.assertEqual([int(row.image[0,0,0]) for row in rows],[0,1,1,1,5,5,5])
        self.assertEqual([row.repaired for row in rows],[False,False,True,True,True,False,True])
        self.assertEqual(rows[2].strategy,'previous');self.assertEqual(rows[4].strategy,'next')

    def test_leading_gap_uses_next_and_empty_decode_fails(self):
        image=np.ones((1,1,3),np.uint8)
        rows=list(repair_timeline([(4,image)],2,4))
        self.assertEqual([(row.index,row.replacement_frame,row.strategy) for row in rows],[(2,4,'next'),(3,4,'next')])
        with self.assertRaisesRegex(RuntimeError,'No decodable source frame'):
            list(repair_timeline([],0,1))

    def test_single_position_chooses_nearest_neighbor_across_stop(self):
        before=np.full((1,1,3),2,np.uint8);after=np.full((1,1,3),4,np.uint8)
        row=next(iter(repair_timeline([(2,before),(4,after)],3,4)))
        self.assertEqual(row.index,3);self.assertEqual(row.replacement_frame,2)
        self.assertEqual(row.strategy,'previous')

    def test_repair_journal_merges_stages(self):
        with tempfile.TemporaryDirectory() as folder:
            record_repairs(folder,'analysis',[dict(frame=3,replacement_frame=2,strategy='previous',reason='missing')])
            record_repairs(folder,'render',[dict(frame=3,replacement_frame=4,strategy='next',reason='missing'),dict(frame=8,replacement_frame=7,strategy='previous',reason='missing')])
            self.assertEqual(repaired_frames(folder),{3,8})
            import json
            value=json.loads((Path(folder)/'source_frame_repairs.json').read_text())
            self.assertEqual(set(value['frames']['3']['stages']),{'analysis','render'})


if __name__=='__main__':unittest.main()
