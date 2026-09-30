"""
Target beacon — square spot in world pixel space.
Wraps a MotionModel. Exposes wx, wy, size_px, color, brightness.
"""
from simulation.motion import create_motion_model, MotionSegment
import random

class Target:
    def __init__(self, cfg, seed=42):
        self.cfg = cfg
        W = int(cfg.world.width)
        H = int(cfg.world.height)

        # Initial position
        pos = str(cfg.target.initial_position).lower()
        if pos in ('near_center', 'near-center'):
            wx0 = W / 2 + 25.0
            wy0 = H / 2 + 25.0
        elif pos in ('center', 'in_fov', 'fov'):
            wx0, wy0 = W // 2, H // 2
        elif pos == 'random':
            random.seed(seed + 1)
            # Spawn near the camera's world-center starting position so the
            # spiral search finds the beacon quickly and deterministically
            # (demo requirement: acquisition within a few seconds).
            wx0 = W / 2 + random.uniform(-250, 250)
            wy0 = H / 2 + random.uniform(-250, 250)
        elif pos == 'anywhere':
            rng = random.Random(seed+1)
            wx0, wy0 = rng.uniform(20,W-20), rng.uniform(20,H-20)
        else:
            wx0, wy0 = W // 2, H // 2

        self.motion = create_motion_model(cfg, seed)
        self.motion.wx = wx0
        self.motion.wy = wy0

        self.size_px   = int(cfg.target.size_px)
        self.color     = tuple(cfg.target.color)
        self.brightness = int(cfg.target.brightness)
        self.t = 0.0
        self.velocity = (0.0, 0.0)
        self._seed = seed
        self._segment_count = 0

    def change_motion(self):
        """Change manoeuvre without changing identity, position or mission time."""
        self._segment_count += 1
        self.motion = MotionSegment(self.cfg, self.world_position, self.velocity,
                                    self._seed + self._segment_count)

    def update(self, dt):
        before = self.world_position
        self.t += dt
        self.motion.update(self.t, dt)
        if dt > 0:
            self.velocity = ((self.wx-before[0])/dt, (self.wy-before[1])/dt)

    @property
    def wx(self): return self.motion.wx

    @property
    def wy(self): return self.motion.wy

    @property
    def world_position(self): return (self.wx, self.wy)
