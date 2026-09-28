import io,json,tempfile,unittest
from pathlib import Path
from urllib.error import HTTPError
from model_response import completion,discover_model,ModelResponseError


class ModelResponseTests(unittest.TestCase):
    def response(self,content,reason='stop'):
        return {'id':'request-test','choices':[{'message':{'content':content},'finish_reason':reason}],'usage':{'completion_tokens':500}}

    def test_truncated_json_is_saved_and_retried_once_with_more_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'request.json';calls=[]
            def api(url,payload):
                calls.append(payload)
                return self.response('{"x":' if len(calls)==1 else '{"x":1}','length' if len(calls)==1 else 'stop')
            result=completion(api,'test',{'max_tokens':1000},path,'comparison',lambda r:None)
            self.assertEqual(result['x'],1);self.assertEqual([r['max_tokens'] for r in calls],[1000,2000])
            self.assertTrue(all(r['response_format']=={'type':'json_object'} for r in calls))
            self.assertTrue((Path(folder)/'request_raw_response.json').exists())
            self.assertEqual(json.loads((Path(folder)/'request_error.json').read_text())['kind'],'truncated_output')

    def test_no_json_is_explicit_and_raw_response_survives(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ModelResponseError) as caught:
                completion(lambda *a:self.response('Sorry, no answer'),'',{'max_tokens':1000},Path(folder)/'request.json','comparison',lambda r:None)
            self.assertIn('no JSON object',str(caught.exception));self.assertNotIn('substring',str(caught.exception))
            self.assertEqual(caught.exception.details['request_id'],'request-test')
            self.assertEqual(caught.exception.details['response_excerpt'],'Sorry, no answer')
            self.assertTrue(Path(caught.exception.details['response_file']).exists())

    def test_http_error_body_and_timeout_are_distinguished(self):
        for kind in ('http','timeout'):
            with tempfile.TemporaryDirectory() as folder:
                def api(*args):
                    if kind=='http':raise HTTPError('test',503,'Unavailable',{},io.BytesIO(b'{"error":"engine unavailable"}'))
                    raise TimeoutError('timed out')
                with self.assertRaises(ModelResponseError) as caught:
                    completion(api,'test',{},Path(folder)/'request.json','summary')
                self.assertIn('503' if kind=='http' else 'timed out',str(caught.exception))
                if kind=='http':self.assertIn('engine unavailable',str(caught.exception))
                self.assertEqual(caught.exception.details['kind'],'http_error' if kind=='http' else 'timeout')

    def test_repeated_truncation_stops_after_two_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            calls=[]
            def api(*args):calls.append(1);return self.response('truncated','length')
            with self.assertRaises(ModelResponseError) as caught:
                completion(api,'',{'max_tokens':800},Path(folder)/'request.json','summary')
            self.assertEqual(len(calls),2);self.assertEqual(caught.exception.details['max_tokens'],1600)

    def test_schema_failure_is_not_treated_as_success(self):
        with tempfile.TemporaryDirectory() as folder:
            def validate(r):raise ValueError('Missing required confidence')
            with self.assertRaisesRegex(ModelResponseError,'Missing required confidence'):
                completion(lambda *a:self.response('{}'),'',{},Path(folder)/'request.json','comparison',validate)

    def test_model_discovery_reports_server_body(self):
        with tempfile.TemporaryDirectory() as folder:
            def api(url):raise HTTPError(url,429,'Busy',{},io.BytesIO(b'{"error":"too many requests"}'))
            with self.assertRaises(ModelResponseError) as caught:
                discover_model(api,'http://test/models',Path(folder)/'models.json')
            self.assertIn('429',str(caught.exception));self.assertIn('too many requests',str(caught.exception))
            self.assertEqual(caught.exception.details['stage'],'model discovery')
