"""Scene gain must exclude every detected foreground blob, including decoys."""
import unittest
from unittest.mock import patch

import numpy as np

from config.loader import cfg
from detection.detector import Candidate
from simulation.camera import VirtualCamera
from tracking.tracker import MasterTracker


class TestSceneReference(unittest.TestCase):
    def test_decoy_does_not_raise_scene_reference(self):
        for offset in ((0.0, 0.0), (17.0, -11.0)):
            with self.subTest(offset=offset):
                tracker = MasterTracker(cfg)
                camera = VirtualCamera(cfg)
                gray = np.full((480, 640), 2, dtype=np.uint8)
                gray[20:28, 20:28] = 44  # unmasked star pixels
                gray[195:206, 195:206] = 120
                gray[295:306, 395:406] = 90  # bright foreground decoy
                candidates = [
                    Candidate(200, 200, 5, 63, 0.8, np.zeros((32, 32)), 0.99),
                    Candidate(400, 300, 5, 55, 0.9, np.zeros((32, 32)), 0.1),
                ]
                with patch.object(tracker.stabiliser, 'update', return_value=offset):
                    tracker.process(candidates, camera, 1 / 60, gray=gray)
                self.assertEqual(tracker.fusion.brightness_gate, 44)
                self.assertEqual(int(gray[300, 400]), 90)  # measurement leaves frame intact


if __name__ == '__main__':
    unittest.main()
