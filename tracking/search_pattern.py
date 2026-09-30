"""
Search Pattern — Stage 5
==========================
When the target is lost, executes a systematic spiral search
to re-acquire the beacon.

Spiral search starts from:
  1. Last known position (if available)
  2. Ephemeris-predicted position (from orbital model)
  3. Camera center (fallback)

The spiral expands outward until a candidate is found
or the maximum search radius is reached.
"""

import math


class SpiralSearch:
    """
    Generates a sequence of (delta_pan, delta_tilt) camera waypoints
    forming an outward spiral from the search center.

    The camera controller moves to each waypoint in sequence.
    When a high-confidence candidate is found, search stops.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.fov = cfg.camera.fov_degrees

        # Search parameters
        self.step_deg       = 1.5    # angular step between spiral points (deg)
        self.max_radius     = 12.0   # max search radius in degrees
        self.dwell_frames   = 8      # frames to dwell at each waypoint
        self.theta_step_deg = 30.0   # angular increment per waypoint (deg)

        # Internal state
        self._waypoints    = []
        self._wp_index     = 0
        self._dwell_count  = 0
        self._center_pan   = 0.0
        self._center_tilt  = 0.0
        self._active       = False

    def start(self, center_pan, center_tilt):
        """
        Begin a new spiral search centered at (center_pan, center_tilt).
        Call when tracker enters LOST state.
        """
        self._center_pan  = center_pan
        self._center_tilt = center_tilt
        self._waypoints   = self._generate_spiral()
        self._wp_index    = 0
        self._dwell_count = 0
        self._active      = True

    def _generate_spiral(self):
        """
        Generate Archimedean spiral waypoints in world degrees.
        Returns list of (pan, tilt) absolute world positions.
        """
        waypoints = [(self._center_pan, self._center_tilt)]

        # Archimedean spiral: r = a * theta
        a = self.step_deg / (2 * math.pi)
        theta = 0.0
        target_gap_px = 300.0
        ppd = self.cfg.camera.resolution_width / self.cfg.camera.hfov_deg

        while True:
            # Adaptive theta_step: keep arc-length <= target_gap_px so
            # outer rings (where a fixed angular step would otherwise
            # produce gaps far wider than the camera frame) get denser
            # sampling, while inner rings keep the fast default step.
            r_px = a * theta * ppd
            if r_px > target_gap_px:
                theta_step = math.asin(min(target_gap_px / r_px, 1.0))
            else:
                theta_step = math.radians(self.theta_step_deg)

            theta += theta_step
            r = a * theta
            if r > self.max_radius:
                break
            pan  = self._center_pan  + r * math.cos(theta)
            tilt = self._center_tilt + r * math.sin(theta)
            # Clamp to camera limits
            pan  = max(-30.0, min(30.0, pan))
            tilt = max(-20.0, min(20.0, tilt))
            waypoints.append((pan, tilt))

        return waypoints

    def get_current_target(self):
        """
        Returns the current search target (pan, tilt) in world degrees.
        Returns None if search is complete (all waypoints visited).
        """
        if not self._active or self._wp_index >= len(self._waypoints):
            return None
        return self._waypoints[self._wp_index]

    def advance(self):
        """
        Call every frame during search.
        Advances to next waypoint after dwell_frames.
        Returns current target (pan, tilt) or None if done.
        """
        if not self._active or self._wp_index >= len(self._waypoints):
            self._active = False
            return None

        self._dwell_count += 1
        if self._dwell_count >= self.dwell_frames:
            self._dwell_count = 0
            self._wp_index   += 1

        if self._wp_index >= len(self._waypoints):
            self._active = False
            return None

        return self._waypoints[self._wp_index]

    def stop(self):
        """Stop search (called when target re-acquired)."""
        self._active = False

    @property
    def is_active(self):
        return self._active

    @property
    def progress(self):
        """Search progress 0.0-1.0."""
        if not self._waypoints:
            return 0.0
        return min(1.0, self._wp_index / len(self._waypoints))

