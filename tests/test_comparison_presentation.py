import unittest
from evaluation.comparison_presentation import presentation
from evaluation.requirements import evaluate

class PresentationTests(unittest.TestCase):
    def test_highlight_does_not_force_hybrid_winner(self):
        modes={m:{'summary':{'rmse_px':v,'processing_fps':10-v}} for m,v in [('cv',1),('ai',2),('hybrid',3)]}
        rows=presentation(modes)['metrics']
        self.assertEqual(rows[0]['leaders'],['cv'])
        self.assertEqual(rows[3]['leaders'],['cv'])
    def test_ties_and_missing_are_explicit(self):
        modes={m:{'summary':{'rmse_px':v}} for m,v in [('cv',1.00001),('ai',None),('hybrid',1.00002)]}
        row=presentation(modes)['metrics'][0]
        self.assertEqual(row['leaders'],['cv','hybrid'])
        self.assertFalse(row['complete'])
        self.assertEqual(presentation({})['metrics'][0]['leaders'],[])
    def test_ps_loss_boundary_is_strict(self):
        summary=dict(total_frames=300,scored_with_gt=True,target_loss_pct=5)
        row=evaluate(summary)['rows'][2]
        self.assertEqual(row['operator'],'<');self.assertEqual(row['status'],'FAIL')
        summary['target_loss_pct']=4.999
        self.assertEqual(evaluate(summary)['rows'][2]['status'],'PASS')
