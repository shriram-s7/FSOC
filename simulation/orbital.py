"""
Clohessy-Wiltshire (CW) orbital model for relative satellite motion.

Models the motion of Satellite B (target) relative to Satellite A
(observer/camera) in Hill's frame (Local Vertical Local Horizontal).

CW equations (linearized relative orbital mechanics):
  x_ddot - 2n*y_dot - 3n²x = 0   (radial)
  y_ddot + 2n*x_dot = 0           (along-track)
  z_ddot + n²z = 0                (cross-track)

Where n = sqrt(mu/a³) is the mean motion (orbital angular rate).

Reference: Clohessy & Wiltshire, 1960, Journal of the Aerospace Sciences.
"""
import numpy as np
import math

class CWOrbitalModel:
    """
    Computes relative position of target satellite in Hill's frame
    and converts to azimuth/elevation as seen from the observer camera.

    Hill's frame axes (centered on observer satellite A):
      x: radial (outward from Earth center)
      y: along-track (direction of motion)
      z: cross-track (orbit normal)
    """

    def __init__(self, cfg):
        self.cfg = cfg

        # Orbital parameters
        self.mu = 3.986e14          # Earth gravitational parameter (m³/s²)
        self.a = 6.771e6            # Orbital radius ~400km LEO (m)
        self.n_physical = math.sqrt(self.mu / self.a**3)  # True mean motion (rad/s)

        # Real LEO relative-motion periods are ~90 minutes — far too slow to
        # be visible in a short interactive session. Speed up the simulated
        # orbital phase so a full relative-motion cycle takes ~55s on screen.
        self.time_scale = 100.0
        self.n = self.n_physical * self.time_scale

        # Initial relative state in Hill's frame (meters)
        # These create a realistic along-track + cross-track relative motion.
        # x0 must be nonzero — with yd0 = -2*n*x0 this yields the classic
        # bounded 2:1 CW relative ellipse (x,y periodic, no secular drift).
        self.x0 = 60.0       # radial offset amplitude driver
        self.y0 = 500.0      # along-track offset (500m ahead) — used as range reference
        self.z0 = 45.0       # cross-track offset
        self.xd0 = 0.0       # radial velocity
        self.yd0 = -2.0 * self.n * self.x0  # along-track vel (CW equilibrium)
        self.zd0 = 3.0       # cross-track velocity

        # Ephemeris uncertainty (grows over time — simulates GPS degradation)
        self.uncertainty_growth_rate = 0.002   # deg/s
        self.max_uncertainty = 3.0              # degrees max uncertainty radius
        self.uncertainty = 0.0

        # Current state
        self.t = 0.0
        self.az = 0.0
        self.el = 0.0
        self.predicted_az = 0.0
        self.predicted_el = 0.0

    def _cw_solution(self, t):
        """
        Closed-form CW solution for position at time t.
        Returns (x, y, z) in meters in Hill's frame.
        """
        n = self.n
        x0, y0, z0 = self.x0, self.y0, self.z0
        xd0, yd0, zd0 = self.xd0, self.yd0, self.zd0

        sin_nt = math.sin(n * t)
        cos_nt = math.cos(n * t)

        x = (4 - 3*cos_nt)*x0 + sin_nt*xd0/n + 2*(1 - cos_nt)*yd0/n
        y = (6*(sin_nt - n*t))*x0 + y0 - 2*(1 - cos_nt)*xd0/n + (4*sin_nt - 3*n*t)*yd0/n
        z = z0*cos_nt + zd0*sin_nt/n

        return x, y, z

    def _hill_to_azel(self, x, y, z):
        """
        Convert Hill's frame position (m) to azimuth/elevation (degrees)
        as seen from observer satellite A.

        With yd0 = -2*n*x0 (the CW periodic-orbit equilibrium), x(t) reduces
        to x0*cos(nt) — already centered on zero — so it maps directly to
        azimuth deviation; z (cross-track) maps to elevation deviation; y
        (along-track range) sets the small-angle scale for both.
        """
        range_ref = max(abs(y), 1.0)

        az = math.degrees(math.atan2(x, range_ref))
        el = math.degrees(math.atan2(z, range_ref))

        # Clamp to reasonable angular range for the simulation (camera FOV
        # is 20 deg, so keep well within +/-10 deg with margin for manual pan).
        az = max(-10.0, min(10.0, az))
        el = max(-9.0, min(9.0, el))

        return az, el

    def update(self, dt):
        """Advance simulation by dt seconds."""
        self.t += dt

        # True position from CW equations
        x, y, z = self._cw_solution(self.t)
        self.az, self.el = self._hill_to_azel(x, y, z)

        # Predicted position (what the system believes from ephemeris)
        # Uncertainty grows over time
        self.uncertainty = min(
            self.uncertainty + self.uncertainty_growth_rate * dt,
            self.max_uncertainty
        )
        # Add noise to prediction proportional to uncertainty
        noise_az = np.random.normal(0, self.uncertainty * 0.1)
        noise_el = np.random.normal(0, self.uncertainty * 0.1)
        self.predicted_az = self.az + noise_az
        self.predicted_el = self.el + noise_el

    @property
    def position(self):
        """True target position (az, el) in degrees."""
        return (self.az, self.el)

    @property
    def predicted_position(self):
        """Ephemeris-predicted position with uncertainty."""
        return (self.predicted_az, self.predicted_el)

    @property
    def position_uncertainty_deg(self):
        """Current prediction uncertainty radius in degrees."""
        return self.uncertainty
