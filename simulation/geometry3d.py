"""
3D geometry utilities for the god-view external camera.
Implements a simple pinhole camera projection — no 3D engine needed.
Used by ui/view3d.py (added in Stage 7).
Stubbed here so imports don't break.
"""
import numpy as np
import math

def project_point(point_3d, cam_pos, cam_target, cam_up, fov_deg, img_w, img_h):
    """
    Project a 3D world point onto a 2D image plane.
    Basic pinhole camera model.

    Args:
        point_3d: np.array [x, y, z] world position
        cam_pos: np.array [x, y, z] camera position
        cam_target: np.array [x, y, z] look-at point
        cam_up: np.array [x, y, z] up vector
        fov_deg: horizontal field of view in degrees
        img_w, img_h: image dimensions in pixels

    Returns:
        (px, py): pixel coordinates, or None if behind camera
    """
    forward = cam_target - cam_pos
    forward = forward / (np.linalg.norm(forward) + 1e-9)
    right = np.cross(forward, cam_up)
    right = right / (np.linalg.norm(right) + 1e-9)
    up = np.cross(right, forward)

    p = point_3d - cam_pos
    z = np.dot(p, forward)
    if z <= 0:
        return None   # behind camera

    x = np.dot(p, right)
    y = np.dot(p, up)

    f = (img_w / 2) / math.tan(math.radians(fov_deg / 2))
    px = int(img_w / 2 + f * x / z)
    py = int(img_h / 2 - f * y / z)

    return (px, py)
