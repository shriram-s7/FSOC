"""
evaluation/metrics.py — FSOC-PAT Simulator (SIH 2025, PS 26169, ISRO)

Pure data-accumulation layer for performance evaluation. Collects
per-frame tracking metrics during a simulation or video-replay session
and reduces them to the summary statistics required by PS 26169
(acquisition time, tracking error, target-loss rate, re-acquisition
time, processing speed). Carries no dependency on pygame, DearPyGui,
OpenCV, or reportlab so it can be unit-tested and reused by both the
CSV logger and the PDF report generator.
"""
import time
import math
import numpy as np

from evaluation.gt_metrics import (FRAME_W, FRAME_H, frame_flags, pull_in,
                                   reacquisition_times, score_frames)


class MetricsAccumulator:
    """Accumulates per-frame metrics for a single session and computes
    summary statistics on demand."""

    def __init__(self, session_id: str, mode: str):
        """
        Args:
            session_id: unique session identifier, e.g.
                "SIM_20250917_105500" or "VID_myclip".
            mode: "simulation" or "video".
        """
        self.session_id = session_id
        self.mode = mode
        # Detector mode label ('Hybrid' / 'CV Only' / 'AI Only'), set by
        # the sim thread; shown in the PDF header.
        self.detector_mode = 'Hybrid'

        self.timestamps = []
        self.track_errors = []
        self.states = []
        self.fps_values = []
        self.confidence_scores = []
        self.gt_x = []
        self.gt_y = []
        self.tracker_x = []
        self.tracker_y = []
        self.stab_x = []
        self.stab_y = []
        self.sim_times = []
        self.disturbances = []
        self.evaluation_events = []
        self.pipeline_ms = []
        self.candidate_counts = []
        self.occluded = []
        self.detector_modes = []
        self.centroid_log_path = None

        self.summary = None
        self.report_path = None

        self._start_time = time.perf_counter()
        self.lost_count = 0

    def record_frame(self, state_dict: dict):
        """Append one frame's worth of data, read from the sim_thread
        shared state dict (or an equivalent dict of the same shape)."""
        raw_state = state_dict.get('track_state')
        if raw_state is None:
            state_str = 'SEARCHING'
        elif hasattr(raw_state, 'name'):
            state_str = raw_state.name
        else:
            state_str = str(raw_state)

        confidence = state_dict.get('confidence')
        if confidence is None:
            confidence = state_dict.get('rolling_conf', 0.0)

        tracker_x = state_dict.get('tracker_x')
        if tracker_x is None:
            tracker_x = state_dict.get('tracker_sx')

        tracker_y = state_dict.get('tracker_y')
        if tracker_y is None:
            tracker_y = state_dict.get('tracker_sy')

        gt_x = state_dict.get('gt_x')
        if gt_x is None:
            gt_x = state_dict.get('gt_sx')

        gt_y = state_dict.get('gt_y')
        if gt_y is None:
            gt_y = state_dict.get('gt_sy')

        self.timestamps.append(time.perf_counter() - self._start_time)
        self.track_errors.append(state_dict.get('track_error_px'))
        self.states.append(state_str)
        self.lost_count += state_str in ('LOST', 'COASTING')
        self.fps_values.append(state_dict.get('fps', 0.0))
        self.confidence_scores.append(confidence)
        self.gt_x.append(gt_x)
        self.gt_y.append(gt_y)
        self.tracker_x.append(tracker_x)
        self.tracker_y.append(tracker_y)
        self.stab_x.append(state_dict.get('tracker_stab_sx'))
        self.stab_y.append(state_dict.get('tracker_stab_sy'))
        self.sim_times.append(state_dict.get('sim_time'))
        self.pipeline_ms.append(state_dict.get('pipeline_ms'))
        d = state_dict.get('disturbances') or {}
        self.disturbances.append(tuple(sorted((k, repr(v)) for k, v in d.items())))
        self.evaluation_events.append(bool(state_dict.get('evaluation_event_active',False)))
        self.candidate_counts.append(state_dict.get('candidates', 0) or 0)
        self.occluded.append(bool(state_dict.get('occluded', False)))
        self.detector_modes.append(state_dict.get('detector_mode_active')
                                   or self.detector_mode)

    def _has_ground_truth(self) -> bool:
        return (any(g is not None for g in self.gt_x)
                and all(t is not None for t in self.sim_times))

    def _gt_scores(self) -> dict:
        """Simulation, or video with a ground-truth file: score with the
        harness's own functions (evaluation/gt_metrics.score_frames) on
        sim time (1/fps steps for video), so the live report and the
        harness always agree. Only explicit evaluation events can pause the
        recovery clock; changing a persistent environment setting must not
        erase recovery time for the rest of the session."""
        t0 = self.sim_times[0]
        frames = [{'t': st - t0, 'state': s,
                   'trk_sx': tx, 'trk_sy': ty, 'stab_sx': sx, 'stab_sy': sy,
                   'gt_sx': gx, 'gt_sy': gy, 'occluded': occ,
                   'event_active': event}
                  for st, s, tx, ty, sx, sy, gx, gy, occ, event in zip(
                      self.sim_times, self.states, self.tracker_x,
                      self.tracker_y, self.stab_x, self.stab_y, self.gt_x,
                      self.gt_y, self.occluded, self.evaluation_events)]
        return score_frames(frames)

    def compute_summary(self) -> dict:
        """Reduce the accumulated per-frame data to the summary dict
        required for the PS 26169 pass/fail certification."""
        total_frames = len(self.states)
        duration_sec = self.timestamps[-1] if self.timestamps else 0.0
        mean_fps = float(np.mean(self.fps_values)) if self.fps_values else 0.0
        locked_count = sum(1 for s in self.states if s == 'LOCKED')
        lock_rate_pct = (100.0 * locked_count / total_frames
                         if total_frames else 0.0)

        if self._has_ground_truth():
            m = self._gt_scores()
            # Video (PS Benchmark-2): the camera doesn't point, so the
            # tracking-error requirement is the centroid error vs GT.
            err = 'centroid_err' if self.mode == 'video' else 'track_err'
            summary = self._finish_summary(
                total_frames, duration_sec, mean_fps, lock_rate_pct,
                acquisition_time_s=m['acquisition_time_s'],
                # Never correctly locked -> the target was lost throughout.
                target_loss_pct=(m['target_loss_pct']
                                 if m['target_loss_pct'] is not None else 100.0),
                reacq_time_s=m['reacq_mean_s'], reacq_max_s=m['reacq_max_s'],
                reacq_events=m['reacq_events'],
                reacq_unrecovered=m['reacq_unrecovered'],
                pull_in_mean_s=m['pull_in_mean_s'],
                pull_in_max_s=m['pull_in_max_s'],
                mean_track_error_px=m[f'{err}_mean_px'],
                max_track_error_px=m[f'{err}_max_px'],
                rmse_px=m[f'{err}_rmse_px'],
                # No pointing in video mode: raw image error doesn't apply.
                raw_sensor_err_mean_px=(None if self.mode == 'video'
                                        else m['raw_sensor_err_mean_px']),
                raw_sensor_err_max_px=(None if self.mode == 'video'
                                       else m['raw_sensor_err_max_px']),
                centroid_rmse_px=m['centroid_err_rmse_px'])
            summary.update({
                'scored_with_gt': True,
                'centroid_err_mean_px': m['centroid_err_mean_px'],
                'centroid_err_max_px': m['centroid_err_max_px'],
                'correct_lock_pct': m['correct_lock_pct'],
                'correct_lock_visible_pct': m['correct_lock_visible_pct'],
                'lock_retention_pct': m['lock_retention_pct'],
                'wrong_lock_events': m['wrong_lock_events'],
                'beacon_out_of_fov_pct': m['beacon_out_of_fov_pct'],
            })
        else:
            summary = self._live_only_summary(total_frames, duration_sec,
                                              mean_fps, lock_rate_pct)
            summary['scored_with_gt'] = False
            if self.mode == 'video':
                self._mark_video_not_scored(summary)
        # Tracking-pipeline FPS (detect -> track -> servo), excluding frame
        # rendering / video decode.
        pipe = [p for p in self.pipeline_ms if p]
        summary['processing_fps'] = (1000.0 / float(np.mean(pipe))
                                     if pipe else None)
        summary['simulation_duration_sec'] = (self.sim_times[-1] - self.sim_times[0]
            if self.sim_times and all(t is not None for t in (self.sim_times[0], self.sim_times[-1])) else None)
        from evaluation.requirements import evaluate
        checked = evaluate(summary)
        for key, row in zip(('pass_acq_time','pass_track_error','pass_target_loss','pass_reacq_time','pass_fps'), checked['rows']):
            summary[key] = True if row['status']=='PASS' else False if row['status']=='FAIL' else None
        summary['overall_pass'] = True if checked['overall']=='PASS' else False if checked['overall']=='FAIL' else None
        summary['overall_status'] = checked['overall']
        return summary

    @staticmethod
    def _mark_video_not_scored(summary):
        """Video without ground truth: a fixed camera doesn't point, so the
        distance of the tracked position from the picture centre means
        nothing, and correct lock / loss / re-acquisition can't be judged.
        Keep only what was measured (acquisition, FPS, the tracker's own
        lock rate); everything else is N/A and the session is NOT SCORED."""
        for k in ('mean_track_error_px', 'max_track_error_px', 'rmse_px',
                  'raw_sensor_err_mean_px', 'raw_sensor_err_max_px',
                  'pull_in_mean_s', 'pull_in_max_s', 'centroid_rmse_px',
                  'target_loss_pct', 'reacq_time_s', 'reacq_max_s'):
            summary[k] = None
        summary['reacq_events'] = None
        summary['reacq_unrecovered'] = None
        for k in ('pass_track_error', 'pass_target_loss', 'pass_reacq_time'):
            summary[k] = None                       # N/A, not PASS
        summary['overall_pass'] = None
        summary['not_scored'] = True

    def _live_only_summary(self, total_frames, duration_sec, mean_fps,
                           lock_rate_pct) -> dict:
        """Video mode (ground truth may not exist): the original live-only
        metric definitions."""

        # Acquisition time = time from the first frame a candidate blob was
        # detected to the first LOCKED frame — not from frame 0 (session
        # start) to first LOCKED, which would include search/spin-up time.
        first_detection_t = None
        acquisition_time_s = None
        # Sim/video time when recorded (a headless replay runs faster or
        # slower than real time); wall clock otherwise.
        times = (self.sim_times if self.sim_times
                 and all(t is not None for t in self.sim_times)
                 else self.timestamps)
        for t, s, c in zip(times, self.states, self.candidate_counts):
            if first_detection_t is None and c > 0:
                first_detection_t = t
            if s == 'LOCKED':
                if first_detection_t is not None:
                    acquisition_time_s = t - first_detection_t
                break

        lost_count = sum(1 for s in self.states if s in ('LOST', 'COASTING'))
        target_loss_pct = (100.0 * lost_count / total_frames
                            if total_frames else 0.0)

        # Re-acquisition time — shared ground-truth definition (see
        # evaluation/gt_metrics.reacquisition_times): for each loss of a
        # correct lock, the clock starts only once the beacon is back in
        # FOV and not occluded, so time the beacon spends hidden is not
        # charged to re-acquisition. The live app has no scripted events.
        frames = [{'state': s, 'trk_sx': tx, 'trk_sy': ty,
                   'gt_sx': gx, 'gt_sy': gy}
                  for s, tx, ty, gx, gy in zip(self.states, self.tracker_x,
                                               self.tracker_y, self.gt_x,
                                               self.gt_y)]
        in_fov, correct, _ = frame_flags(frames)
        visible = [v and not o for v, o in zip(in_fov, self.occluded)]
        reacq_durations, reacq_unrecovered = reacquisition_times(
            times, correct, visible, [False] * len(correct))
        reacq_time_s = (float(np.mean(reacq_durations))
                         if reacq_durations else None)
        reacq_max_s = (float(np.max(reacq_durations))
                        if reacq_durations else None)

        # Tracking error — distance of the tracked position from frame
        # centre over LOCKED frames, excluding each lock's pull-in with the
        # same rule the harness uses (evaluation/gt_metrics.pull_in).
        # Stabilised coordinates when available; the raw (jittered) sensor
        # error is reported separately.
        locked = [s == 'LOCKED' for s in self.states]

        def centre(xs, ys):
            return [math.hypot(x - FRAME_W / 2.0, y - FRAME_H / 2.0)
                    if lk and x is not None and y is not None else None
                    for lk, x, y in zip(locked, xs, ys)]
        raw_err = centre(self.tracker_x, self.tracker_y)
        centre_err = centre(
            [s if s is not None else t for s, t in zip(self.stab_x, self.tracker_x)],
            [s if s is not None else t for s, t in zip(self.stab_y, self.tracker_y)])
        keep, pull_ins = pull_in(times, locked, centre_err)
        locked_errors = [e for e, k in zip(centre_err, keep) if k]
        raw_errors = [e for e, k in zip(raw_err, keep) if k and e is not None]
        pull_in_mean_s = float(np.mean(pull_ins)) if pull_ins else None
        pull_in_max_s = float(np.max(pull_ins)) if pull_ins else None
        if locked_errors:
            mean_track_error_px = float(np.mean(locked_errors))
            max_track_error_px = float(np.max(locked_errors))
            rmse_px = float(np.sqrt(np.mean(np.square(locked_errors))))
        else:
            mean_track_error_px = None
            max_track_error_px = None
            rmse_px = None

        centroid_dists = []
        for s, gx, gy, tx, ty in zip(self.states, self.gt_x, self.gt_y,
                                      self.tracker_x, self.tracker_y):
            if s == 'LOCKED' and gx is not None and gy is not None \
                    and tx is not None and ty is not None:
                centroid_dists.append((gx - tx) ** 2 + (gy - ty) ** 2)
        centroid_rmse_px = (float(np.sqrt(np.mean(centroid_dists)))
                             if centroid_dists else None)

        return self._finish_summary(
            total_frames, duration_sec, mean_fps, lock_rate_pct,
            acquisition_time_s=acquisition_time_s,
            target_loss_pct=target_loss_pct,
            reacq_time_s=reacq_time_s, reacq_max_s=reacq_max_s,
            reacq_events=len(reacq_durations),
            reacq_unrecovered=reacq_unrecovered,
            pull_in_mean_s=pull_in_mean_s, pull_in_max_s=pull_in_max_s,
            mean_track_error_px=mean_track_error_px,
            max_track_error_px=max_track_error_px, rmse_px=rmse_px,
            raw_sensor_err_mean_px=(float(np.mean(raw_errors))
                                    if raw_errors else None),
            raw_sensor_err_max_px=(float(np.max(raw_errors))
                                   if raw_errors else None),
            centroid_rmse_px=centroid_rmse_px)

    def _finish_summary(self, total_frames, duration_sec, mean_fps,
                        lock_rate_pct, *, acquisition_time_s,
                        target_loss_pct, reacq_time_s, reacq_max_s,
                        reacq_events, reacq_unrecovered, pull_in_mean_s,
                        pull_in_max_s, mean_track_error_px,
                        max_track_error_px, rmse_px, raw_sensor_err_mean_px,
                        raw_sensor_err_max_px, centroid_rmse_px) -> dict:
        """Apply the PS 26169 pass/fail thresholds and store the summary."""
        pass_acq_time = (acquisition_time_s is not None
                          and acquisition_time_s <= 2.0)
        pass_track_error = (mean_track_error_px is not None
                             and mean_track_error_px <= 10.0)
        pass_target_loss = target_loss_pct < 5.0
        pass_reacq_time = (reacq_time_s is None) or (reacq_time_s <= 1.0)
        pass_fps = mean_fps >= 20.0
        overall_pass = all([pass_acq_time, pass_track_error,
                             pass_target_loss, pass_reacq_time, pass_fps])

        self.summary = {
            'session_id': self.session_id,
            'mode': self.mode,
            'detector_mode': getattr(self, 'detector_mode', 'Hybrid'),
            'total_frames': total_frames,
            'duration_sec': duration_sec,
            'mean_fps': mean_fps,
            'acquisition_time_s': acquisition_time_s,
            'lock_rate_pct': lock_rate_pct,
            'target_loss_pct': target_loss_pct,
            'reacq_time_s': reacq_time_s,
            'reacq_max_s': reacq_max_s,
            'reacq_events': reacq_events,
            'reacq_unrecovered': reacq_unrecovered,
            'pull_in_mean_s': pull_in_mean_s,
            'pull_in_max_s': pull_in_max_s,
            'mean_track_error_px': mean_track_error_px,
            'max_track_error_px': max_track_error_px,
            'rmse_px': rmse_px,
            'raw_sensor_err_mean_px': raw_sensor_err_mean_px,
            'raw_sensor_err_max_px': raw_sensor_err_max_px,
            'centroid_rmse_px': centroid_rmse_px,
            'pass_acq_time': pass_acq_time,
            'pass_track_error': pass_track_error,
            'pass_target_loss': pass_target_loss,
            'pass_reacq_time': pass_reacq_time,
            'pass_fps': pass_fps,
            'overall_pass': overall_pass,
        }
        return self.summary

    def get_centroid_rows(self) -> list:
        """Rows for evaluation/centroid_log.write_centroid_log()."""
        return [{'frame': i,
                 'time_s': (self.sim_times[i] if self.sim_times[i] is not None
                            else self.timestamps[i]),
                 'state': self.states[i],
                 'x_est': self.tracker_x[i], 'y_est': self.tracker_y[i],
                 'confidence': self.confidence_scores[i],
                 'detector_mode': self.detector_modes[i],
                 'gt_x': self.gt_x[i], 'gt_y': self.gt_y[i]}
                for i in range(len(self.states))]

    def get_frame_data(self) -> list:
        """Return the per-frame data as a list of dicts, ready for
        CSV export."""
        rows = []
        for i in range(len(self.states)):
            rows.append({
                'frame': i,
                'timestamp_s': self.timestamps[i],
                'state': self.states[i],
                'track_error_px': self.track_errors[i],
                'fps': self.fps_values[i],
                'confidence': self.confidence_scores[i],
                'gt_x': self.gt_x[i],
                'gt_y': self.gt_y[i],
                'tracker_x': self.tracker_x[i],
                'tracker_y': self.tracker_y[i],
                'tracker_stab_x': self.stab_x[i],
                'tracker_stab_y': self.stab_y[i],
                'sim_time': self.sim_times[i],
                'occluded': self.occluded[i],
            })
        return rows
