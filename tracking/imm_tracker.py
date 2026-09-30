"""
IMM Tracker — Step 4
=====================
Interacting Multiple Model filter with two motion models, as a drop-in
replacement for KalmanTracker (same interface: initialize / predict /
gate_check / update / coast / reset / compensate_ego_motion, position,
velocity, uncertainty_radius, is_uncertain, x, P).

State vector (both models): [x, y, vx, vy, w, a]
  x, y   : pixel position (camera frame, ego-motion compensated)
  vx, vy : pixel velocity (pixels/frame)
  w      : turn rate (rad/frame)
  a      : along-track acceleration (px/frame^2) — speed change on a curve

Models:
  CV  constant velocity — the old KalmanTracker behaviour (same Q on
      x, y, vx, vy); w and a are carried along untouched.
  CT  coordinated turn — velocity vector rotates by w and its length
      changes by a every frame; w and a are estimated (random walks). Low process noise, so it wins the
      likelihood contest whenever the beacon really moves on a curve.

Each frame (standard IMM): mix the model states by the Markov switch
matrix and the model probabilities, predict each model, update each with
the measurement, re-weight the model probabilities by each model's
measurement likelihood, and output the probability-weighted combination
(x, P = combined mean / covariance incl. spread-of-means).

Coasting (no measurement): the models are predicted without mixing and
the model probabilities are held — with no new evidence, the belief about
which model fits stays where the last measurements left it (the Markov
prior would otherwise pull it back to 50/50 within ~1 s and flatten the
turn out of the prediction exactly when it matters).
"""

import numpy as np

N = 6   # [x, y, vx, vy, w, a]

_H = np.zeros((2, N), dtype=np.float64)
_H[0, 0] = 1.0
_H[1, 1] = 1.0


def _f_cv(s):
    return np.array([s[0] + s[2], s[1] + s[3], s[2], s[3], s[4], s[5]])


def _F_cv(s):
    F = np.eye(N)
    F[0, 2] = F[1, 3] = 1.0
    return F


def _f_ct(s):
    """Coordinated turn with along-track acceleration: the velocity
    vector turns by w and its length grows by a each frame; position
    advances by the mean of the old and new velocity."""
    x, y, vx, vy, w, a = s
    sp = np.hypot(vx, vy)
    cw, sw = np.cos(w), np.sin(w)
    nvx, nvy = cw * vx - sw * vy, sw * vx + cw * vy
    if sp > 1e-6:
        g = max(sp + a, 0.0) / sp
        nvx, nvy = nvx * g, nvy * g
    return np.array([x + 0.5 * (vx + nvx), y + 0.5 * (vy + nvy),
                     nvx, nvy, w, a])


def _F_ct(s):
    """Numeric Jacobian of _f_ct."""
    F = np.empty((N, N))
    for k in range(N):
        h = 1e-6 if k >= 4 else 1e-4
        d = np.zeros(N)
        d[k] = h
        F[:, k] = (_f_ct(s + d) - _f_ct(s - d)) / (2 * h)
    return F


class IMMTracker:
    """CV + CT interacting multiple model filter in 2D pixel space."""

    V_CLAMP = 30.0      # px/frame, as KalmanTracker
    W_CLAMP = 0.1       # rad/frame (~6 rad/s)
    A_CLAMP = 0.5       # px/frame^2 along-track

    def __init__(self, cfg):
        self.cfg = cfg
        q = float(cfg.tracking.kalman_process_noise)       # 0.1
        r = float(cfg.tracking.kalman_measurement_noise)   # 6.0

        # CV: exactly the KalmanTracker process noise on x, y, vx, vy.
        q_cv = np.diag([q, q, q * 4, q * 4, 1e-8, 1e-8])
        # CT: small noise — the turn does the work, so it only wins the
        # likelihood when the motion really is a smooth curve.
        # Turn-rate noise tuned offline on synthetic circle / figure-8 /
        # sine / line tracks (1 s gap). Along-track acceleration a is
        # frozen at 0 (zero noise and zero initial variance): in the loop
        # it drifted positive on straight motion and over-predicted speed.
        q_ct = np.diag([q * 0.1, q * 0.1, q * 0.05, q * 0.05, 1e-6, 0.0])
        self.models = [(_f_cv, _F_cv, q_cv), (_f_ct, _F_ct, q_ct)]
        self.R = np.eye(2) * r
        self.H = _H

        # Markov model-switch matrix (per frame): mean sojourn ~1.7 s.
        self.PI = np.array([[0.99, 0.01],
                            [0.01, 0.99]])
        self.mu0 = np.array([0.5, 0.5])

        self.xs = None      # per-model states
        self.Ps = None      # per-model covariances
        self.mu = None      # model probabilities
        self.x = None       # combined state (6,)
        self.P = None       # combined covariance (6,6)

        # Same gates / limits as KalmanTracker.
        self.gate_threshold = 25.0
        self.strict_gate_threshold = 9.21
        self.strict_gate_max_px = 40.0
        self.max_cov_trace = 5000.0

        self.coast_frames = 0
        self.total_updates = 0
        self.total_predictions = 0

    # --- lifecycle ---------------------------------------------------
    def initialize(self, x, y):
        s = np.array([x, y, 0.0, 0.0, 0.0, 0.0])
        P = np.diag([50.0, 50.0, 100.0, 100.0, 1e-4, 0.0])
        self.xs = [s.copy(), s.copy()]
        self.Ps = [P.copy(), P.copy()]
        self.mu = self.mu0.copy()
        self._combine()
        self.coast_frames = 0

    def reset(self):
        self.xs = self.Ps = self.mu = None
        self.x = self.P = None
        self.coast_frames = 0

    def _combine(self):
        x = sum(m * s for m, s in zip(self.mu, self.xs))
        P = np.zeros((N, N))
        for m, s, Pi in zip(self.mu, self.xs, self.Ps):
            d = s - x
            P += m * (Pi + np.outer(d, d))
        self.x, self.P = x, P

    def _clamp(self, s):
        s[2] = np.clip(s[2], -self.V_CLAMP, self.V_CLAMP)
        s[3] = np.clip(s[3], -self.V_CLAMP, self.V_CLAMP)
        s[4] = np.clip(s[4], -self.W_CLAMP, self.W_CLAMP)
        s[5] = np.clip(s[5], -self.A_CLAMP, self.A_CLAMP)

    # --- IMM cycle ---------------------------------------------------
    def predict(self):
        """Advance one frame. Mixes the models (interaction) only when the
        previous frame had a measurement; while coasting the models run
        independently and the model probabilities are held."""
        if self.x is None:
            return None
        if self.coast_frames == 0:
            c = self.PI.T @ self.mu                       # predicted mode probs
            w = (self.PI * self.mu[:, None]) / c[None, :]  # w[i, j] = P(i | j)
            mixed_x, mixed_P = [], []
            for j in range(2):
                xj = sum(w[i, j] * self.xs[i] for i in range(2))
                Pj = np.zeros((N, N))
                for i in range(2):
                    d = self.xs[i] - xj
                    Pj += w[i, j] * (self.Ps[i] + np.outer(d, d))
                mixed_x.append(xj)
                mixed_P.append(Pj)
            self.mu = c
        else:
            mixed_x, mixed_P = self.xs, self.Ps
        xs, Ps = [], []
        for (f, Fj, Q), s, P in zip(self.models, mixed_x, mixed_P):
            F = Fj(s)
            s2 = f(s)
            self._clamp(s2)
            xs.append(s2)
            Ps.append(F @ P @ F.T + Q)
        self.xs, self.Ps = xs, Ps
        self._combine()
        self.total_predictions += 1
        return (float(self.x[0]), float(self.x[1]))

    def gate_check(self, meas_x, meas_y, strict=False, extra_px=0.0):
        """Mahalanobis gate against the COMBINED prediction and covariance;
        strict=True adds the 9.21 chi-square limit and the 40 px cap.
        extra_px: additional measurement uncertainty (the image
        stabiliser's own, when its correlation was weak) - widens both."""
        if self.x is None:
            return True
        innovation = np.array([meas_x - self.x[0], meas_y - self.x[1]])
        if strict and float(np.hypot(*innovation)) > self.strict_gate_max_px + extra_px:
            return False
        S = self.H @ self.P @ self.H.T + self.R + (extra_px ** 2) * np.eye(2)
        try:
            S_inv = np.linalg.inv(S)
        except np.linalg.LinAlgError:
            return True
        dist_sq = float(innovation @ S_inv @ innovation)
        limit = self.strict_gate_threshold if strict else self.gate_threshold
        return dist_sq <= limit

    def update(self, meas_x, meas_y):
        if self.x is None:
            self.initialize(meas_x, meas_y)
            return (meas_x, meas_y)
        z = np.array([meas_x, meas_y])
        lik = np.zeros(2)
        xs, Ps = [], []
        for j, (s, P) in enumerate(zip(self.xs, self.Ps)):
            nu = z - self.H @ s
            S = self.H @ P @ self.H.T + self.R
            try:
                S_inv = np.linalg.inv(S)
            except np.linalg.LinAlgError:
                return (float(self.x[0]), float(self.x[1]))
            K = P @ self.H.T @ S_inv
            xs.append(s + K @ nu)
            Ps.append((np.eye(N) - K @ self.H) @ P)
            lik[j] = (np.exp(-0.5 * float(nu @ S_inv @ nu))
                      / (2 * np.pi * np.sqrt(max(np.linalg.det(S), 1e-12))))
        mu = self.mu * lik
        tot = mu.sum()
        # All likelihoods underflowed (huge innovation) — keep the old mix.
        self.mu = mu / tot if tot > 1e-300 else self.mu
        self.mu = np.clip(self.mu, 1e-4, None)
        self.mu /= self.mu.sum()
        self.xs, self.Ps = xs, Ps
        self._combine()
        self.total_updates += 1
        self.coast_frames = 0
        return (float(self.x[0]), float(self.x[1]))

    def coast(self):
        self.coast_frames += 1

    def compensate_ego_motion(self, dx_px, dy_px):
        """Shift every model's position by the camera's own pixel motion
        (see KalmanTracker.compensate_ego_motion). A pure translation, so
        velocities and the turn rate are unchanged."""
        if self.x is None:
            return
        for s in self.xs:
            s[0] += dx_px
            s[1] += dy_px
        self.x[0] += dx_px
        self.x[1] += dy_px

    # --- read-outs ---------------------------------------------------
    @property
    def position(self):
        if self.x is None:
            return None
        return (float(self.x[0]), float(self.x[1]))

    @property
    def velocity(self):
        if self.x is None:
            return None
        return (float(self.x[2]), float(self.x[3]))

    @property
    def turn_rate(self):
        """Combined turn-rate estimate (rad/frame) or None."""
        return None if self.x is None else float(self.x[4])

    @property
    def model_probs(self):
        """(P(CV), P(CT)) or None."""
        return None if self.mu is None else (float(self.mu[0]), float(self.mu[1]))

    @property
    def uncertainty_radius(self):
        if self.P is None:
            return 999.0
        return float(np.sqrt((self.P[0, 0] + self.P[1, 1]) / 2))

    @property
    def is_uncertain(self):
        if self.P is None:
            return True
        return np.trace(self.P[:4, :4]) > self.max_cov_trace
