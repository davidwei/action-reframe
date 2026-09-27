import unittest
import tempfile
import cv2
import numpy as np
from dual_tracking import expanded_rotation, transform_points, box_points, source_box, box_iou, observe_path


class DualTrackingTests(unittest.TestCase):
    def test_expanded_rotation_preserves_corners_and_inverse(self):
        for angle in (-89,-35,0,25,90):
            matrix,size=expanded_rotation(1920,1080,angle)
            points=box_points([0,0,1920,1080]);view=transform_points(points,matrix)
            self.assertTrue(np.all(view>=-1e-8))
            self.assertTrue(np.all(view<=np.array(size)+1e-8))
            np.testing.assert_allclose(transform_points(view,cv2.invertAffineTransform(matrix)),points,atol=1e-9)

    def test_inverse_box_contains_polygon_and_identity(self):
        matrix,size=expanded_rotation(1920,1080,0)
        box,polygon=source_box([200,300,400,600],matrix,size,(1920,1080))
        np.testing.assert_allclose(box,[200,300,400,600])
        matrix,size=expanded_rotation(1920,1080,30)
        box,polygon=source_box([400,400,500,500],matrix,size,(1920,1080))
        pixels=np.array(box)*[1.92,1.08,1.92,1.08]
        self.assertTrue(np.all(np.array(polygon)>=pixels[:2]-1e-9))
        self.assertTrue(np.all(np.array(polygon)<=pixels[2:]+1e-9))
        self.assertEqual(box_iou(box,box),1)
        self.assertIsNone(box_iou(box,None))

    def test_local_search_box_maps_back_to_original_pixels(self):
        with tempfile.TemporaryDirectory() as folder:
            meta={'cache':folder,'width':200,'height':100,'fps':30}
            c={'target':'boat','verify_boxes':False,'_search_region':[40,20,100,70]}
            def completion(c,meta,index,direction,rows,model,images,prompt,tokens):
                self.assertIn('local SEARCH CROP',prompt)
                return {'choices':[{'message':{'content':'{"bbox":[0,0,1000,1000],"confidence":0.9,"visibility":"visible"}'}}]},{}
            helpers=(lambda *args:np.zeros((100,200,3),np.uint8),completion,lambda *args:None)
            for path in ('raw_angle','leveled'):
                result=observe_path(c,meta,{'frames':[{'roll':0}]},0,'test',[],path,'forward',helpers)
                np.testing.assert_allclose(result['bbox'],[200,200,500,700])
                self.assertEqual(result['view_size'],[60,50])

    def test_paths_pass_angle_without_previous_hint(self):
        with tempfile.TemporaryDirectory() as folder:
            meta={'cache':folder,'width':200,'height':100,'fps':30}
            c={'target':'boat','temporal_context':{},'verify_boxes':False}
            history=[{'frame':0,'bbox':[200,300,400,600]}]
            gyro={'frames':[{'roll':30},{'roll':30}]}
            requests=[]
            def completion(c,meta,index,direction,rows,model,images,prompt,tokens):
                requests.append((prompt,images,rows))
                return {'choices':[{'message':{'content':'{"bbox":[400,400,500,500],"confidence":0.9,"visibility":"visible"}'}}]},{}
            helpers=(lambda *args:np.zeros((100,200,3),np.uint8),completion,lambda *args:None)
            raw=observe_path(c,meta,gyro,1,'test',history,'raw_angle','forward',helpers)
            level=observe_path(c,meta,gyro,1,'test',history,'leveled','forward',helpers)
            self.assertEqual(raw['bbox'],[400,400,500,500])
            self.assertNotEqual(level['bbox'],raw['bbox'])
            self.assertIsNone(level['previous_hint_frame'])
            self.assertIsNone(level['previous_hint_polygon_px'])
            self.assertEqual(len(requests[0][1]),2)
            self.assertNotIn('projected hint polygon',requests[0][0])
            self.assertIn('30.000000',requests[0][0])
            self.assertIn('already been rotated',requests[1][0])
            self.assertEqual(history[0]['bbox'],[200,300,400,600])

if __name__=='__main__':unittest.main()

class DualRunnerTests(unittest.TestCase):
    def test_histories_and_backward_recovery_are_independent(self):
        import json
        from pathlib import Path
        from unittest.mock import patch
        from dual_tracking import run_dual
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'reference.jpg').write_bytes(b'reference')
            c={'output_dir':folder,'video':'synthetic','analysis_fps':2,'backward_recovery':True}
            meta={'cache':folder,'samples':[0,15,30],'fps':30}
            import threading
            barrier=threading.Barrier(2,timeout=5)
            calls=[]
            def observe(c,meta,gyro,index,model,history,path,direction,helpers):
                if direction=='forward':barrier.wait()
                self.assertTrue(all(r['path']==path for r in history))
                self.assertTrue(all((r['frame']<index if direction=='forward' else r['frame']>index) for r in history))
                calls.append((path,direction,index))
                good=index!=15 or direction=='backward'
                return {'frame':index,'time':index/30,'path':path,'direction':direction,
                        'bbox':[100,100,200,200] if good else None,'confidence':.9 if good else 0,
                        'visibility':'visible' if good else 'uncertain','source_polygon_px':[[1,2]],
                        'qwen_view_bbox':[100,100,200,200] if good else None}
            def save(path,data):Path(path).write_text(json.dumps(data))
            with patch('dual_tracking.extract_gyro',return_value={'frames':[]}),patch('dual_tracking.observe_path',side_effect=observe):
                run_dual(c,meta,'model',(None,None,save))
            for path in ('raw_angle','leveled'):
                self.assertIn((path,'backward',15),calls)
                records=json.loads((root/f'tracking_{path}.json').read_text())
                self.assertTrue(records[1]['backward_recovered'])
                self.assertEqual(records[1]['direction'],'backward')
                self.assertEqual(records[1]['qwen_view_bbox'],[100,100,200,200])
            pairs=json.loads((root/'tracking_comparison.json').read_text())
            self.assertEqual(pairs[1]['box_iou'],1)
