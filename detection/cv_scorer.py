"""
Hand-made beacon score — detector mode 'cv' (Step 5a)
=====================================================
Scores blob-detector candidates WITHOUT the CNN, from four hand-made
features of the same 32x32 patch the CNN would see:

  peak       brightest pixel in the patch centre (grey levels / 255)
  size       area (px) of the blob above half its height over background
  square     squareness of that blob = area / bounding-box area
             (a filled square -> 1.0, a disc -> ~0.79)
  contrast   blob mean minus the mean of a surrounding ring (/255)

score = sigmoid(w . [peak, size/100, square, contrast] + bias), in 0..1.
Weights come from config (detection.cv_weights / cv_bias); they were fitted
ONLY on the CNN training seeds 1000-1005 (scratch/s5/fit_cv.py).
"""
import numpy as np

FEATURES = ('peak', 'size', 'square', 'contrast')


def patch_features(patch):
    """patch: (32, 32) float [0,1]. Returns a (4,) float array."""
    p = np.asarray(patch, dtype=np.float32)
    c = p[8:24, 8:24]                                   # 16x16 centre
    ring = np.concatenate([p[2:6, 2:30].ravel(), p[26:30, 2:30].ravel(),
                           p[6:26, 2:6].ravel(), p[6:26, 26:30].ravel()])
    bg = float(np.median(ring))
    peak = float(c.max())
    thr = bg + 0.5 * (peak - bg)
    m = c >= thr
    # Keep only the connected region around the brightest pixel (simple
    # flood via repeated dilation inside the mask).
    iy, ix = np.unravel_index(int(np.argmax(c)), c.shape)
    reg = np.zeros_like(m)
    reg[iy, ix] = True
    for _ in range(16):
        grown = reg.copy()
        grown[1:, :] |= reg[:-1, :]
        grown[:-1, :] |= reg[1:, :]
        grown[:, 1:] |= reg[:, :-1]
        grown[:, :-1] |= reg[:, 1:]
        grown &= m
        if (grown == reg).all():
            break
        reg = grown
    area = float(reg.sum())
    ys, xs = np.nonzero(reg)
    bbox = float((ys.max() - ys.min() + 1) * (xs.max() - xs.min() + 1))
    square = area / bbox if bbox > 0 else 0.0
    contrast = float(c[reg].mean()) - float(ring.mean())
    return np.array([peak, area, square, contrast], dtype=np.float32)


def feature_vector(patch):
    f = patch_features(patch)
    return np.array([f[0], f[1] / 100.0, f[2], f[3]], dtype=np.float32)


class CVScorer:
    """Drop-in for BeaconClassifier.classify() without a CNN."""

    SINGLE_FRAME_THRESHOLD = 0.60

    def __init__(self, cfg):
        d = cfg.get('detection') or {}
        self.w = np.asarray(d.get('cv_weights', [0.0, 0.0, 0.0, 0.0]), dtype=np.float64)
        self.b = float(d.get('cv_bias', 0.0))
        # Operating-point calibration (Step 5c): temporal fusion locks at
        # 0.82, a level chosen for the CNN's scores. The raw CV score's own
        # operating threshold (chosen on the training seeds only) is mapped
        # to that level by a monotonic piecewise-linear rescale:
        #   [0, t] -> [0, 0.82],  [t, 1] -> [0.82, 1].
        # None = raw score (the Step 5b 'first run').
        t = d.get('cv_operating_threshold')
        self.op_t = None if t is None else float(t)
        self.op_level = float(d.get('cv_operating_level', 0.82))

    def raw_score(self, patch):
        z = float(self.w @ feature_vector(patch)) + self.b
        return float(1.0 / (1.0 + np.exp(-z)))

    def calibrate(self, s):
        t, L = self.op_t, self.op_level
        if t is None:
            return s
        if s <= t:
            return L * s / t
        return L + (1.0 - L) * (s - t) / (1.0 - t)

    def score(self, patch):
        return self.calibrate(self.raw_score(patch))

    def classify(self, candidates):
        for c in candidates:
            c.confidence = self.score(c.patch)
            c.is_beacon = c.confidence >= self.SINGLE_FRAME_THRESHOLD
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates
