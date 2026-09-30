"""
Image stabiliser — star-field phase correlation
================================================
Stars are fixed in the world, so the frame-to-frame translation of the
whole image, minus the shift the commanded camera pan/tilt should cause,
is platform jitter. Estimated from the image alone (never from the
disturbance engine), high-passed, and handed to the tracker so it can
gate/update in stabilised coordinates.
"""
import time

import cv2
import numpy as np


class ImageStabiliser:
    def __init__(self, full_size=(640, 480), small_size=(320, 240),
                 min_response=0.2, max_shift=60.0,
                 highpass_alpha=0.05, keyframe_frames=30,
                 keyframe_max_move=80.0):
        self.small_size   = small_size
        self.scale_x      = full_size[0] / small_size[0]
        self.scale_y      = full_size[1] / small_size[1]
        self.min_response = min_response
        # Larger than any plausible jitter (+/-20) plus jerk (35) offset.
        self.max_shift    = max_shift
        self._window = cv2.createHanningWindow(small_size, cv2.CV_32F)
        # Jitter is zero-mean, but the image only gives it relative to the
        # first frame and summing per-frame shifts random-walks. The
        # accumulated shift is therefore high-passed (minus its slow EMA,
        # ~0.5 Hz at 60 fps; vibration is 6-15 Hz) — anything slower is
        # real drift the Kalman model already absorbs.
        self.highpass_alpha = highpass_alpha
        # Frames are correlated against a keyframe (refreshed every
        # keyframe_frames, or once the camera has moved keyframe_max_move
        # px since it), not the previous frame: stars are drawn on integer
        # pixels and phaseCorrelate's sub-pixel estimate of such small
        # steps is biased, so chaining frame-to-frame shifts drifts.
        self.keyframe_frames   = keyframe_frames
        self.keyframe_max_move = keyframe_max_move
        # Rain mode (Prompt 3): the scene estimator decides from the
        # image when streaks cover enough of the frame to count as rain and
        # hands over their mask; those pixels are blanked and correlation
        # runs on a 3x3 compact-feature opening (streak remnants vanish).
        self.streak_px = 0            # pixels blanked this frame
        self._ref = None
        self._ref_compact = None
        self._ref_off = [0.0, 0.0]   # raw offset estimate at the keyframe
        self._ref_exp = [0.0, 0.0]   # commanded image shift since keyframe
        self._ref_age = 0
        self._raw  = [0.0, 0.0]      # raw offset relative to frame 0
        self._mean = [0.0, 0.0]      # slow EMA of _raw
        self.offset   = (0.0, 0.0)   # jitter estimate (px), high-passed
        self.jitter   = (0.0, 0.0)   # this frame's jitter estimate (px)
        self.response = 0.0
        self.last_ms  = 0.0
        # Own uncertainty (px): a weak correlation peak (< reliable_response;
        # clean star fields give >= 0.58) may be a wrong peak, off by up to
        # the jitter amplitude - estimated as the RMS of this stabiliser's
        # own recent offsets. 0 when the peak is strong.
        self.reliable_response = 0.5
        self._off_sq = 0.0
        self.uncertainty = 0.0

    def reset(self):
        self._ref = None
        self._ref_compact = None
        self._ref_off = [0.0, 0.0]
        self._ref_exp = [0.0, 0.0]
        self._ref_age = 0
        self._raw  = [0.0, 0.0]
        self._mean = [0.0, 0.0]
        self.offset = (0.0, 0.0)
        self.jitter = (0.0, 0.0)

    def update(self, gray, expected_dx, expected_dy, blobs=(),
               prepared=None, fill=None, streak_mask=None):
        """gray: full-res (H, W) uint8 frame, denoised (the detector's
        median+Gaussian cleaned frame; salt & pepper defeats correlation).
        expected_dx/dy: image shift (px) the commanded camera move since
        the previous frame should cause. blobs: detected candidates (x, y, radius in full-res px) -
        the beacon and moving distractors, which are blanked out so only
        the world-fixed star field drives the correlation (the beacon the
        camera follows would otherwise bias it toward zero shift).
        prepared / fill: the same small frame with the blobs already
        blanked (SceneEstimator.small / .fill) - used instead of gray.
        streak_mask: rain-streak mask from the scene estimator (rain mode)
        or None.
        Returns the accumulated jitter offset (x, y)."""
        t0 = time.perf_counter()
        if prepared is not None:
            small = prepared.astype(np.float32)
        else:
            small = cv2.resize(gray, self.small_size,
                               interpolation=cv2.INTER_AREA).astype(np.float32)
            if blobs:
                fill = float(np.median(small))
                for bx, by, br in blobs:
                    cv2.circle(small, (int(bx / self.scale_x), int(by / self.scale_y)),
                               int((3 * br + 40) / self.scale_x), fill, -1)
        self.streak_px = 0
        if streak_mask is not None:
            if fill is None:
                fill = float(np.median(small))
            small[streak_mask > 0] = fill
            self.streak_px = int(streak_mask.sum())
        self.response = 0.0
        raw = list(self._raw)
        if self._ref is not None:
            self._ref_exp[0] += expected_dx
            self._ref_exp[1] += expected_dy
            # Warp the keyframe by the commanded camera move since it was
            # taken, so the correlation measures jitter only.
            M = np.float32([[1, 0, self._ref_exp[0] / self.scale_x],
                            [0, 1, self._ref_exp[1] / self.scale_y]])
            use_compact = bool(self.streak_px)
            ref_source = (self._ref_compact if use_compact
                          else self._ref)
            current = (cv2.morphologyEx(
                small, cv2.MORPH_OPEN,
                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
                if use_compact else small)
            ref = cv2.warpAffine(ref_source, M, self.small_size,
                                 borderMode=cv2.BORDER_REPLICATE)
            (sx, sy), resp = cv2.phaseCorrelate(ref, current, self._window)
            self.response = float(resp)
            rx, ry = sx * self.scale_x, sy * self.scale_y
            # Weak peak (fog, noise, few stars) or implausible jump: hold
            # the previous estimate, i.e. this frame's jitter = (0, 0).
            # Compact-feature correlation suppresses rain streaks directly;
            # use the normal minimum response on that filtered representation.
            min_resp = self.min_response
            if (resp >= min_resp
                    and np.hypot(rx, ry) <= self.max_shift):
                raw = [self._ref_off[0] + rx, self._ref_off[1] + ry]
        self._ref_age += 1
        if (self._ref is None or self._ref_age >= self.keyframe_frames
                or np.hypot(*self._ref_exp) > self.keyframe_max_move):
            self._ref, self._ref_off = small, list(raw)
            self._ref_compact = cv2.morphologyEx(
                small, cv2.MORPH_OPEN,
                cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
            self._ref_exp, self._ref_age = [0.0, 0.0], 0
        jx, jy = raw[0] - self._raw[0], raw[1] - self._raw[1]
        self._raw = raw
        self.jitter = (jx, jy)
        a = self.highpass_alpha
        for i in (0, 1):
            self._mean[i] += a * (self._raw[i] - self._mean[i])
        self.offset = (self._raw[0] - self._mean[0],
                       self._raw[1] - self._mean[1])
        self._off_sq += 0.05 * (self.offset[0] ** 2 + self.offset[1] ** 2 - self._off_sq)
        weak = float(np.clip((self.reliable_response - self.response) / 0.3, 0.0, 1.0))
        self.uncertainty = weak * float(np.sqrt(self._off_sq)) if self._ref_age else 0.0
        self.last_ms = (time.perf_counter() - t0) * 1000.0
        return self.offset
