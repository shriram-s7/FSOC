"""
Disturbance Engine — applies realistic sensor degradation to camera frames.

Simulates real-world degradation that a satellite camera experiences:
  1. Atmospheric turbulence  — optical wavefront distortion (image warp)
  2. Platform vibration      — mechanical shake (image translation)
  3. Sensor noise            — CCD/CMOS noise (pixel-level grain)
  4. Scintillation           — intensity fluctuation on received beacon
  5. Jerk events             — sudden attitude disturbance (large shift)

Each disturbance has a strength parameter 0.0 (off) to 1.0 (maximum).
All are independently controllable via the UI sliders (Stage 7).

Pipeline order (applied in sequence each frame):
  raw frame → turbulence warp → vibration shift → noise → output
  (scintillation is applied during world rendering, not here)
"""

import cv2
import numpy as np
import math
import random


class DisturbanceEngine:
    """
    Applies stacked disturbances to a pygame Surface each frame.
    
    Usage:
        engine = DisturbanceEngine(cfg)
        engine.set_levels(turbulence=0.3, vibration=0.2, noise=0.4,
                          scintillation=0.1, jerk=0.02)
        disturbed_surface = engine.apply(raw_surface)
        scintillation_factor = engine.get_scintillation()
    
    All apply() input/output are pygame.Surface objects.
    Internally converts to numpy arrays for OpenCV processing.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.width  = cfg.window.width
        self.height = cfg.window.height

        # Disturbance levels (0.0 - 1.0)
        self.turbulence    = 0.0
        self.vibration     = 0.0
        self.noise         = 0.0
        self.scintillation = 0.0
        self.jerk_prob     = 0.0

        self.atmosphere    = 'clear'   # clear/haze/fog/rain/lowlight
        self.noise_gaussian    = True
        self.noise_saltpepper  = False
        self.noise_poisson     = False
        self.platform_enabled  = False
        self.platform_dx       = 0.0
        self.platform_dy       = 0.0
        self.platform_speed    = 5.0   # pixels per second
        self.low_light         = False # independent of atmosphere
        self._rain_drops       = None  # (x, y, length, brightness) arrays
        self._dt               = 1.0 / 60
        d = cfg.get('disturbance') or {}
        self._rain_cfg = dict(d.get('rain') or {})
        self._low_cfg  = dict(d.get('low_light') or {})
        self._platform_offset_x = 0.0
        self._platform_offset_y = 0.0

        # Internal state
        self._vib_phase_x  = random.uniform(0, 2 * math.pi)
        self._vib_phase_y  = random.uniform(0, 2 * math.pi)
        self._vib_freq_x   = random.uniform(8, 15)   # Hz
        self._vib_freq_y   = random.uniform(6, 12)   # Hz
        self._sim_time     = 0.0
        self._scint_value  = 1.0   # current scintillation multiplier
        self._scint_target = 1.0
        self._scint_speed  = 3.0  # how fast scintillation changes

        # Pre-build displacement field maps (reused each frame, updated periodically)
        self._turb_map_x = np.zeros((self.height, self.width), dtype=np.float32)
        self._turb_map_y = np.zeros((self.height, self.width), dtype=np.float32)
        self._turb_update_counter = 0
        self._TURB_UPDATE_INTERVAL = 4   # update turbulence field every N frames

        # Cumulative vibration offset (pixels)
        self._vib_offset_x = 0.0
        self._vib_offset_y = 0.0

        # Total whole-image translation (px) applied by the last apply()
        # call: vibration + jerk + platform motion. Content at screen
        # (x, y) in the rendered frame appears at (x + dx, y + dy) in the
        # output. Used only for ground-truth scoring, never by the tracker.
        self._frame_offset = [0.0, 0.0]

    def set_levels(self, turbulence=None, vibration=None, noise=None,
                   scintillation=None, jerk=None,
                   atmosphere=None,
                   noise_gaussian=None,
                   noise_saltpepper=None,
                   noise_poisson=None,
                   platform_enabled=None,
                   platform_speed=None,
                   low_light=None):
        """Set disturbance strength levels. Pass only params you want to change."""
        if turbulence       is not None: self.turbulence       = max(0.0, min(1.0, turbulence))
        if vibration        is not None: self.vibration        = max(0.0, min(1.0, vibration))
        if noise            is not None: self.noise            = max(0.0, min(1.0, noise))
        if scintillation    is not None: self.scintillation    = max(0.0, min(1.0, scintillation))
        if jerk             is not None: self.jerk_prob        = max(0.0, min(0.1, jerk))
        if atmosphere       is not None: self.atmosphere       = str(atmosphere)
        if noise_gaussian   is not None: self.noise_gaussian   = bool(noise_gaussian)
        if noise_saltpepper is not None: self.noise_saltpepper = bool(noise_saltpepper)
        if noise_poisson    is not None: self.noise_poisson    = bool(noise_poisson)
        if platform_enabled is not None: self.platform_enabled = bool(platform_enabled)
        if platform_speed   is not None: self.platform_speed   = float(platform_speed)
        if low_light        is not None: self.low_light        = bool(low_light)

    def _update_turbulence_field(self):
        """
        Generate a smooth random displacement field for image warping.
        Uses low-frequency random noise smoothed with Gaussian blur
        to approximate Kolmogorov atmospheric turbulence.
        """
        if self.turbulence < 0.01:
            self._turb_map_x[:] = 0
            self._turb_map_y[:] = 0
            return

        max_displacement = self.turbulence * 12.0   # pixels

        # Generate at low resolution for speed, then upscale
        scale = 8
        lw = self.width  // scale
        lh = self.height // scale

        raw_x = np.random.randn(lh, lw).astype(np.float32)
        raw_y = np.random.randn(lh, lw).astype(np.float32)

        # Smooth with Gaussian to create coherent turbulence cells
        blur_k = max(3, int(self.turbulence * 5) * 2 + 1)
        raw_x = cv2.GaussianBlur(raw_x, (blur_k, blur_k), 0)
        raw_y = cv2.GaussianBlur(raw_y, (blur_k, blur_k), 0)

        # Normalise to [-1, 1]
        def norm(a):
            m = np.abs(a).max()
            return a / m if m > 0 else a

        raw_x = norm(raw_x) * max_displacement
        raw_y = norm(raw_y) * max_displacement

        # Upscale to full resolution
        up_x = cv2.resize(raw_x, (self.width, self.height),
                          interpolation=cv2.INTER_CUBIC)
        up_y = cv2.resize(raw_y, (self.width, self.height),
                          interpolation=cv2.INTER_CUBIC)

        # Add pixel coordinate grid (remap needs absolute coords)
        grid_x, grid_y = np.meshgrid(
            np.arange(self.width,  dtype=np.float32),
            np.arange(self.height, dtype=np.float32)
        )
        self._turb_map_x = grid_x + up_x
        self._turb_map_y = grid_y + up_y

    def _apply_turbulence(self, frame_bgr):
        """Warp the frame using the current turbulence displacement field."""
        if self.turbulence < 0.01:
            return frame_bgr
        self._turb_update_counter += 1
        if self._turb_update_counter >= self._TURB_UPDATE_INTERVAL:
            self._update_turbulence_field()
            self._turb_update_counter = 0
        return cv2.remap(frame_bgr,
                         self._turb_map_x,
                         self._turb_map_y,
                         interpolation=cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_REFLECT)

    def _apply_vibration(self, frame_bgr, dt):
        """
        Translate the frame by a sinusoidal + random vibration offset.
        Simulates platform mechanical vibration.
        """
        if self.vibration < 0.01:
            return frame_bgr

        # Level 1.0 = PS camera jitter of +/-20 px per frame, per axis.
        max_amp = self.vibration * 20.0   # pixels

        # Sinusoidal base (structural resonance)
        sx = max_amp * 0.6 * math.sin(
            2 * math.pi * self._vib_freq_x * self._sim_time + self._vib_phase_x)
        sy = max_amp * 0.6 * math.sin(
            2 * math.pi * self._vib_freq_y * self._sim_time + self._vib_phase_y)

        # Random component (broadband vibration)
        rx = random.gauss(0, max_amp * 0.25)
        ry = random.gauss(0, max_amp * 0.25)

        dx = max(-max_amp, min(max_amp, sx + rx))
        dy = max(-max_amp, min(max_amp, sy + ry))
        self._frame_offset[0] += dx
        self._frame_offset[1] += dy

        M = np.float32([[1, 0, dx], [0, 1, dy]])
        return cv2.warpAffine(frame_bgr, M,
                              (self.width, self.height),
                              borderMode=cv2.BORDER_REFLECT)

    def _apply_jerk(self, frame_bgr):
        """
        Occasionally apply a large sudden translation (attitude disturbance).
        Models thruster firings or momentum wheel desaturation events.
        """
        if random.random() > self.jerk_prob:
            return frame_bgr

        max_jerk = 35.0   # pixels
        dx = random.uniform(-max_jerk, max_jerk)
        dy = random.uniform(-max_jerk * 0.6, max_jerk * 0.6)
        self._frame_offset[0] += dx
        self._frame_offset[1] += dy

        M = np.float32([[1, 0, dx], [0, 1, dy]])
        return cv2.warpAffine(frame_bgr, M,
                              (self.width, self.height),
                              borderMode=cv2.BORDER_REFLECT)

    # Noise level 1.0 = PS 26169 maximum for each noise type.
    GAUSS_SIGMA_MAX   = 20.0   # grey levels (0-255) — PS max noise std
    SALTPEPPER_MAX    = 0.10   # fraction of pixels corrupted — PS ~10%
    POISSON_GAIN_MAX  = 8.0    # grey levels per photon at level 1.0

    def _apply_poisson_noise(self, frame_bgr):
        """
        Poisson (photon shot) noise — signal-dependent.
        Each pixel's grey level I is converted to an expected photon count
        I / gain, a Poisson count is drawn, and converted back, so the
        noise std is sqrt(gain * I): zero on black, largest on the beacon.
        gain = POISSON_GAIN_MAX * level (level 1.0 -> std ~45 at I=255).
        """
        if self.noise < 0.01:
            return frame_bgr
        gain = self.POISSON_GAIN_MAX * self.noise
        photons = frame_bgr.astype(np.float32) / gain
        noisy = np.random.poisson(photons).astype(np.float32)
        result = np.clip(noisy * gain, 0, 255).astype(np.uint8)
        return result

    def _apply_noise(self, frame_bgr):
        if self.noise < 0.01:
            return frame_bgr
        result = frame_bgr.copy()
        
        if self.noise_gaussian:
            sigma = self.noise * self.GAUSS_SIGMA_MAX
            gauss = np.random.normal(
                0, sigma, result.shape).astype(np.float32)
            result = np.clip(
                result.astype(np.float32) + gauss,
                0, 255).astype(np.uint8)
        
        if self.noise_saltpepper:
            # Fraction of pixels corrupted = SALTPEPPER_MAX * level,
            # split evenly between salt (255) and pepper (0).
            frac = self.noise * self.SALTPEPPER_MAX
            u = np.random.random(result.shape[:2])
            result[u < frac / 2] = 255
            result[(u >= frac / 2) & (u < frac)] = 0
        
        if self.noise_poisson:
            result = self._apply_poisson_noise(result)
        
        return result

    def _apply_atmosphere(self, frame_bgr):
        """
        Apply atmospheric degradation to frame.
        Each mode affects contrast, brightness, visibility differently.

        clear     — no effect
        haze      — mild contrast reduction, slight brightness increase
                    blend toward gray: frame = frame*0.85 + 128*0.15
        fog       — strong contrast reduction + Gaussian blur
                    blend toward white: frame = frame*0.5 + 220*0.5
                    then blur with 15x15 Gaussian kernel
        rain      — falling thin bright diagonal streaks over a slightly
                    blurred, slightly dimmed scene (_apply_rain;
                    strengths in config disturbance.rain)
        low_light — legacy atmosphere name; low light is now the
                    independent `low_light` flag (_apply_low_light),
                    applied after any atmosphere in apply()
        """
        mode = self.atmosphere.lower().replace(' ', '_')
        if mode == 'clear' or not mode:
            return frame_bgr
        
        if mode == 'haze':
            gray = np.full_like(frame_bgr, 128)
            return cv2.addWeighted(frame_bgr, 0.85, gray, 0.15, 0)
        
        elif mode == 'fog':
            white = np.full_like(frame_bgr, 220)
            blended = cv2.addWeighted(frame_bgr, 0.5, white, 0.5, 0)
            return cv2.GaussianBlur(blended, (15, 15), 0)

        elif mode == 'dense_fog':
            # Near-opaque fog: almost nothing of the scene survives, so the
            # beacon is not detectable (harness T3b).
            white = np.full_like(frame_bgr, 220)
            blended = cv2.addWeighted(frame_bgr, 0.02, white, 0.98, 0)
            return cv2.GaussianBlur(blended, (15, 15), 0)
        
        elif mode == 'rain':
            return self._apply_rain(frame_bgr)

        elif mode in ('low_light', 'lowlight'):
            # Legacy atmosphere name: same effect as the low_light flag
            # (applied in apply()).
            return frame_bgr

        return frame_bgr

    def _apply_rain(self, frame_bgr):
        """Rain: thin bright diagonal streaks falling across a slightly
        dimmed, slightly blurred scene (strengths: config disturbance.rain)."""
        r = self._rain_cfg
        h, w = frame_bgr.shape[:2]
        n = int(r.get('streaks', 110))
        lmin, lmax = r.get('length_px', [12, 30])
        bmin, bmax = r.get('brightness', [140, 200])
        slant = float(r.get('slant', 0.35))
        if self._rain_drops is None or len(self._rain_drops[0]) != n:
            self._rain_drops = (np.random.uniform(0, w, n),
                                np.random.uniform(0, h, n),
                                np.random.uniform(lmin, lmax, n),
                                np.random.randint(bmin, bmax + 1, n))
        x, y, ln, br = self._rain_drops
        dy = float(r.get('fall_px_s', 700)) * self._dt
        y += dy
        x += slant * dy
        gone = y > h
        k = int(gone.sum())
        if k:
            y[gone] = np.random.uniform(-lmax, 0, k)
            x[gone] = np.random.uniform(-slant * h, w, k)
            ln[gone] = np.random.uniform(lmin, lmax, k)
            br[gone] = np.random.randint(bmin, bmax + 1, k)
        x %= (w + slant * h)
        out = frame_bgr
        kz = int(r.get('blur_ksize', 3))
        if kz > 1:
            out = cv2.GaussianBlur(out, (kz | 1, kz | 1), 0)
        out = cv2.convertScaleAbs(out, alpha=float(r.get('dim', 0.85)))
        for xi, yi, li, bi in zip(x, y, ln, br):
            x2 = xi - slant * li
            y2 = yi - li
            c = int(bi)
            cv2.line(out, (int(xi), int(yi)), (int(x2), int(y2)), (c, c, c), 1, cv2.LINE_AA)
        return out

    def _apply_low_light(self, frame_bgr):
        """Low light: lower sensor gain + more sensor noise — Poisson shot
        noise on the (fewer) photons plus Gaussian read noise
        (strengths: config disturbance.low_light)."""
        c = self._low_cfg
        dark = frame_bgr.astype(np.float32) * float(c.get('gain', 0.35))
        g = float(c.get('shot_gain', 2.0))
        if g > 0:
            dark = np.random.poisson(dark / g).astype(np.float32) * g
        sig = float(c.get('read_noise_sigma', 6.0))
        if sig > 0:
            dark += np.random.normal(0, sig, dark.shape).astype(np.float32)
        return np.clip(dark, 0, 255).astype(np.uint8)

    def _low_light_active(self):
        a = (self.atmosphere or '').lower().replace(' ', '_')
        return self.low_light or a in ('low_light', 'lowlight')

    def _apply_platform_motion(self, frame_bgr, dt):
        """
        Platform motion — translates entire frame simulating
        movement of the satellite/UAV platform itself.
        Mandatory: linear motion.
        The translation represents relative motion between
        observer platform and the scene.
        Max: ±20 pixels per frame as per PS spec.
        """
        if not self.platform_enabled:
            return frame_bgr
        
        max_per_frame = min(20.0, self.platform_speed * dt * 60)
        
        # Linear drift with slow random walk
        self._platform_offset_x += np.random.uniform(
            -max_per_frame*0.3, max_per_frame*0.3)
        self._platform_offset_y += np.random.uniform(
            -max_per_frame*0.2, max_per_frame*0.2)
        
        # Clamp to max ±20px per frame
        self._platform_offset_x = np.clip(
            self._platform_offset_x, -20, 20)
        self._platform_offset_y = np.clip(
            self._platform_offset_y, -20, 20)
        
        dx = int(self._platform_offset_x)
        dy = int(self._platform_offset_y)
        self._frame_offset[0] += dx
        self._frame_offset[1] += dy
        
        h, w = frame_bgr.shape[:2]
        M = np.float32([[1, 0, dx], [0, 1, dy]])
        return cv2.warpAffine(frame_bgr, M, (w, h),
                              borderMode=cv2.BORDER_REFLECT)

    def _update_scintillation(self, dt):
        """
        Smoothly vary the scintillation multiplier.
        Models intensity fluctuation of beacon due to atmospheric scintillation.
        Scintillation affects beacon brightness — applied during rendering.
        """
        if self.scintillation < 0.01:
            self._scint_value = 1.0
            return

        # Random walk toward a new target occasionally
        if random.random() < 0.08:
            depth = self.scintillation * 0.7
            self._scint_target = random.uniform(1.0 - depth, 1.0 + depth * 0.3)
            self._scint_target = max(0.2, min(1.3, self._scint_target))

        # Smooth interpolation
        diff = self._scint_target - self._scint_value
        self._scint_value += diff * self._scint_speed * dt
        self._scint_value = max(0.15, min(1.35, self._scint_value))

    @property
    def applied_offset(self):
        """(dx, dy) whole-image translation applied by the last apply()."""
        return (self._frame_offset[0], self._frame_offset[1])

    def get_scintillation(self):
        """
        Returns current scintillation multiplier (float).
        World renderer multiplies beacon intensity by this value.
        Range: ~0.15 (very dim) to ~1.35 (slightly brighter than normal).
        """
        return self._scint_value

    def apply(self, pygame_surface, dt=0.016):
        """
        Apply all active disturbances to a pygame Surface.
        
        Args:
            pygame_surface: pygame.Surface — the rendered camera frame
            dt: float — frame delta time in seconds
        
        Returns:
            pygame.Surface — disturbed frame (same size as input)
        """
        import pygame

        self._sim_time += dt
        self._update_scintillation(dt)
        self._frame_offset = [0.0, 0.0]

        # Skip processing if all disturbances are off
        atmo_active = bool(self.atmosphere and self.atmosphere.lower().replace(' ', '_') != 'clear')
        self._dt = dt
        if (self.turbulence < 0.01 and self.vibration < 0.01 and
                self.noise < 0.01 and self.jerk_prob < 0.01 and
                not atmo_active and not self.platform_enabled and
                not self.low_light):
            return pygame_surface

        # Convert pygame Surface → numpy BGR array (OpenCV format)
        raw_rgb = pygame.surfarray.array3d(pygame_surface)
        # surfarray gives (width, height, 3) in RGB — convert to (height, width, 3) BGR
        frame_bgr = cv2.cvtColor(
            np.transpose(raw_rgb, (1, 0, 2)),
            cv2.COLOR_RGB2BGR
        )

        # Apply disturbances in order: turbulence → vibration → jerk → noise → atmosphere → platform
        frame_bgr = self._apply_turbulence(frame_bgr)
        frame_bgr = self._apply_vibration(frame_bgr, dt)
        frame_bgr = self._apply_jerk(frame_bgr)
        frame_bgr = self._apply_noise(frame_bgr)
        frame_bgr = self._apply_atmosphere(frame_bgr)
        if self._low_light_active():
            frame_bgr = self._apply_low_light(frame_bgr)
        frame_bgr = self._apply_platform_motion(frame_bgr, dt)

        # Convert back: BGR numpy → RGB → pygame Surface
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        # Transpose back to (width, height, 3) for pygame
        frame_rgb_t = np.transpose(frame_rgb, (1, 0, 2))
        out_surface = pygame.surfarray.make_surface(frame_rgb_t)

        return out_surface
