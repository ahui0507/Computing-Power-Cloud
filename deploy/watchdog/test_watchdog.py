import importlib.util
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('watchdog',Path(__file__).with_name('watchdog.py'))
w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)


class IncidentTests(unittest.TestCase):
    def test_failure_confirmation_and_no_repeat_events(self):
        state={}
        for now in (0,30):w.update_incidents(state,{'platform-api':{'ok':False}},now)
        self.assertFalse(state['incidents'])
        w.update_incidents(state,{'platform-api':{'ok':False}},60)
        first=state['incidents'][0]['id']
        w.update_incidents(state,{'platform-api':{'ok':False}},90)
        self.assertEqual(len(state['incidents']),1);self.assertEqual(state['incidents'][0]['id'],first)
        w.update_incidents(state,{'platform-api':{'ok':True}},120)
        w.update_incidents(state,{'platform-api':{'ok':True}},150)
        self.assertFalse(state['incidents'][0]['active'])
        for now in (180,210,240):w.update_incidents(state,{'platform-api':{'ok':False}},now)
        self.assertEqual(len(state['incidents']),2)

    def test_peer_outage_reports_are_merged_without_disclosing_diagnostics(self):
        state={};w.update_incidents(state,{'platform-api':{'ok':False,'detail':'private path'}},100,1)
        first=state['incidents'][0];second=dict(first,id='peer',first_seen=110)
        result=w.public_incidents([first,second]);self.assertEqual(len(result),1)
        self.assertNotIn('detail',result[0]);self.assertEqual(result[0]['first_seen'],100)

    def test_escalation_generates_a_new_episode(self):
        state={};w.update_incidents(state,{'disk-compute':{'ok':False}},100,1)
        w.update_incidents(state,{'disk-compute':{'ok':False,'severity':'critical'}},130,1)
        self.assertEqual(len(state['incidents']),2);self.assertEqual(state['incidents'][-1]['first_seen'],130)

    def test_records_survive_without_application_dependencies(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'status.json';w.atomic_json(path,{'incidents':[{'code':'platform-api'}]})
            self.assertEqual(w.load_json(path,{})['incidents'][0]['code'],'platform-api')


if __name__=='__main__':unittest.main()
