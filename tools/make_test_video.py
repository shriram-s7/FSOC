"""
Make a synthetic MP4 test clip with known ground truth for video mode
(PS Benchmark-2), using the simulator's own renderer and disturbance
engine with the camera FIXED (no servo).

    venv\\Scripts\\python -m tools.make_test_video --seed 1
    venv\\Scripts\\python -m tools.make_test_video --clean

Beacon: figure-8 inside the 640x480 frame, pushed out of frame once for
~1.5 s around t=20 s. Noisy clips add moderate Gaussian noise throughout,
3 round distractors, and fog from 28-31 s. The clean clip has distractors
but no noise and no fog.

Writes data/test_videos/test_seed<N>.mp4 (or test_clean.mp4) and a
matching *_gt.csv with columns frame,t,x,y,visible — (x, y) is the true
beacon pixel centre in the video frame (may lie outside it; visible=0
then).
"""
import argparse
import csv
import math
import os
import random
import sys

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cv2          # noqa: E402
import numpy as np  # noqa: E402
import pygame       # noqa: E402

from config.loader import cfg                      # noqa: E402
from disturbance.disturbance import DisturbanceEngine  # noqa: E402
from simulation.camera import VirtualCamera         # noqa: E402
from simulation.world import World                  # noqa: E402

W, H = 640, 480
FPS = 30
DURATION_S = 40.0
FOG = (28.0, 31.0)
NOISE_LEVEL = 0.4          # moderate Gaussian noise (sigma ~8 grey levels)
EXIT_T = 20.0              # centre of the out-of-frame excursion


def beacon_screen_pos(t):
    """Figure-8 (Lissajous 1:2) around frame centre, plus a smooth push
    off the right edge centred on EXIT_T."""
    T = 16.0
    x = W / 2 + 200 * math.sin(2 * math.pi * t / T)
    y = H / 2 + 120 * math.sin(4 * math.pi * t / T)
    half = 2.0
    if abs(t - EXIT_T) < half:
        x += 200 * 0.5 * (1 + math.cos(math.pi * (t - EXIT_T) / half))
    return x, y


class _Beacon:
    """Just what World.render needs from a target."""
    def __init__(self):
        self.wx = self.wy = 0.0
        self.size_px = int(cfg.target.size_px)
        self.color = tuple(cfg.target.color)
        self.brightness = int(cfg.target.brightness)


def _distractors(rng):
    out = []
    for _ in range(3):
        out.append({
            'sx': rng.uniform(60, W - 60), 'sy': rng.uniform(60, H - 60),
            'vx': rng.uniform(-25, 25), 'vy': rng.uniform(-25, 25),
            'size': rng.randint(8, 12), 'brightness': rng.randint(220, 255),
            'color': (rng.randint(235, 255), rng.randint(235, 255),
                      rng.randint(215, 255)),
            'shape': 'round',
        })
    return out


def make(seed, clean, out_dir):
    random.seed(seed)
    np.random.seed(seed)
    rng = random.Random(seed)
    pygame.init()

    camera = VirtualCamera(cfg)                 # fixed: never commanded
    world = World(cfg)
    dist = DisturbanceEngine(cfg)
    dist.set_levels(noise=0.0 if clean else NOISE_LEVEL, noise_gaussian=True,
                    noise_saltpepper=False, noise_poisson=False,
                    vibration=0.0, turbulence=0.0, scintillation=0.0,
                    jerk=0.0, atmosphere='clear', platform_enabled=False)
    beacon = _Beacon()
    dists = _distractors(rng)

    name = 'test_clean' if clean else f'test_seed{seed}'
    os.makedirs(out_dir, exist_ok=True)
    mp4 = os.path.join(out_dir, name + '.mp4')
    gt_path = os.path.join(out_dir, name + '_gt.csv')
    vw = cv2.VideoWriter(mp4, cv2.VideoWriter_fourcc(*'mp4v'), FPS, (W, H))
    if not vw.isOpened():
        raise IOError(f'cannot open VideoWriter for {mp4}')

    to_world = lambda sx, sy: (sx - W / 2 + camera.cam_x, sy - H / 2 + camera.cam_y)
    dt = 1.0 / FPS
    n = int(round(DURATION_S * FPS))
    out_frames = 0
    with open(gt_path, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(['frame', 't', 'x', 'y', 'visible'])
        for i in range(n):
            t = i * dt
            if not clean:
                dist.set_levels(atmosphere='fog' if FOG[0] <= t < FOG[1] else 'clear')
            for d in dists:
                d['sx'] += d['vx'] * dt
                d['sy'] += d['vy'] * dt
                if not 30 < d['sx'] < W - 30: d['vx'] *= -1
                if not 30 < d['sy'] < H - 30: d['vy'] *= -1
                d['wx'], d['wy'] = to_world(d['sx'], d['sy'])
            sx, sy = beacon_screen_pos(t)
            beacon.wx, beacon.wy = to_world(sx, sy)

            surf, _ = world.render(camera.cam_x, camera.cam_y, [beacon],
                                   distractors=dists, obstacles=None,
                                   scintillation=1.0)
            surf = dist.apply(surf, dt)
            ox, oy = dist.applied_offset          # 0 here (no jitter)
            gx, gy = sx + ox, sy + oy
            visible = int(0 <= gx < W and 0 <= gy < H)
            out_frames += 1 - visible

            rgb = np.transpose(pygame.surfarray.array3d(surf), (1, 0, 2))
            vw.write(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
            w.writerow([i, f'{t:.6f}', f'{gx:.3f}', f'{gy:.3f}', visible])
    vw.release()
    pygame.quit()
    print(f'{mp4}: {n} frames @ {FPS} fps, out of frame {out_frames / FPS:.2f} s')
    return mp4, gt_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--clean', action='store_true')
    ap.add_argument('--out', default=os.path.join(ROOT, 'data', 'test_videos'))
    a = ap.parse_args()
    make(a.seed, a.clean, a.out)


if __name__ == '__main__':
    main()
