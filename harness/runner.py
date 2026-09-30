"""
Headless, deterministic single-run executor for the test harness.

Drives the live app's own per-frame pipeline — ui.sim_thread.
SimulationThread.build_pipeline() + step(dt) — with a fixed dt, every RNG
seeded, no window and no web server, as fast as the CPU allows. Ground
truth is read back from the shared-state dict after each step and used
only for scoring (evaluation/gt_metrics.py).
"""
import contextlib
import copy
import csv
import hashlib
import io
import math
import os
import random
import time

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

import numpy as np
import pygame
import torch
import cv2

from config.loader import cfg
from evaluation.gt_metrics import score_frames, sign_flips
from evaluation.centroid_log import write_centroid_log
from harness.scenarios import disturbances_dict
from ui.sim_thread import SimulationThread

# Snapshot of config/default.yaml before any scenario mutates the global cfg.
_PRISTINE_CFG = copy.deepcopy(dict(cfg))

FRAME_FIELDS = ['t', 'state', 'trk_sx', 'trk_sy', 'stab_sx', 'stab_sy', 'gt_sx', 'gt_sy',
                'gt_wx', 'gt_wy', 'img_dx', 'img_dy', 'cam_x', 'cam_y',
                'occluded', 'event_active', 'blackout', 'compute_ms',
                'jit_ex', 'jit_ey', 'stab_resp', 'stab_ms', 'jit_rx', 'jit_ry',
                'spiral', 'pred_sx', 'pred_sy']


def _configure_threads():
    # Fixed thread counts so results are identical whether runs execute
    # serially or in parallel worker processes.
    torch.set_num_threads(1)
    cv2.setNumThreads(1)


def _apply_cfg(sc):
    cfg.clear()
    cfg.update(copy.deepcopy(_PRISTINE_CFG))
    cfg['motion']['type'] = str(sc['motion']).lower().replace('-', '')
    cfg['motion']['speed_px_s'] = float(sc['speed_px_s'])
    cfg['target']['initial_position'] = str(sc['initial_position'])
    cfg['distractors']['count'] = int(sc['num_distractors'])
    cfg['motion']['circular_omega'] = float(sc.get('circular_omega', 0.3))
    if sc.get('num_stars') is not None:
        cfg['world']['num_stars'] = int(sc['num_stars'])
    if sc.get('detector_mode'):
        cfg.setdefault('detection', {})['mode'] = str(sc['detector_mode'])


def _seed_all(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def run_one(sc, seed, dt=1.0 / 60.0, duration_s=None, frames_csv=None):
    """Run scenario `sc` (resolved dict) with `seed`. Returns a dict of
    scored metrics plus run info. Optionally writes a per-frame CSV."""
    _configure_threads()
    duration_s = float(duration_s if duration_s is not None else sc['duration_s'])
    n_frames = int(round(duration_s / dt))

    _apply_cfg(sc)
    baseline_sc = dict(sc)
    current_sc = dict(sc)
    dist = disturbances_dict(current_sc)
    baseline_dist = dict(dist)

    state = {
        'seed': seed,
        'num_distractors': int(sc['num_distractors']),
        'disturbances': dist,
    }

    set_events = sorted((e for e in sc.get('events') or [] if 'set' in e),
                        key=lambda e: e['t'])
    blackouts = [(float(e['t']), float(e['t']) + float(e['blackout']))
                 for e in sc.get('events') or [] if 'blackout' in e]

    log = io.StringIO()
    frames, compute_s, pipeline_s = [], [], []
    hasher = hashlib.sha1()

    wall0 = time.perf_counter()
    with contextlib.redirect_stdout(log):
        sim = SimulationThread(state)          # never start()ed
        sim._metrics = None                    # harness scores separately
        # Same order as SimulationThread.run(): seed -> pygame.init -> build.
        _seed_all(seed)
        pygame.init()
        sim.build_pipeline(seed)
        sim.process_every_k = int(sc.get('process_every_k', 1))
        if sc.get('decoys_in_view'):
            # Decoys start in the camera view around the beacon (as the
            # live UI 'Decoys' toggle), not anywhere in the world.
            sim.distractors.place_near(sim.target.wx, sim.target.wy)

        next_ev = 0
        for i in range(n_frames):
            t_now = i * dt
            while next_ev < len(set_events) and set_events[next_ev]['t'] <= t_now + 1e-9:
                current_sc.update(set_events[next_ev]['set'])
                state['disturbances'] = disturbances_dict(current_sc)
                next_ev += 1
            blackout = any(a <= t_now + 1e-9 < b for a, b in blackouts)
            sim.detector_blackout = blackout
            event_active = blackout or state['disturbances'] != baseline_dist

            c0 = time.perf_counter()
            sim.step(dt)
            compute_s.append(time.perf_counter() - c0)
            pipeline_s.append(sim.last_pipeline_ms / 1000.0)

            st = state['track_state']
            st = getattr(st, 'name', str(st))
            tsx, tsy = state['tracker_sx'], state['tracker_sy']
            pred = sim.tracker.predicted_pixel
            cam_x, cam_y = state['cam_x'], state['cam_y']
            f = {
                't': sim.sim_time, 'state': st,
                'trk_sx': tsx, 'trk_sy': tsy,
                'stab_sx': state['tracker_stab_sx'],
                'stab_sy': state['tracker_stab_sy'],
                'gt_sx': state['gt_sx'], 'gt_sy': state['gt_sy'],
                'gt_wx': state['tgt_wx'], 'gt_wy': state['tgt_wy'],
                'img_dx': sim.disturbance.applied_offset[0],
                'img_dy': sim.disturbance.applied_offset[1],
                'cam_x': cam_x, 'cam_y': cam_y,
                'occluded': bool(state['occluded']),
                'event_active': bool(event_active),
                'blackout': bool(blackout),
                'compute_ms': compute_s[-1] * 1000.0,
                # Tracker's image-only jitter estimate (accumulated), logged
                # here purely to score it against img_dx/img_dy.
                # Spiral search actually driving the camera this frame.
                'spiral': bool(st in ('SEARCHING', 'LOST')
                               and sim.tracker.search.is_active
                               and not sim.tracker.predictive_search_active),
                'pred_sx': pred[0] if pred is not None else None,
                'pred_sy': pred[1] if pred is not None else None,
                'jit_ex': sim.tracker.stabiliser.offset[0],
                'jit_ey': sim.tracker.stabiliser.offset[1],
                'stab_resp': sim.tracker.stabiliser.response,
                'stab_ms': sim.tracker.stabiliser.last_ms,
                'jit_rx': sim.tracker.stabiliser.jitter[0],
                'jit_ry': sim.tracker.stabiliser.jitter[1],
            }
            f['_conf'] = state.get('rolling_conf')
            f['_mode'] = state.get('detector_mode_active')
            frames.append(f)
            hasher.update(repr((st, tsx, tsy, cam_x, cam_y,
                                state['tgt_wx'], state['tgt_wy'])).encode())
        pygame.quit()
    wall = time.perf_counter() - wall0

    metrics = score_frames(frames, compute_s=compute_s)
    # Tracking-pipeline FPS (detect -> servo only; excludes rendering and
    # disturbance synthesis, which a real camera does not pay for).
    metrics['pipeline_fps'] = 1.0 / float(np.mean(pipeline_s))
    metrics['spiral_frames'] = sum(1 for f in frames if f['spiral'])
    gap = [math.hypot(f['gt_wx'] - f['cam_x'], f['gt_wy'] - f['cam_y'])
           for f in frames if f['event_active']]
    metrics['gap_max_dist_px'] = max(gap) if gap else None
    # Camera shake: cam_x sign flips over the first 600 LOCKED frames.
    locked_cam_x = [f['cam_x'] for f in frames if f['state'] == 'LOCKED'][:600]
    metrics['cam_flips_600'] = (sign_flips(locked_cam_x)
                                if len(locked_cam_x) == 600 else None)
    metrics.update({
        'scenario': sc['name'], 'desc': sc.get('desc', ''), 'seed': seed,
        'dt': dt, 'sim_duration_s': n_frames * dt,
        'wall_s': wall, 'trace_hash': hasher.hexdigest()[:16],
    })

    if sc.get('_session_dir'):
        write_centroid_log(
            os.path.join(sc['_session_dir'], 'centroid_log.csv'),
            [{'frame': i, 'time_s': f['t'], 'state': f['state'],
              'x_est': f['trk_sx'], 'y_est': f['trk_sy'],
              'confidence': f['_conf'], 'detector_mode': f['_mode'],
              'gt_x': f['gt_sx'], 'gt_y': f['gt_sy']}
             for i, f in enumerate(frames)])
    if frames_csv:
        os.makedirs(os.path.dirname(frames_csv), exist_ok=True)
        with open(frames_csv, 'w', newline='') as fh:
            w = csv.DictWriter(fh, fieldnames=FRAME_FIELDS)
            w.writeheader()
            for f in frames:
                w.writerow({k: ('' if v is None else v) for k, v in f.items()
                            if not k.startswith('_')})
    return metrics
