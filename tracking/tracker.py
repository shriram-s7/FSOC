"""
Master Tracker — Stage 5
==========================
Combines Kalman filter, temporal fusion buffer, and search pattern
into a single unified tracking interface.

This is the main module that main.py uses.
Everything else in tracking/ is an implementation detail.

State machine:
  SEARCHING → (high confidence candidate found) → ACQUIRING
  ACQUIRING → (sustained confidence) → LOCKED
  LOCKED    → (confidence drops)     → COASTING
  COASTING  → (re-acquired)          → LOCKED
  COASTING  → (timeout)              → LOST
  LOST      → (auto)                 → SEARCHING

Output every frame:
  tracker.state          : TrackState enum
  tracker.tracked_pixel  : (x, y) pixel position or None
  tracker.search_target  : (pan, tilt) for camera during search or None
  tracker.uncertainty    : position uncertainty radius in pixels
"""

import copy
import time

import numpy as np
from tracking.kalman_tracker import KalmanTracker
from tracking.imm_tracker import IMMTracker
from tracking.temporal_fusion import TemporalFusionBuffer, TrackState
from tracking.search_pattern import SpiralSearch
from tracking.stabiliser import ImageStabiliser
from tracking.scene_estimator import SceneEstimator


class MasterTracker:
    """
    Unified tracker combining Kalman + temporal fusion + search.

    Call process() every frame with the classified candidate list.
    Read state and tracked_pixel for camera control.
    """

    def __init__(self, cfg):
        self.cfg    = cfg
        # prediction_model: 'imm' (CV + coordinated-turn IMM, default) or
        # 'cv' (the single constant-velocity Kalman).
        self.prediction_model = str(getattr(cfg.tracking, 'prediction_model',
                                            'imm')).lower()
        self.kalman = (IMMTracker(cfg) if self.prediction_model == 'imm'
                       else KalmanTracker(cfg))
        # imm: after LOCKED/COASTING -> LOST, a copy of the filter that
        # keeps predicting through predictive re-acquisition, so the camera
        # follows the predicted (possibly curved) path, not a straight line.
        self._gap = None
        self.fusion = TemporalFusionBuffer(cfg)
        self.search = SpiralSearch(cfg)
        self.stabiliser = ImageStabiliser()
        # Prompt 3: every adaptive behaviour (lock gates, coast budget,
        # brightness reference, stabiliser rain mode) comes from this
        # image-only estimate - never from disturbance/atmosphere settings.
        self.scene = SceneEstimator(cfg)

        self._last_known_pan  = 0.0
        self._last_known_tilt = 0.0
        self._tracked_pixel   = None
        self._stab_pixel      = None
        self._search_target   = None
        self._acquisition_start_time = None
        self._lock_start_time        = None
        self._prev_cam_pan  = None
        self._prev_cam_tilt = None
        self._frame_count   = 0

        # Performance metrics
        self.acquisition_time = None   # seconds to first lock
        self.reacquire_count  = 0

        # Predictive re-acquisition — on LOST, search around where the
        # beacon is predicted to be (last locked position + velocity)
        # before falling back to the full spiral search.
        self._last_locked_pos    = None   # (x,y) screen position
        self._last_locked_vel    = None   # (vx,vy) pixels/frame
        self._last_locked_time   = None   # frame count when locked
        self._predictive_search_active = False
        self._predictive_search_frames = 0
        self._predictive_target  = None   # (px,py) pixel prediction, for display
        self.MAX_PREDICTIVE_FRAMES = 120  # ~2s at 60fps — rate-coasting in
                                           # camera_servo stays valid far
                                           # longer than a stale position
                                           # extrapolation did

    def process(self, candidates, camera, dt, gray=None, raw=None):
        """
        Main entry point — call every frame.

        Args:
            candidates : List[Candidate] from classifier.classify()
                         sorted by confidence descending
            camera     : VirtualCamera instance (for coordinate conversion)
            dt         : frame delta time in seconds
            gray       : full-res CLEANED grey frame the detector saw
                         (median + Gaussian), for the scene estimator and
                         image stabilisation (None disables both)
            raw        : full-res raw grey frame the detector saw (scene
                         estimator noise / saturation), or None

        Returns:
            TrackState: current state
        """
        self._frame_count += 1

        # Scene estimate from the image (candidates masked) -> lock gates /
        # coasting budget, before this frame's fusion update consumes them.
        if gray is not None:
            blobs = [(c.x, c.y, c.radius) for c in candidates]
            if not blobs:
                # Detector returned nothing (blackout, fade) but the beacon
                # is still in the picture where the tracker last put it /
                # predicts it: mask that too, or the correlation locks onto
                # the beacon the camera is following and reads the
                # commanded pan as jitter (stabiliser drift in a gap).
                est = self._tracked_pixel or self._predictive_target
                if est is not None:
                    blobs = [(est[0], est[1], 4.0)]
            self.scene.update(raw, gray, blobs, dt)
            self.fusion.apply_params(self.scene.params())

        # --- Ego-motion compensation ---
        # The Kalman filter tracks position in camera-pixel space, but the
        # camera itself pans/tilts every frame (including from this
        # tracker's own auto-follow commands). Shift the filter's stored
        # position by the camera's own motion since last frame so a
        # world-fixed target's pixel-space prediction/gate stay valid.
        dx_px = dy_px = 0.0
        if self._prev_cam_pan is not None:
            delta_pan  = camera.pan  - self._prev_cam_pan
            delta_tilt = camera.tilt - self._prev_cam_tilt
            if delta_pan != 0.0 or delta_tilt != 0.0:
                dx_px = -delta_pan * camera.ppd
                dy_px =  delta_tilt * camera.ppd
                self.kalman.compensate_ego_motion(dx_px, dy_px)
                if self._gap is not None:
                    self._gap.compensate_ego_motion(dx_px, dy_px)
        self._prev_cam_pan  = camera.pan
        self._prev_cam_tilt = camera.tilt

        # --- Image stabilisation ---
        # Whole-image shift (star field phase correlation) minus the shift
        # the commanded camera move explains = platform jitter. Candidates
        # are moved into stabilised coordinates before gating/Kalman; the
        # tracked pixel handed to the servo is moved back to the sensor.
        # Camera motion during frames skipped by predict_only() is added,
        # so the stabiliser (which compares with the last PROCESSED frame)
        # does not read the camera's own move as jitter. 0 when k = 1.
        pdx, pdy = getattr(self, '_pending_ego', (0.0, 0.0))
        self._pending_ego = (0.0, 0.0)
        ox, oy = (self.stabiliser.update(
                      None, dx_px + pdx, dy_px + pdy,
                      prepared=self.scene.small, fill=self.scene.fill,
                      streak_mask=self.scene.streak_mask)
                  if gray is not None else (0.0, 0.0))
        self._last_offset = (ox, oy)      # held by predict_only()
        if ox != 0.0 or oy != 0.0:
            stab = []
            for c in candidates:
                c = copy.copy(c)
                c.x -= ox
                c.y -= oy
                stab.append(c)
            candidates = stab

        # --- Kalman predict (every frame) ---
        predicted_pos = self.kalman.predict()

        # --- Data association ---
        # An established track (LOCKED/COASTING with a Kalman state) only
        # sees candidates inside the strict gate of its prediction: they
        # alone may update the Kalman AND feed the lock logic. A different
        # object elsewhere in the frame can therefore neither pull the
        # track nor keep it alive — with nothing in the gate the track
        # coasts, and when coasting runs out it drops to LOST/SEARCHING and
        # must pass ACQUIRING again before it can lock on anything. The one
        # exception (below): while COASTING, a confident candidate outside
        # the gate starts a fresh ACQUIRING on it (never a direct lock).
        tracking = (self.fusion.state in (TrackState.LOCKED, TrackState.COASTING)
                    and self.kalman.x is not None)
        outside_best = None
        if tracking:
            ex = self.stabiliser.uncertainty if gray is not None else 0.0
            gated = [c for c in candidates
                     if self.kalman.gate_check(c.x, c.y, strict=True, extra_px=ex)]
            # COASTING: the prediction may be stale/wrong. If nothing
            # confident is inside the gate but a beacon-like candidate is
            # elsewhere in the frame, go and ACQUIRE it (full lock gates,
            # never straight to LOCKED) instead of coasting on the stale
            # prediction until the coast budget runs out.
            if self.fusion.state == TrackState.COASTING:
                gated_best = max((c.confidence for c in gated), default=0.0)
                others = [c for c in candidates if c not in gated]
                best = max(others, key=lambda c: c.confidence, default=None)
                if (gated_best < self.fusion.lock_threshold and best is not None
                        and best.confidence >= self.fusion.lock_threshold):
                    outside_best = best
            candidates = gated

        # Extract top two confidences for temporal fusion
        top_conf   = candidates[0].confidence if candidates else 0.0
        second_conf = candidates[1].confidence if len(candidates) > 1 else 0.0
        # World coordinates, not screen — the servo slews the camera hard
        # during ACQUIRING, which swings the candidate's SCREEN position by
        # tens of px per frame even for a real, smoothly-moving beacon.
        # fusion._position_stable() needs actual target drift, which is
        # only visible in world space.
        top_pos    = (camera.screen_to_world(candidates[0].x, candidates[0].y)
                      if candidates else None)
        top_bright = candidates[0].brightness if candidates else None
        has_det    = bool(candidates)

        # --- Scene brightness reference (image only) for the relative
        # brightness gate; only needed while a lock can be formed.
        if (gray is not None and
                self.fusion.state in (TrackState.SEARCHING, TrackState.ACQUIRING,
                                      TrackState.LOST)):
            # Foreground decoys must not raise the star reference above a
            # dim beacon: the estimator masks every detected blob.
            self.fusion.observe_scene(self.scene.star_level)

        # --- Temporal fusion update ---
        prev_state = self.fusion.state
        if outside_best is not None:
            # Switch to the out-of-gate candidate: fresh Kalman (it
            # initialises from this measurement below), fresh acquisition.
            self.kalman.reset()
            candidates = [outside_best]
            new_state = self.fusion.begin_acquire(
                outside_best.confidence,
                camera.screen_to_world(outside_best.x, outside_best.y),
                outside_best.brightness)
        else:
            new_state = self.fusion.update(top_conf, second_conf, has_det,
                                           top_position=top_pos,
                                           top_brightness=top_bright)

        # --- State transition side effects ---
        if prev_state != TrackState.LOCKED and new_state == TrackState.LOCKED:
            # Just locked — (re)initialise the filter on the confirmed
            # candidate unless its prediction already agrees with it: a
            # filter that coasted through ACQUIRING (measurements gated
            # out) must not report a stale position as the lock.
            if candidates and (self.kalman.x is None or
                               not self.kalman.gate_check(candidates[0].x, candidates[0].y)):
                self.kalman.reset()
                self.kalman.initialize(candidates[0].x, candidates[0].y)
            if self._lock_start_time is None:
                self._lock_start_time = time.time()
                if self._acquisition_start_time is not None:
                    self.acquisition_time = (self._lock_start_time -
                                             self._acquisition_start_time)
            self.search.stop()
            # Re-acquired — predictive search is no longer needed
            self._predictive_search_active = False
            self._gap = None

        # --- Predictive re-acquisition: activate on LOCKED/COASTING -> LOST ---
        if (prev_state in (TrackState.LOCKED, TrackState.COASTING) and
                new_state == TrackState.LOST and
                self._last_locked_pos is not None):
            self._predictive_search_active = True
            self._predictive_search_frames = 0
            if self.prediction_model == 'imm' and self.kalman.x is not None:
                self._gap = copy.deepcopy(self.kalman)
            print(f'[Tracker] Predictive search activated: pos='
                  f'{self._last_locked_pos}, vel={self._last_locked_vel}')

        if prev_state != TrackState.SEARCHING and new_state == TrackState.SEARCHING:
            # Just went to searching
            if prev_state == TrackState.LOST:
                self.reacquire_count += 1
                pan  = self._last_known_pan
                tilt = self._last_known_tilt
                # Full loss — clear stale Kalman state so re-acquisition
                # initializes fresh from the next real measurement instead
                # of resuming from drifted pre-loss extrapolation.
                self.kalman.reset()
            else:
                pan  = camera.pan
                tilt = camera.tilt
            self.search.start(pan, tilt)
            if self._acquisition_start_time is None:
                self._acquisition_start_time = time.time()

        # --- Measurement update for Kalman ---
        measured = None
        if new_state in (TrackState.LOCKED, TrackState.ACQUIRING):
            if candidates:
                best = candidates[0]
                if self.kalman.gate_check(best.x, best.y,
                                          extra_px=self.stabiliser.uncertainty if gray is not None else 0.0):
                    pos = self.kalman.update(best.x, best.y)
                    measured = (best.x, best.y)
                    self._tracked_pixel = pos
                    # Update last known world position
                    world = camera.pixel_to_world(pos[0], pos[1])
                    self._last_known_pan  = world[0]
                    self._last_known_tilt = world[1]
                else:
                    # Gated out — coast
                    self.kalman.coast()
                    self._tracked_pixel = predicted_pos
            else:
                self.kalman.coast()
                self._tracked_pixel = predicted_pos

        elif new_state == TrackState.COASTING:
            self.kalman.coast()
            self._tracked_pixel = predicted_pos

        else:
            # SEARCHING or LOST
            self._tracked_pixel = None

        # --- Save last-locked Kalman state for predictive re-acquisition ---
        if new_state == TrackState.LOCKED and self.kalman.x is not None:
            self._last_locked_pos  = self.kalman.position
            self._last_locked_vel  = self.kalman.velocity
            self._last_locked_time = self._frame_count

        # --- Search pattern advancement ---
        # Guarded against predictive search: search.advance() mutates the
        # spiral's internal waypoint index as a side effect, so calling it
        # here and then overriding _search_target below (predictive
        # re-acquisition) still silently walks the spiral forward every
        # frame — by the time predictive search expires and the spiral
        # should take over fresh, it has already advanced dozens of
        # waypoints from a stale center, driving the camera away from
        # the beacon instead of where it actually is.
        if (new_state in (TrackState.SEARCHING, TrackState.LOST) and
                not self._predictive_search_active):
            self._search_target = self.search.advance()
        else:
            self._search_target = None

        # --- Predictive re-acquisition override ---
        # Search around frame center (the camera itself is rate-coasting
        # to extrapolate the beacon's motion, see camera_servo.py) instead
        # of the spiral, until re-acquired or MAX_PREDICTIVE_FRAMES elapses
        # without a lock.
        if (self._predictive_search_active and
                new_state in (TrackState.SEARCHING, TrackState.LOST)):
            # The camera itself is now doing the extrapolating (see
            # camera_servo.py's rate-coasting), so the predictive search
            # target is simply frame center rather than a position
            # extrapolated from stale pre-loss velocity.
            px, py = 320, 240
            if self._gap is not None:
                # imm: the camera follows the filter's own prediction
                # (camera_servo.py); the target is that prediction.
                if self._predictive_search_frames > 0:
                    self._gap.predict()
                    self._gap.coast()
                px = self._gap.position[0] + ox
                py = self._gap.position[1] + oy

            self._predictive_target = (px, py)
            self._search_target = camera.pixel_to_world(px, py)
            self._predictive_search_frames += 1

            if self._predictive_search_frames > self.MAX_PREDICTIVE_FRAMES:
                self._predictive_search_active = False
                self._last_locked_pos = None
                self._predictive_target = None
                self._gap = None
                print('[Tracker] Predictive search expired, using spiral')
        else:
            self._predictive_target = None

        self._stab_pixel = self._tracked_pixel
        if self._tracked_pixel is not None:
            self._tracked_pixel = (self._tracked_pixel[0] + ox,
                                   self._tracked_pixel[1] + oy)
            # Weak star-field correlation: this frame's jitter offset may be
            # a wrong peak, so the SENSOR position is the measured centroid
            # itself (when one was accepted), not filter + doubtful offset.
            # The servo keeps steering on the filtered stabilised estimate.
            if (measured is not None and gray is not None
                    and self.stabiliser.uncertainty > 0.0):
                self._tracked_pixel = (measured[0] + ox, measured[1] + oy)
        self.last_measurement = None if measured is None else (float(measured[0]+ox),float(measured[1]+oy))
        self.last_measurement_score = float(best.confidence) if measured is not None else None
        self.display_prediction = None if self.kalman.x is None else (float(self.kalman.x[0]+self.kalman.x[2]+ox),float(self.kalman.x[1]+self.kalman.x[3]+oy))
        return new_state

    def predict_only(self, camera):
        """Real-time frame skipping (harness 'B' runs): a frame the detector
        had no time to process. No measurement and NO temporal-fusion
        update (a skipped frame is not a missed detection): camera
        ego-motion is compensated, the filter predicts one frame, the
        tracked position follows the prediction, and the search patterns
        keep running on time. The image-stabiliser offset is held."""
        self.last_measurement = None
        self.last_measurement_score = None
        self._frame_count += 1
        if self._prev_cam_pan is not None:
            delta_pan  = camera.pan  - self._prev_cam_pan
            delta_tilt = camera.tilt - self._prev_cam_tilt
            if delta_pan != 0.0 or delta_tilt != 0.0:
                dx_px = -delta_pan * camera.ppd
                dy_px =  delta_tilt * camera.ppd
                self.kalman.compensate_ego_motion(dx_px, dy_px)
                if self._gap is not None:
                    self._gap.compensate_ego_motion(dx_px, dy_px)
                pdx, pdy = getattr(self, '_pending_ego', (0.0, 0.0))
                self._pending_ego = (pdx + dx_px, pdy + dy_px)
        self._prev_cam_pan  = camera.pan
        self._prev_cam_tilt = camera.tilt
        ox, oy = getattr(self, '_last_offset', (0.0, 0.0))

        st = self.fusion.state
        pred = self.kalman.predict()
        if st in (TrackState.LOCKED, TrackState.COASTING, TrackState.ACQUIRING)                 and pred is not None:
            self.kalman.coast()
            self._stab_pixel = pred
            self._tracked_pixel = (pred[0] + ox, pred[1] + oy)
        elif st in (TrackState.SEARCHING, TrackState.LOST):
            self._stab_pixel = self._tracked_pixel = None
            if self._predictive_search_active:
                px, py = 320, 240
                if self._gap is not None:
                    self._gap.predict()
                    self._gap.coast()
                    px = self._gap.position[0] + ox
                    py = self._gap.position[1] + oy
                self._predictive_target = (px, py)
                self._search_target = camera.pixel_to_world(px, py)
                self._predictive_search_frames += 1
            else:
                self._search_target = self.search.advance()
        self.display_prediction = None if self.kalman.x is None else (float(self.kalman.x[0]+self.kalman.x[2]+ox),float(self.kalman.x[1]+self.kalman.x[3]+oy))
        return st

    @property
    def state(self):
        return self.fusion.state

    @property
    def state_name(self):
        return self.fusion.state.name

    @property
    def tracked_pixel(self):
        """Current tracked position in camera pixels, or None."""
        return self._tracked_pixel

    @property
    def stabilised_pixel(self):
        """Tracked position in stabilised coordinates (camera jitter
        estimate removed), or None. The image jitter does not move the
        camera's real pointing, so this is what the servo steers on."""
        return self._stab_pixel

    @property
    def predicted_pixel(self):
        """The tracker's current best guess of the beacon position, in
        STABILISED pixels (same coordinates the servo steers on; the image
        jitter estimate is not part of the prediction), or None: the
        tracked/predicted position while LOCKED, ACQUIRING or COASTING;
        during predictive re-acquisition after a loss, the frame centre
        (cv: the camera itself rate-coasts along the extrapolated motion)
        or the IMM gap prediction (imm). Scoring/display only."""
        if self._stab_pixel is not None:
            return self._stab_pixel
        if self._predictive_target is None:
            return None
        if self._gap is not None:
            return self._gap.position
        return self._predictive_target

    @property
    def follow_prediction(self):
        """imm only: (stabilised pixel, velocity px/frame) the camera
        should follow while the beacon is not measured — COASTING (the
        filter's prediction) or predictive re-acquisition (the gap
        filter's prediction). None otherwise, and always None for cv
        (camera_servo then rate-coasts as before)."""
        if self.prediction_model != 'imm':
            return None
        st = self.fusion.state
        if st == TrackState.COASTING and self.kalman.x is not None \
                and self._stab_pixel is not None:
            return self._stab_pixel, self.kalman.velocity
        if (st in (TrackState.SEARCHING, TrackState.LOST)
                and self._predictive_search_active and self._gap is not None):
            return self._gap.position, self._gap.velocity
        return None

    @property
    def search_target(self):
        """Camera target (pan, tilt) during search, or None."""
        return self._search_target

    @property
    def predictive_target(self):
        """Predicted beacon pixel position (px, py) during predictive
        re-acquisition search, or None if not active."""
        return self._predictive_target

    @property
    def predictive_search_active(self):
        """True while predictive re-acquisition is overriding the spiral
        search target after a LOCKED/COASTING -> LOST loss."""
        return self._predictive_search_active

    @property
    def uncertainty(self):
        """Position uncertainty radius in pixels."""
        return self.kalman.uncertainty_radius

    @property
    def lock_retention_rate(self):
        return self.fusion.lock_retention_rate

    @property
    def rolling_confidence(self):
        return self.fusion.rolling_mean
