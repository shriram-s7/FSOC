"""Distractor beacons — round, near-white spots of beacon-like size and
brightness, so a simple brightness/size rule could mistake them for the
(square, white) beacon."""
import random, math

class Distractors:
    def __init__(self, cfg):
        self.cfg = cfg
        W = int(cfg.world.width)
        H = int(cfg.world.height)
        self.objects = []
        for i in range(int(cfg.distractors.count)):
            obj = {
                'wx': random.uniform(W*0.05, W*0.95),
                'wy': random.uniform(H*0.05, H*0.95),
                'vx': random.uniform(-1,1) * float(cfg.distractors.speed_px_s),
                'vy': random.uniform(-1,1) * float(cfg.distractors.speed_px_s),
                'size': random.randint(8, 12),          # beacon: 10 px
                'brightness': random.randint(220, 255),  # beacon: 255
                'color': (
                    random.randint(235,255),
                    random.randint(235,255),
                    random.randint(215,255)),
                'shape': 'round',
                'W': W, 'H': H,
            }
            self.objects.append(obj)

    def place_near(self, wx, wy, rx=260, ry=190, min_d=60):
        """Re-place every distractor inside the camera view around the
        beacon at (wx, wy), at least min_d px from it (live UI 'Decoys'
        toggle - spawned anywhere in the world they are almost never in
        view)."""
        for o in self.objects:
            while True:
                dx, dy = random.uniform(-rx, rx), random.uniform(-ry, ry)
                if math.hypot(dx, dy) >= min_d:
                    break
            o['wx'], o['wy'] = wx + dx, wy + dy

    def update(self, dt):
        for o in self.objects:
            o['wx'] += o['vx'] * dt
            o['wy'] += o['vy'] * dt
            if o['wx'] < 50 or o['wx'] > o['W']-50: o['vx'] *= -1
            if o['wy'] < 50 or o['wy'] > o['H']-50: o['vy'] *= -1

    @property
    def positions(self): return self.objects
