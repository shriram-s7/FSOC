import copy
import hashlib
import json
from config.loader import cfg, _A
from simulation.motion import MotionSegment

def make_scenario(motion='straight',duration=20.,seed=42,dropout=True,renderer='classic'):
    if motion not in ('straight','figure8','sinusoidal'):raise ValueError('Unsupported comparison motion')
    if not 1<=duration<=30:raise ValueError('Duration must be 1–30 source seconds')
    config=copy.deepcopy(dict(cfg))
    if renderer not in ('classic','optical'):raise ValueError('Unknown renderer')
    config['rendering']={'profile':renderer}
    config['motion'].update(type=motion,speed_px_s=30.)
    config['target']['initial_position']='in_fov'
    config['distractors']['count']=0
    model=MotionSegment(_A(config),(1000.,1000.),seed=seed+1)
    schedule=[]
    for i in range(round(duration*60)):
        model.update((i+1)/60,1/60)
        schedule.append(dict(frame=i,t=(i+1)/60,x=model.wx,y=model.wy,rng_seed=seed*100000+i,
            blackout=bool(dropout and duration>=4 and duration/2 <= i/60 < duration/2+.5)))
    payload=dict(schema_version=1,motion=motion,duration=duration,seed=seed,dt=1/60,configuration=config,schedule=schedule,
        disturbances=dict(turbulence=0.,vibration=0.,noise=.1,scintillation=0.,jerk=0.,atmosphere='clear',noise_gaussian=True),
        description='Fixed-seed, mild sensor noise; optional common 0.5 s observation dropout. No scenario search or mode tuning.')
    payload['schedule_hash']=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
    return payload
