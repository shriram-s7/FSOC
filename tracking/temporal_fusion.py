"""
Temporal Fusion Buffer — Stage 5
==================================
Prevents false locks by requiring sustained high confidence
over multiple frames before committing to LOCKED state.

This is our key differentiator over competing solutions.
A single-frame fluke (distractor briefly outscoring beacon)
cannot trigger a lock or cause a lock to be lost.

How it works:
  - Maintains a rolling window of last N confidence scores
    for the currently tracked candidate
  - LOCK requires: rolling mean > LOCK_THRESHOLD for N frames
    AND the last 4 candidate positions logged during ACQUIRING
    are spatially consistent in WORLD coordinates (stddev <=
    POSITION_STD_LIMIT) — this rejects a mean built from several
    different candidates (e.g. stars swept past during search)
    rather than one stable one. World space, not screen space: the
    servo slews the camera hard during ACQUIRING, which swings a
    real beacon's SCREEN position by tens of px/frame even though
    its WORLD position barely moves — measuring in screen space
    made the gate unsatisfiable.
  - UNLOCK requires: rolling mean < UNLOCK_THRESHOLD (hysteresis)
  - RE-ACQUIRE requires: mean > REACQUIRE_THRESHOLD AND
    margin over second-best > MARGIN_THRESHOLD

States:
  SEARCHING  — no candidate found yet, running search pattern
  ACQUIRING  — candidate found, building confidence history
  LOCKED     — sustained high confidence, actively tracking
  COASTING   — brief loss, using Kalman prediction only
  LOST       — coasting failed, returning to SEARCHING
"""

from collections import deque
import numpy as np
from enum import Enum, auto


class TrackState(Enum):
    SEARCHING  = auto()
    ACQUIRING  = auto()
    LOCKED     = auto()
    COASTING   = auto()
    LOST       = auto()


class TemporalFusionBuffer:
    """
    Rolling confidence buffer with hysteresis lock/unlock logic.

    Parameters (all tunable via config):
      window_size        : N frames to buffer (default 8)
      lock_threshold     : mean confidence to enter LOCKED (0.82)
      unlock_threshold   : mean confidence to leave LOCKED (0.35)
      reacquire_threshold: mean needed to re-lock after COASTING (0.85)
      margin_threshold   : top vs second-best margin for re-acquire (0.25)
      max_coast_frames   : frames allowed in COASTING before → LOST (30)
      min_acquire_frames : minimum frames in ACQUIRING before can lock (8)
      position_std_limit : max stddev of last 4 ACQUIRING positions, in
                            WORLD pixels, to allow LOCKED — rejects a
                            confidence buffer built from several
                            different drifting candidates rather than
                            one stable one (40 world px: a beacon at
                            20-30 px/s drifts ~2px world-space over 4
                            frames at 60fps, far under 40; a star swept
                            past during spiral search jumps hundreds of
                            world px between samples)
      brightness_min      : min mean brightness of last 4 ACQUIRING
                             candidates to allow LOCKED. Measured top-
                             candidate medians: S14 clear+jitter 173-175,
                             X05 rain 144-149, X07 low light 62-63
                             (0-255 mean blob intensity, seeds 1-3).
                             Set every frame by apply_params() from the
                             image-only SceneEstimator: 100 at
                             degradation 0 (clear) down to 60 at
                             degradation 1 (fog / rain / low light, as
                             measured from the frame), then lowered by
                             30 x estimated noise level above 0.3 (floor
                             40). The gate actually applied is
                             brightness_gate = min(brightness_min,
                             brightness_rel_ratio (1.0) x median
                             star-field level of the last 8 frames).
                             The reference is the 32nd brightest cleaned
                             pixel after masking ALL detected candidates:
                             X07 measures 46-54 during initial acquisition.
                             Masking only the top candidate let decoys
                             raise seed 2's reference to 83-88 and blocked
                             its ~63-brightness beacon for 12.7 s.
    """

    def __init__(self, cfg):
        t = cfg.tracking
        self.window_size         = int(t.temporal_fusion_window)  # 8
        self.lock_threshold      = float(t.lock_threshold)         # 0.75
        self.unlock_threshold    = float(t.unlock_threshold)       # 0.35
        self.reacquire_threshold = float(t.reacquire_threshold)     # 0.85
        self.margin_threshold    = 0.25
        self.max_coast_frames    = 45
        self.min_acquire_frames  = 8
        self.position_std_limit  = 40.0
        self.brightness_min      = 100.0
        # Step 6b-1: the brightness gate is also RELATIVE to the scene.
        # A global gain drop (low light) dims beacon and stars alike, so
        # the fixed 100 blocks the beacon. The tracker measures the
        # star-field level from the image each frame (observe_scene),
        # excluding all detected foreground candidates, including decoys.
        # The gate is min(brightness_min, ratio x that level); X07 initial
        # references are 46-54 versus beacon blob means around 62-63.
        # Pixel-level reference and blob-mean brightness are distinct
        # measurements; the confidence and stability gates still apply.
        self.brightness_rel_ratio = float(t.get('brightness_rel_ratio', 1.0))
        self._scene_levels = deque(maxlen=8)

        self._buffer      = deque(maxlen=self.window_size)
        self._acquire_positions   = deque(maxlen=8)  # WORLD coordinates
        self._acquire_brightness  = deque(maxlen=8)
        self._state       = TrackState.SEARCHING
        self._coast_count = 0
        self._acq_count   = 0

        # True once the buffer has ever reached LOCKED and hasn't since
        # fully timed out through COASTING -> LOST. A confidence drop
        # while this is True degrades to COASTING (same object, still
        # trackable) instead of SEARCHING (throws the buffer away and
        # hands pointing authority to the spiral).
        self._had_recent_lock = False

        # Stats
        self.frames_locked    = 0
        self.frames_total     = 0
        self.false_lock_count = 0

    PARAM_FIELDS = ('lock_threshold', 'brightness_min', 'position_std_limit',
                    'min_acquire_frames', 'max_coast_frames',
                    'unlock_threshold', 'reacquire_threshold')

    def apply_params(self, params):
        """Set the adaptive lock gates / coasting budget. Called once per
        frame from MasterTracker.process() with SceneEstimator.params(),
        i.e. from what the IMAGE shows (clear-sky values at degradation 0,
        relaxed fog/rain/low-light values at 1) - never from disturbance
        settings. No other code should assign these fields directly."""
        for k in self.PARAM_FIELDS:
            if k in params:
                setattr(self, k, params[k])

    def reset(self):
        """Full reset — go back to SEARCHING."""
        self._buffer.clear()
        self._acquire_positions.clear()
        self._acquire_brightness.clear()
        self._state       = TrackState.SEARCHING
        self._coast_count = 0
        self._acq_count   = 0
        self._had_recent_lock = False

    def _position_stable(self):
        """
        Check whether the last 4 candidate positions logged during
        ACQUIRING — in WORLD coordinates — are spatially consistent
        (stddev <= position_std_limit).

        A real beacon has low WORLD position variance frame-to-frame
        even while the servo is slewing the camera hard to converge on
        it (that slewing only moves its SCREEN position, which is why
        world space is used here). A confidence buffer built from
        several different stars swept past during search — each
        individually scoring high for a frame or two — shows high
        world-position variance even though the *confidence* values
        look sustained. Returns False (not stable) if fewer than 4
        positions are logged yet.
        """
        if len(self._acquire_positions) < 4:
            return False
        recent = np.array(list(self._acquire_positions)[-4:])
        std_x = np.std(recent[:, 0])
        std_y = np.std(recent[:, 1])
        position_std = float(np.sqrt(std_x ** 2 + std_y ** 2))
        return position_std <= self.position_std_limit

    def observe_scene(self, star_level):
        """Brightest-star level of this frame, measured from the image
        (MasterTracker.process). None = not measured."""
        if star_level is not None:
            self._scene_levels.append(float(star_level))

    @property
    def brightness_gate(self):
        """Effective brightness gate: brightness_min, lowered only when
        the measured scene is dimmer than it (see __init__)."""
        if not self._scene_levels or self.brightness_rel_ratio <= 0:
            return self.brightness_min
        level = float(np.median(self._scene_levels))
        return min(self.brightness_min, self.brightness_rel_ratio * level)

    def _brightness_consistent(self):
        """
        Check whether the last 4 ACQUIRING candidates were bright enough
        to plausibly be the beacon rather than a background star.

        Compared against brightness_gate (see class docstring): measured
        clear+jitter beacon medians are 173-175, above the clear-sky
        ceiling of 100; X07 low-light beacon medians are 62-63, above
        the masked star-field reference of 46-54. The relative term
        lowers the gate along with the star field. Returns False if
        fewer than 4 samples logged.
        """
        if len(self._acquire_brightness) < 4:
            return False
        recent = list(self._acquire_brightness)[-4:]
        return float(np.mean(recent)) >= self.brightness_gate

    @property
    def state(self):
        return self._state

    @property
    def rolling_mean(self):
        if not self._buffer:
            return 0.0
        return float(np.mean(self._buffer))

    @property
    def lock_retention_rate(self):
        if self.frames_total == 0:
            return 0.0
        return self.frames_locked / self.frames_total

    def begin_acquire(self, confidence, position=None, brightness=None):
        """COASTING -> ACQUIRING on a confident candidate found elsewhere
        in the frame (outside the strict association gate). It must pass
        the full normal lock gates (confidence, min_acquire_frames,
        position stability, brightness) — never straight to LOCKED. The
        old track is abandoned: if this acquisition fails it drops to
        SEARCHING, not back to COASTING on the stale prediction."""
        self._buffer.clear()
        self._buffer.append(confidence)
        self._acquire_positions.clear()
        self._acquire_brightness.clear()
        if position is not None:
            self._acquire_positions.append(position)
        if brightness is not None:
            self._acquire_brightness.append(brightness)
        self._acq_count = 1
        self._coast_count = 0
        self._had_recent_lock = False
        self._state = TrackState.ACQUIRING
        return self._state

    def update(self, top_confidence, second_confidence=0.0,
               detection_available=True, top_position=None,
               top_brightness=None):
        """
        Update buffer with new frame's classification results.

        Args:
            top_confidence     : P(beacon) for best candidate this frame
            second_confidence  : P(beacon) for second-best (for margin check)
            detection_available: False if detector found no candidates
            top_position       : (x, y) WORLD pixel position of the top
                                  candidate this frame, or None. Used to
                                  reject a LOCK built from several
                                  spatially inconsistent candidates (see
                                  _position_stable).
            top_brightness      : mean blob brightness (0-255) of the top
                                  candidate this frame, or None. Used to
                                  reject a LOCK on a dim background star
                                  (see _brightness_consistent).

        Returns:
            TrackState: new state after update
        """
        self.frames_total += 1

        if self._state == TrackState.SEARCHING:
            if detection_available and top_confidence >= self.lock_threshold:
                self._buffer.clear()
                self._buffer.append(top_confidence)
                self._acquire_positions.clear()
                self._acquire_brightness.clear()
                if top_position is not None:
                    self._acquire_positions.append(top_position)
                if top_brightness is not None:
                    self._acquire_brightness.append(top_brightness)
                self._acq_count = 1
                self._state = TrackState.ACQUIRING

        elif self._state == TrackState.ACQUIRING:
            if detection_available:
                self._buffer.append(top_confidence)
                if top_position is not None:
                    self._acquire_positions.append(top_position)
                if top_brightness is not None:
                    self._acquire_brightness.append(top_brightness)
                self._acq_count += 1
                mean = self.rolling_mean
                # Promote to LOCKED only if sustained high confidence,
                # the candidate stayed in roughly the same place (rejects
                # a mean built from several different objects), and it's
                # bright enough to plausibly be the beacon rather than a
                # star.
                if (self._acq_count >= self.min_acquire_frames and
                        mean >= self.lock_threshold and
                        self._position_stable() and
                        self._brightness_consistent()):
                    self._state = TrackState.LOCKED
                    self._had_recent_lock = True
                # Fall back if confidence drops
                elif mean < self.unlock_threshold:
                    if self._had_recent_lock:
                        # A recently-held target dimming out (e.g. fog
                        # sagging confidence gradually) is still the same
                        # object — coast instead of throwing the buffer
                        # away and handing pointing authority to the
                        # spiral.
                        self._state = TrackState.COASTING
                        self._coast_count = 0
                    else:
                        self._state = TrackState.SEARCHING
                        self._buffer.clear()
                        self._acquire_positions.clear()
                        self._acquire_brightness.clear()
                        self._acq_count = 0
            else:
                # No detection during acquisition
                if self._had_recent_lock:
                    self._state = TrackState.COASTING
                    self._coast_count = 0
                else:
                    # Never actually locked yet — reset
                    self._state = TrackState.SEARCHING
                    self._buffer.clear()
                    self._acquire_positions.clear()
                    self._acquire_brightness.clear()
                    self._acq_count = 0

        elif self._state == TrackState.LOCKED:
            self.frames_locked += 1
            if detection_available:
                self._buffer.append(top_confidence)
                self._coast_count = 0
                mean = self.rolling_mean
                if mean < self.unlock_threshold:
                    # Confidence dropped — start coasting. (had_recent_lock
                    # is necessarily True here already; the check keeps
                    # this branch's shape identical to the ACQUIRING ones
                    # above rather than relying on that implicitly.)
                    if self._had_recent_lock:
                        self._state = TrackState.COASTING
                        self._coast_count = 0
                    else:
                        self._state = TrackState.SEARCHING
                        self._buffer.clear()
                        self._acquire_positions.clear()
                        self._acquire_brightness.clear()
                        self._acq_count = 0
            else:
                # No detection — start coasting
                if self._had_recent_lock:
                    self._coast_count += 1
                    self._state = TrackState.COASTING
                else:
                    self._state = TrackState.SEARCHING
                    self._buffer.clear()
                    self._acquire_positions.clear()
                    self._acquire_brightness.clear()
                    self._acq_count = 0

        elif self._state == TrackState.COASTING:
            if detection_available:
                margin = top_confidence - second_confidence
                # Strict re-acquire: high confidence AND clear margin
                if (top_confidence >= self.reacquire_threshold and
                        margin >= self.margin_threshold):
                    self._buffer.append(top_confidence)
                    self._coast_count = 0
                    self._state = TrackState.LOCKED
                    self._had_recent_lock = True
                else:
                    self._coast_count += 1
            else:
                self._coast_count += 1

            # Give up coasting → LOST. Only a genuine coast timeout may
            # fall through to SEARCHING and clear the buffers.
            if self._coast_count >= self.max_coast_frames:
                self._state = TrackState.LOST
                self._buffer.clear()
                self._had_recent_lock = False

        elif self._state == TrackState.LOST:
            # Auto-recover to SEARCHING
            self._state = TrackState.SEARCHING
            self._buffer.clear()
            self._acquire_positions.clear()
            self._acquire_brightness.clear()
            self._acq_count   = 0
            self._coast_count = 0

        return self._state
