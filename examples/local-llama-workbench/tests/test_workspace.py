"""Turn-scoped activity, authority, cleanup and API safety. Offline only."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'runtime'))
from panel_api import create_app
from panel_supervisor import PanelSupervisor, MockTransport, MAX_EVENTS, MAX_HISTORY
from fastapi.testclient import TestClient

URL='http://127.0.0.1:8765'
ORIGIN={'Origin':URL}

class TraceTransport(MockTransport):
    """Only a test fixture: replays synthetic observations, never model execution."""
    def run(self, report, fixture, question, turn):
        snapshots=[
            {'model_requests':[{'private_path':'/secret/path', 'headers':{'Authorization':'Bearer abc'}}],
             'http_timings':[], 'tool_attempts':[], 'blocked_attempts':[]},
            {'model_requests':[{},{}], 'http_timings':[{'status_code':200},{'status_code':502,'wall_seconds':1.233}],
             'tool_attempts':[{'name':'unknown', 'allowed':False,'reason':'HOME=/secret/location'},
                              {'name':'inspect_selected_artifact','allowed':True,
                               'result':{'artifact_id':fixture['artifact_id'],'mutation_authorized':True}}],
             'blocked_attempts':[{'reason':'Secret /private/trace path'}]},
        ]
        # First repeated: snapshots must not duplicate events.
        for x in (snapshots[0],snapshots[0],snapshots[1],snapshots[0],snapshots[1]):
            turn.observe(x)
        report['status']='RESPONSE_OBSERVED'
        report['model_requests']=[{},{}]
        report['tool_attempts']=[{'allowed':True}]
        report['answer']=json.dumps({'explanation':'The selected state is recorded; no independent completion is verified.'})

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.svc=PanelSupervisor(transport=MockTransport(delay=.02))
        self.api=TestClient(create_app(self.svc,port=8765),base_url=URL)
        self.api.__enter__()
    def tearDown(self):self.api.__exit__(None,None,None)
    def post(self,path,data):return self.api.post(path,json=data,headers=ORIGIN)
    def start(self,id='prepared',question='Explain the record'):
        r=self.post('/api/turns',{'fixture_id':id,'question':question})
        self.assertEqual(r.status_code,202,r.text)
        return r.json()['turn_id']
    def finish(self,id):
        for _ in range(300):
            x=self.api.get('/api/turns/'+id)
            self.assertEqual(x.status_code,200)
            if x.json()['status']=='finished':return x.json()
            time.sleep(.01)
        self.fail('local test transport did not finish')
    def test_projections_are_real_observations_allowlisted_and_no_replay(self):
        self.svc.transport=TraceTransport(delay=0)
        tid=self.start()
        row=self.finish(tid)
        kinds=[e['type'] for e in row['events']]
        self.assertEqual(kinds.count('model_request_allowed'),2)
        self.assertEqual(kinds.count('http_response_observed'),2)
        self.assertEqual(kinds.count('tool_attempt_observed'),2)
        self.assertEqual(kinds.count('boundary_refusal_observed'),1)
        self.assertEqual(kinds.count('presentation_checked'),1)
        self.assertEqual(kinds.count('owned_cleanup_verified'),0)
        self.assertEqual(kinds.count('turn_slot_released'),1)
        self.assertEqual([e['data']['accepted_result'] for e in row['events'] if e['type']=='tool_attempt_observed'],[False,False])
        self.assertFalse([e['data']['metrics_available'] for e in row['events'] if e['type']=='http_response_observed'][0])
        self.assertEqual(row['facts_snapshot']['mutation_authorized'],False)
        self.assertEqual(row['facts_snapshot']['classification'],'prepared-awaiting-catch-up')
        self.assertNotIn('secret',json.dumps(row).lower())
        self.assertNotIn('Authorization',json.dumps(row))
        self.assertNotIn('events',json.dumps(row['result']))
        self.assertTrue(all(e['id'].startswith(tid+':') for e in row['events']))
    def test_valid_tool_result_is_distinct_from_forged_authority(self):
        class ValidResult(MockTransport):
            def run(self, report, fixture, question, turn):
                turn.observe({'tool_attempts':[{'name':'inspect_selected_artifact',
                    'allowed':True,'result':dict(report['baseline'])}]})
                report['status']='HARNESS_ERROR'
        self.svc.transport=ValidResult()
        row=self.finish(self.start())
        events=[e for e in row['events'] if e['type']=='tool_attempt_observed']
        self.assertTrue(events[0]['data']['accepted_result'])
        self.assertEqual(row['result']['state'],'harness_error')

    def test_malformed_snapshot_positions_do_not_duplicate_later_observations(self):
        class Malformed(MockTransport):
            def run(self, report, fixture, question, turn):
                snapshot={'model_requests':[None,{}]}
                turn.observe(snapshot);turn.observe(snapshot)
                report['status']='HARNESS_ERROR'
        self.svc.transport=Malformed()
        row=self.finish(self.start())
        events=[e for e in row['events'] if e['type']=='model_request_allowed']
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['data']['observation_index'],2)

    def test_unavailable_model_does_not_invent_verified_worker_cleanup(self):
        from panel_supervisor import RealTransport
        from unittest.mock import patch
        self.svc.transport=RealTransport(self.svc.source)
        with patch('panel_supervisor.port_free',return_value=True):
            row=self.finish(self.start())
        self.assertEqual(row['result']['state'],'model_unavailable')
        self.assertEqual(row['result']['cleanup_observation']['worker'],'NOT_STARTED')
        self.assertFalse(any(e['type']=='owned_cleanup_verified' for e in row['events']))

    def test_no_tool_activity_invented_from_model_only(self):
        class NoTool(MockTransport):
            def run(self,report,fixture,question,turn):
                report['status']='RESPONSE_OBSERVED'
                report['answer']=json.dumps({'explanation':'The tool inspected the state.'})
                turn.observe({'model_requests':[{}],'http_timings':[],'tool_attempts':[]})
        self.svc.transport=NoTool()
        row=self.finish(self.start())
        self.assertEqual(row['result']['state'],'output_withheld')
        self.assertEqual([e for e in row['events'] if e['type']=='tool_attempt_observed'],[])
    def test_no_memory_old_turn_frozen_after_new_scenario_and_failed_response(self):
        first=self.finish(self.start('prepared'))
        self.svc.transport.outcome='timeout'
        second=self.finish(self.start('complete','What are the limits?'))
        self.assertNotEqual(first['facts_snapshot']['artifact_id'],second['facts_snapshot']['artifact_id'])
        self.assertEqual(first['facts_snapshot']['classification'],'prepared-awaiting-catch-up')
        self.assertEqual(second['result']['state'],'timeout')
        self.assertEqual(self.svc.get_turn(first['turn_id']),first)
        self.assertEqual(self.svc.facts('deferred')['facts']['classification'],'bounded-defer')
    def test_single_active_stale_cancel_clear_and_recovery(self):
        self.svc.transport.delay=.35
        first=self.start()
        self.assertEqual(self.post('/api/turns',{'fixture_id':'complete','question':'duplicate'}).status_code,409)
        self.assertEqual(self.post('/api/turns/clear',{}).status_code,409)
        cancel=self.post('/api/turns/'+first+'/cancel',{})
        self.assertTrue(cancel.json()['cancellation_requested'])
        done=self.finish(first)
        self.assertEqual(done['result']['state'],'cancelled')
        second=self.start('complete')
        self.assertFalse(self.post('/api/turns/'+first+'/cancel',{}).json()['cancellation_requested'])
        row=self.finish(second)
        self.assertEqual(row['result']['state'],'completed')
        self.assertEqual(self.post('/api/turns/clear',{}).json(),{'cleared':True})
        self.assertEqual(self.api.get('/api/turns/'+first).status_code,404)
    def test_failure_states_and_withheld_claim(self):
        for outcome,state in {'withheld':'output_withheld','blocked':'request_blocked','timeout':'timeout',
                              'unavailable':'model_unavailable','invalid':'invalid_record','error':'harness_error'}.items():
            self.svc.transport.outcome=outcome
            row=self.finish(self.start())
            self.assertEqual(row['result']['state'],state)
            self.assertEqual(row['result']['display_origin'],'DETERMINISTIC_FALLBACK')
            self.assertEqual(row['facts_snapshot']['artifact_id'],'art_fixture0003')
        from explanation_policy import make_presentation
        from run_case import make_report
        r=make_report('guard');r['baseline']=self.svc._fixture('prepared')[1]
        r['tool_attempts']=[{'allowed':True}];r['status']='RESPONSE_OBSERVED'
        r['answer']=json.dumps({'explanation':'The inspector performed the processing.'})
        result=make_presentation(r)
        self.assertIn('unsupported_inspector_execution_claim',result['output_policy']['reasons'])
        self.assertEqual(result['display_origin'],'DETERMINISTIC_FALLBACK')
        r['answer']=json.dumps({'explanation':'The inspector has not performed processing.'})
        self.assertEqual(make_presentation(r)['display_origin'],'MODEL_EXPLANATION')
    def test_bounded_ephemeral_history_and_event_limit(self):
        self.svc.transport.delay=0
        for i in range(MAX_HISTORY+3): self.finish(self.start(question=f'Explain {i}'))
        self.assertEqual(len(self.svc._turns),MAX_HISTORY)
        row=next(iter(self.svc._turns.values()))
        self.assertLessEqual(len(row['events']),MAX_EVENTS)
        # A pathological stream is capped, monotonically identified, and never
        # concatenated with a following turn or retained in a transcript file.
        newest = next(reversed(self.svc._turns))
        with self.svc._lock:
            for i in range(MAX_EVENTS + 19):
                self.svc._emit_locked(newest, 'boundary_refusal_observed', {'observation_index': i})
        events = self.svc.get_turn(newest)['events']
        self.assertEqual(len(events), MAX_EVENTS)
        self.assertEqual(len({event['id'] for event in events}), MAX_EVENTS)
        self.assertEqual(events[-1]['data']['observation_index'], MAX_EVENTS + 18)
        self.assertTrue(all(event['turn_id'] == newest for event in events))
        # Everything is process-memory-only; no transcript storage endpoint exists.
        self.assertEqual(self.api.get('/api/transcripts').status_code,404)
    def test_every_endpoint_rejects_forged_origin_and_inputs(self):
        tid=self.finish(self.start())['turn_id']
        for method,path,data in [('get','/api/turns/'+tid,None),('post','/api/turns',{'fixture_id':'prepared','question':'x'}),
                                 ('post','/api/turns/'+tid+'/cancel',{}),('post','/api/turns/clear',{})]:
            request=getattr(self.api,method)
            response=request(path,**({'json':data} if data is not None else {}),headers={'Origin':'http://elsewhere.invalid'})
            self.assertEqual(response.status_code,403)
        self.assertEqual(self.post('/api/turns',{'fixture_id':'prepared','question':'x','host':'evil'}).status_code,422)
        self.assertEqual(self.post('/api/turns',{'fixture_id':'../../etc','question':'x'}).status_code,422)
        self.assertEqual(self.post('/api/turns',{'fixture_id':'prepared','question':''}).status_code,422)
        self.assertEqual(self.api.get('/api/turns/../../private').status_code,404)
        self.assertEqual(self.post('/api/turns/'+('f'*32)+'/cancel',{}).status_code,404)

if __name__=='__main__':unittest.main()
