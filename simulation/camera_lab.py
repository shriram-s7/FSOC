"""Manual control ownership and angular envelope for stationary-beacon lab."""
import math
import time

class CameraLab:
    def __init__(self):
        self.mode='manual'
        self.pan_rate=self.tilt_rate=0.
        self.last_input=0.
        self.radius=5.
        self.home=False

    def command(self, data):
        mode=data.get('mode',self.mode)
        if mode not in ('manual','assist','auto'):raise ValueError('Invalid lab mode')
        pan,tilt=float(data.get('pan',0)),float(data.get('tilt',0))
        if not all(math.isfinite(v) and abs(v)<=2 for v in (pan,tilt)):raise ValueError('Manual rates must be finite and within 2 degrees/s')
        self.mode=mode;self.pan_rate=pan;self.tilt_rate=tilt
        self.home=bool(data.get('home',False));self.last_input=time.monotonic()

    def update(self, camera, dt):
        if self.mode=='auto':return
        if self.home:
            camera.command_world(camera.W/2,camera.H/2)
            if abs(camera.pan)+abs(camera.tilt)<.01:self.home=False
            return
        active=time.monotonic()-self.last_input<.35
        # Advance commanded angle so command latency does not divide input rate.
        pan=(camera.cmd_x-camera.W/2)/camera.ppd_h+(self.pan_rate if active else 0)*dt
        tilt=-(camera.cmd_y-camera.H/2)/camera.ppd_v+(self.tilt_rate if active else 0)*dt
        magnitude=math.hypot(pan,tilt)
        if magnitude>self.radius:pan*=self.radius/magnitude;tilt*=self.radius/magnitude
        camera.command_world(camera.W/2+pan*camera.ppd_h,camera.H/2-tilt*camera.ppd_v)

    def status(self,camera,target):
        return dict(mode=self.mode,pan=camera.pan,tilt=camera.tilt,radius=self.radius,
                    target=list(target.world_position),owner='Automatic controller' if self.mode=='auto' else 'User',
                    model='2D angular viewport approximation')
