"""
Motion models for the beacon target.
All positions in world pixel coordinates (0..2000, 0..2000).
Common interface: update(t, dt) -> None, then read .wx, .wy
"""
import math, random
import numpy as np


class MotionSegment:
    """A live manoeuvre anchored at the current position, with local RNG/time.

    Pattern velocities blend from the incoming velocity over 0.25 s. An
    unfolded trajectory is reflected at world borders (never flat-clamped).
    Legacy initial scenes deliberately retain their original factory path.
    """
    def __init__(self, cfg, position, velocity=(0, 0), seed=42):
        self.wx, self.wy = position
        self._x, self._y = position
        self._incoming = velocity
        self._rng = random.Random(seed)
        self._t = 0.0
        self.kind = str(cfg.motion.type).lower().replace('-', '')
        self.W, self.H = float(cfg.world.width), float(cfg.world.height)
        self.m = dict(cfg.motion)
        self.scale = max(0.0, float(self.m['speed_px_s'])) / 30.0
        self.angle = math.atan2(velocity[1], velocity[0]) if math.hypot(*velocity) > .01 else self._rng.uniform(0, 2 * math.pi)
        self._rv = list(velocity)

    def _curve(self, t):
        m = self.m
        if self.kind == 'circular':
            a = float(m.get('circular_omega', .3)) * t
            r = float(m['circular_radius'])
            return r * math.cos(a), r * math.sin(a)
        if self.kind == 'figure8':
            a = 2 * math.pi * float(m['figure8_frequency']) * t
            return float(m['figure8_amplitude_x']) * math.sin(a), float(m['figure8_amplitude_y']) * math.sin(2*a)/2
        if self.kind == 'sinusoidal':
            a = 2 * math.pi * float(m['sinusoidal_frequency']) * t
            return float(m['sinusoidal_amplitude_x']) * math.sin(a), float(m['sinusoidal_amplitude_y']) * math.cos(2*a)
        if self.kind == 'spiral':
            r = min(50 + float(m['spiral_growth_rate'])*t, min(self.W,self.H)*.45)
            return r*math.cos(.4*t), r*math.sin(.4*t)
        speed = 30.0
        return speed*math.cos(self.angle)*t, speed*math.sin(self.angle)*t

    @staticmethod
    def _reflect(value, upper):
        span = upper - 20.0
        phase = (value - 10.0) % (2*span)
        return 10.0 + (phase if phase <= span else 2*span-phase)

    def update(self, t, dt):
        if dt <= 0:
            return
        if self.kind == 'random':
            for i in range(2):
                self._rv[i] += self._rng.gauss(0, float(self.m['random_volatility'])) * dt
            mag = math.hypot(*self._rv)
            cap = float(self.m['random_max_speed']) * self.scale
            factor = min(1, cap / max(mag, 1e-12))
            desired = [v * factor for v in self._rv]
            self._rv = desired
        else:
            a, b = self._curve(self._t*self.scale), self._curve((self._t+dt)*self.scale)
            desired = [(b[i]-a[i])/dt for i in range(2)]
        blend = math.exp(-(self._t + dt/2)/.25)
        vel = [self._incoming[i]*blend + desired[i]*(1-blend) for i in range(2)]
        self._x += vel[0]*dt
        self._y += vel[1]*dt
        self.wx, self.wy = self._reflect(self._x,self.W), self._reflect(self._y,self.H)
        self._t += dt

class MotionModel:
    def __init__(self, wx0, wy0, world_w, world_h):
        self.wx = wx0
        self.wy = wy0
        self.world_w = world_w
        self.world_h = world_h

    def update(self, t, dt): pass

    def _clamp(self):
        self.wx = max(10, min(self.world_w-10, self.wx))
        self.wy = max(10, min(self.world_h-10, self.wy))


class StraightLine(MotionModel):
    def __init__(self, wx0, wy0, world_w, world_h, speed, angle_deg, bounce=True):
        super().__init__(wx0, wy0, world_w, world_h)
        self.speed = speed
        self.vx = speed * math.cos(math.radians(angle_deg))
        self.vy = speed * math.sin(math.radians(angle_deg))
        self.bounce = bounce

    def update(self, t, dt):
        self.wx += self.vx * dt
        self.wy += self.vy * dt
        if self.bounce:
            if self.wx < 10 or self.wx > self.world_w-10:
                self.vx *= -1
            if self.wy < 10 or self.wy > self.world_h-10:
                self.vy *= -1
        self._clamp()


class Circular(MotionModel):
    def __init__(self, cx, cy, world_w, world_h, radius, omega):
        super().__init__(cx + radius, cy, world_w, world_h)
        self.cx = cx
        self.cy = cy
        self.radius = radius
        self.omega = omega

    def update(self, t, dt):
        self.wx = self.cx + self.radius * math.cos(self.omega * t)
        self.wy = self.cy + self.radius * math.sin(self.omega * t)
        self._clamp()


class Figure8(MotionModel):
    def __init__(self, cx, cy, world_w, world_h, amp_x, amp_y, freq):
        super().__init__(cx, cy, world_w, world_h)
        self.cx = cx
        self.cy = cy
        self.amp_x = amp_x
        self.amp_y = amp_y
        self.omega = 2 * math.pi * freq

    def update(self, t, dt):
        self.wx = self.cx + self.amp_x * math.sin(self.omega * t)
        self.wy = self.cy + self.amp_y * math.sin(2 * self.omega * t) / 2
        self._clamp()


class RandomWalk(MotionModel):
    def __init__(self, wx0, wy0, world_w, world_h,
                 volatility, max_speed):
        super().__init__(wx0, wy0, world_w, world_h)
        self.vx = 0.0
        self.vy = 0.0
        self.vol = volatility
        self.max_speed = max_speed

    def update(self, t, dt):
        self.vx += random.gauss(0, self.vol) * dt
        self.vy += random.gauss(0, self.vol) * dt
        speed = math.hypot(self.vx, self.vy)
        if speed > self.max_speed:
            self.vx = self.vx / speed * self.max_speed
            self.vy = self.vy / speed * self.max_speed
        self.wx += self.vx * dt
        self.wy += self.vy * dt
        if self.wx < 50 or self.wx > self.world_w-50:
            self.vx *= -1
        if self.wy < 50 or self.wy > self.world_h-50:
            self.vy *= -1
        self._clamp()


class Spiral(MotionModel):
    def __init__(self, cx, cy, world_w, world_h, r0, growth, omega):
        super().__init__(cx + r0, cy, world_w, world_h)
        self.cx = cx
        self.cy = cy
        self.r0 = r0
        self.growth = growth
        self.omega = omega

    def update(self, t, dt):
        r = self.r0 + self.growth * t
        r = min(r, min(self.world_w, self.world_h) * 0.45)
        self.wx = self.cx + r * math.cos(self.omega * t)
        self.wy = self.cy + r * math.sin(self.omega * t)
        self._clamp()


class Sinusoidal(MotionModel):
    def __init__(self, cx, cy, world_w, world_h, amp_x, amp_y, freq):
        super().__init__(cx, cy, world_w, world_h)
        self.cx = cx
        self.cy = cy
        self.amp_x = amp_x
        self.amp_y = amp_y
        self.omega = 2 * math.pi * freq

    def update(self, t, dt):
        self.wx = self.cx + self.amp_x * math.sin(self.omega * t)
        self.wy = self.cy + self.amp_y * math.cos(2 * self.omega * t)
        self._clamp()


def create_motion_model(cfg, seed=42):
    """Factory — creates motion model from config."""
    random.seed(seed)
    np.random.seed(seed)
    W = int(cfg.world.width)
    H = int(cfg.world.height)
    cx, cy = W // 2, H // 2
    mtype = str(cfg.motion.type).lower()

    if mtype == 'straight':
        angle = random.uniform(0, 360)
        return StraightLine(cx, cy, W, H,
                            float(cfg.motion.speed_px_s),
                            angle, bool(cfg.motion.bounce_walls))
    elif mtype == 'circular':
        return Circular(cx, cy, W, H,
                        float(cfg.motion.circular_radius),
                        float(cfg.motion.get('circular_omega', 0.3)))
    elif mtype in ('figure8', 'figure-8'):
        return Figure8(cx, cy, W, H,
                       float(cfg.motion.figure8_amplitude_x),
                       float(cfg.motion.figure8_amplitude_y),
                       float(cfg.motion.figure8_frequency))
    elif mtype == 'random':
        return RandomWalk(cx, cy, W, H,
                          float(cfg.motion.random_volatility),
                          float(cfg.motion.random_max_speed))
    elif mtype == 'spiral':
        return Spiral(cx, cy, W, H, 50,
                      float(cfg.motion.spiral_growth_rate), 0.4)
    elif mtype == 'sinusoidal':
        return Sinusoidal(cx, cy, W, H,
                          float(cfg.motion.sinusoidal_amplitude_x),
                          float(cfg.motion.sinusoidal_amplitude_y),
                          float(cfg.motion.sinusoidal_frequency))
    else:
        return StraightLine(cx, cy, W, H,
                            float(cfg.motion.speed_px_s), 45.0)
