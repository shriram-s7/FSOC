"""
FSOC-PAT Simulator — Simulation Frame Source.

Provides a concrete implementation of FrameSource that wraps the existing
Pygame-based simulation thread, delegating frame access, ground truth
extraction, and reset triggers to the shared state dictionary.
"""

from typing import Dict, Optional, Tuple, Any
import numpy as np

from input.frame_source import FrameSource


class SimulationSource(FrameSource):
    """
    Frame source adapter for the internal FSOC-PAT simulation.

    Interfaces directly with the shared state dictionary populated by
    SimulationThread to supply 640x480 RGB frames and ground truth coordinates.
    """

    def __init__(self, shared_state: Dict[str, Any]):
        """
        Initialize the simulation frame source adapter.

        Args:
            shared_state (dict): The shared state dictionary coordinated with
                SimulationThread and Dashboard.
        """
        self.shared_state = shared_state

    def get_frame(self) -> Tuple[Optional[np.ndarray], Optional[Tuple[float, float]], bool]:
        """
        Fetch the current frame and ground truth from the simulation thread.

        Returns:
            tuple: (frame, ground_truth, is_done)
                - frame (np.ndarray or None): RGB uint8 array with shape (480, 640, 3).
                - ground_truth (tuple of (float, float) or None): Screen pixel coordinates
                  (gt_sx, gt_sy) of the target beacon, or None if off-screen/uninitialized.
                - is_done (bool): Always False (simulation runs continuously).
        """
        frame = self.shared_state.get('frame_rgb')
        gt_x = self.shared_state.get('gt_sx')
        gt_y = self.shared_state.get('gt_sy')

        gt = (float(gt_x), float(gt_y)) if (gt_x is not None and gt_y is not None) else None
        return frame, gt, False

    def reset(self) -> None:
        """Request a reset of the tracker and simulation metrics via shared state."""
        self.shared_state['cmd_reset'] = True

    def get_fps(self) -> float:
        """
        Return the target frame rate of the simulation engine.

        Returns:
            float: Fixed target simulation rate of 60.0 FPS.
        """
        return 60.0

    def release(self) -> None:
        """Cleanup frame source. Lifetime is managed by SimulationThread."""
        pass
