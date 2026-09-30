"""
PID Controller for virtual pan-tilt camera
============================================
Computes angular velocity commands to keep tracked target
centered in the camera frame.

Error signal:
  pixel error → angular error (via camera FOV and resolution)
  → PID → angular velocity command (deg/s) → camera.command()

Anti-windup: integral term is clamped to prevent accumulation
during target loss or saturation periods.

Gains loaded from config (control/pid_controller.py never hardcodes
these — see config/default.yaml's pid: block for current values).

Note on kd: the derivative term is divided by dt (~0.0167s at 60fps),
so its effective gain on frame-to-frame jitter is kd/dt. A kd that
looks small in isolation can still amplify normal pixel-level
detection noise into full output-clamp saturation that overrides the
correctly-signed proportional term — this caused a real bug where
LOCKED camera would drift 90-300px off the beacon instead of centering
it (kd=0.3 was ~18x per degree of jitter at this dt). Keep kd well
under ~0.05 unless dt or the noise floor changes.
"""


class PIDController:
    """
    Two-axis (pan, tilt) PID controller for camera pointing.

    Operates in ANGULAR ERROR space (degrees), not pixel space.
    Converts pixel error → angular error using camera geometry.

    Output: (delta_pan, delta_tilt) in degrees
    Apply as: camera.command(camera.pan + delta_pan,
                             camera.tilt + delta_tilt)
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.kp = float(cfg.pid.kp)     # 0.8
        self.ki = float(cfg.pid.ki)     # 0.01
        self.kd = float(cfg.pid.kd)     # 0.1

        # Camera geometry for pixel→angle conversion
        self.width  = cfg.window.width
        self.height = cfg.window.height
        self.fov    = cfg.camera.fov_degrees
        self.ppd    = self.width / self.fov   # pixels per degree

        # Integral accumulator
        self._integral_pan  = 0.0
        self._integral_tilt = 0.0

        # Previous error (for derivative)
        self._prev_err_pan  = 0.0
        self._prev_err_tilt = 0.0

        # Anti-windup clamp (degrees)
        self.integral_clamp = 5.0

        # Output clamp — max correction per frame in degrees
        self.output_clamp   = cfg.camera.slew_rate_deg_per_sec / 60.0

        # Reset flag
        self._initialized = False

    def reset(self):
        """Reset integrator and derivative history. Call on lock loss."""
        self._integral_pan  = 0.0
        self._integral_tilt = 0.0
        self._prev_err_pan  = 0.0
        self._prev_err_tilt = 0.0
        self._initialized   = False

    def _pixel_to_angle(self, pixel_error_x, pixel_error_y):
        """
        Convert pixel error to angular error in degrees.
        pixel_error_x: target_x - frame_center_x (positive = target right of center)
        pixel_error_y: target_y - frame_center_y (positive = target below center)

        Returns (err_pan, err_tilt) in degrees.
        Note: tilt sign is inverted (y increases downward in pixels,
              but tilt increases upward in world space).
        """
        err_pan  =  pixel_error_x / self.ppd
        err_tilt = -pixel_error_y / self.ppd   # invert y axis
        return err_pan, err_tilt

    def compute(self, tracked_pixel, dt,
                predicted_pixel=None):
        """
        Compute PID output.
        tracked_pixel: current (x,y) in screen coords
        predicted_pixel: feedforward target (x,y) — if None,
                         uses tracked_pixel
        """
        if tracked_pixel is None or dt < 1e-6:
            self.reset()
            return (0.0, 0.0)

        target = predicted_pixel if predicted_pixel else tracked_pixel
        cx = self.width  / 2.0
        cy = self.height / 2.0
        px_err_x = target[0] - cx
        px_err_y = target[1] - cy
        err_pan, err_tilt = self._pixel_to_angle(px_err_x, px_err_y)

        if not self._initialized:
            self._prev_err_pan  = err_pan
            self._prev_err_tilt = err_tilt
            self._initialized   = True

        p_pan  = self.kp * err_pan
        p_tilt = self.kp * err_tilt

        self._integral_pan  = max(-self.integral_clamp,
            min(self.integral_clamp,
                self._integral_pan + err_pan * dt))
        self._integral_tilt = max(-self.integral_clamp,
            min(self.integral_clamp,
                self._integral_tilt + err_tilt * dt))
        i_pan  = self.ki * self._integral_pan
        i_tilt = self.ki * self._integral_tilt

        d_pan  = self.kd*(err_pan  - self._prev_err_pan)  / dt
        d_tilt = self.kd*(err_tilt - self._prev_err_tilt) / dt
        self._prev_err_pan  = err_pan
        self._prev_err_tilt = err_tilt

        out_pan  = max(-self.output_clamp,
                       min(self.output_clamp, p_pan+i_pan+d_pan))
        out_tilt = max(-self.output_clamp,
                       min(self.output_clamp, p_tilt+i_tilt+d_tilt))
        return (out_pan, out_tilt)

    @property
    def integral_state(self):
        """Returns current integral accumulator (pan, tilt) for debugging."""
        return (self._integral_pan, self._integral_tilt)
