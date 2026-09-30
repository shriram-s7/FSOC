import os
os.environ.setdefault('SDL_VIDEODRIVER','dummy')
import copy,random,unittest
import numpy as np
import pygame
from config.loader import cfg,_A
from simulation.world import World
from simulation.optical_world import make_world,OpticalWorld
from simulation.target import Target
from evaluation.metrics import MetricsAccumulator

class OpticalProfileTests(unittest.TestCase):
    def test_classic_pixels_are_unchanged_and_optical_is_distinct(self):
        config=copy.deepcopy(dict(cfg));config['target']['initial_position']='in_fov';config['rendering']={'profile':'classic'};config=_A(config)
        target=Target(config,42)
        random.seed(42);classic=World(config);random.seed(42);fallback=make_world(config)
        a,occ=classic.render(1000,1000,[target]);b,occ2=fallback.render(1000,1000,[target])
        np.testing.assert_array_equal(pygame.surfarray.array3d(a),pygame.surfarray.array3d(b));self.assertEqual(occ,occ2)
        config['rendering']['profile']='optical';random.seed(42);optical=make_world(config)
        c,occ3=optical.render(1000,1000,[target]);self.assertIsInstance(optical,OpticalWorld)
        self.assertEqual(c.get_size(),(640,480));self.assertEqual(occ,occ3)
        self.assertFalse(np.array_equal(pygame.surfarray.array3d(a),pygame.surfarray.array3d(c)))
    def test_changed_atmosphere_does_not_suspend_recovery_clock(self):
        m=MetricsAccumulator('test','simulation')
        for i,state in enumerate(['LOCKED','LOST','LOST','LOCKED']):
            m.record_frame(dict(track_state=state,sim_time=i*.1,gt_sx=320,gt_sy=240,tracker_x=320,tracker_y=240,tracker_stab_sx=320,tracker_stab_sy=240,fps=30,disturbances={'atmosphere':'clear' if i==0 else 'fog'}))
        self.assertAlmostEqual(m._gt_scores()['reacq_mean_s'],.2)
