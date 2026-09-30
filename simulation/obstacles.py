"""Opaque obstacles that occlude the beacon."""
import random

class Obstacles:
    def __init__(self, cfg):
        W = int(cfg.world.width)
        H = int(cfg.world.height)
        self.objects = [{
            'wx': random.uniform(W*0.1, W*0.3),
            'wy': random.uniform(H*0.3, H*0.7),
            'vx': random.uniform(8, 18),
            'vy': random.uniform(-5, 5),
            'w': random.randint(80, 160),
            'h': random.randint(60, 120),
            'W': W, 'H': H,
        }]

    def update(self, dt):
        for o in self.objects:
            o['wx'] += o['vx'] * dt
            o['wy'] += o['vy'] * dt
            if o['wx'] > o['W'] + 100:
                o['wx'] = -100
                o['wy'] = random.uniform(
                    o['H']*0.2, o['H']*0.8)

    @property
    def rects(self): return self.objects
