"""
FSOC-PAT deterministic test harness.

    venv\\Scripts\\python -m harness                      # baseline S01-S15, 5 seeds, 60 s
    venv\\Scripts\\python -m harness --quick              # 2 seeds, 30 s each
    venv\\Scripts\\python -m harness --scenarios S01,S08 --seeds 3
    venv\\Scripts\\python -m harness --scenarios all --dt 1/30 --workers 4

Writes logs/harness/<timestamp>/runs.csv, summary.csv and (unless
--no-frames) frames/<scenario>_s<seed>.csv, and prints a summary table.
"""
import argparse
import csv
import datetime
import math
import json
import subprocess
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BASELINE = [f'S{i:02d}' for i in range(1, 16)]

# (metric, direction) — direction says which way is worse, for worst-case.
METRICS = [
    ('acquisition_time_s', 'high'),
    ('correct_lock_pct', 'low'),
    ('in_fov_pct', 'low'),
    ('wrong_lock_events', 'high'),
    ('wrong_lock_s', 'high'),
    ('reacq_events', 'high'),
    ('reacq_mean_s', 'high'),
    ('reacq_max_s', 'high'),
    ('reacq_unrecovered', 'high'),
    ('event_recovery_s', 'high'),
    ('event_unrecovered', 'high'),
    ('pred_err_event_end_px', 'high'),
    ('target_loss_pct', 'high'),
    ('beacon_out_of_fov_pct', 'high'),
    ('pull_in_mean_s', 'high'),
    ('pull_in_max_s', 'high'),
    ('track_err_mean_px', 'high'),
    ('track_err_max_px', 'high'),
    ('track_err_rmse_px', 'high'),
    ('raw_sensor_err_mean_px', 'high'),
    ('raw_sensor_err_max_px', 'high'),
    ('boresight_err_mean_px', 'high'),
    ('boresight_err_max_px', 'high'),
    ('centroid_err_mean_px', 'high'),
    ('centroid_err_max_px', 'high'),
    ('centroid_err_rmse_px', 'high'),
    ('processing_fps', 'low'),
    ('pipeline_fps', 'low'),
    ('cam_flips_600', 'high'),
    ('spiral_frames', 'high'),
    ('gap_max_dist_px', 'high'),
]

RUN_FIELDS = (['scenario', 'desc', 'seed', 'dt', 'sim_duration_s']
              + [m for m, _ in METRICS] + ['frames', 'wall_s', 'trace_hash'])


def _worker(args):
    sc, seed, dt, duration, frames_csv = args
    from harness.runner import run_one
    return run_one(sc, seed, dt=dt, duration_s=duration, frames_csv=frames_csv)


def _subprocess_worker(args):
    """Same job in a fresh `python -m harness._one` process — used for
    --workers > 1 (multiprocessing spawn is unreliable under some Windows
    launchers/sandboxes)."""
    sc, seed, dt, duration, frames_csv = args
    job = json.dumps({'sc': sc, 'seed': seed, 'dt': dt, 'duration': duration,
                      'frames_csv': frames_csv})
    p = subprocess.run([sys.executable, '-m', 'harness._one', job], cwd=ROOT,
                       capture_output=True, text=True)
    for line in p.stdout.splitlines():
        if line.startswith('RESULT:'):
            return json.loads(line[len('RESULT:'):])
    raise RuntimeError(f"{sc['name']} seed {seed} failed:\n{p.stderr[-2000:]}")


def _fmt(v, nd=2):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return '-'
    if isinstance(v, float):
        return f'{v:.{nd}f}'
    return str(v)


def summarise(rows):
    """Per scenario: mean over seeds and worst case over seeds. None values
    (e.g. never acquired) are excluded from the mean and counted in
    `<metric>_n_none`; acquisition failures make the worst case 'None'."""
    by = {}
    for r in rows:
        by.setdefault(r['scenario'], []).append(r)
    out = []
    for name, rs in by.items():
        s = {'scenario': name, 'desc': rs[0]['desc'], 'seeds': len(rs)}
        for m, worse in METRICS:
            vals = [r[m] for r in rs if r[m] is not None]
            n_none = len(rs) - len(vals)
            s[f'{m}_mean'] = sum(vals) / len(vals) if vals else None
            if vals:
                s[f'{m}_worst'] = max(vals) if worse == 'high' else min(vals)
            else:
                s[f'{m}_worst'] = None
            s[f'{m}_n_none'] = n_none
        out.append(s)
    return out


def print_table(summary):
    cols = [
        ('Scen', lambda s: s['scenario'], 4),
        ('Acq s mean/worst', lambda s: f"{_fmt(s['acquisition_time_s_mean'])}/{_fmt(s['acquisition_time_s_worst'])}"
            + (f" ({s['acquisition_time_s_n_none']} none)" if s['acquisition_time_s_n_none'] else ''), 22),
        ('CorrLock%', lambda s: f"{_fmt(s['correct_lock_pct_mean'],1)}/{_fmt(s['correct_lock_pct_worst'],1)}", 11),
        ('WrongLk ev/s', lambda s: f"{_fmt(s['wrong_lock_events_mean'],1)}/{_fmt(s['wrong_lock_s_mean'],1)}", 12),
        ('Reacq n', lambda s: _fmt(s['reacq_events_mean'], 1), 7),
        ('Reacq s mean/max', lambda s: f"{_fmt(s['reacq_mean_s_mean'])}/{_fmt(s['reacq_max_s_worst'])}", 16),
        ('Unrec', lambda s: _fmt(s['reacq_unrecovered_mean'], 1), 5),
        ('EvRecov s mean/worst', lambda s: f"{_fmt(s['event_recovery_s_mean'])}/{_fmt(s['event_recovery_s_worst'])}"
            + (f" ({s['event_unrecovered_mean'] * s['seeds']:.0f} unrec)" if s['event_unrecovered_mean'] else ''), 22),
        ('Loss%', lambda s: f"{_fmt(s['target_loss_pct_mean'],1)}/{_fmt(s['target_loss_pct_worst'],1)}", 11),
        ('OutFOV%', lambda s: f"{_fmt(s['beacon_out_of_fov_pct_mean'],1)}/{_fmt(s['beacon_out_of_fov_pct_worst'],1)}", 11),
        ('TrkErr mean/max/rmse', lambda s: f"{_fmt(s['track_err_mean_px_mean'])}/{_fmt(s['track_err_max_px_worst'],1)}/{_fmt(s['track_err_rmse_px_mean'])}", 20),
        ('RawErr/GTBore mean', lambda s: f"{_fmt(s['raw_sensor_err_mean_px_mean'])}/{_fmt(s['boresight_err_mean_px_mean'])}", 18),
        ('Centroid mean/max/rmse', lambda s: f"{_fmt(s['centroid_err_mean_px_mean'])}/{_fmt(s['centroid_err_max_px_worst'],1)}/{_fmt(s['centroid_err_rmse_px_mean'])}", 22),
        ('PullIn s mean/max', lambda s: f"{_fmt(s['pull_in_mean_s_mean'])}/{_fmt(s['pull_in_max_s_worst'])}", 17),
        ('FPS loop/pipe', lambda s: f"{_fmt(s['processing_fps_mean'], 0)}/{_fmt(s['pipeline_fps_mean'], 0)}", 13),
        ('Flips600 mean/worst', lambda s: f"{_fmt(s['cam_flips_600_mean'],0)}/{_fmt(s['cam_flips_600_worst'])}", 19),
    ]
    head = ' | '.join(h.ljust(w) for h, _, w in cols)
    print(head)
    print('-' * len(head))
    for s in summary:
        print(' | '.join(str(f(s)).ljust(w) for _, f, w in cols))
    print('\nFormat: a/b = mean over seeds / worst seed (max for errors, times, '
          'loss; min for CorrLock%, FPS).\nTrkErr/Centroid: mean of means / '
          'worst max / mean of RMSEs. Errors are over correct_lock frames only;\n'
          'TrkErr excludes each lock pull-in (until <10 px, max 1.0 s), '
          'reported separately as PullIn.')


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m harness', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--scenarios', default='baseline',
                    help="comma list, 'baseline' (S01-S15) or 'all'")
    ap.add_argument('--seeds', type=int, default=5, help='number of seeds')
    ap.add_argument('--seed-start', type=int, default=1)
    ap.add_argument('--seed-list', default=None,
                    help='explicit comma list of seeds (overrides --seeds/--seed-start)')
    ap.add_argument('--duration', type=float, default=None,
                    help='override every scenario duration (s)')
    ap.add_argument('--quick', action='store_true', help='2 seeds, 30 s each')
    ap.add_argument('--dt', default='1/60', help='fixed time step, e.g. 1/60 or 1/30')
    ap.add_argument('--workers', type=int, default=1,
                    help='parallel worker processes (results are identical '
                         'for any value; processing_fps drops under contention)')
    ap.add_argument('--mode', default=None, choices=['hybrid', 'cv', 'ai'],
                    help='detector mode for every run (default: config)')
    ap.add_argument('--every-k', type=int, default=1,
                    help="real-time 'B' runs: detector processes only every "
                         'k-th frame, tracker predicts in between (default 1)')
    ap.add_argument('--no-frames', action='store_true',
                    help='skip per-frame CSVs')
    ap.add_argument('--out', default=os.path.join('logs', 'harness'))
    args = ap.parse_args(argv)

    os.chdir(ROOT)
    sys.path.insert(0, ROOT)
    from harness.scenarios import load_scenarios

    scen = load_scenarios()
    if args.scenarios == 'baseline':
        names = BASELINE
    elif args.scenarios == 'all':
        names = list(scen)
    else:
        names = [n.strip() for n in args.scenarios.split(',') if n.strip()]
    unknown = [n for n in names if n not in scen]
    if unknown:
        ap.error(f'unknown scenarios: {unknown}')

    n_seeds, duration = args.seeds, args.duration
    if args.quick:
        n_seeds, duration = 2, 30.0
    seeds = list(range(args.seed_start, args.seed_start + n_seeds))
    if args.seed_list:
        seeds = [int(x) for x in args.seed_list.split(',') if x.strip()]
    dt = float(Fraction(args.dt))

    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    # Detector mode (and k) in the folder name, so batches started in the
    # same second can never overwrite each other.
    from config.loader import cfg
    mode = args.mode or str((cfg.get('detection') or {}).get('mode', 'hybrid'))
    tag = mode + (f'_k{args.every_k}' if args.every_k > 1 else '')
    out_dir = os.path.join(args.out, f'{stamp}_{tag}')
    n = 1
    while os.path.exists(out_dir):
        n += 1
        out_dir = os.path.join(args.out, f'{stamp}_{tag}_{n}')
    os.makedirs(out_dir, exist_ok=True)

    jobs = []
    for n in names:
        for sd in seeds:
            fcsv = None if args.no_frames else os.path.join(out_dir, 'frames', f'{n}_s{sd}.csv')
            sc = dict(scen[n], detector_mode=args.mode) if args.mode else dict(scen[n])
            sc['_session_dir'] = os.path.join(out_dir, 'sessions', f'{n}_s{sd}')
            if args.every_k > 1:
                sc['process_every_k'] = args.every_k
            jobs.append((sc, sd, dt, duration, fcsv))

    print(f'[harness] {len(names)} scenarios x {len(seeds)} seeds = {len(jobs)} runs, '
          f'dt={args.dt}, duration={duration or "per-scenario"}s, workers={args.workers}')
    print(f'[harness] output: {out_dir}')

    t0 = time.perf_counter()
    rows = []
    if args.workers > 1:
        with ThreadPoolExecutor(args.workers) as pool:
            for r in pool.map(_subprocess_worker, jobs):
                rows.append(r)
                print(f"  {r['scenario']} seed {r['seed']}: done in {r['wall_s']:.1f}s "
                      f"(hash {r['trace_hash']})", flush=True)
    else:
        for j in jobs:
            r = _worker(j)
            rows.append(r)
            print(f"  {r['scenario']} seed {r['seed']}: done in {r['wall_s']:.1f}s "
                  f"(hash {r['trace_hash']})", flush=True)
    total = time.perf_counter() - t0

    with open(os.path.join(out_dir, 'runs.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=RUN_FIELDS, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow({k: ('' if r.get(k) is None else r.get(k)) for k in RUN_FIELDS})

    summary = summarise(rows)
    s_fields = list(summary[0].keys()) if summary else []
    with open(os.path.join(out_dir, 'summary.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=s_fields)
        w.writeheader()
        for s in summary:
            w.writerow({k: ('' if v is None else v) for k, v in s.items()})

    print(f'\n[harness] {len(rows)} runs in {total:.1f}s wall\n')
    print_table(summary)
    print(f'\n[harness] wrote {out_dir}\\runs.csv, summary.csv')
    return out_dir


if __name__ == '__main__':
    main()
