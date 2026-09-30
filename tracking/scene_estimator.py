"""
Scene estimator - image-only estimate of the viewing conditions
===============================================================
One module that turns each frame's pixels (plus the current candidate
list, so the beacon and decoys can be masked out) into a small set of
smoothed scene measurements, and derives from them every adaptive
behaviour of the tracker. Nothing here reads a disturbance, atmosphere,
noise, toggle, scenario or ground-truth value: the only inputs are the
raw grey frame the detector saw, its cleaned (median + Gaussian) copy,
and the candidate blobs.

Measurements (per frame, then smoothed - see TAU_* below):
  background     median grey level of the cleaned frame (candidates
                 masked); fog/haze veil raises it
  contrast       99.9th percentile minus background of the cleaned frame
                 (candidates masked) - how far the star field stands out
  noise_sigma    robust sensor-noise sigma of the RAW frame:
                 1.4826 x MAD of a 3x3 high-pass (sparse stars do not move
                 the median)
  streak_frac    fraction of the (320x240) frame covered by thin, bright,
                 elongated components (rain streaks) after 3x3 dilation
  star_level     star_level_top_px-th brightest pixel of the cleaned
                 full-res frame with every candidate masked (brightness
                 reference for the relative lock gate)
  saturation     fraction of raw pixels >= 250
  visibility     derived 0..1 score (1 = clear sky, 0 = heavily degraded);
                 `degradation` = 1 - visibility = max of
                   veil   background 12 -> 0, 23 -> 0.5, >= 60 -> 1
                          (training seeds: clear 4, noisy <= 9, haze 23,
                          fog 112, dense fog 216)
                   dim    star contrast (star_level - background)
                          >= 60 -> 0, <= 45 -> 1 (low light 35-46; every
                          other non-fog condition >= 52)
                   rain   streak_frac 1 % -> 0, 2 % -> 1 (clear <= 0.69 %,
                          rain 4.3-5.3 %)
  noise_level    derived 0..1 sensor-noise level = max of
                   sigma  noise_sigma 3.0 -> 0, 4.0 -> 1 (low light 2.5-2.6,
                          poisson(1.0) 3.6, gaussian 0.5 / 1.0 4.6 / 8.2)
                   sat    saturation 0.1 % -> 0, 5 % -> 1 (clear 0.03 %,
                          salt & pepper 1.0 5.0 %)

Behaviour derived here (params()): lock threshold, brightness_min,
position std limit, min acquire frames and coast budget (interpolated
between the clear-sky and the degraded set by `degradation`, then lowered
for noise); the stabiliser's rain mode (streak mask handed over when the
frame's streak fraction >= streak_min_frac). The mapping constants were
calibrated on the CNN training seeds 1000-1005 rendered under each
condition (scratch/p3/calib*), never on the S/X/C test scenarios.
"""
import time

import cv2
import numpy as np

# Smoothing time constants (seconds). Attack = the estimate moving towards
# "worse" (degradation up / noise up), release = back towards clear. Fast
# attack so a fog bank relaxes the gates / extends the coast budget within
# a few frames of it arriving; slower release so one clean-looking frame
# inside fog does not snap the strict gates back.
TAU_ATTACK_S  = 0.25
TAU_RELEASE_S = 1.00
TAU_LEVEL_S   = 0.25     # background / contrast / noise / saturation EMA


class SceneEstimator:
    def __init__(self, cfg=None, full_size=(640, 480), small_size=(320, 240)):
        sc = (cfg.get('scene') if cfg is not None and hasattr(cfg, 'get') else None) or {}
        st = (cfg.get('stabiliser') if cfg is not None and hasattr(cfg, 'get') else None) or {}
        tr = (cfg.get('tracking') if cfg is not None and hasattr(cfg, 'get') else None) or {}
        self.small_size = small_size
        self.scale_x = full_size[0] / small_size[0]
        self.scale_y = full_size[1] / small_size[1]
        # Streak (rain) detection - same definition the stabiliser used.
        self.streak_min_len  = float(st.get('streak_min_len_px', 10) or 0)
        self.streak_contrast = float(st.get('streak_contrast', 8.0))
        self.streak_min_frac = float(st.get('streak_min_frac', 0.02))
        self.streak_dilate   = 3
        self.star_level_top_px = int(tr.get('star_level_top_px', 32))
        # Calibration (training seeds 1000-1005; see module docstring).
        self.veil_bg_pts   = [float(v) for v in sc.get('veil_background', [12.0, 23.0, 60.0])]
        self.dim_star_pts  = [float(v) for v in sc.get('dim_star_contrast', [45.0, 60.0])]
        self.rain_frac_pts = [float(v) for v in sc.get('rain_streak_frac', [0.01, 0.02])]
        self.noise_sigma_pts = [float(v) for v in sc.get('noise_sigma', [3.0, 4.0])]
        self.noise_sat_pts   = [float(v) for v in sc.get('noise_saturation', [0.001, 0.05])]
        self.reset()

    def reset(self):
        self.background = None
        self.contrast = None
        self.noise_sigma = None
        self.saturation = None
        self.streak_frac = 0.0        # this frame (unsmoothed)
        self.streak_mask = None       # this frame's streak mask (small px) or None
        self.star_level = None        # this frame (unsmoothed)
        self.degradation = None       # smoothed 0..1
        self.noise_level = None       # smoothed 0..1
        self.small = None             # float32 small frame, candidates masked
        self.fill = 0.0
        self.last_ms = 0.0
        self.raw = {}

    # -- helpers ---------------------------------------------------------
    @staticmethod
    def _ema(prev, x, dt, tau):
        if prev is None:
            return float(x)
        a = 1.0 - np.exp(-dt / max(tau, 1e-6))
        return float(prev + a * (x - prev))

    def _ema_att(self, prev, x, dt):
        if prev is None:
            return float(x)
        return self._ema(prev, x, dt, TAU_ATTACK_S if x > prev else TAU_RELEASE_S)

    def _streaks(self, small, fill):
        """Mask (uint8, small px) of thin elongated bright components."""
        if self.streak_min_len <= 0:
            return None
        bw = (small > fill + self.streak_contrast).astype(np.uint8)
        n, lab, st, _ = cv2.connectedComponentsWithStats(bw, connectivity=8)
        if n <= 1:
            return None
        w = st[1:, cv2.CC_STAT_WIDTH].astype(np.float32) * self.scale_x
        h = st[1:, cv2.CC_STAT_HEIGHT].astype(np.float32) * self.scale_y
        L, W = np.maximum(w, h), np.minimum(w, h)
        streak = np.zeros(n, bool)
        streak[1:] = (L >= self.streak_min_len) & (W <= 0.5 * L)
        if not streak.any():
            return None
        return cv2.dilate(streak[lab].astype(np.uint8),
                          np.ones((self.streak_dilate, self.streak_dilate), np.uint8))

    def _star_level(self, cleaned, blobs):
        """star_level_top_px-th brightest pixel of the cleaned full-res
        frame with every candidate blob's box masked (masked pixels count
        as 0). Exact, via histograms: whole frame minus the candidates'
        bounding region, plus that region with the boxes masked."""
        if self.star_level_top_px <= 0:
            return None
        H, W = cleaned.shape
        hist = cv2.calcHist([cleaned], [0], None, [256], [0, 256]).ravel()
        boxes = []
        for bx, by, br in blobs:
            r = int(3 * br + 15)
            x, y = int(bx), int(by)
            x0, y0 = max(0, x - r), max(0, y - r)
            x1, y1 = min(W, x + r + 1), min(H, y + r + 1)
            if x1 > x0 and y1 > y0:
                boxes.append((x0, y0, x1, y1))
        if boxes:
            X0 = min(b[0] for b in boxes); Y0 = min(b[1] for b in boxes)
            X1 = max(b[2] for b in boxes); Y1 = max(b[3] for b in boxes)
            reg = cleaned[Y0:Y1, X0:X1]
            mask = np.full(reg.shape, 255, np.uint8)
            for x0, y0, x1, y1 in boxes:
                mask[y0 - Y0:y1 - Y0, x0 - X0:x1 - X0] = 0
            hist -= cv2.calcHist([reg], [0], None, [256], [0, 256]).ravel()
            hist += cv2.calcHist([reg], [0], mask, [256], [0, 256]).ravel()
            hist[0] += float(mask.size - cv2.countNonZero(mask))
        c = np.cumsum(hist[::-1])
        k = min(self.star_level_top_px, cleaned.size)
        return float(255 - int(np.searchsorted(c, k)))

    @staticmethod
    def _ramp(x, lo, hi):
        return float(np.clip((x - lo) / max(hi - lo, 1e-6), 0.0, 1.0))

    def _degradation(self, background, star_level, streak_frac):
        b0, b1, b2 = self.veil_bg_pts
        veil = (0.5 * self._ramp(background, b0, b1) if background < b1
                else 0.5 + 0.5 * self._ramp(background, b1, b2))
        dim = (1.0 - self._ramp(star_level - background, *self.dim_star_pts)
               if star_level is not None else 0.0)
        rain = self._ramp(streak_frac, *self.rain_frac_pts)
        return max(veil, dim, rain)

    def _noise(self, sigma, sat):
        return max(self._ramp(sigma, *self.noise_sigma_pts),
                   self._ramp(sat, *self.noise_sat_pts))

    @staticmethod
    def _pct(hist, q):
        """q-quantile (0..1) of a 256-bin grey histogram."""
        c = np.cumsum(hist)
        return float(np.searchsorted(c, q * c[-1]))

    # -- main ------------------------------------------------------------
    def update(self, raw, cleaned, blobs=(), dt=1.0 / 60.0):
        """raw / cleaned: full-res uint8 grey frames (detector input and its
        median+Gaussian cleaned copy). blobs: candidates (x, y, radius) in
        SENSOR pixels. Returns self. All statistics are 256-bin
        histograms (cheap: ~1 ms/frame in total)."""
        t0 = time.perf_counter()
        small = cv2.resize(cleaned, self.small_size, interpolation=cv2.INTER_AREA)
        fill = self._pct(cv2.calcHist([small], [0], None, [256], [0, 256]).ravel(), 0.5)
        if blobs:
            for bx, by, br in blobs:
                cv2.circle(small, (int(bx / self.scale_x), int(by / self.scale_y)),
                           int((3 * br + 40) / self.scale_x), int(fill), -1)
        hist = cv2.calcHist([small], [0], None, [256], [0, 256]).ravel()
        fill = self._pct(hist, 0.5)
        self.small, self.fill = small, fill

        m = self._streaks(small, fill)
        frac = float(m.sum()) / m.size if m is not None else 0.0
        self.streak_frac = frac
        self.streak_mask = m if frac >= self.streak_min_frac else None

        contrast = self._pct(hist, 0.999) - fill
        if raw is not None:
            sub = raw[::4, ::4]       # 160x120: ample for a robust sigma
            f = sub.astype(np.float32)
            hp = cv2.absdiff(f, cv2.blur(f, (3, 3)))
            # 1/8-grey-level bins over [0, 64): an integer MAD is too coarse
            # to separate low-light read noise (2.5) from shot noise (3.6).
            h = cv2.calcHist([hp], [0], None, [512], [0, 64]).ravel()
            sigma = 1.4826 * self._pct(h, 0.5) / 8.0
            sat = float(cv2.calcHist([sub], [0], None, [256], [0, 256])[250:].sum()) / sub.size
        else:
            sigma, sat = 0.0, 0.0
        self.star_level = self._star_level(cleaned, blobs)

        self.background  = self._ema(self.background, fill, dt, TAU_LEVEL_S)
        self.contrast    = self._ema(self.contrast, contrast, dt, TAU_LEVEL_S)
        self.noise_sigma = self._ema(self.noise_sigma, sigma, dt, TAU_LEVEL_S)
        self.saturation  = self._ema(self.saturation, sat, dt, TAU_LEVEL_S)
        deg = self._degradation(fill, self.star_level, frac)
        noise_est = self._noise(sigma, sat)
        self.degradation = self._ema_att(self.degradation, deg, dt)
        self.noise_level = self._ema_att(self.noise_level, noise_est, dt)
        self.raw = {'background': fill, 'contrast': contrast, 'noise_sigma': sigma,
                    'streak_frac': frac, 'star_level': self.star_level,
                    'saturation': sat, 'degradation': deg, 'noise_est': noise_est}
        self.last_ms = (time.perf_counter() - t0) * 1000.0
        return self

    @property
    def visibility(self):
        return None if self.degradation is None else 1.0 - self.degradation

    def params(self):
        """Adaptive tracker behaviour from the smoothed estimates. Clear-sky
        set at degradation 0, degraded set at 1, linear in between; then
        lowered with the sensor-noise level (above 0.3). The two end sets
        are the former hand-set clear / degraded gates; which point in
        between applies is now measured from the image."""
        d = 0.0 if self.degradation is None else self.degradation
        n = 0.0 if self.noise_level is None else self.noise_level
        p = {
            'lock_threshold':     0.82 - 0.10 * d,
            'brightness_min':     100.0 - 40.0 * d,
            'position_std_limit': 40.0 + 26.67 * d,
            'min_acquire_frames': int(round(8 - 3 * d)),
            'max_coast_frames':   int(round(45 + 45 * d)),
            # Hysteresis: a dim beacon's CNN score flickers. Training seeds
            # 1000-1001 under rain + low light (degradation 1): the beacon's
            # 8-frame mean confidence is < 0.35 in 8.1 % of frames, p1 0.15,
            # median 0.55; clear: never < 0.35 (scratch/p3/calib_conf.log).
            'unlock_threshold':    0.35 - 0.23 * d,
            'reacquire_threshold': 0.85 - 0.10 * d,
        }
        if n > 0.3:
            p['lock_threshold'] = max(0.65, p['lock_threshold'] - n * 0.1)
            p['brightness_min'] = max(40.0, p['brightness_min'] - n * 30)
        return p
