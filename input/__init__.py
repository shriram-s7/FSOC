"""
FSOC-PAT Simulator — Input Package.

Provides frame source abstractions for the FSOC-PAT simulation and
video ingestion pipelines.
"""

from input.frame_source import FrameSource
from input.video_source import VideoSource
from input.simulation_source import SimulationSource

__all__ = ['FrameSource', 'VideoSource', 'SimulationSource']

