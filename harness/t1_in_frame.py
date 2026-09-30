"""
Step-3 test T1 — "if the beacon is in frame, find it".

    venv\\Scripts\\python -m harness.t1_in_frame --trials 200 --workers 8

Each trial (3 s, seed = trial number): the beacon sits at a random point
inside the camera view, moving slowly (10 px/s); 3 round decoys are also
in view; Gaussian noise level is random in 0-0.5. The tracker starts
COASTING with a stale, WRONG prediction — a random point >= 150 px from
the beacon. Scored from ground truth (never fed to the tracker): did it
lock correctly within 1.0 s, time to correct lock, wrong-lock frames.
"""
import argparse
import json
import math
import os
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOL_PX = 25.0
DUR_S = 3.0
DT = 1.0 / 60.0


def run_trial(seed, sim_cls, harness_cfg):
    import numpy as np
    import pygame
    import torch
    from config.loader import cfg
    from tracking.temporal_fusion import TrackState

    harness_cfg(seed)
    rng = random.Random(1000 + seed)
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)
    noise = rng.uniform(0.0, 0.5)
    state = {'seed': seed, 'num_distractors': 3, 'disturbances': {
        'noise': noise, 'noise_gaussian': True, 'noise_saltpepper': False,
        'noise_poisson': False, 'atmosphere': 'clear', 'vibration': 0.0,
        'turbulence': 0.0, 'scintillation': 0.0, 'jerk': 0.0,
        'platform_enabled': False}}
    sim = sim_cls(state)
    sim._metrics = None
    pygame.init()
    sim.build_pipeline(seed)
    cam, tgt, trk = sim.camera, sim.target, sim.tracker

    # Beacon at a random screen point: move the camera so it lands there.
    bx, by = rng.uniform(60, 580), rng.uniform(60, 420)
    cam.cam_x = cam.cmd_x = tgt.wx - (bx - cam.cam_w / 2)
    cam.cam_y = cam.cmd_y = tgt.wy - (by - cam.cam_h / 2)
    cam.lat_buf.clear()
    cam.lat_buf.extend([(cam.cmd_x, cam.cmd_y)] * cam.lat_buf.maxlen)
    cam.update(0.0)                         # pan/tilt from cam_x/cam_y
    # 3 round decoys in view, >= 40 px from the beacon.
    for d in sim.distractors.positions:
        while True:
            dx, dy = rng.uniform(40, 600), rng.uniform(40, 440)
            if math.hypot(dx - bx, dy - by) >= 40:
                break
        d['wx'] = dx - cam.cam_w / 2 + cam.cam_x
        d['wy'] = dy - cam.cam_h / 2 + cam.cam_y
    # Stale, wrong prediction >= 150 px from the beacon.
    while True:
        px, py = rng.uniform(0, 640), rng.uniform(0, 480)
        if math.hypot(px - bx, py - by) >= 150:
            break
    trk.kalman.initialize(px, py)
    trk.fusion._state = TrackState.COASTING
    trk.fusion._had_recent_lock = True
    trk.fusion._coast_count = 0
    trk.fusion._buffer.extend([0.9] * trk.fusion._buffer.maxlen)
    trk._last_locked_pos = (px, py)
    trk._last_locked_vel = (0.0, 0.0)
    trk._last_known_pan, trk._last_known_tilt = cam.pixel_to_world(px, py)
    trk._prev_cam_pan, trk._prev_cam_tilt = cam.pan, cam.tilt

    t_lock, wrong, wrong_ev, prev_wrong, spiral = None, 0, 0, False, 0
    for i in range(int(round(DUR_S / DT))):
        sim.step(DT)
        st = state['track_state']
        st = getattr(st, 'name', str(st))
        gx, gy = cam.world_to_screen(tgt.wx, tgt.wy)
        tx, ty = state['tracker_sx'], state['tracker_sy']
        locked = st == 'LOCKED'
        ok = locked and tx is not None and math.hypot(tx - gx, ty - gy) <= TOL_PX
        if ok and t_lock is None:
            t_lock = (i + 1) * DT
        is_wrong = locked and not ok
        wrong += is_wrong
        wrong_ev += is_wrong and not prev_wrong
        prev_wrong = is_wrong
        spiral += (st in ('SEARCHING', 'LOST') and trk.search.is_active
                   and not trk.predictive_search_active)
    pygame.quit()
    return {'seed': seed, 'noise': round(noise, 3), 't_lock': t_lock,
            'wrong_frames': wrong, 'wrong_events': wrong_ev,
            'spiral_frames': spiral}


def run_chunk(seeds):
    import contextlib
    import copy
    import io
    os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
    os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
    os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
    import torch
    import cv2
    torch.set_num_threads(1)
    cv2.setNumThreads(1)
    from config.loader import cfg
    import ui.sim_thread as st_mod
    pristine = copy.deepcopy(dict(cfg))

    # Load the CNN once per process, not once per trial.
    cached = {}
    real_cls = st_mod.BeaconClassifier

    def cached_classifier():
        if 'c' not in cached:
            cached['c'] = real_cls()
        return cached['c']
    st_mod.BeaconClassifier = cached_classifier

    def harness_cfg(seed):
        cfg.clear()
        cfg.update(copy.deepcopy(pristine))
        cfg['motion']['type'] = 'straight'
        cfg['motion']['speed_px_s'] = 10.0
        cfg['target']['initial_position'] = 'center'
        cfg['distractors']['count'] = 3
        cfg['distractors']['speed_px_s'] = 8.0

    out = []
    with contextlib.redirect_stdout(io.StringIO()):
        for s in seeds:
            out.append(run_trial(s, st_mod.SimulationThread, harness_cfg))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--trials', type=int, default=200)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--chunk', default=None, help=argparse.SUPPRESS)
    ap.add_argument('--out', default=os.path.join(ROOT, 'logs', 'harness', 't1'))
    a = ap.parse_args()
    os.chdir(ROOT)
    sys.path.insert(0, ROOT)

    if a.chunk:                               # worker process
        seeds = [int(x) for x in a.chunk.split(',')]
        print('RESULT:' + json.dumps(run_chunk(seeds)), flush=True)
        return

    seeds = list(range(1, a.trials + 1))
    chunks = [seeds[i::a.workers] for i in range(a.workers)]

    def work(ch):
        p = subprocess.run([sys.executable, '-m', 'harness.t1_in_frame',
                            '--chunk', ','.join(map(str, ch))],
                           cwd=ROOT, capture_output=True, text=True)
        for line in p.stdout.splitlines():
            if line.startswith('RESULT:'):
                return json.loads(line[7:])
        raise RuntimeError(p.stderr[-2000:])

    t0 = time.perf_counter()
    with ThreadPoolExecutor(a.workers) as pool:
        rows = sorted((r for ch in pool.map(work, chunks) for r in ch),
                      key=lambda r: r['seed'])
    os.makedirs(a.out, exist_ok=True)
    stamp = time.strftime('%Y%m%d_%H%M%S')
    with open(os.path.join(a.out, f't1_{stamp}.json'), 'w') as f:
        json.dump(rows, f, indent=1)

    locked = [r['t_lock'] for r in rows if r['t_lock'] is not None]
    within = sum(1 for t in locked if t <= 1.0)
    wrong_trials = [r['seed'] for r in rows if r['wrong_frames']]
    print(f"T1: {within}/{len(rows)} locked correctly within 1.0 s; "
          f"{len(locked)}/{len(rows)} within {DUR_S:.0f} s")
    if locked:
        locked.sort()
        print(f"   time to lock: median {locked[len(locked)//2]:.2f} s, "
              f"worst {locked[-1]:.2f} s")
    print(f"   never locked: {[r['seed'] for r in rows if r['t_lock'] is None][:20]}")
    print(f"   wrong-lock trials: {len(wrong_trials)} {wrong_trials[:20]}  "
          f"(events {sum(r['wrong_events'] for r in rows)})")
    print(f"   spiral frames total: {sum(r['spiral_frames'] for r in rows)}")
    print(f"   wall {time.perf_counter() - t0:.0f} s -> {a.out}")


if __name__ == '__main__':
    main()
