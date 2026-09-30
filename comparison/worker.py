"""One real mode in a private process; never starts the live server."""
import os
os.environ.setdefault('SDL_VIDEODRIVER','dummy')
os.environ.setdefault('SDL_AUDIODRIVER','dummy')
import sys
import json
import random
import time
import hashlib
from pathlib import Path
import numpy as np
import pygame
import cv2
import torch
from config.loader import cfg
from ui.sim_thread import SimulationThread, MODE_LABELS
from evaluation.metrics import MetricsAccumulator
from evaluation.requirements import evaluate

def atomic(path,data):
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(data,allow_nan=False),encoding='utf-8');os.replace(temporary,path)

class ScheduledTarget:
    def __init__(self,original,schedule):
        self.size_px,self.color,self.brightness=original.size_px,original.color,original.brightness
        self.schedule=schedule;self.index=0;self.wx=self.wy=1000.
    def update(self,dt):
        entry=self.schedule[self.index];self.wx,self.wy=entry['x'],entry['y'];self.index+=1
    @property
    def world_position(self):return self.wx,self.wy

def run(folder,mode):
    root=Path(folder);scenario=json.loads((root/'scenario.json').read_text())
    output=root/mode;output.mkdir(exist_ok=True);frames_dir=output/'frames';frames_dir.mkdir(exist_ok=True)
    cfg.clear();cfg.update(scenario['configuration']);cfg['detection']['mode']=mode
    torch.set_num_threads(1);cv2.setNumThreads(1)
    seed=scenario['seed'];random.seed(seed);np.random.seed(seed);torch.manual_seed(seed)
    pygame.init()
    state=dict(seed=seed,num_distractors=0,disturbances=scenario['disturbances'],occlusion=False)
    sim=SimulationThread(state);sim._metrics=None;sim.build_pipeline(seed)
    sim.target=ScheduledTarget(sim.target,scenario['schedule'])
    metrics=MetricsAccumulator(root.name+'_'+mode.upper(),'simulation');metrics.detector_mode=MODE_LABELS[mode]
    telemetry=[];preview=[];size=0;started=time.perf_counter()
    for i,event in enumerate(scenario['schedule']):
        if (root/'cancel').exists():raise InterruptedError('Comparison cancelled')
        # Reset exogenous sensor randomness at every scheduled frame. Tracking
        # cannot affect the next frame's disturbance through random consumption.
        random.seed(event['rng_seed']);np.random.seed(event['rng_seed'])
        sim.detector_blackout=event['blackout']
        tick=time.perf_counter();sim.step(scenario['dt']);compute_ms=(time.perf_counter()-tick)*1000
        metrics.record_frame(state)
        item=dict(state['frame_packet']['telemetry']);item.update(state=state['track_state'].name,
            frame=i,time_s=event['t'],confidence=float(state.get('rolling_conf') or 0),
            mode=mode,blackout=event['blackout'],compute_ms=compute_ms,
            tracker_stab_x=state.get('tracker_stab_sx'),tracker_stab_y=state.get('tracker_stab_sy'))
        coords=[state.get(k) for k in ('tracker_x','tracker_y','gt_sx','gt_sy')]
        item['centroid_error_px']=float(np.hypot(coords[0]-coords[2],coords[1]-coords[3])) if all(v is not None for v in coords) else None
        telemetry.append(item)
        if i%5==0 or i==len(scenario['schedule'])-1:
            name=f'{i:05d}.jpg';path=frames_dir/name
            cv2.imwrite(str(path),cv2.cvtColor(state['frame_packet']['rgb'],cv2.COLOR_RGB2BGR),[cv2.IMWRITE_JPEG_QUALITY,80])
            size+=path.stat().st_size
            if size>80*1024*1024:raise RuntimeError('Preview exceeds 80 MB per-mode size limit')
            preview.append(dict(frame=i,time_s=event['t'],file='frames/'+name))
        if i%15==0:atomic(output/'progress.json',dict(frame=i+1,total=len(scenario['schedule']),mode=mode,elapsed_s=time.perf_counter()-started,compute_fps=(i+1)/max(.001,time.perf_counter()-started)))
    summary=metrics.compute_summary()
    summary['unpaced_compute_fps']=1000/float(np.mean([t['compute_ms'] for t in telemetry]))
    summary['valid_error_frames']=sum(t['track_error_px'] is not None for t in telemetry)
    checks=evaluate(summary,realtime=False)
    summary['pass_fps']=None
    summary['overall_status']=checks['overall']
    summary['overall_pass']=True if checks['overall']=='PASS' else False if checks['overall']=='FAIL' else None
    result=dict(mode=mode,schedule_hash=scenario['schedule_hash'],summary=summary,requirements=evaluate(summary,realtime=False),
                model_sha256=hashlib.sha256(Path('models/beacon_classifier_v2.pt').read_bytes()).hexdigest() if mode!='cv' else None,
                preview=preview,wall_seconds=time.perf_counter()-started,recording_bytes=size,
                timing_note='Unpaced isolated generation; playback speed is not realtime processing performance')
    (output/'telemetry.jsonl').write_text('\n'.join(json.dumps(t,allow_nan=False) for t in telemetry),encoding='utf-8')
    atomic(output/'result.json',result)
    atomic(output/'progress.json',dict(frame=len(telemetry),total=len(telemetry),mode=mode))
    pygame.quit()

if __name__=='__main__':run(sys.argv[1],sys.argv[2])
