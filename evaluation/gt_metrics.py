"""
evaluation/gt_metrics.py — FSOC-PAT Simulator (SIH 2025, PS 26169, ISRO)

Ground-truth scoring functions shared by the headless test harness
(harness/) and the live session report (evaluation/metrics.py). Ground
truth is used here ONLY for scoring — nothing in this module is ever fed
back to the tracker.

Input is a frame log: a list of dicts, one per frame, with keys
    t              time of the frame in seconds (sim time or wall clock)
    state          tracker state name ('LOCKED', 'SEARCHING', ...)
    trk_sx, trk_sy tracker estimate in screen px (None when not LOCKED),
                   at the raw (jittered) sensor position
    stab_sx, stab_sy optional — the same estimate in stabilised
                   coordinates (camera jitter estimate removed); tracking
                   error uses it when present, else trk_sx/trk_sy
    gt_wx, gt_wy,  optional (harness only) — beacon world position and
    cam_x, cam_y   camera world centre, for the ground-truth boresight
                   error
    gt_sx, gt_sy   true beacon position in screen px, i.e. where it is in
                   the image the detector saw (world_to_screen plus any
                   jitter/platform image offset); None if unknown
    occluded       optional bool — beacon hidden behind an obstacle
    event_active   optional bool — a scripted blackout/atmosphere event
                   is active on this frame
    pred_sx, pred_sy optional — the tracker's own predicted beacon
                   position in screen px (None when it has none)

Per-frame definitions:
    beacon_in_fov  true beacon inside the frame_w x frame_h image
    correct_lock   LOCKED and the tracker estimate is within tol_px of the
                   true beacon, in screen space
    wrong_lock     LOCKED but not correct_lock
"""
import math

import numpy as np

FRAME_W = 640
FRAME_H = 480
CORRECT_LOCK_TOL_PX = 25.0
PULL_IN_THRESH_PX = 10.0
PULL_IN_CAP_S = 1.0


def _dist(ax, ay, bx, by):
    if ax is None or ay is None or bx is None or by is None:
        return None
    return math.hypot(ax - bx, ay - by)


def frame_flags(frames, frame_w=FRAME_W, frame_h=FRAME_H,
                tol_px=CORRECT_LOCK_TOL_PX):
    """Return (in_fov, correct, wrong) — three lists of bools, one entry
    per frame."""
    in_fov, correct, wrong = [], [], []
    for f in frames:
        gx, gy = f.get('gt_sx'), f.get('gt_sy')
        fov = (gx is not None and gy is not None
               and 0 <= gx < frame_w and 0 <= gy < frame_h)
        locked = f.get('state') == 'LOCKED'
        d = _dist(f.get('trk_sx'), f.get('trk_sy'), gx, gy)
        ok = locked and d is not None and d <= tol_px
        in_fov.append(fov)
        correct.append(ok)
        wrong.append(locked and not ok)
    return in_fov, correct, wrong


def stretches(flags):
    """Maximal runs of True as (start, end_inclusive) index pairs."""
    runs, start = [], None
    for i, v in enumerate(flags):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(flags) - 1))
    return runs


def frame_period(times):
    """Median frame period (s) of a timestamp list; 0.0 if < 2 frames."""
    if len(times) < 2:
        return 0.0
    return float(np.median(np.diff(np.asarray(times, dtype=float))))


def acquisition_time(times, in_fov, correct):
    """Seconds from the first beacon_in_fov frame to the first
    correct_lock frame at or after it. None if either never happens."""
    first_fov = next((i for i, v in enumerate(in_fov) if v), None)
    if first_fov is None:
        return None
    first_ok = next((i for i in range(first_fov, len(correct)) if correct[i]),
                    None)
    if first_ok is None:
        return None
    return times[first_ok] - times[first_fov]


def wrong_lock_stats(times, wrong):
    """(number of separate wrong_lock stretches, total wrong_lock s).
    Duration of a stretch = its frame count x the median frame period."""
    runs = stretches(wrong)
    period = frame_period(times)
    total = sum((e - s + 1) * period for s, e in runs)
    return len(runs), total


def reacquisition_times(times, correct, visible, event_active):
    """Re-acquisition after each loss of correct_lock.

    For every correct_lock -> not-correct_lock transition, the clock
    starts at the first frame (from the loss frame on) where the beacon
    is visible (in FOV and not occluded) AND no scripted event is active,
    and stops at the next correct_lock frame. Time spent while the beacon
    cannot be seen, or during a scripted blackout/atmosphere event, is
    therefore not charged to re-acquisition.

    If lock returns before the clock could start (e.g. re-locked during
    the event itself), that loss scores 0.0 s.

    Returns (durations, unrecovered): durations is a list of seconds for
    losses that recovered; unrecovered counts losses where the clock
    started but correct_lock never returned before the log ended.
    """
    durations, unrecovered = [], 0
    n = len(correct)
    i = 1
    while i < n:
        if correct[i - 1] and not correct[i]:
            clock = None
            j = i
            while j < n and not correct[j]:
                if clock is None and visible[j] and not event_active[j]:
                    clock = times[j]
                j += 1
            if j < n:
                durations.append(0.0 if clock is None else times[j] - clock)
            elif clock is not None:
                unrecovered += 1
            i = j
        else:
            i += 1
    return durations, unrecovered


def event_recovery(times, correct, event_active):
    """Recovery after each scripted event (blackout / atmosphere change).

    For every maximal stretch of event_active frames, the clock starts at
    the first frame after the stretch and stops at the first correct_lock
    frame at or after it — regardless of whether the beacon is in view
    (unlike reacquisition_times, a camera left pointing the wrong way IS
    charged here). An event that runs to the end of the log is ignored.

    Returns (durations, unrecovered): seconds for each event that
    recovered, and the number of events after which correct_lock never
    returned before the log ended.
    """
    durations, unrecovered = [], 0
    n = len(correct)
    for _, e in stretches(event_active):
        start = e + 1
        if start >= n:
            continue
        ok = next((i for i in range(start, n) if correct[i]), None)
        if ok is None:
            unrecovered += 1
        else:
            durations.append(times[ok] - times[start])
    return durations, unrecovered


def prediction_error_at_event_end(frames):
    """Distance (px) between the tracker's predicted beacon position
    (optional pred_sx/pred_sy keys) and the true beacon (gt_sx/gt_sy) on
    the last frame of the last event stretch. None when there is no event,
    or the tracker had no prediction on that frame."""
    ev = [bool(f.get('event_active', False)) for f in frames]
    runs = stretches(ev)
    if not runs:
        return None
    f = frames[runs[-1][1]]
    return _dist(f.get('pred_sx'), f.get('pred_sy'), f.get('gt_sx'), f.get('gt_sy'))


def pull_in(times, locked, err, thresh_px=PULL_IN_THRESH_PX,
            cap_s=PULL_IN_CAP_S):
    """Pull-in rule shared by the harness and the live PDF.

    For each stretch of locked frames, the frames from the lock start
    until the tracking error (distance from frame centre) first falls
    below thresh_px are the pull-in; the pull-in is capped at cap_s —
    from cap_s after the lock start on, every frame counts.

    Returns (keep, durations): keep[i] is True for locked frames that
    count toward tracking-error statistics; durations lists the pull-in
    time (s) of every lock stretch (a stretch that ends before the
    pull-in completes contributes its whole length).
    """
    keep = [False] * len(locked)
    durations = []
    for s, e in stretches(locked):
        k = s
        while (k <= e and err[k] is not None and err[k] >= thresh_px
               and times[k] - times[s] < cap_s - 1e-9):
            k += 1
        end_t = times[k] if k <= e else times[e] + frame_period(times)
        durations.append(end_t - times[s])
        for i in range(k, e + 1):
            keep[i] = err[i] is not None
    return keep, durations


def sign_flips(values):
    """Number of sign changes in the frame-to-frame differences of a
    series (zero differences skipped) — the camera shake measure."""
    d = np.diff(np.asarray(values, dtype=float))
    s = np.sign(d[np.abs(d) > 1e-9])
    return int(np.sum(s[1:] != s[:-1])) if len(s) > 1 else 0


def error_stats(values):
    """(mean, max, rmse) of a list of distances, or (None, None, None)."""
    if not values:
        return None, None, None
    a = np.asarray(values, dtype=float)
    return float(a.mean()), float(a.max()), float(np.sqrt(np.mean(a * a)))


def score_frames(frames, compute_s=None, frame_w=FRAME_W, frame_h=FRAME_H,
                 tol_px=CORRECT_LOCK_TOL_PX):
    """Score a whole frame log. compute_s: optional list of measured
    per-frame compute times (s) for processing_fps."""
    times = [f['t'] for f in frames]
    in_fov, correct, wrong = frame_flags(frames, frame_w, frame_h, tol_px)
    visible = [v and not f.get('occluded', False)
               for v, f in zip(in_fov, frames)]
    events = [bool(f.get('event_active', False)) for f in frames]
    period = frame_period(times)

    acq = acquisition_time(times, in_fov, correct)
    wl_events, wl_seconds = wrong_lock_stats(times, wrong)
    reacq, unrecovered = reacquisition_times(times, correct, visible, events)
    ev_rec, ev_unrec = event_recovery(times, correct, events)

    # Target loss — from the first correct_lock frame onward, the share of
    # frames where the beacon is in FOV but not correctly locked.
    # Frames where the beacon has left the FOV are reported separately
    # (beacon_out_of_fov_pct) so a camera that loses the beacon out of
    # frame is still visible in the table.
    first_ok = next((i for i, v in enumerate(correct) if v), None)
    if first_ok is not None:
        after = range(first_ok, len(frames))
        n_after = len(after)
        loss = sum(1 for i in after if in_fov[i] and not correct[i])
        out = sum(1 for i in after if not in_fov[i])
        target_loss_pct = 100.0 * loss / n_after
        out_of_fov_pct = 100.0 * out / n_after
    else:
        target_loss_pct = None
        out_of_fov_pct = None

    # Tracking error (distance from frame centre) over correct_lock frames,
    # excluding each lock's pull-in (see pull_in()), in stabilised
    # coordinates — the real pointing error. raw_sensor_err is the same
    # at the jittered image position (includes camera jitter); boresight
    # is |beacon world - camera world centre| from ground truth, on the
    # same frames. Centroid error uses every correct_lock frame.
    cx, cy = frame_w / 2.0, frame_h / 2.0

    def _stab(f):
        if f.get('stab_sx') is not None and f.get('stab_sy') is not None:
            return f['stab_sx'], f['stab_sy']
        return f['trk_sx'], f['trk_sy']

    centre_err = [math.hypot(_stab(f)[0] - cx, _stab(f)[1] - cy) if ok else None
                  for f, ok in zip(frames, correct)]
    keep, pull_ins = pull_in(times, correct, centre_err)
    track_errs = [e for e, k in zip(centre_err, keep) if k]
    raw_errs = [math.hypot(f['trk_sx'] - cx, f['trk_sy'] - cy)
                for f, k in zip(frames, keep) if k]
    bore_errs = [math.hypot(f['gt_wx'] - f['cam_x'], f['gt_wy'] - f['cam_y'])
                 for f, k in zip(frames, keep)
                 if k and all(f.get(key) is not None
                              for key in ('gt_wx', 'gt_wy', 'cam_x', 'cam_y'))]
    centroid_errs = [math.hypot(f['trk_sx'] - f['gt_sx'], f['trk_sy'] - f['gt_sy'])
                     for f, ok in zip(frames, correct) if ok]
    te_mean, te_max, te_rmse = error_stats(track_errs)
    re_mean, re_max, re_rmse = error_stats(raw_errs)
    be_mean, be_max, be_rmse = error_stats(bore_errs)
    ce_mean, ce_max, ce_rmse = error_stats(centroid_errs)

    fps = None
    if compute_s:
        mean_c = float(np.mean(compute_s))
        fps = 1.0 / mean_c if mean_c > 0 else None

    n = len(frames)
    return {
        'frames': n,
        'duration_s': n * period,
        'in_fov_pct': 100.0 * sum(in_fov) / n if n else None,
        'correct_lock_pct': 100.0 * sum(correct) / n if n else None,
        # Share of frames with the beacon in the image that are correctly
        # locked — over the whole log, and from the first correct lock on
        # (lock retention).
        'correct_lock_visible_pct': (100.0 * sum(c for c, v in zip(correct, in_fov) if v)
                                     / sum(in_fov) if any(in_fov) else None),
        'lock_retention_pct': (
            100.0 * sum(1 for i in range(first_ok, n) if correct[i] and in_fov[i])
            / max(1, sum(1 for i in range(first_ok, n) if in_fov[i]))
            if first_ok is not None else None),
        'acquisition_time_s': acq,
        'wrong_lock_events': wl_events,
        'wrong_lock_s': wl_seconds,
        'reacq_events': len(reacq),
        'reacq_mean_s': float(np.mean(reacq)) if reacq else None,
        'reacq_max_s': float(np.max(reacq)) if reacq else None,
        'reacq_unrecovered': unrecovered,
        # Recovery after a scripted event: event end -> first correct lock
        # (worst event of the run; None if no event or none recovered).
        'event_recovery_s': float(np.max(ev_rec)) if ev_rec else None,
        'event_unrecovered': ev_unrec,
        'pred_err_event_end_px': prediction_error_at_event_end(frames),
        'target_loss_pct': target_loss_pct,
        'beacon_out_of_fov_pct': out_of_fov_pct,
        'pull_in_events': len(pull_ins),
        'pull_in_mean_s': float(np.mean(pull_ins)) if pull_ins else None,
        'pull_in_max_s': float(np.max(pull_ins)) if pull_ins else None,
        'track_err_mean_px': te_mean,
        'track_err_max_px': te_max,
        'track_err_rmse_px': te_rmse,
        'raw_sensor_err_mean_px': re_mean,
        'raw_sensor_err_max_px': re_max,
        'raw_sensor_err_rmse_px': re_rmse,
        'boresight_err_mean_px': be_mean,
        'boresight_err_max_px': be_max,
        'boresight_err_rmse_px': be_rmse,
        'centroid_err_mean_px': ce_mean,
        'centroid_err_max_px': ce_max,
        'centroid_err_rmse_px': ce_rmse,
        'processing_fps': fps,
    }
