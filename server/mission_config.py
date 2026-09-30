"""Validated mission configuration and side-effect-free trajectory previews."""
import copy
import random
from config.loader import cfg, _A
from simulation.motion import MotionSegment

def resolve(data):
    config=copy.deepcopy(dict(cfg))
    renderer=data.get('renderer','classic')
    if renderer not in ('classic','optical'):raise ValueError('Unknown renderer')
    config['rendering']={'profile':renderer}
    motion=str(data.get('motion','Straight')).lower().replace('-','')
    if motion not in ('straight','circular','figure8','random','spiral','sinusoidal'):raise ValueError('Unknown motion')
    speed={'Slow':15.,'Normal':30.,'Fast':55.}.get(data.get('speed','Normal'))
    if speed is None:raise ValueError('Unknown speed')
    position={'In Camera View':'in_fov','Near Camera View':'near_center','Anywhere':'anywhere','near_center':'near_center'}.get(data.get('position','Near Camera View'))
    if position is None:raise ValueError('Unknown initial position')
    mode={'Hybrid':'hybrid','CV Only':'cv','AI Only':'ai'}.get(data.get('tracking','Hybrid'))
    if mode is None:raise ValueError('Unknown tracking mode')
    atmosphere=data.get('atmosphere','clear')
    if atmosphere not in ('clear','haze','fog','rain','low_light'):raise ValueError('Unknown atmosphere')
    intensity=float(data.get('disturbanceIntensity',.3))
    if not 0<=intensity<=1:raise ValueError('Intensity must be between 0 and 1')
    enabled=data.get('disturbances',[])
    if any(k not in ('turbulence','vibration','noise','scintillation','jerk') for k in enabled):raise ValueError('Unknown disturbance')
    config['motion'].update(type=motion,speed_px_s=speed)
    config['target']['initial_position']=position
    config.setdefault('detection',{})['mode']=mode
    return config, dict(atmosphere='clear' if atmosphere=='low_light' else atmosphere,low_light=atmosphere=='low_light',
        **{k:intensity if k in enabled else 0. for k in ('turbulence','vibration','noise','scintillation','jerk')})

def start_position(config,seed=42):
    w,h=config['world']['width'],config['world']['height'];pos=config['target']['initial_position']
    if pos=='anywhere':
        rng=random.Random(seed+1);return rng.uniform(20,w-20),rng.uniform(20,h-20)
    if pos=='near_center':return w/2+25,h/2+25
    return w/2,h/2

def preview(data):
    config,_=resolve(data);origin=start_position(config)
    model=MotionSegment(_A(config),origin,seed=43);points=[dict(t=0,x=origin[0],y=origin[1])]
    for i in range(1,401):
        model.update(i*.05,.05)
        if i%5==0:points.append(dict(t=i*.05,x=model.wx,y=model.wy))
    return dict(points=points,configuration=config)
