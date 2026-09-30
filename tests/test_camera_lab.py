import unittest
from config.loader import cfg
from simulation.camera import VirtualCamera
from simulation.camera_lab import CameraLab

class CameraLabTests(unittest.TestCase):
    def test_rates_limits_and_sign(self):
        cam=VirtualCamera(cfg);lab=CameraLab()
        for _ in range(1200):
            lab.command({'pan':2,'tilt':2});lab.update(cam,1/60);cam.update(1/60)
        self.assertLessEqual((cam.pan**2+cam.tilt**2)**.5,5.00001)
        sx,sy=cam.world_to_screen(1000,1000)
        self.assertLess(sx,320);self.assertGreater(sy,240)
        lab.command({'home':True})
        for _ in range(120):lab.update(cam,1/60);cam.update(1/60)
        self.assertAlmostEqual(cam.pan,0);self.assertAlmostEqual(cam.tilt,0)
    def test_timeout_auto_and_validation(self):
        cam=VirtualCamera(cfg);lab=CameraLab()
        lab.command({'pan':1});lab.last_input=0;lab.update(cam,.1)
        self.assertEqual(cam.cmd_x,1000)
        lab.command({'mode':'auto','pan':1});lab.update(cam,.1)
        self.assertEqual(cam.cmd_x,1000)
        for value in [float('nan'),float('inf'),3]:
            with self.assertRaises(ValueError):lab.command({'pan':value})
