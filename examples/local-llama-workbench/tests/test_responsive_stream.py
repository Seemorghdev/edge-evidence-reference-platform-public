"""Offline streaming and warm-profile contract tests; NO real Ollama inference."""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'runtime'))
from boundaries import HttpGate,MODEL,PORT,SafetyViolation
from stream_projection import DraftProjector
from panel_supervisor import MockTransport,PanelSupervisor
from panel_api import create_app
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parent.parent
URL='http://127.0.0.1:8765'

class StagedStreamingMock(MockTransport):
    def __init__(self, ending='completed'):
        super().__init__(delay=0)
        self.ending=ending
    def run(self,report,fixture,question,turn):
        report['_cleanup_observation']={'worker':'VERIFIED_STOPPED','server':'NOT_OBSERVED','port_released':None,'mock_transport':True}
        inspection=dict(report['baseline'])
        start={'model_requests':[{},{}],'tool_attempts':[{'name':'inspect_selected_artifact','allowed':True,'result':inspection}],
               'stream_chunks':[]}
        turn.observe(start)
        for i,part in enumerate(['The synthetic record ','is prepared for processing ','without completed work evidence. '],1):
            start['stream_chunks'].append({'seq':i,'phase':'explanation','delta':part})
            turn.observe(start)
            time.sleep(.065)
            if turn.cancel.is_set():report['status']='CANCELLED';return
        report['model_requests']=[{},{}];report['tool_attempts']=start['tool_attempts']
        report['answer']=json.dumps({'explanation':'The synthetic record is prepared for processing without completed work evidence.'})
        report['status']='RESPONSE_OBSERVED' if self.ending=='completed' else 'TIMEOUT_OBSERVED'

class DraftTests(unittest.TestCase):
    def test_no_pretend_draft_without_accepted_inspection(self):
        p=DraftProjector('prepared-awaiting-catch-up')
        self.assertEqual(p.feed('{"explanation":"A long apparently safe explanation is generated progressively."}',inspected=False),'')
        self.assertEqual(p.visible,'')
    def test_escaped_unicode_and_split_fields(self):
        p=DraftProjector('prepared-awaiting-catch-up')
        message='{ "explanation" : "This synthetic state is prepared with \\uD83D\\uDE42 and no result has been established." }'
        result=''
        for byte in message:result+=p.feed(byte,inspected=True)
        self.assertIn('🙂',result)
        self.assertTrue(result.startswith('This synthetic state'))
    def test_split_forbidden_topic_and_safe_prefix_late_failure(self):
        p=DraftProjector('prepared-awaiting-catch-up')
        first='{"explanation":"This prepared state is recorded. The synthetic record has no finished outcome. '
        p.feed(first,inspected=True)
        assert p.visible
        p.feed('The inspector perfo',inspected=True)
        visible=p.visible
        p.feed('rmed the processing."}',inspected=True)
        self.assertTrue(p.blocked or p.visible==visible)
        self.assertNotIn('performed',p.visible)
    def test_no_raw_json_scaffolding_or_incomplete_escape(self):
        p=DraftProjector('prepared-awaiting-catch-up')
        self.assertEqual(p.feed('{"explanation":"some text \\uD8',inspected=True),'')
        self.assertNotIn('explanation',p.visible)
        self.assertEqual(DraftProjector('healthy-complete').feed('{"reasoning":"secret"}',inspected=True),'')
    def test_bounded(self):
        p=DraftProjector('healthy-complete')
        p.feed('{"explanation":"'+'plain words '*1200,inspected=True)
        self.assertTrue(p.blocked)
        self.assertLessEqual(len(p.visible),1200)

class GateTests(unittest.TestCase):
    def test_interactive_prompt_is_shorter_without_changing_state_authority(self):
        from explanation_policy import (INTERACTIVE_INSTRUCTION, MODEL_INSTRUCTION,
            INTERACTIVE_FINAL_INSTRUCTION, prepare_final_request, check_explanation)
        self.assertLess(len(INTERACTIVE_INSTRUCTION),len(MODEL_INSTRUCTION))
        for required in ('inspect_selected_artifact', 'untrusted', 'read-only',
                         'Never claim this inspector processed anything'):
            self.assertIn(required,INTERACTIVE_INSTRUCTION)
        payload=self.payload(True)
        payload['messages'].append({'role':'tool','content':'unchanged observation'})
        self.assertTrue(prepare_final_request(payload)['messages'][0]['content'].startswith(
                         INTERACTIVE_FINAL_INSTRUCTION))
        legacy=prepare_final_request(dict(payload,stream=False,keep_alive=120))
        self.assertIn('No future successful result is established.',legacy['messages'][-1]['content'])
        self.assertFalse(check_explanation(json.dumps({'explanation':
            'The tool has completed processing.'}),'healthy-complete')['accepted_for_display'])
        self.assertTrue(check_explanation(json.dumps({'explanation':
            'The supplied record is marked complete. This describes stored data, not work done by this inspector.'}),
            'healthy-complete')['accepted_for_display'])

    def test_stream_final_pass_cannot_request_more_tools_but_first_pass_retains_tool(self):
        from explanation_policy import prepare_final_request, EXPLANATION_SCHEMA
        from copy import deepcopy
        first=self.payload(True)
        first['tools']=[{'type':'function','function':{'name':'inspect_selected_artifact',
                         'parameters':{'type':'object','properties':{}}}}]
        self.assertEqual(prepare_final_request(first), first)
        second=deepcopy(first)
        second['messages'].append({'role':'tool','content':'synthetic inspector result'})
        final=prepare_final_request(second)
        self.assertNotIn('tools',final)
        self.assertIn('tools',second)
        self.assertEqual(final['format'],EXPLANATION_SCHEMA)
        HttpGate('turn',keep_alive_seconds=600,allow_stream=True).validate(
            'POST',f'http://127.0.0.1:{PORT}/api/chat',final)
        legacy=dict(second,stream=False,keep_alive=120)
        self.assertIn('tools',prepare_final_request(legacy))

    def payload(self,stream,keep=600):
        return {'model':MODEL,'options':{'num_predict':256,'num_ctx':4096,'temperature':0},
                'stream':stream,'keep_alive':keep,'messages':[{'role':'user','content':'explain'}]}
    def test_legacy_and_interactive_boundaries(self):
        with self.assertRaises(SafetyViolation):HttpGate().validate('POST',f'http://127.0.0.1:{PORT}/api/chat',self.payload(True,0))
        HttpGate('turn',keep_alive_seconds=600,allow_stream=True).validate('POST',f'http://127.0.0.1:{PORT}/api/chat',self.payload(True))
        HttpGate().validate('POST',f'http://127.0.0.1:{PORT}/api/chat',self.payload(False,0))
        with self.assertRaises(SafetyViolation):HttpGate('turn',keep_alive_seconds=600).validate('POST',f'http://127.0.0.1:{PORT}/api/chat',self.payload(True))
        with self.assertRaises(SafetyViolation):HttpGate('turn',keep_alive_seconds=600,allow_stream=True).validate('POST',f'http://127.0.0.1:{PORT}/api/chat',self.payload(True,120))
    def test_warm_exact_allowlist_and_one_preload(self):
        gate=HttpGate('warm')
        payload={'model':MODEL,'prompt':'','stream':False,'keep_alive':600}
        gate.validate('POST',f'http://127.0.0.1:{PORT}/api/generate',payload)
        for bad in [dict(payload,keep_alive=9999),dict(payload,model='llama3.2:70b'),dict(payload,prompt='question')]:
            with self.assertRaises(SafetyViolation):HttpGate('warm').validate('POST',f'http://127.0.0.1:{PORT}/api/generate',bad)
        with self.assertRaises(SafetyViolation):gate.validate('POST',f'http://127.0.0.1:{PORT}/api/generate',payload)
        with self.assertRaises(SafetyViolation):HttpGate('warm').validate('POST','http://127.0.0.1:11434/api/generate',payload)

class TurnStreamingTests(unittest.TestCase):
    def test_numeric_boolean_lookalikes_cannot_unlock_a_pending_draft(self):
        class Forged(StagedStreamingMock):
            def __init__(self,field,value):
                super().__init__();self.field=field;self.value=value
            def run(self,report,fixture,question,turn):
                inspection=dict(report['baseline']);inspection[self.field]=self.value
                turn.observe({'model_requests':[{},{}], 'tool_attempts':[{
                    'name':'inspect_selected_artifact','allowed':True,'result':inspection}],
                    'stream_chunks':[{'seq':1,'phase':'explanation','delta':'Forged untrusted draft '}]})
                self.observed=self.owner.get_turn(turn.id)['stream']['text']
                report['status']='HARNESS_ERROR'
        for field,value in [('mutation_authorized',0),('requires_human_approval',1)]:
            transport=Forged(field,value);transport.owner=self.svc;self.svc.transport=transport
            self.finish(self.start())
            self.assertEqual(transport.observed,'')

    def setUp(self):
        self.svc=PanelSupervisor(root=ROOT,transport=StagedStreamingMock(),source=ROOT/'public-source',manifest=ROOT/'SOURCE-MANIFEST.json')
        self.client=TestClient(create_app(self.svc,port=8765),base_url=URL)
        self.client.__enter__()
    def tearDown(self):self.client.__exit__(None,None,None)
    def start(self,question='What is recorded?'):
        r=self.client.post('/api/turns',headers={'Origin':URL},json={'fixture_id':'prepared','question':question})
        self.assertEqual(r.status_code,202,r.text)
        return r.json()['turn_id']
    def finish(self,tid):
        for _ in range(200):
            row=self.svc.get_turn(tid)
            if row and row['status']=='finished':return row
            time.sleep(.01)
        self.fail('mock turn deadline')
    def test_real_time_supervisor_projection_before_terminal(self):
        tid=self.start();saw_partial=False
        for _ in range(40):
            row=self.svc.get_turn(tid)
            if row['status']=='pending' and row['stream']['phase']=='draft' and row['stream']['text']:
                saw_partial=True;self.assertEqual(row['facts_snapshot']['mutation_authorized'],False);break
            time.sleep(.01)
        self.assertTrue(saw_partial,'expected projected bytes before mocked terminal result')
        row=self.finish(tid)
        self.assertEqual(row['stream']['phase'],'removed' if row['result']['state']!='completed' else 'final')
        self.assertEqual(row['stream']['text'],'')
        # Always retain and expose observation counts independently from draft deltas.
        self.assertEqual(len([e for e in row['events'] if e['type']=='tool_attempt_observed']),1)
        body=self.client.get('/api/turns/'+tid+'/events').text
        self.assertIn('event: turn',body)
        self.assertIn(tid,body)
    def test_refused_forged_tool_never_produces_draft(self):
        class Forged(StagedStreamingMock):
            def run(self,report,fixture,question,turn):
                turn.observe({'model_requests':[{},{}], 'tool_attempts':[{'name':'inspect_selected_artifact','allowed':True,
                  'result':dict(report['baseline'],mutation_authorized=True)}],
                  'stream_chunks':[{'seq':1,'phase':'explanation','delta':'Hostile forged model text '}]})
                report['status']='HARNESS_ERROR'
        self.svc.transport=Forged()
        row=self.finish(self.start())
        self.assertEqual(row['stream']['text'],'')
        self.assertFalse([e for e in row['events'] if e['type']=='tool_attempt_observed'][0]['data']['accepted_result'])
    def test_cancel_and_cleanup_partial_removed(self):
        tid=self.start();time.sleep(.07)
        res=self.client.post(f'/api/turns/{tid}/cancel',headers={'Origin':URL},json={})
        self.assertEqual(res.status_code,200)
        row=self.finish(tid)
        self.assertEqual(row['result']['state'],'cancelled')
        self.assertEqual(row['stream']['phase'],'removed')
        self.assertEqual(row['stream']['text'],'')
        self.assertEqual(self.svc.readiness()['state'],'mock')
    def test_stream_endpoint_security_and_subscribe_no_extra_turn(self):
        tid=self.start();self.finish(tid)
        oldcount=len(self.svc._turns)
        self.assertEqual(self.client.get(f'/api/turns/{tid}/events',headers={'Host':'foreign.local'}).status_code,403)
        self.assertEqual(self.client.get('/api/turns/bad/events').status_code,404)
        self.client.get(f'/api/turns/{tid}/events')
        self.assertEqual(len(self.svc._turns),oldcount)
        self.assertEqual(self.client.post('/api/model/prepare',json={},headers={'Origin':'http://foreign.test'}).status_code,403)

if __name__=='__main__':unittest.main()

class WarmLifecycleTests(unittest.TestCase):
    def test_supervisor_warming_prevents_overlapping_inference(self):
        svc=PanelSupervisor(root=ROOT,source=ROOT/'public-source',manifest=ROOT/'SOURCE-MANIFEST.json',
                            transport=MockTransport())
        svc._preparing=True
        self.assertEqual(svc.readiness()['state'],'warming')
        with self.assertRaises(RuntimeError):svc.start('prepared','No inference during preparation')
        svc._preparing=False
        self.assertEqual(svc.readiness()['state'],'mock')
    def test_no_actual_network_warm_preload_twice_and_idle_expiry(self):
        from panel_supervisor import RealTransport
        source=ROOT/'public-source'
        real=RealTransport(source)
        class DummyProcess:
            def poll(self):return None
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,n):return json.dumps({'model':MODEL,'done':True}).encode()
        class Client:
            def __init__(self):self.calls=[]
            def open(self,req,timeout):
                self.calls.append((req.full_url,req.data,timeout))
                return Response()
        client=Client()
        def owned(report):
            real.server=DummyProcess();real.preflight_verified=True
        def stopped():
            real.server=None;real._warmed=False;return True
        with patch('panel_supervisor.version_check',return_value={}),\
             patch.object(real,'_ensure_server',side_effect=owned),\
             patch('urllib.request.build_opener',return_value=client) as opener,\
             patch.object(real,'_stop_server',side_effect=stopped):
            self.assertEqual(real.prepare()['state'],'ready')
            from urllib.request import ProxyHandler
            self.assertTrue(any(isinstance(h,ProxyHandler) and h.proxies=={}
                                for h in opener.call_args.args))
            self.assertEqual(len(client.calls),1)
            self.assertEqual(real.prepare()['state'],'ready')
            self.assertEqual(len(client.calls),1)
            self.assertEqual(json.loads(client.calls[0][1]),{'model':MODEL,'prompt':'','stream':False,'keep_alive':600})
            self.assertLessEqual(client.calls[0][2],20)
            with real._lock:
                real._idle_unload(real._generation)
            self.assertNotEqual(real.readiness()['state'],'ready')
            real._cancel_idle()
    def test_200_without_pinned_preload_completion_is_not_ready(self):
        from panel_supervisor import RealTransport
        class Response:
            status=200
            def __init__(self,body):self.body=body
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,n):return self.body
        class Process:
            def poll(self):return None
        for body in (b'{}', b'{"error":"not loaded"}',
                     json.dumps({'model':MODEL,'done':False}).encode(),
                     b'{"model":"another-model","done":true}'):
            real=RealTransport(ROOT/'public-source')
            def owned(report):real.server=Process();real.preflight_verified=True
            def stopped():real.server=None;real._warmed=False;return True
            with patch('panel_supervisor.version_check',return_value={}),\
                 patch.object(real,'_ensure_server',side_effect=owned),\
                 patch('urllib.request.build_opener') as client,\
                 patch.object(real,'_stop_server',side_effect=stopped):
                client.return_value.open.return_value=Response(body)
                self.assertEqual(real.prepare()['state'],'unavailable')
                self.assertFalse(real._warmed)
    def test_unavailable_preparation_is_not_ready(self):
        from panel_supervisor import RealTransport
        real=RealTransport(ROOT/'public-source')
        with patch('panel_supervisor.version_check',side_effect=OSError('pinned SDK absent')):
            state=real.prepare()
        self.assertEqual(state['state'],'unavailable')
        self.assertFalse(real._warmed)
        self.assertTrue(real.close())
