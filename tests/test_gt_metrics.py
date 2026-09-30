"""Unit tests for evaluation/gt_metrics.py — hand-made frame logs with
known answers. Run:  venv\\Scripts\\python -m unittest tests.test_gt_metrics -v
"""
import math
import unittest

from evaluation import gt_metrics as gm
from evaluation.metrics import MetricsAccumulator

DT = 1.0 / 60.0
CENTER = (320.0, 240.0)


def make_log(n, locked=(), wrong=(), out_of_fov=(), occluded=(), events=(),
             trk_offset=(3.0, 4.0)):
    """n frames at 60 fps. Beacon sits at frame centre unless its frame
    index is in out_of_fov. Frames in `locked` are LOCKED with the tracker
    `trk_offset` px from the beacon; frames in `wrong` are LOCKED with the
    tracker 40 px away."""
    locked, wrong = set(locked), set(wrong)
    frames = []
    for i in range(n):
        gx, gy = CENTER
        if i in out_of_fov:
            gx = -50.0
        f = {'t': (i + 1) * DT, 'state': 'SEARCHING', 'trk_sx': None,
             'trk_sy': None, 'gt_sx': gx, 'gt_sy': gy,
             'occluded': i in occluded, 'event_active': i in events}
        if i in locked:
            f.update(state='LOCKED', trk_sx=gx + trk_offset[0],
                     trk_sy=gy + trk_offset[1])
        elif i in wrong:
            f.update(state='LOCKED', trk_sx=gx + 40.0, trk_sy=gy)
        frames.append(f)
    return frames


class TestFlags(unittest.TestCase):
    def test_tolerance_boundary(self):
        frames = make_log(2, locked=[0, 1])
        frames[0]['trk_sx'] = CENTER[0] + 25.0; frames[0]['trk_sy'] = CENTER[1]
        frames[1]['trk_sx'] = CENTER[0] + 25.1; frames[1]['trk_sy'] = CENTER[1]
        _, correct, wrong = gm.frame_flags(frames)
        self.assertEqual(correct, [True, False])
        self.assertEqual(wrong, [False, True])

    def test_scored_in_screen_space(self):
        # World fields are ignored; only screen tracker vs screen truth
        # (which already includes the image offset) decides correctness.
        frames = make_log(1, locked=[0], trk_offset=(0.0, 0.0))
        frames[0].update(trk_wx=1000.0, trk_wy=1000.0, gt_wx=1030.0, gt_wy=1000.0)
        _, correct, wrong = gm.frame_flags(frames)
        self.assertEqual((correct, wrong), ([True], [False]))

    def test_jittered_truth(self):
        # Image shifted by +20 px: tracker on the shifted beacon is correct,
        # tracker on the unshifted world_to_screen position (30 px off
        # after a further 10 px error) is wrong.
        frames = make_log(2, locked=[0, 1], trk_offset=(0.0, 0.0))
        for f in frames:
            f['gt_sx'] += 20.0
        frames[0]['trk_sx'] = frames[0]['gt_sx'] + 2.0
        frames[1]['trk_sx'] = frames[1]['gt_sx'] - 30.0
        _, correct, _ = gm.frame_flags(frames)
        self.assertEqual(correct, [True, False])

    def test_in_fov(self):
        frames = make_log(3)
        frames[1]['gt_sx'] = 640.0      # right edge is outside [0, 640)
        frames[2]['gt_sx'] = None
        in_fov, _, _ = gm.frame_flags(frames)
        self.assertEqual(in_fov, [True, False, False])


class TestAcquisition(unittest.TestCase):
    def test_known_acquisition(self):
        # In FOV from frame 0, first correct lock at frame 10 -> 10 frames.
        frames = make_log(50, locked=range(10, 50))
        s = gm.score_frames(frames)
        self.assertAlmostEqual(s['acquisition_time_s'], 10 * DT)

    def test_clock_starts_at_first_fov(self):
        frames = make_log(50, locked=range(30, 50), out_of_fov=range(0, 20))
        s = gm.score_frames(frames)
        self.assertAlmostEqual(s['acquisition_time_s'], 10 * DT)

    def test_never_acquired(self):
        s = gm.score_frames(make_log(20))
        self.assertIsNone(s['acquisition_time_s'])
        self.assertIsNone(s['target_loss_pct'])
        self.assertIsNone(s['track_err_mean_px'])


class TestReacquisition(unittest.TestCase):
    def test_occlusion_duration_excluded(self):
        # Locked 0-99, lost 100-159, beacon out of FOV 100-129, back in
        # FOV at 130, correct lock again at 160 -> 30 frames = 0.5 s,
        # not the 60-frame (1.0 s) span the old metric charged.
        frames = make_log(200, locked=list(range(0, 100)) + list(range(160, 200)),
                          out_of_fov=range(100, 130))
        s = gm.score_frames(frames)
        self.assertEqual(s['reacq_events'], 1)
        self.assertAlmostEqual(s['reacq_mean_s'], 0.5)
        self.assertAlmostEqual(s['reacq_max_s'], 0.5)
        self.assertEqual(s['reacq_unrecovered'], 0)

    def test_obstacle_occlusion_excluded(self):
        frames = make_log(200, locked=list(range(0, 100)) + list(range(145, 200)),
                          occluded=range(100, 130))
        s = gm.score_frames(frames)
        self.assertAlmostEqual(s['reacq_mean_s'], 15 * DT)

    def test_scripted_event_excluded(self):
        # Fog-style event 100-149 with the beacon still in FOV; relock at
        # 170 -> clock runs 150..170 = 20 frames.
        frames = make_log(200, locked=list(range(0, 100)) + list(range(170, 200)),
                          events=range(100, 150))
        s = gm.score_frames(frames)
        self.assertAlmostEqual(s['reacq_mean_s'], 20 * DT)

    def test_relock_during_event_scores_zero(self):
        frames = make_log(200, locked=list(range(0, 100)) + list(range(120, 200)),
                          events=range(100, 150))
        s = gm.score_frames(frames)
        self.assertEqual(s['reacq_events'], 1)
        self.assertEqual(s['reacq_mean_s'], 0.0)

    def test_mean_and_max_of_two_losses(self):
        # Loss A: 50-59 (10 frames). Loss B: 100-129 (30 frames).
        locked = [i for i in range(200) if not (50 <= i < 60 or 100 <= i < 130)]
        s = gm.score_frames(make_log(200, locked=locked))
        self.assertEqual(s['reacq_events'], 2)
        self.assertAlmostEqual(s['reacq_mean_s'], 20 * DT)
        self.assertAlmostEqual(s['reacq_max_s'], 30 * DT)

    def test_unrecovered(self):
        s = gm.score_frames(make_log(100, locked=range(0, 60)))
        self.assertEqual(s['reacq_events'], 0)
        self.assertIsNone(s['reacq_mean_s'])
        self.assertEqual(s['reacq_unrecovered'], 1)

    def test_wrong_lock_is_a_loss(self):
        # Correct 0-49, wrong lock 50-69, correct again from 70.
        frames = make_log(100, locked=list(range(0, 50)) + list(range(70, 100)),
                          wrong=range(50, 70))
        s = gm.score_frames(frames)
        self.assertAlmostEqual(s['reacq_mean_s'], 20 * DT)


class TestEventRecovery(unittest.TestCase):
    def test_out_of_view_is_charged(self):
        # Event 100-149, beacon out of view 150-179, relock at 190 ->
        # clock runs 150..190 = 40 frames (reacq would charge only 10).
        frames = make_log(200, locked=list(range(0, 100)) + list(range(190, 200)),
                          events=range(100, 150), out_of_fov=range(150, 180))
        s = gm.score_frames(frames)
        self.assertAlmostEqual(s['event_recovery_s'], 40 * DT)
        self.assertEqual(s['event_unrecovered'], 0)
        self.assertAlmostEqual(s['reacq_mean_s'], 10 * DT)

    def test_locked_at_event_end_is_zero(self):
        s = gm.score_frames(make_log(200, locked=range(200), events=range(100, 150)))
        self.assertEqual(s['event_recovery_s'], 0.0)

    def test_never_recovers(self):
        s = gm.score_frames(make_log(200, locked=range(0, 100), events=range(100, 150)))
        self.assertIsNone(s['event_recovery_s'])
        self.assertEqual(s['event_unrecovered'], 1)

    def test_no_event(self):
        s = gm.score_frames(make_log(100, locked=range(100)))
        self.assertIsNone(s['event_recovery_s'])
        self.assertEqual(s['event_unrecovered'], 0)
        self.assertIsNone(s['pred_err_event_end_px'])

    def test_worst_of_two_events(self):
        locked = [i for i in range(300) if not (50 <= i < 70 or 150 <= i < 200)]
        s = gm.score_frames(make_log(300, locked=locked,
                                     events=list(range(50, 60)) + list(range(150, 160))))
        self.assertAlmostEqual(s['event_recovery_s'], 40 * DT)

    def test_prediction_error_at_event_end(self):
        frames = make_log(100, locked=range(0, 40), events=range(40, 60))
        frames[59].update(pred_sx=CENTER[0] + 30.0, pred_sy=CENTER[1] + 40.0)
        s = gm.score_frames(frames)
        self.assertAlmostEqual(s['pred_err_event_end_px'], 50.0)


class TestWrongLockAndLoss(unittest.TestCase):
    def test_wrong_lock_events(self):
        frames = make_log(100, locked=range(0, 100))
        for i in list(range(20, 25)) + list(range(60, 70)):
            frames[i]['trk_sx'] = CENTER[0] + 40.0
        s = gm.score_frames(frames)
        self.assertEqual(s['wrong_lock_events'], 2)
        self.assertAlmostEqual(s['wrong_lock_s'], 15 * DT)

    def test_target_loss_pct(self):
        # First correct at 0; 100 frames after; 10 frames in FOV but not
        # locked; 20 frames out of FOV (unlocked) -> 10% loss, 20% out.
        locked = [i for i in range(100) if not (40 <= i < 70)]
        frames = make_log(100, locked=locked, out_of_fov=range(50, 70))
        s = gm.score_frames(frames)
        self.assertAlmostEqual(s['target_loss_pct'], 10.0)
        self.assertAlmostEqual(s['beacon_out_of_fov_pct'], 20.0)

    def test_target_loss_counts_from_first_acquisition(self):
        # 50 unlocked frames before first lock are not target loss.
        frames = make_log(150, locked=range(50, 150))
        self.assertAlmostEqual(gm.score_frames(frames)['target_loss_pct'], 0.0)


class TestErrors(unittest.TestCase):
    def test_track_and_centroid_error(self):
        # Beacon at centre, tracker offset (3,4) -> both errors exactly 5.
        s = gm.score_frames(make_log(10, locked=range(10)))
        for k in ('track_err_mean_px', 'track_err_max_px', 'track_err_rmse_px',
                  'centroid_err_mean_px', 'centroid_err_max_px',
                  'centroid_err_rmse_px'):
            self.assertAlmostEqual(s[k], 5.0, msg=k)

    def test_errors_only_over_correct_lock(self):
        frames = make_log(10, locked=range(5), wrong=range(5, 10))
        s = gm.score_frames(frames)
        self.assertAlmostEqual(s['centroid_err_max_px'], 5.0)

    def test_rmse(self):
        self.assertEqual(gm.error_stats([3.0, 4.0]),
                         (3.5, 4.0, math.sqrt(12.5)))

    def test_processing_fps(self):
        s = gm.score_frames(make_log(3), compute_s=[0.01, 0.02, 0.03])
        self.assertAlmostEqual(s['processing_fps'], 50.0)


class TestPullIn(unittest.TestCase):
    def test_pull_in_until_below_threshold(self):
        # Lock at frame 0 with centre error 30, 25, 20, 15, then 5 -> the
        # first 4 frames are pull-in (4 frames), the rest count.
        t = [(i + 1) * DT for i in range(10)]
        err = [30, 25, 20, 15] + [5] * 6
        keep, dur = gm.pull_in(t, [True] * 10, err)
        self.assertEqual(keep, [False] * 4 + [True] * 6)
        self.assertEqual(len(dur), 1)
        self.assertAlmostEqual(dur[0], 4 * DT)

    def test_pull_in_capped_at_one_second(self):
        # Error never falls below 10 px: only the first 1.0 s is excluded.
        t = [(i + 1) * DT for i in range(120)]
        keep, dur = gm.pull_in(t, [True] * 120, [50.0] * 120)
        self.assertEqual(keep.index(True), 60)
        self.assertAlmostEqual(dur[0], 1.0)

    def test_each_lock_start_gets_its_own_pull_in(self):
        t = [(i + 1) * DT for i in range(20)]
        locked = [True] * 8 + [False] * 4 + [True] * 8
        err = [20, 5, 5, 5, 5, 5, 5, 5, None, None, None, None,
               40, 30, 5, 5, 5, 5, 5, 5]
        keep, dur = gm.pull_in(t, locked, err)
        self.assertEqual([i for i, k in enumerate(keep) if k],
                         list(range(1, 8)) + list(range(14, 20)))
        self.assertEqual(len(dur), 2)
        self.assertAlmostEqual(dur[1], 2 * DT)

    def test_score_frames_excludes_pull_in_from_tracking_error_only(self):
        frames = make_log(20, locked=range(20), trk_offset=(0.0, 0.0))
        for f in frames[:3]:                     # beacon 30 px off-centre
            f['gt_sx'] = f['trk_sx'] = CENTER[0] + 30.0
        s = gm.score_frames(frames)
        self.assertAlmostEqual(s['track_err_max_px'], 0.0)
        self.assertAlmostEqual(s['pull_in_mean_s'], 3 * DT)
        self.assertEqual(s['centroid_err_mean_px'], 0.0)


class TestLiveReportUsesSharedDefinition(unittest.TestCase):
    def test_accumulator_pull_in(self):
        # Live PDF path: same pull-in rule as the harness.
        m = MetricsAccumulator('TEST', 'simulation')
        errs = [30, 20, 12, 3, 2, 3, 2, 3]
        for e in errs:
            m.record_frame({'track_state': 'LOCKED', 'tracker_x': CENTER[0] + e,
                            'tracker_y': CENTER[1], 'gt_x': CENTER[0] + e,
                            'gt_y': CENTER[1], 'fps': 60.0})
        m.timestamps = [(i + 1) * DT for i in range(len(errs))]
        s = m.compute_summary()
        self.assertAlmostEqual(s['max_track_error_px'], 3.0)
        self.assertAlmostEqual(s['pull_in_mean_s'], 3 * DT)

    def test_accumulator_reacq(self):
        # Same scenario as test_occlusion_duration_excluded, fed through
        # MetricsAccumulator (live PDF path) -> 0.5 s.
        m = MetricsAccumulator('TEST', 'simulation')
        frames = make_log(200, locked=list(range(0, 100)) + list(range(160, 200)),
                          out_of_fov=range(100, 130))
        for f in frames:
            m.record_frame({'track_state': f['state'], 'tracker_x': f['trk_sx'],
                            'tracker_y': f['trk_sy'], 'gt_x': f['gt_sx'],
                            'gt_y': f['gt_sy'], 'occluded': False,
                            'track_error_px': 0.0, 'fps': 60.0})
        m.timestamps = [f['t'] for f in frames]   # replace wall-clock stamps
        s = m.compute_summary()
        self.assertAlmostEqual(s['reacq_time_s'], 0.5)
        self.assertEqual(s['reacq_events'], 1)


if __name__ == '__main__':
    unittest.main()
