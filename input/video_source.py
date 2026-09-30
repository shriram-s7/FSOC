"""
FSOC-PAT Simulator — Video File Frame Source.

Provides a concrete implementation of FrameSource that streams frames from
an external video file (e.g. MP4) using OpenCV VideoCapture, with optional
ground truth loading from CSV files for benchmark validation.
"""

import os
import csv
from typing import Dict, Optional, Tuple
import cv2
import numpy as np

from input.frame_source import FrameSource


def find_gt_csv(video_path: str) -> Optional[str]:
    """Return '<video stem>_gt.csv' next to the video if it exists."""
    p = os.path.splitext(video_path)[0] + '_gt.csv'
    return p if os.path.exists(p) else None


class VideoSource(FrameSource):
    """
    Video file frame source backed by OpenCV VideoCapture.

    Ingests external video files, converts BGR video frames into the simulation's
    standard RGB uint8 640x480 format, tracks playback progress, and optionally
    supplies frame-synchronized ground truth coordinates from a CSV file.
    """

    TARGET_WIDTH = 640
    TARGET_HEIGHT = 480

    def __init__(self, filepath: str):
        """
        Initialize the video source and open the video stream.

        Args:
            filepath (str): Path to the video file (e.g. MP4).

        Raises:
            IOError: If the video file does not exist or cannot be opened by OpenCV.
        """
        if not os.path.exists(filepath):
            raise IOError(f"Video file not found: {filepath}")

        self.filepath = filepath
        self._cap = cv2.VideoCapture(filepath)

        if not self._cap.isOpened():
            raise IOError(f"Failed to open video file via cv2.VideoCapture: {filepath}")

        # Query native video frame rate
        fps = self._cap.get(cv2.CAP_PROP_FPS)
        self._fps = float(fps) if (fps and fps > 0.0) else 30.0

        # Query total frame count
        total = self._cap.get(cv2.CAP_PROP_FRAME_COUNT)
        self._total_frames = int(total) if total > 0 else 0

        self._frame_idx = 0
        self._gt_data: Optional[Dict[int, Tuple[float, float]]] = None

    def load_ground_truth(self, csv_path: str) -> None:
        """
        Load per-frame ground truth coordinates from a CSV file.

        Expects CSV headers or columns containing 'frame', 'x', and 'y'.
        Coordinates must be in screen pixel coordinates relative to 640x480.

        Args:
            csv_path (str): Path to the ground truth CSV file.

        Raises:
            IOError: If the CSV file cannot be opened.
        """
        if not os.path.exists(csv_path):
            raise IOError(f"Ground truth CSV file not found: {csv_path}")

        gt_dict: Dict[int, Tuple[float, float]] = {}

        with open(csv_path, mode='r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                self._gt_data = gt_dict
                return

            # Identify column indices
            col_map = {name.strip().lower(): idx for idx, name in enumerate(header)}
            f_idx = col_map.get('frame', 0)
            x_idx = col_map.get('x', 1)
            y_idx = col_map.get('y', 2)

            for row in reader:
                if not row or len(row) < 3:
                    continue
                try:
                    f_num = int(float(row[f_idx].strip()))
                    x_val = float(row[x_idx].strip())
                    y_val = float(row[y_idx].strip())
                    visible_index = col_map.get('visible')
                    if visible_index is not None and row[visible_index].strip().lower() in ('0','false','no'):
                        continue
                    gt_dict[f_num] = (x_val, y_val)
                except (ValueError, IndexError):
                    continue

        self._gt_data = gt_dict

    def get_frame(self) -> Tuple[Optional[np.ndarray], Optional[Tuple[float, float]], bool]:
        """
        Read the next frame from the video stream.

        Converts frame to RGB uint8 and resizes to 640x480 if necessary.

        Returns:
            tuple: (frame, ground_truth, is_done)
                - frame (np.ndarray or None): RGB uint8 array of shape (480, 640, 3)
                  or None if end-of-file.
                - ground_truth (tuple of (float, float) or None): (x, y) beacon pixel
                  coordinates for this frame, or None if no ground truth was provided.
                - is_done (bool): True if end-of-video reached or frame read failed.
        """
        if not self._cap.isOpened():
            return None, None, True

        ret, bgr_frame = self._cap.read()
        if not ret or bgr_frame is None:
            return None, None, True

        current_idx = self._frame_idx
        self._frame_idx += 1

        # Look up ground truth (check 0-indexed and 1-indexed representations)
        gt = None
        if self._gt_data is not None:
            if current_idx in self._gt_data:
                gt = self._gt_data[current_idx]

        # Convert OpenCV BGR -> standard simulation RGB format
        rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)

        # Ensure frame dimensions strictly match 640x480
        h, w = rgb_frame.shape[:2]
        if w != self.TARGET_WIDTH or h != self.TARGET_HEIGHT:
            interpolation = cv2.INTER_AREA if (w > self.TARGET_WIDTH and h > self.TARGET_HEIGHT) else cv2.INTER_LINEAR
            rgb_frame = cv2.resize(rgb_frame, (self.TARGET_WIDTH, self.TARGET_HEIGHT), interpolation=interpolation)

        if rgb_frame.dtype != np.uint8:
            rgb_frame = rgb_frame.astype(np.uint8)
        rgb_frame = np.ascontiguousarray(rgb_frame)

        return rgb_frame, gt, False

    def get_progress(self) -> Tuple[int, int]:
        """
        Return the current playback progress.

        Returns:
            tuple: (current_frame_index, total_frames)
        """
        return self._frame_idx, self._total_frames

    def reset(self) -> None:
        """Seek VideoCapture back to frame 0 and reset counter."""
        if self._cap.isOpened():
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        self._frame_idx = 0

    def get_fps(self) -> float:
        """
        Return the native FPS of the video stream.

        Returns:
            float: Frames per second.
        """
        return self._fps

    def release(self) -> None:
        """Release the OpenCV VideoCapture resource."""
        if self._cap is not None and self._cap.isOpened():
            self._cap.release()
