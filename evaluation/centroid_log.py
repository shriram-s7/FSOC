"""
evaluation/centroid_log.py - per-session centroid log.

Every session (live simulation, live/harness video, harness run) writes
<session>/centroid_log.csv: one row per frame with the tracker's sub-pixel
beacon estimate in NATIVE image coordinates (x_est, y_est; empty while the
tracker has no estimate), its confidence and the detector mode; when the
session has ground truth, also gt_x, gt_y and err_px = |estimate - GT|.
Scoring/reporting only - nothing here feeds back into tracking.
"""
import csv
import math
import os

FIELDS_GT = ['frame', 'time_s', 'state', 'x_est', 'y_est', 'confidence',
             'detector_mode', 'gt_x', 'gt_y', 'err_px']
FIELDS_NO_GT = FIELDS_GT[:7]


def _num(v, nd=3):
    return '' if v is None else round(float(v), nd)


def write_centroid_log(path, rows):
    """rows: dicts with frame, time_s, state, x_est, y_est, confidence,
    detector_mode and optionally gt_x, gt_y. GT columns are written only
    if any row has GT. Returns the path."""
    has_gt = any(r.get('gt_x') is not None for r in rows)
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(FIELDS_GT if has_gt else FIELDS_NO_GT)
        for r in rows:
            x, y = r.get('x_est'), r.get('y_est')
            row = [r['frame'], _num(r.get('time_s'), 6), r.get('state', ''),
                   _num(x), _num(y), _num(r.get('confidence'), 4),
                   r.get('detector_mode') or '']
            if has_gt:
                gx, gy = r.get('gt_x'), r.get('gt_y')
                err = (math.hypot(x - gx, y - gy)
                       if None not in (x, y, gx, gy) else None)
                row += [_num(gx), _num(gy), _num(err)]
            w.writerow(row)
    return path
