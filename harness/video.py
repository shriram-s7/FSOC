"""
Headless video-mode runner (PS Benchmark-2).

    venv\\Scripts\\python -m harness.video --video data/test_videos/test_seed1.mp4 --out logs/video/seed1

Plays a recorded video through the live app's own per-frame pipeline
(ui.sim_thread.SimulationThread.step) in video mode — fixed camera, no
servo, dt = 1/native fps — as fast as the CPU allows. Ground truth
(--gt only; never picked up implicitly) goes to the metrics layer only.

Writes to --out: frames.csv (frame, t, state, tracker x/y, gt x/y, error,
confidence, stabiliser shift), the session's summary.csv / frames CSV and
the PDF report.
"""
import argparse
import csv
import math
import os
import random
import sys
import time

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402
import pygame       # noqa: E402
import torch        # noqa: E402

from evaluation.logger import SessionLogger              # noqa: E402
from evaluation.report_generator import ReportGenerator  # noqa: E402
from input.video_source import VideoSource  # noqa: E402
from ui.sim_thread import SimulationThread               # noqa: E402


def run_video(video, gt=None, out_dir='logs/video', seed=1, mode=None,
              every_k=1):
    os.makedirs(out_dir, exist_ok=True)
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)

    state = {'seed': seed, 'num_distractors': 0, 'disturbances': {}}
    sim = SimulationThread(state)              # never start()ed
    pygame.init()
    if mode:
        from config.loader import cfg
        cfg.setdefault('detection', {})['mode'] = mode
    sim.build_pipeline(seed)
    sim.process_every_k = int(every_k)
    sim._logger = SessionLogger(output_dir=out_dir)
    sim._report_gen = ReportGenerator(output_dir=out_dir)

    src = VideoSource(video)
    if gt:
        src.load_ground_truth(gt)              # -> metrics layer only
    sim.set_video_mode(src)
    dt = 1.0 / src.get_fps()

    rows = []
    wall0 = time.perf_counter()
    while True:
        if sim.step(dt) == 'video_done':
            break
        st = sim.state
        s = st['track_state']
        tx, ty, gx, gy = st['tracker_x'], st['tracker_y'], st['gt_sx'], st['gt_sy']
        err = (math.hypot(tx - gx, ty - gy)
               if None not in (tx, ty, gx, gy) else None)
        stab = sim.tracker.stabiliser
        rows.append({
            'frame': len(rows), 't': round(st['sim_time'], 6),
            'state': getattr(s, 'name', str(s)),
            'tracker_x': tx, 'tracker_y': ty, 'gt_x': gx, 'gt_y': gy,
            'error_px': err, 'confidence': st.get('acquire_confidence'),
            'stab_jitter_x': stab.jitter[0], 'stab_jitter_y': stab.jitter[1],
            'stab_offset_x': stab.offset[0], 'stab_offset_y': stab.offset[1],
            'pipeline_ms': st.get('pipeline_ms'),
        })
    wall = time.perf_counter() - wall0
    src.release()

    with open(os.path.join(out_dir, 'frames.csv'), 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow({k: ('' if v is None else v) for k, v in r.items()})

    metrics = sim._metrics
    summary = metrics.compute_summary()
    sim._logger.export_csv(metrics)
    pdf = sim._report_gen.generate(metrics)
    pygame.quit()

    jx = np.array([r['stab_jitter_x'] for r in rows])
    jy = np.array([r['stab_jitter_y'] for r in rows])
    summary['stab_shift_mean_px'] = float(np.mean(np.hypot(jx, jy)))
    summary['stab_shift_max_px'] = float(np.max(np.hypot(jx, jy)))
    summary['wall_s'] = wall
    summary['pdf'] = pdf
    return summary, rows


def main():
    ap = argparse.ArgumentParser(prog='python -m harness.video')
    ap.add_argument('--video', required=True)
    ap.add_argument('--gt', default=None)
    ap.add_argument('--out', required=True)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--mode', default=None, choices=['hybrid', 'cv', 'ai'],
                    help='detector mode (default: config)')
    ap.add_argument('--every-k', type=int, default=1,
                    help='real-time runs: process only every k-th frame')
    a = ap.parse_args()
    s, _ = run_video(a.video, a.gt, a.out, a.seed, a.mode, a.every_k)
    for k in ('acquisition_time_s', 'correct_lock_pct', 'correct_lock_visible_pct',
              'lock_retention_pct', 'centroid_err_mean_px', 'centroid_rmse_px',
              'centroid_err_max_px', 'reacq_events', 'reacq_time_s', 'reacq_max_s',
              'reacq_unrecovered', 'wrong_lock_events', 'target_loss_pct',
              'beacon_out_of_fov_pct', 'processing_fps', 'stab_shift_mean_px',
              'stab_shift_max_px', 'overall_pass', 'wall_s', 'pdf'):
        print(f'{k}: {s.get(k)}')


if __name__ == '__main__':
    main()
