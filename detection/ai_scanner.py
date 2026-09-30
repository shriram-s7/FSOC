"""
Whole-frame CNN scanner — detector mode 'ai' (Step 5a)
======================================================
No blob detector. The CNN v2 (same weights as hybrid) scores EVERY 32x32
window of the grey frame on a stride-8 grid -> confidence map -> local
maxima (non-max suppression) -> candidates.

Implementation: the CNN's three conv+pool blocks halve the resolution
three times, so running them once over the whole frame gives a feature
map at exactly 1/8 resolution; every 4x4 block of it is the feature
tensor of one 32x32 window at stride 8, which the CNN's classifier head
(Flatten + FC) then scores in one batch. This is the sliding window with
the shared convolution work computed once instead of per window. One
difference from scoring cut-out patches: at a window's edge the convs see
the real neighbouring pixels instead of zero padding.

Each peak's position is refined to sub-cell accuracy by a background-
subtracted intensity centroid inside the peak's own 16x16 window (the CNN
grid is 8 px; this is the detector's regression step, it uses no blobs).
"""
import time

import cv2
import numpy as np
import pygame
import torch

from detection.detector import Candidate


class AIScanner:
    PATCH = 32
    STRIDE = 8

    def __init__(self, cfg, classifier, detector):
        """classifier: BeaconClassifier (its CNN is reused); detector: the
        BeaconDetector, used ONLY for its frame conversion / patch cut-out
        helpers and to publish last_cleaned for the image stabiliser."""
        self.model = classifier.model
        self.det = detector
        d = cfg.get('detection') or {}
        self.min_conf = float(d.get('ai_min_conf', 0.3))
        self.max_cands = 10
        self.last_candidate_count = 0
        self.last_processing_ms = 0.0
        self.last_map = None

    @torch.no_grad()
    def confidence_map(self, gray):
        """(H/8-3, W/8-3) map: P(beacon) of the 32x32 window whose top-left
        corner is (8*j, 8*i)."""
        x = torch.from_numpy(gray.astype(np.float32) / 255.0)[None, None]
        f = self.model.features(x)                       # (1, 32, H/8, W/8)
        win = f.unfold(2, 4, 1).unfold(3, 4, 1)          # (1,32,h,w,4,4)
        h, w = win.shape[2], win.shape[3]
        win = win.permute(0, 2, 3, 1, 4, 5).reshape(h * w, 32 * 4 * 4)
        logits = self.model.classifier[1:](win)          # skip Flatten
        return torch.softmax(logits, 1)[:, 1].reshape(h, w).numpy()

    def detect(self, surface: pygame.Surface):
        t0 = time.perf_counter()
        gray = self.det._surface_to_gray(surface)
        # Publish the current input for the shared scene estimator, as CV does.
        self.det.last_gray = gray
        # Same cleaned frame the blob detector would publish — the image
        # stabiliser (identical in every mode) reads it. Not used here.
        self.det.last_cleaned = cv2.GaussianBlur(cv2.medianBlur(gray, 3), (5, 5), 0)

        cmap = self.confidence_map(gray)
        self.last_map = cmap
        # Non-max suppression: 3x3-cell local maxima above min_conf.
        dil = cv2.dilate(cmap, np.ones((3, 3), np.uint8))
        peaks = np.argwhere((cmap >= dil) & (cmap >= self.min_conf))
        order = np.argsort(-cmap[peaks[:, 0], peaks[:, 1]])
        H, W = gray.shape
        cands, taken = [], []
        for i, j in peaks[order]:
            cx = self.STRIDE * j + self.PATCH / 2
            cy = self.STRIDE * i + self.PATCH / 2
            x, y, r, bright = self._refine(gray, cx, cy)
            if any(np.hypot(x - a, y - b) < 12.0 for a, b in taken):
                continue
            taken.append((x, y))
            c = Candidate(x=x, y=y, radius=r, brightness=bright,
                          circularity=0.5, patch=self.det._extract_patch(gray, x, y))
            c.confidence = float(cmap[i, j])
            c.is_beacon = c.confidence >= 0.60
            cands.append(c)
            if len(cands) >= self.max_cands:
                break
        self.last_candidate_count = len(cands)
        self.last_processing_ms = (time.perf_counter() - t0) * 1000
        return cands

    def _refine(self, gray, cx, cy):
        H, W = gray.shape
        x1, y1 = int(max(0, cx - 8)), int(max(0, cy - 8))
        x2, y2 = int(min(W, cx + 8)), int(min(H, cy + 8))
        reg = gray[y1:y2, x1:x2].astype(np.float32)
        if reg.size == 0:
            return cx, cy, 2.0, 0.0
        bg = float(np.median(reg))
        wgt = np.clip(reg - bg, 0, None)
        wgt[wgt < 0.5 * wgt.max()] = 0.0
        s = float(wgt.sum())
        if s <= 0:
            return cx, cy, 2.0, float(reg.mean())
        ys, xs = np.mgrid[y1:y2, x1:x2]
        x = float((wgt * xs).sum() / s)
        y = float((wgt * ys).sum() / s)
        area = float((wgt > 0).sum())
        r = max(2.0, float(np.sqrt(area / np.pi)))
        # Brightness exactly as the blob detector measures it (local mean
        # over radius+2), so temporal fusion's consistency check compares
        # like with like.
        ir = int(r) + 2
        bx1, bx2 = max(0, int(x) - ir), min(W, int(x) + ir)
        by1, by2 = max(0, int(y) - ir), min(H, int(y) + ir)
        bright = float(gray[by1:by2, bx1:bx2].mean())
        return x, y, r, bright
