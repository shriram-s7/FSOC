"""
Virtual pan-tilt camera.
State: cam_x, cam_y — camera center in world pixel coordinates.
Pan/tilt in degrees mapped to pixel offsets via FOV.
Slew rate limited. Command latency buffer.
"""
from collections import deque
import math

class VirtualCamera:
    def __init__(self, cfg):
        self.cfg = cfg
        self.W = int(cfg.world.width)
        self.H = int(cfg.world.height)
        self.cam_w = int(cfg.camera.resolution_width)
        self.cam_h = int(cfg.camera.resolution_height)
        self.hfov = float(cfg.camera.hfov_deg)
        self.vfov = float(cfg.camera.vfov_deg)
        self.max_pan_speed  = float(cfg.camera.max_pan_speed_deg_s)
        self.max_tilt_speed = float(cfg.camera.max_tilt_speed_deg_s)
        self.latency = int(cfg.camera.latency_frames)

        # pixels per degree
        self.ppd_h = self.cam_w / self.hfov
        self.ppd_v = self.cam_h / self.vfov

        # Camera pointing limits come from the gimbal's pan/tilt range
        # (config), not from the world canvas size — the camera is free
        # to point past the world edge; render() just shows background
        # there. cam_x/cam_y bounds below are world center +/- the pixel
        # extent of pan_min/max, tilt_min/max.
        self.pan_min  = float(cfg.camera.pan_min)
        self.pan_max  = float(cfg.camera.pan_max)
        self.tilt_min = float(cfg.camera.tilt_min)
        self.tilt_max = float(cfg.camera.tilt_max)

        # cam_x/cam_y bounds implied by the pan/tilt limits (world center
        # +/- angular limit converted to pixels). tilt is inverted vs cam_y
        # (see update()'s self.tilt formula below).
        cx0 = self.W / 2
        cy0 = self.H / 2
        self.cam_x_min = cx0 + self.pan_min * self.ppd_h
        self.cam_x_max = cx0 + self.pan_max * self.ppd_h
        self.cam_y_min = cy0 - self.tilt_max * self.ppd_v
        self.cam_y_max = cy0 - self.tilt_min * self.ppd_v

        # Camera center starts at world center
        self.cam_x = float(self.W / 2)
        self.cam_y = float(self.H / 2)

        # Pan/tilt in degrees (for angular error calculation)
        self.pan  = 0.0
        self.tilt = 0.0

        # Command targets
        self.cmd_x = self.cam_x
        self.cmd_y = self.cam_y

        # Latency buffer
        self.lat_buf = deque(
            [(self.cmd_x, self.cmd_y)] * self.latency,
            maxlen=self.latency)

    def command_world(self, target_wx, target_wy):
        """Command camera to move toward world position."""
        self.cmd_x = max(self.cam_x_min, min(self.cam_x_max, target_wx))
        self.cmd_y = max(self.cam_y_min, min(self.cam_y_max, target_wy))

    def command_delta_deg(self, dpan, dtilt):
        """Command camera by angular delta in degrees."""
        dx = dpan  * self.ppd_h
        dy = -dtilt * self.ppd_v
        self.cmd_x = max(self.cam_x_min,
                         min(self.cam_x_max, self.cam_x + dx))
        self.cmd_y = max(self.cam_y_min,
                         min(self.cam_y_max, self.cam_y + dy))

    def update(self, dt):
        self.lat_buf.append((self.cmd_x, self.cmd_y))
        tx, ty = self.lat_buf[0]

        max_dx = self.max_pan_speed  * self.ppd_h * dt
        max_dy = self.max_tilt_speed * self.ppd_v * dt

        dx = tx - self.cam_x
        dy = ty - self.cam_y
        dx = max(-max_dx, min(max_dx, dx))
        dy = max(-max_dy, min(max_dy, dy))

        self.cam_x += dx
        self.cam_y += dy

        # Update angular pan/tilt for reporting
        cx0 = self.W / 2
        cy0 = self.H / 2
        self.pan  =  (self.cam_x - cx0) / self.ppd_h
        self.tilt = -(self.cam_y - cy0) / self.ppd_v

    def world_to_screen(self, wx, wy):
        """World pixel → screen pixel."""
        sx = wx - self.cam_x + self.cam_w / 2
        sy = wy - self.cam_y + self.cam_h / 2
        return (sx, sy)

    def screen_to_world(self, sx, sy):
        """Screen pixel → world pixel."""
        wx = sx + self.cam_x - self.cam_w / 2
        wy = sy + self.cam_y - self.cam_h / 2
        return (wx, wy)

    def pixel_to_world(self, px, py):
        """Compatibility shim for tracking/tracker.py: screen pixel
        -> (pan, tilt) angular world position in degrees."""
        cx = self.cam_w / 2.0
        cy = self.cam_h / 2.0
        az = self.pan + (px - cx) / self.ppd_h
        el = self.tilt - (py - cy) / self.ppd_v
        return (az, el)

    def pixel_error_to_angle(self, px_err_x, px_err_y):
        """Convert pixel error to angular error (degrees)."""
        return (px_err_x / self.ppd_h,
                -px_err_y / self.ppd_v)

    @property
    def ppd(self):
        """Compatibility alias for tracking/tracker.py (ppd_h == ppd_v here)."""
        return self.ppd_h

    @property
    def cam_px_per_deg_h(self): return self.ppd_h

    @property
    def cam_px_per_deg_v(self): return self.ppd_v
