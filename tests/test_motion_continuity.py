import copy
import math
import random
import unittest
import numpy as np
from config.loader import cfg
from simulation.target import Target


class MotionContinuity(unittest.TestCase):
    def setUp(self):
        self.saved = copy.deepcopy(dict(cfg))

    def tearDown(self):
        cfg.clear()
        cfg.update(self.saved)

    def test_all_switch_pairs_and_edges(self):
        kinds = ['straight', 'circular', 'figure8', 'random', 'spiral', 'sinusoidal']
        for old in kinds:
            for new in kinds:
                for pos in [(350, 650), (1989, 11), (11, 1989)]:
                    cfg['motion']['type'] = old
                    target = Target(cfg, 42)
                    target.motion.wx, target.motion.wy = pos
                    target.t = 25
                    target.velocity = (12, -5)
                    cfg['motion']['type'] = new
                    rng = random.getstate()
                    nrng = np.random.get_state()
                    target.change_motion()
                    self.assertEqual(target.world_position, pos)
                    self.assertEqual(target.t, 25)
                    self.assertEqual(random.getstate(), rng)
                    self.assertTrue(np.array_equal(nrng[1], np.random.get_state()[1]))
                    for _ in range(90):
                        before = target.world_position
                        target.update(1/60)
                        self.assertLess(math.dist(before, target.world_position), 12)
                        self.assertTrue(all(10 <= v <= 1990 for v in target.world_position))

    def test_repeated_switch_and_pause(self):
        target = Target(cfg)
        target.update(.1)
        before, t = target.world_position, target.t
        for kind in ['figure8', 'sinusoidal', 'circular']*3:
            cfg['motion']['type'] = kind
            target.change_motion()
            target.update(0)
            self.assertEqual(target.world_position, before)
            self.assertEqual(target.t, t)

    def test_periodic_speed(self):
        distances = []
        for speed in [15, 55]:
            cfg['motion']['type'] = 'figure8'
            cfg['motion']['speed_px_s'] = speed
            target = Target(cfg)
            target.change_motion()
            start = target.world_position
            for _ in range(30):
                target.update(1/60)
            distances.append(math.dist(start, target.world_position))
        self.assertGreater(distances[1], distances[0]*2)
