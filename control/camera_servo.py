"""Camera servo with feedforward prediction."""
import math
from tracking.temporal_fusion import TrackState

class CameraServo:
    def __init__(self, cfg, camera, pid):
        self.cfg    = cfg
        self.camera = camera
        self.pid    = pid

        # Sustained commanded slew rate while LOCKED — this is the rate
        # that was cancelling the beacon's world motion (screen velocity
        # stays ~0 while well-tracked, so the *commanded* rate, not the
        # Kalman screen velocity, is what needs to be coasted through a
        # loss). Smoothed because the instantaneous per-frame delta is
        # noisy.
        self._last_pan_rate  = 0.0    # deg/frame
        self._last_tilt_rate = 0.0
        self._rate_smooth = 0.15

        # Smoothed feedforward velocity (raw per-frame Kalman velocity is
        # noisy enough to make the feedforward term shake the camera).
        self._ff_vx = 0.0
        self._ff_vy = 0.0
        self._ff_smooth = 0.2

        # LOCKED control law (no mode switching): every frame the camera
        # target advances by the beacon's velocity (smoothed Kalman
        # estimate) plus a proportional correction that fades to zero
        # within CORR_DEADZONE_PX of centre. The correction is applied to
        # the last COMMANDED target, not the current camera position, so
        # the commands still in flight through the camera's latency buffer
        # are not double-counted — with a 2-frame latency this loop is
        # stable for CORR_GAIN < ~0.6 and best damped near 0.15. (The old
        # PID-on-current-position + hold/active switching formed a 3-frame
        # limit cycle whenever the error never dropped below the hold
        # threshold.)
        self.CORR_GAIN = 0.15
        self.CORR_DEADZONE_PX = 2.0

    def _feedforward_predict(self, tracker, tracked):
        """Smoothed feedforward-predicted pixel target, or None."""
        if tracked is None or tracker.kalman.velocity is None:
            return None
        vx, vy = tracker.kalman.velocity
        self._ff_vx = ((1 - self._ff_smooth) * self._ff_vx
                        + self._ff_smooth * vx)
        self._ff_vy = ((1 - self._ff_smooth) * self._ff_vy
                        + self._ff_smooth * vy)
        lat = int(self.cfg.camera.latency_frames)
        ff_mult = float(getattr(self.cfg.camera, 'ff_mult',
                        getattr(self.cfg.pid, 'ff_mult', 1.3)))
        return (tracked[0] + self._ff_vx * lat * ff_mult,
                tracked[1] + self._ff_vy * lat * ff_mult)

    def update(self, tracker, dt):
        state = tracker.state

        # imm: while the beacon is unmeasured (COASTING / predictive
        # re-acquisition) the camera follows the filter's prediction with
        # the LOCKED control law, so it follows a curve instead of
        # rate-coasting in a straight line.
        follow = tracker.follow_prediction
        if state == TrackState.LOCKED or follow is not None:
            if follow is not None:
                tracked, vel = follow
            else:
                tracked = tracker.stabilised_pixel
                vel = tracker.kalman.velocity
            if tracked is None or vel is None:
                self.camera.command_delta_deg(self._last_pan_rate,
                                               self._last_tilt_rate)
                return

            # Velocity (feedforward) term, px/frame, lightly smoothed.
            self._ff_vx = ((1 - self._ff_smooth) * self._ff_vx
                            + self._ff_smooth * vel[0])
            self._ff_vy = ((1 - self._ff_smooth) * self._ff_vy
                            + self._ff_smooth * vel[1])

            # Proportional correction on max(0, |e| - deadzone) along e.
            ex = tracked[0] - self.cfg.window.width  / 2.0
            ey = tracked[1] - self.cfg.window.height / 2.0
            mag = math.hypot(ex, ey)
            fade = (max(0.0, mag - self.CORR_DEADZONE_PX) / mag
                    if mag > 1e-9 else 0.0)
            step_x = self._ff_vx + self.CORR_GAIN * ex * fade
            step_y = self._ff_vy + self.CORR_GAIN * ey * fade

            # Advance the last commanded target; bound how far it may lead
            # the camera (anti-windup when slew-limited).
            cam = self.camera
            lead = (cam.latency + 1) * max(
                cam.max_pan_speed * cam.ppd_h, cam.max_tilt_speed * cam.ppd_v) * dt
            tx = min(cam.cam_x + lead, max(cam.cam_x - lead, cam.cmd_x + step_x))
            ty = min(cam.cam_y + lead, max(cam.cam_y - lead, cam.cmd_y + step_y))
            cam.command_world(tx, ty)

            # Equivalent per-frame delta command relative to the current
            # camera position — the same quantity command_delta_deg takes —
            # smoothed for COASTING on loss (unchanged coasting logic).
            delta_pan  =  (cam.cmd_x - cam.cam_x) / cam.ppd_h
            delta_tilt = -(cam.cmd_y - cam.cam_y) / cam.ppd_v
            self._last_pan_rate = (
                (1 - self._rate_smooth) * self._last_pan_rate
                + self._rate_smooth * delta_pan)
            self._last_tilt_rate = (
                (1 - self._rate_smooth) * self._last_tilt_rate
                + self._rate_smooth * delta_tilt)

        elif state == TrackState.ACQUIRING:
            tracked = tracker.stabilised_pixel
            predicted = self._feedforward_predict(tracker, tracked)

            delta_pan, delta_tilt = self.pid.compute(
                tracked, dt, predicted_pixel=predicted)

            # Deadband — larger than LOCKED's, since ACQUIRING only needs
            # to settle (not precisely center) before the position-
            # stability gate can pass. Without this the servo bangs
            # against the slew clamp every frame chasing small error,
            # which swings the candidate's screen position and (pre-fix)
            # also broke the world-space stability gate below.
            if tracked is not None:
                cx = self.cfg.window.width  / 2.0
                cy = self.cfg.window.height / 2.0
                pan_error_px  = tracked[0] - cx
                tilt_error_px = tracked[1] - cy
                err_mag = math.hypot(pan_error_px, tilt_error_px)
                DEADBAND_PX = 8.0
                if err_mag < DEADBAND_PX:
                    delta_pan  = 0.0
                    delta_tilt = 0.0

            self.camera.command_delta_deg(delta_pan, delta_tilt)

        elif state == TrackState.COASTING or (
                state in (TrackState.SEARCHING, TrackState.LOST) and
                tracker._predictive_search_active):
            # Beacon lost from detection but the camera was already
            # slewing to cancel its world motion — keep applying that
            # rate instead of freezing or jumping to a spiral/extrapolated
            # waypoint, so the beacon doesn't drift out of frame.
            self.camera.command_delta_deg(self._last_pan_rate,
                                           self._last_tilt_rate)
            self._last_pan_rate  *= 0.995
            self._last_tilt_rate *= 0.995

        elif state in (TrackState.SEARCHING, TrackState.LOST):
            # Full fallback to spiral search — rate-coasting is no longer
            # valid, reset it so a long loss doesn't run away.
            self._last_pan_rate  = 0.0
            self._last_tilt_rate = 0.0

            # tracker.search only starts on a state *transition* into
            # SEARCHING/LOST, but the tracker begins life already in
            # SEARCHING — that edge never fires on startup, so kick the
            # spiral search off manually here if it isn't running yet.
            # Skip this while predictive re-acquisition is active so it
            # doesn't get overwritten by a spiral waypoint on the LOST
            # frame, before tracker.py's own transition handler has had
            # a chance to (re)start the spiral on its own.
            if not tracker.search.is_active and not tracker._predictive_search_active:
                tracker.search.start(tracker._last_known_pan, tracker._last_known_tilt)
                tracker._search_target = tracker.search.advance()

            if tracker.search_target is not None:
                # search_target is (pan_deg, tilt_deg) from center
                W = int(self.cfg.world.width)
                H = int(self.cfg.world.height)
                cx = W / 2 + tracker.search_target[0] * self.camera.ppd_h
                cy = H / 2 - tracker.search_target[1] * self.camera.ppd_v
                self.camera.command_world(cx, cy)
            self.pid.reset()
