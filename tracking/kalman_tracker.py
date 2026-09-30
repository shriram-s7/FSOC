"""
Kalman Filter Tracker — Stage 5
=================================
Tracks beacon position and velocity in camera pixel space.

State vector: [x, y, vx, vy]
  x, y   : pixel position
  vx, vy : pixel velocity (pixels/frame)

Prediction: constant-velocity model
Update: incorporates detection measurement when available

Gated association: only accepts measurements within
Mahalanobis distance threshold of the predicted position.
This prevents the tracker from jumping to wrong candidates.

When no measurement available (coasting):
  Continues predicting without measurement update.
  Covariance grows — tracker becomes less certain.
"""

import numpy as np


class KalmanTracker:
    """
    4-state Kalman filter: position + velocity in 2D pixel space.

    Coordinate system: pixel (x, y) in camera frame
      (0,0) = top-left corner
      x increases rightward, y increases downward
    """

    def __init__(self, cfg):
        self.cfg = cfg
        q = float(cfg.tracking.kalman_process_noise)       # 0.1
        r = float(cfg.tracking.kalman_measurement_noise)   # 2.0

        # State transition matrix (constant velocity model)
        self.F = np.eye(4, dtype=np.float64)
        self.F[0, 2] = 1.0   # x += vx
        self.F[1, 3] = 1.0   # y += vy

        # Measurement matrix (we observe x, y only)
        self.H = np.zeros((2, 4), dtype=np.float64)
        self.H[0, 0] = 1.0
        self.H[1, 1] = 1.0

        # Process noise covariance
        self.Q = np.eye(4, dtype=np.float64) * q
        self.Q[2, 2] = q * 4   # velocity noise higher
        self.Q[3, 3] = q * 4

        # Measurement noise covariance
        self.R = np.eye(2, dtype=np.float64) * r

        # State and covariance — initialized on first detection
        self.x = None    # state vector (4,)
        self.P = None    # covariance matrix (4,4)

        # Gate threshold (Mahalanobis distance squared)
        self.gate_threshold = 25.0   # ~5 sigma, generous gate (acquisition)
        # Strict gate for an established track (LOCKED/COASTING): chi-square
        # 99% for 2 dof AND a hard cap on distance from the prediction, so a
        # locked track can never jump to a different object.
        self.strict_gate_threshold = 9.21
        self.strict_gate_max_px = 40.0

        # Max covariance before we declare tracker uncertain
        self.max_cov_trace = 5000.0

        # Stats
        self.coast_frames = 0
        self.total_updates = 0
        self.total_predictions = 0

    def initialize(self, x, y):
        """
        Initialize tracker at pixel position (x, y).
        Called when first lock is acquired.
        """
        self.x = np.array([x, y, 0.0, 0.0], dtype=np.float64)
        self.P = np.eye(4, dtype=np.float64) * 50.0
        self.P[2, 2] = 100.0   # high velocity uncertainty initially
        self.P[3, 3] = 100.0
        self.coast_frames = 0

    def predict(self):
        """
        Kalman predict step — advance state by one frame.
        Call every frame regardless of detection.
        Returns predicted (x, y) position.
        """
        if self.x is None:
            return None

        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        self.total_predictions += 1

        # Clamp velocity to prevent runaway
        self.x[2] = np.clip(self.x[2], -30, 30)
        self.x[3] = np.clip(self.x[3], -30, 30)

        return (float(self.x[0]), float(self.x[1]))

    def gate_check(self, meas_x, meas_y, strict=False, extra_px=0.0):
        """
        Check if measurement (meas_x, meas_y) passes the innovation gate.
        Uses Mahalanobis distance; strict=True (established track) uses the
        chi-square 9.21 gate plus a hard strict_gate_max_px distance cap.
        Returns True if measurement should be accepted.
        """
        if self.x is None:
            return True   # no prior state — accept anything

        innovation = np.array([meas_x - self.x[0],
                                meas_y - self.x[1]], dtype=np.float64)
        if strict and float(np.hypot(*innovation)) > self.strict_gate_max_px + extra_px:
            return False
        S = self.H @ self.P @ self.H.T + self.R + (extra_px ** 2) * np.eye(2)
        try:
            S_inv = np.linalg.inv(S)
        except np.linalg.LinAlgError:
            return True
        dist_sq = float(innovation.T @ S_inv @ innovation)
        limit = self.strict_gate_threshold if strict else self.gate_threshold
        return dist_sq <= limit

    def update(self, meas_x, meas_y):
        """
        Kalman update step — incorporate measurement.
        Only call when gate_check passes.
        Returns updated (x, y) position.
        """
        if self.x is None:
            self.initialize(meas_x, meas_y)
            return (meas_x, meas_y)

        z = np.array([meas_x, meas_y], dtype=np.float64)
        innovation = z - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R
        try:
            K = self.P @ self.H.T @ np.linalg.inv(S)
        except np.linalg.LinAlgError:
            return (float(self.x[0]), float(self.x[1]))

        self.x = self.x + K @ innovation
        self.P = (np.eye(4) - K @ self.H) @ self.P
        self.total_updates += 1
        self.coast_frames = 0

        return (float(self.x[0]), float(self.x[1]))

    def coast(self):
        """Call when no valid measurement available. Increments coast count."""
        self.coast_frames += 1

    def reset(self):
        """
        Clear all filter state. Call on a full track loss (LOST) so the
        next re-acquisition starts fresh from the new measurement instead
        of resuming from stale pre-loss state — carrying old state forward
        across a LOST/re-search gap (even with ego-motion compensation,
        which is only a rigid small-angle approximation) accumulates error
        over the many un-measured predict() calls during search, and the
        inflated covariance from that gap makes the gate dangerously loose.
        """
        self.x = None
        self.P = None
        self.coast_frames = 0

    def compensate_ego_motion(self, dx_px, dy_px):
        """
        Shift the tracked pixel position by (dx_px, dy_px) to account for
        camera pan/tilt motion since the last frame.

        The filter tracks position in camera-pixel space, but a
        world-fixed target's pixel position also shifts whenever the
        camera itself pans/tilts (e.g. from this tracker's own auto-follow
        commands). Without this compensation, the constant-velocity model
        and gate_check() treat that camera-induced pixel shift as an
        unexpected jump, reject the correct detection, and the tracker
        drifts away from the real target. Call once per frame with the
        camera's pixel-space displacement, before predict()/gate_check().
        """
        if self.x is None:
            return
        self.x[0] += dx_px
        self.x[1] += dy_px

    @property
    def position(self):
        """Current estimated position (x, y) or None."""
        if self.x is None:
            return None
        return (float(self.x[0]), float(self.x[1]))

    @property
    def velocity(self):
        """Current estimated velocity (vx, vy) or None."""
        if self.x is None:
            return None
        return (float(self.x[2]), float(self.x[3]))

    @property
    def uncertainty_radius(self):
        """Position uncertainty as pixel radius (1-sigma)."""
        if self.P is None:
            return 999.0
        return float(np.sqrt((self.P[0,0] + self.P[1,1]) / 2))

    @property
    def is_uncertain(self):
        """True if tracker has become too uncertain to trust."""
        if self.P is None:
            return True
        return np.trace(self.P) > self.max_cov_trace
