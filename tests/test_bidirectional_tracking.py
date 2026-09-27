import copy,unittest
from backward_tracking import bidirectional_pass


def row(frame,score=.9,box=None,**kwargs):
    return dict(frame=frame,time=frame/30,bbox=box or [100,100,200,200],confidence=score,
                visibility='visible',note='verified target',**kwargs)

class BidirectionalTests(unittest.TestCase):
    def fail_judge(self,*args):self.fail('Unnecessary adjudication')

    def test_slightly_higher_wins_tie_keeps_forward_and_forward_win_does_not_stop(self):
        forward=[row(0,.8),row(15,.9),row(30,.95),row(45,.9)]
        original=copy.deepcopy(forward);calls=[]
        def attempt(current,seed,history):
            calls.append((current['frame'],[(r['frame'],r['confidence']) for r in history]))
            return row(current['frame'],{30:.8,15:.9,0:.800001}[current['frame']],direction='backward')
        result,report=bidirectional_pass(forward,attempt,self.fail_judge)
        self.assertEqual([r['direction_choice'] for r in result],['backward','forward','forward','forward'])
        self.assertEqual(calls[1][1],[(45,.9),(30,.8)]) # Reverse history uses its own estimate, not winning forward .95.
        self.assertEqual(report['attempted_samples'],3);self.assertEqual(report['improved_samples'],1)
        self.assertEqual(result[0]['direction_comparison']['forward']['confidence'],.8)
        self.assertEqual(forward,original)

    def test_disagreement_adjudicates_regardless_of_score(self):
        forward=[row(0,.99),row(15)]
        def attempt(*args):return row(0,.8,[700,100,800,200])
        result,report=bidirectional_pass(forward,attempt,lambda *_:{'choice':'backward','confidence':.9,'reason':'crop identity'})
        self.assertEqual(result[0]['direction_choice'],'backward')
        self.assertIn('tracking_direction_disagreement',result[0]['direction_flags'])
        result,_=bidirectional_pass(forward,attempt,lambda *_:{'choice':'neither','confidence':.9})
        self.assertEqual(result[0]['direction_choice'],'neither');self.assertIsNone(result[0]['bbox'])

    def test_unreliable_reverse_stops_then_earlier_forward_anchor_restarts(self):
        calls=[]
        def attempt(current,*args):
            calls.append(current['frame']);return row(current['frame'],.3 if current['frame']==30 else .95)
        rows=[row(0),row(15),row(30),row(45)]
        result,report=bidirectional_pass(rows,attempt,self.fail_judge)
        self.assertEqual(calls,[30,0])
        self.assertEqual(result[1]['direction_choice'],'forward')
        self.assertEqual(report['chains'][0]['stop_reason'],'Backward confidence/verification failed')

    def test_manual_absence_blocks_propagation(self):
        calls=[]
        def attempt(current,*args):calls.append(current['frame']);return row(current['frame'])
        rows=[row(0,.1),dict(row(15),bbox=None,confidence=0,manual=True,visibility='absent'),row(30)]
        result,_=bidirectional_pass(rows,attempt,self.fail_judge)
        self.assertEqual(calls,[]);self.assertEqual(result[1]['direction_choice'],'manual')

    def test_backward_error_never_replaces_confident_forward(self):
        result,_=bidirectional_pass([row(0),row(15)],lambda *_:row(0,.99,error='verification failed'),self.fail_judge)
        self.assertEqual(result[0]['direction_choice'],'forward')
        self.assertFalse(result[0]['backward_attempt']['reliable'])

class DirectionAdjudicationTests(unittest.TestCase):
    def test_qwen_adapter_labels_and_backward_context(self):
        import json,tempfile
        from pathlib import Path
        import numpy as np
        from dual_tracking import adjudicate_pair
        with tempfile.TemporaryDirectory() as folder:
            calls=[]
            def completion(c,meta,index,direction,history,model,images,prompt,tokens):
                calls.append((direction,history,prompt))
                return {'choices':[{'message':{'content':json.dumps({'choice':'backward','confidence':.9,'reason':'target visible'})}}]},{}
            def save(path,data):Path(path).write_text(json.dumps(data))
            result=adjudicate_pair({'target':'boat'}, {'cache':folder},0,'model',
                {'forward':row(0),'backward':row(0)},[row(15)],
                (lambda *_:np.zeros((100,200,3),np.uint8),completion,save),
                labels=('forward','backward'),direction='backward')
            self.assertEqual(result['choice'],'backward')
            self.assertEqual(calls[0][0],'backward')
            self.assertIn('forward = cyan, backward = orange',calls[0][2])
            self.assertIn('forward|backward|neither',calls[0][2])
