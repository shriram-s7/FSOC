import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from evaluation.metrics import MetricsAccumulator
from evaluation.session_record import make_record, save_record
from server.sessions import read_session, list_sessions, safe_session
from evaluation.requirements import evaluate

class SessionRecordTests(unittest.TestCase):
    def test_atomic_record_and_empty(self):
        root=Path('scratch/handoff-verification/tests')/uuid4().hex
        root.mkdir(parents=True)
        if root.exists():
            m=MetricsAccumulator('SIM_test', 'simulation')
            record=make_record(m)
            save_record(root,record)
            save_record(root,record)
            self.assertEqual(read_session(root,'SIM_test'),record)
            self.assertEqual(len(list_sessions(root)),1)
            self.assertNotEqual(record['requirements']['overall'],'PASS')

    def test_checks_and_zero(self):
        s=dict(scored_with_gt=True, acquisition_time_s=0,mean_track_error_px=0,target_loss_pct=0,reacq_time_s=.5,mean_fps=40)
        self.assertEqual(evaluate(s)['overall'],'PASS')
        s['reacq_time_s']=None
        self.assertEqual(evaluate(s)['overall'],'INCOMPLETE')
        self.assertEqual(evaluate(s,False)['rows'][-1]['status'],'NOT_TESTED')
        s.update(not_scored=True,scored_with_gt=False)
        self.assertEqual(evaluate(s)['overall'],'NOT_SCORED')

    def test_traversal(self):
        for sid in ['../test','a/b','a\\b','C:foo']:
            with self.assertRaises(ValueError): safe_session('.',sid)
