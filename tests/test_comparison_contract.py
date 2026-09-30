import copy
import random
import unittest
from comparison.scenario import make_scenario
from config.loader import cfg
from server.mission_config import preview,resolve
from evaluation.requirements import evaluate

class ComparisonContractTests(unittest.TestCase):
    def test_scenario_reproducible_and_does_not_change_runtime(self):
        before=copy.deepcopy(dict(cfg));random.seed(93);rng=random.getstate()
        a=make_scenario('figure8',5);b=make_scenario('figure8',5)
        self.assertEqual(a,b);self.assertEqual(before,dict(cfg));self.assertEqual(rng,random.getstate())
        self.assertEqual(len(a['schedule']),300)
        self.assertEqual(sum(s['blackout'] for s in a['schedule']),30)
        self.assertTrue(all(s['frame']==i for i,s in enumerate(a['schedule'])))
    def test_unpaced_comparison_cannot_claim_realtime_pass(self):
        summary=dict(total_frames=300,scored_with_gt=True,acquisition_time_s=.2,mean_track_error_px=1.,target_loss_pct=0.,reacq_time_s=.2,mean_fps=60)
        result=evaluate(summary,realtime=False)
        self.assertEqual(result['overall'],'INCOMPLETE');self.assertEqual(result['rows'][-1]['status'],'NOT_TESTED')
    def test_preview_is_isolated_and_settings_validated(self):
        before=copy.deepcopy(dict(cfg));random.seed(12);rng=random.getstate()
        result=preview(dict(motion='Figure-8',speed='Fast',position='Anywhere'))
        self.assertEqual(before,dict(cfg));self.assertEqual(rng,random.getstate())
        self.assertEqual(result['configuration']['motion']['speed_px_s'],55.)
        with self.assertRaises(ValueError):resolve(dict(speed='Invalid'))
        with self.assertRaises(ValueError):make_scenario(duration=float('nan'))
    def test_empty_session_is_not_failure_or_pass(self):
        result=evaluate(dict(total_frames=0,mean_fps=0))
        self.assertEqual(result['overall'],'INCOMPLETE')
        self.assertTrue(all(r['status']=='NOT_TESTED' for r in result['rows']))
