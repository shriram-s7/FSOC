"""
Beacon Detector — Stage 4A
===========================
Finds bright candidate blobs in the disturbed camera frame.
This is Stage 1 of the 2-stage detection pipeline:
  Stage 1 (this file): Find ALL bright candidates via OpenCV blob detection
  Stage 2 (classifier.py): CNN classifies each candidate as beacon or decoy

CRITICAL DESIGN RULE:
  This detector NEVER reads the true target position.
  It only sees the raw pixel frame — exactly like a real camera sensor.
  Input:  pygame.Surface (the disturbed camera frame)
  Output: list of Candidate objects (position, size, brightness, patch)

Pipeline:
  pygame Surface
    → numpy array
    → grayscale
    → preprocessing (blur, normalize)
    → blob detection
    → filter by size/brightness/circularity
    → extract 32x32 patch around each candidate
    → return list of Candidate objects
"""

import cv2
import numpy as np
import pygame
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


@dataclass
class Candidate:
    """
    A detected blob candidate in the camera frame.
    May or may not be the true beacon — classifier decides.
    
    Attributes:
        x, y        : pixel position in frame (float)
        radius      : estimated blob radius in pixels (float)
        brightness  : mean pixel intensity in blob region (float, 0-255)
        circularity : how circular the blob is (float, 0-1, 1=perfect circle)
        patch       : 32x32 grayscale numpy array centered on candidate
        confidence  : CNN confidence score (set by classifier, default 0.0)
        is_beacon   : classifier decision (set by classifier, default None)
    """
    x: float
    y: float
    radius: float
    brightness: float
    circularity: float
    patch: np.ndarray          # shape (32, 32), dtype float32, range [0,1]
    confidence: float = 0.0    # filled by classifier
    is_beacon: Optional[bool] = None  # filled by classifier


class BeaconDetector:
    """
    Detects bright blob candidates in a camera frame using OpenCV.
    
    Two detection methods run in parallel and results are merged:
      Method A: SimpleBlobDetector (fast, good for clean frames)
      Method B: Contour-based (more robust under noise/disturbance)
    
    Results are deduplicated by proximity.
    Each candidate gets a 32x32 patch extracted for CNN classification.
    """
    
    # Patch size for CNN input
    PATCH_SIZE = 32
    
    # Minimum distance between two candidates (pixels) — deduplication
    MIN_CANDIDATE_DIST = 12.0

    # Raw blob detections kept for merging/patch extraction, ranked by
    # (smoothed brightness x area). Bounds per-frame cost under noise.
    TOP_K_RAW = 15
    
    def __init__(self, cfg):
        self.cfg = cfg
        self.width  = cfg.window.width
        self.height = cfg.window.height
        
        # SimpleBlobDetector params
        params = cv2.SimpleBlobDetector_Params()
        params.filterByArea      = True
        params.minArea           = 8        # min 8 pixels area
        params.maxArea           = 800      # max 800 pixels area
        params.filterByCircularity = True
        params.minCircularity    = 0.4      # moderately circular
        params.filterByConvexity = True
        params.minConvexity      = 0.7
        params.filterByInertia   = False
        params.filterByColor     = True
        params.blobColor         = 255      # detect bright blobs
        params.minDistBetweenBlobs = 8.0
        params.minThreshold      = 40
        params.maxThreshold      = 255
        params.thresholdStep     = 20
        self._blob_detector = cv2.SimpleBlobDetector_create(params)
        
        # Stats
        self.last_candidate_count = 0
        self.last_processing_ms   = 0.0

    def _surface_to_gray(self, surface: pygame.Surface) -> np.ndarray:
        """
        Convert pygame Surface to grayscale numpy array.
        Returns: (H, W) uint8 array
        """
        rgb = pygame.surfarray.pixels3d(surface)          # (W, H, 3)
        rgb = np.transpose(rgb, (1, 0, 2))                # → (H, W, 3)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        return gray

    def _preprocess(self, gray: np.ndarray) -> np.ndarray:
        """
        Preprocess grayscale frame for blob detection.
        Applies mild blur to reduce noise, then normalizes contrast.
        """
        # Mild Gaussian blur — reduces noise without blurring blobs much
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        
        # CLAHE — enhances local contrast (helps in high-noise conditions)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(blurred)
        
        return enhanced

    def _extract_patch(self, gray: np.ndarray, cx: float, cy: float) -> np.ndarray:
        """
        Extract a PATCH_SIZE x PATCH_SIZE region centered on (cx, cy).
        Pads with zeros if near the frame border.
        Returns: float32 array, normalized to [0, 1].
        """
        half = self.PATCH_SIZE // 2
        x1 = int(cx) - half
        y1 = int(cy) - half
        x2 = x1 + self.PATCH_SIZE
        y2 = y1 + self.PATCH_SIZE
        
        # Pad frame if needed
        pad_l = max(0, -x1)
        pad_t = max(0, -y1)
        pad_r = max(0, x2 - self.width)
        pad_b = max(0, y2 - self.height)
        
        x1c = max(0, x1); y1c = max(0, y1)
        x2c = min(self.width, x2); y2c = min(self.height, y2)
        
        patch = np.zeros((self.PATCH_SIZE, self.PATCH_SIZE), dtype=np.uint8)
        region = gray[y1c:y2c, x1c:x2c]
        
        if region.size > 0:
            rh, rw = region.shape
            patch[pad_t:pad_t+rh, pad_l:pad_l+rw] = region
        
        return patch.astype(np.float32) / 255.0

    def _compute_circularity(self, contour) -> float:
        """Compute circularity = 4π·Area / Perimeter² (1.0 = perfect circle)."""
        area = cv2.contourArea(contour)
        perimeter = cv2.arcLength(contour, True)
        if perimeter < 1e-6:
            return 0.0
        return min(1.0, (4 * np.pi * area) / (perimeter ** 2))

    def _detect_blobs_simple(self, preprocessed: np.ndarray) -> List[Tuple]:
        """
        Method A: OpenCV SimpleBlobDetector.
        Returns list of (x, y, radius) tuples.
        """
        # SimpleBlobDetector needs inverted image for bright blobs
        # Actually blobColor=255 means detect bright, so no inversion needed
        keypoints = self._blob_detector.detect(preprocessed)
        results = []
        for kp in keypoints:
            x, y = kp.pt
            r = kp.size / 2.0
            results.append((x, y, max(r, 2.0)))
        return results

    def _detect_blobs_contour(self, gray: np.ndarray,
                               preprocessed: np.ndarray) -> List[Tuple]:
        """
        Method B: Adaptive threshold + contour detection.
        More robust than SimpleBlobDetector under heavy noise.
        Returns list of (x, y, radius) tuples.
        """
        # Adaptive threshold — finds bright regions relative to local background
        thresh = cv2.adaptiveThreshold(
            preprocessed, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            blockSize=15,
            C=-8
        )
        
        # Also apply global threshold for very bright regions
        _, global_thresh = cv2.threshold(preprocessed, 180, 255, cv2.THRESH_BINARY)
        
        # Combine both
        combined = cv2.bitwise_or(thresh, global_thresh)
        
        # Morphological closing — fills small gaps in blobs
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel)
        
        contours, _ = cv2.findContours(
            combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        results = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 6 or area > 1000:
                continue
            
            M = cv2.moments(cnt)
            if M['m00'] < 1e-6:
                continue
            
            cx = M['m10'] / M['m00']
            cy = M['m01'] / M['m00']
            radius = np.sqrt(area / np.pi)
            
            # Brightness check — must be genuinely bright
            bx, by, bw, bh = cv2.boundingRect(cnt)
            sub_gray = gray[by:by+bh, bx:bx+bw]
            sub_mask = np.zeros((bh, bw), dtype=np.uint8)
            cv2.drawContours(sub_mask, [cnt - [bx, by]], -1, 255, -1)
            mean_val = cv2.mean(sub_gray, mask=sub_mask)[0]
            if mean_val < 60:
                continue
            
            results.append((cx, cy, max(radius, 2.0)))
        
        return results

    def _merge_and_deduplicate(self, gray: np.ndarray,
                                detections: List[Tuple]) -> List[Candidate]:
        """
        Merge detections from both methods.
        Remove duplicates within MIN_CANDIDATE_DIST pixels.
        Build Candidate objects with patches.
        Returns list of Candidate objects, sorted by brightness (desc).
        """
        if not detections:
            return []
        
        # Deduplicate by distance — of two detections within
        # MIN_CANDIDATE_DIST, keep the brighter one (tie: larger area), so
        # a dim star next to the beacon can never displace the beacon.
        def blob_brightness(x, y, r):
            ir = int(r) + 2
            x1 = max(0, int(x) - ir); x2 = min(self.width,  int(x) + ir)
            y1 = max(0, int(y) - ir); y2 = min(self.height, int(y) + ir)
            region = gray[y1:y2, x1:x2]
            return float(region.mean()) if region.size > 0 else 0.0
        ranked = sorted(detections,
                        key=lambda d: (blob_brightness(*d), d[2]),
                        reverse=True)
        kept = []
        for (x, y, r) in ranked:
            too_close = False
            for (kx, ky, _) in kept:
                if np.hypot(x - kx, y - ky) < self.MIN_CANDIDATE_DIST:
                    too_close = True
                    break
            if not too_close:
                kept.append((x, y, r))
        
        # Build Candidate objects
        candidates = []
        for (x, y, r) in kept:
            # Bounds check
            if not (0 <= x < self.width and 0 <= y < self.height):
                continue
            
            # Extract patch
            patch = self._extract_patch(gray, x, y)
            
            # Compute brightness in local region
            ir = int(r) + 2
            x1 = max(0, int(x) - ir); x2 = min(self.width,  int(x) + ir)
            y1 = max(0, int(y) - ir); y2 = min(self.height, int(y) + ir)
            region = gray[y1:y2, x1:x2]
            brightness = float(region.mean()) if region.size > 0 else 0.0
            
            if brightness < 40:
                continue
            
            # Estimate circularity from patch
            patch_u8 = (patch * 255).astype(np.uint8)
            _, thr = cv2.threshold(patch_u8, 100, 255, cv2.THRESH_BINARY)
            cnts, _ = cv2.findContours(thr, cv2.RETR_EXTERNAL,
                                        cv2.CHAIN_APPROX_SIMPLE)
            circularity = 0.5
            if cnts:
                largest = max(cnts, key=cv2.contourArea)
                circularity = self._compute_circularity(largest)
            
            candidates.append(Candidate(
                x=x, y=y, radius=r,
                brightness=brightness,
                circularity=circularity,
                patch=patch
            ))
        
        # Sort by brightness descending
        candidates.sort(key=lambda c: c.brightness, reverse=True)
        
        # Cap at 10 candidates max (performance)
        return candidates[:10]

    def detect(self, surface: pygame.Surface) -> List[Candidate]:
        """
        Main detection entry point. Call every frame.
        
        Args:
            surface: pygame.Surface — the (possibly disturbed) camera frame
        
        Returns:
            List[Candidate] — sorted by brightness desc, confidence=0.0
                              (call classifier.classify() to fill confidence)
        """
        import time
        t0 = time.perf_counter()
        
        gray = self._surface_to_gray(surface)
        # Blob FINDING runs on a cleaned copy: a 3x3 median removes salt &
        # pepper and single-pixel specks, and a light 5x5 Gaussian blur
        # stops Gaussian sensor noise from splitting into thousands of
        # tiny contours. Brightness checks, CNN patches and ranking still
        # use the ORIGINAL grey frame (`gray`), so the CNN sees what it
        # was trained on.
        cleaned = cv2.GaussianBlur(cv2.medianBlur(gray, 3), (5, 5), 0)
        self.last_cleaned = cleaned   # reused by the tracker's image stabiliser
        self.last_gray = gray         # raw frame, for the scene estimator (noise, saturation)
        preprocessed = self._preprocess(cleaned)
        
        # Run both detection methods
        simple_dets   = self._detect_blobs_simple(preprocessed)
        contour_dets  = self._detect_blobs_contour(gray, preprocessed)
        
        # Merge — keep only the TOP_K_RAW strongest raw detections, ranked
        # by brightness (cleaned frame at the blob centre) x area (r^2).
        all_dets = simple_dets + contour_dets
        h, w = cleaned.shape
        def strength(d):
            x, y, r = d
            xi = min(w - 1, max(0, int(x))); yi = min(h - 1, max(0, int(y)))
            return float(cleaned[yi, xi]) * r * r
        all_dets = sorted(all_dets, key=strength, reverse=True)[:self.TOP_K_RAW]
        
        candidates = self._merge_and_deduplicate(gray, all_dets)
        
        self.last_candidate_count = len(candidates)
        self.last_processing_ms = (time.perf_counter() - t0) * 1000
        
        return candidates

    def debug_draw(self, surface: pygame.Surface,
                   candidates: List[Candidate]) -> None:
        """
        Draw detection results on surface for debugging.
        Call AFTER detect() to visualize what was found.
        Draws cyan circles around all detected candidates.
        """
        for c in candidates:
            pygame.draw.circle(
                surface, (0, 200, 255),
                (int(c.x), int(c.y)),
                int(c.radius) + 4, 1
            )
            # Brightness label
            font = pygame.font.SysFont('Consolas', 10)
            txt = font.render(f'{c.brightness:.0f}', True, (0, 200, 255))
            surface.blit(txt, (int(c.x) + int(c.radius) + 5, int(c.y) - 5))
