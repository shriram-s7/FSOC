import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import Mock
from evaluation.metrics import MetricsAccumulator
from ui.sim_thread import SimulationThread

class FinalisationTests(unittest.TestCase):
    def test_failed_export_can_retry_same_session_and_stop_is_idempotent(self):
        sim=SimulationThread.__new__(SimulationThread)
        sim.state={};sim.output_dir=Path('scratch/handoff-verification/tests')/uuid4().hex
        sim._metrics=MetricsAccumulator('SIM_retry','simulation')
        sim._metrics.record_frame(dict(track_state='SEARCHING',sim_time=0,fps=25))
        sim._logger=Mock();sim._logger.export_csv.return_value='SIM_retry_frames.csv'
        sim._report_gen=Mock();sim._report_gen.generate.side_effect=[OSError('test disk failure'),'SIM_retry_report.pdf']
        sim._finish_session()
        self.assertEqual(sim.state['finalisation'],'error');self.assertIsNotNone(sim._metrics)
        sim._finish_session()
        self.assertEqual(sim.state['finished_session_id'],'SIM_retry');self.assertEqual(sim.state['finalisation'],'ready')
        self.assertIsNone(sim._metrics)
        sim._finish_session();self.assertEqual(sim._report_gen.generate.call_count,2)
        self.assertTrue((sim.output_dir/'SIM_retry/session.json').exists())
    def test_empty_session_does_not_create_report(self):
        sim=SimulationThread.__new__(SimulationThread);sim.state={}
        sim._metrics=MetricsAccumulator('SIM_empty','simulation');sim._logger=Mock()
        sim._finish_session();sim._logger.export_csv.assert_not_called()
        self.assertEqual(sim.state['finalisation'],'ready');self.assertIsNone(sim.state['finished_session_id'])
