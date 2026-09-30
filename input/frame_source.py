"""
FSOC-PAT Simulator — Frame Source Abstraction.

Defines the abstract base interface FrameSource, allowing the downstream
detection, classification, and tracking pipeline to ingest frames seamlessly
from either the interactive Pygame simulation or external video files (e.g. MP4).
"""

from abc import ABC, abstractmethod
from typing import Optional, Tuple
import numpy as np


class FrameSource(ABC):
    """
    Abstract base class representing a generic frame provider.

    Standardizes frame format, frame rate reporting, ground truth retrieval,
    and lifecycle management across simulation and external video inputs.
    """

    @abstractmethod
    def get_frame(self) -> Tuple[Optional[np.ndarray], Optional[Tuple[float, float]], bool]:
        """
        Fetch the next frame from this source.

        Returns:
            tuple: (frame, ground_truth, is_done)
                - frame (np.ndarray or None): RGB uint8 array with shape (480, 640, 3),
                  matching the simulation output, or None if stream is finished.
                - ground_truth (tuple of (float, float) or None): Ground truth beacon
                  position in 640x480 screen pixel coordinates (sx, sy), or None if unavailable.
                - is_done (bool): True if the frame source has reached its end (e.g. video EOF),
                  False otherwise.
        """
        pass

    @abstractmethod
    def reset(self) -> None:
        """
        Reset the frame source to the beginning.

        For video files, seeks back to frame 0.
        For simulation, triggers simulator state reset.
        """
        pass

    @abstractmethod
    def get_fps(self) -> float:
        """
        Return the native or expected frame rate of this source.

        Returns:
            float: Frame rate in frames per second (Hz).
        """
        pass

    def release(self) -> None:
        """
        Release any system or hardware resources held by this source.
        Default implementation is a no-op.
        """
        pass
