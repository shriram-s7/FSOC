"""
FSOC-PAT Simulator — FastAPI backend.

Runs the SimulationThread in the background and exposes REST + WebSocket
endpoints so a web frontend can drive/observe the simulation.
"""
import asyncio
import base64
import io
import json
import os
import time
import hashlib
import platform
import sys
from collections import deque
from functools import lru_cache
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from PIL import Image
from server.sessions import list_sessions, read_session, session_frames
from server.mission_config import resolve as resolve_mission, preview as preview_mission

from ui.sim_thread import SimulationThread

FRONTEND_DIR = Path(__file__).resolve().parents[1] / 'frontend' / 'src'

# ---------------------------------------------------------------------------
# Paths — everything stays under F:\FSOC
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # F:\FSOC
INPUT_VIDEOS_DIR = os.environ.get('FSOC_VIDEOS_DIR', os.path.join(BASE_DIR, 'input_videos'))
LOGS_DIR = os.environ.get('FSOC_LOGS_DIR', os.path.join(BASE_DIR, 'logs'))

os.makedirs(INPUT_VIDEOS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Shared state — same structure as main.py
# ---------------------------------------------------------------------------

def _initial_detector_mode():
    """UI label of config detection.mode (hybrid | cv | ai)."""
    from config.loader import cfg
    m = str((cfg.get('detection') or {}).get('mode', 'hybrid')).lower()
    return {'cv': 'CV Only', 'ai': 'AI Only'}.get(m, 'Hybrid')

shared: dict = {
    'frame_rgb': None, 'fps': 0.0, 'sim_time': 0.0,
    'track_state': None, 'track_error_px': 0.0,
    'max_error_px': 0.0, 'rolling_conf': 0.0,
    'lock_rate': 0.0, 'acq_time': None,
    'reacq_count': 0, 'uncertainty_px': 0.0,
    'cam_x': 1000.0, 'cam_y': 1000.0,
    'cam_pan': 0.0, 'cam_tilt': 0.0,
    'tgt_wx': 1000.0, 'tgt_wy': 1000.0,
    'gt_sx': None, 'gt_sy': None,
    'tracker_sx': None, 'tracker_sy': None,
    'tracker_x': None, 'tracker_y': None,
    'occluded': False, 'candidates': 0,
    'det_ms': 0.0, 'pid_i': (0.0, 0.0),
    'running': False, 'seed': 42,
    'world_w': 2000, 'world_h': 2000,
    'video_mode': False,
    'video_file': None,
    'video_done': False,
    'last_report_path': None,
    'detector_mode': _initial_detector_mode(),
    'detector_mode_active': None,
    'beacon_motion': 'Straight',
    'num_distractors': 0,
    'disturbances': {
        'turbulence': 0.0, 'vibration': 0.0,
        'noise': 0.0, 'scintillation': 0.0,
        'jerk': 0.0,
        'atmosphere': 'clear',
        'noise_gaussian': True,
        'noise_saltpepper': False,
        'noise_poisson': False,
        'platform_enabled': False,
        'platform_speed': 5.0,
        'low_light': False,
    },
    # Live 'Occlusion' switch (see SimulationThread._update_occlusion_toggle).
    'occlusion': False,
    # Live app: decoys switched on are placed in the camera view.
    'decoys_in_view': True,
    'cmd_pause': False, 'cmd_unpause': False, 'cmd_reset': False,
    'cmd_quit': False, 'cmd_motion_change': False,
    'predicted_x': None, 'predicted_y': None,
    'pipeline_ms': 0.0, 'det_ms': 0.0,
    'target_loss': 0.0, 'reacq_time': None,
    'current_state_time': 0.0,
    'state_durations': {'SEARCHING': 0.0, 'ACQUIRING': 0.0, 'LOCKED': 0.0, 'COASTING': 0.0, 'LOST': 0.0},
    'state_history': [{'state': 'SEARCHING', 'duration': 0.0}],
}

sim_thread: Optional[SimulationThread] = None


# ---------------------------------------------------------------------------
# Lifespan — start the simulation thread alongside the API
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global sim_thread
    sim_thread = SimulationThread(shared)
    sim_thread.start()
    shared['running'] = False
    yield
    try:
        shared['cmd_quit'] = True
        if sim_thread is not None:
            sim_thread.join(timeout=3.0)
    except Exception as e:
        print(f"[Shutdown] Error stopping sim thread: {e}")


app = FastAPI(title="FSOC-PAT Simulator API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_no_cache_header(request, call_next):
    response = await call_next(request)
    if request.method == 'POST' and response.status_code < 300 and request.url.path.startswith('/api/set_'):
        shared.setdefault('pending_events', []).append({'type':request.url.path.rsplit('/',1)[-1],
            'details':{'motion':shared.get('beacon_motion'),'mode':shared.get('detector_mode'),'disturbances':dict(shared.get('disturbances',{}))}})
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _round(val, ndigits=2):
    try:
        if val is None:
            return None
        return round(float(val), ndigits)
    except (TypeError, ValueError):
        return None


def serialize_state() -> dict:
    """Thread-safe-ish snapshot of shared state, JSON-serializable, per spec."""
    try:
        from config.loader import cfg
        track_state = shared.get('track_state')
        track_state_str = getattr(track_state, 'name', track_state)

        pid_i = shared.get('pid_i')
        if isinstance(pid_i, (tuple, list)) and len(pid_i) >= 1:
            pid_integral = [_round(v) for v in pid_i]
        else:
            pid_integral = _round(pid_i)

        tracker_x = shared.get('tracker_x', shared.get('tracker_sx'))
        tracker_y = shared.get('tracker_y', shared.get('tracker_sy'))

        return {
            'track_state': track_state_str,
            'camera_config': {'width': cfg.camera.resolution_width, 'height': cfg.camera.resolution_height, 'hfov': cfg.camera.hfov_deg, 'vfov': cfg.camera.vfov_deg, 'update_rate': cfg.camera.update_rate_hz, 'max_slew': cfg.camera.max_pan_speed_deg_s},
            'state_update_hz': 10,
            'session_id': getattr(getattr(sim_thread, '_metrics', None), 'session_id', None),
            'track_error_px': _round(shared.get('track_error_px')),
            'fps': _round(shared.get('fps')),
            'lock_rate': _round(shared.get('lock_rate')),
            'lock_rate_source': shared.get('lock_rate_source', 'tracker'),
            'acq_time': _round(shared.get('acq_time')),
            'rmse': _round(shared.get('rmse')),
            'max_error_px': _round(shared.get('max_error_px')),
            'target_loss': shared.get('target_loss'),
            'gt_sx': _round(shared.get('gt_sx')),
            'gt_sy': _round(shared.get('gt_sy')),
            'tracker_x': _round(tracker_x),
            'tracker_y': _round(tracker_y),
            'confidence': _round(shared.get('rolling_conf')),
            'running': bool(shared.get('running', False)),
            'video_mode': bool(shared.get('video_mode', False)),
            'video_done': bool(shared.get('video_done', False)),
            'video_file': shared.get('video_file'),
            'video_fps': _round(shared.get('video_fps')),
            'video_gt_loaded': bool(shared.get('video_gt_loaded', False)),
            'centroid_err_gt_px': _round(shared.get('centroid_err_gt_px')),
            'last_report_path': shared.get('last_report_path'),
            'lab_status': shared.get('lab_status'),
            'finalisation': shared.get('finalisation'),
            'finished_session_id': shared.get('finished_session_id'),
            'sim_time': _round(shared.get('sim_time')),
            'reacq_count': shared.get('reacq_count', 0),
            'uncertainty': _round(shared.get('uncertainty_px')),
            'pid_integral': pid_integral,
            'scan_coverage_pct': _round(shared.get('scan_coverage_pct')),
            'acquire_confidence': _round(shared.get('acquire_confidence')),
            'acquire_frames': shared.get('acquire_frames', 0),
            'cam_x': _round(shared.get('cam_x')),
            'cam_y': _round(shared.get('cam_y')),
            'target_wx': _round(shared.get('tgt_wx')),
            'target_wy': _round(shared.get('tgt_wy')),
            'pan_deg': _round(shared.get('cam_pan')),
            'tilt_deg': _round(shared.get('cam_tilt')),
            'search_target_wx': _round(shared.get('search_target_wx')),
            'search_target_wy': _round(shared.get('search_target_wy')),
            'num_distractors': shared.get('num_distractors', 0),
            'detector_mode': shared.get('detector_mode_active') or shared.get('detector_mode'),
            # Step 6a: the disturbance state the sim thread actually reads,
            # so the UI buttons reflect the backend, not the last click.
            'disturbances': dict(shared.get('disturbances') or {}),
            'atmosphere': (shared.get('disturbances') or {}).get('atmosphere', 'clear'),
            'toggles': toggle_state(),
            'occluded': bool(shared.get('occluded', False)),
            'predicted_x': _round(shared.get('predicted_x')),
            'predicted_y': _round(shared.get('predicted_y')),
            'pipeline_ms': _round(shared.get('pipeline_ms'), 1),
            'det_ms': _round(shared.get('det_ms'), 1),
            'reacq_time': _round(shared.get('reacq_time')),
            'current_state_time': _round(shared.get('current_state_time'), 1),
            'state_durations': {k: _round(v, 1) for k, v in (shared.get('state_durations') or {}).items()},
            'state_history': shared.get('state_history', []),
        }
    except Exception as e:
        print(f"[serialize_state] Error: {e}")
        return {}


PRESETS = {
    'EASY': dict(motion='Straight', speed=20, atmosphere='clear',
                 turbulence=0.0, vibration=0.0, noise=0.0,
                 scintillation=0.0, jerk=0.0, distractors=0),
    'MOD':  dict(motion='Circular', speed=30, atmosphere='haze',
                 turbulence=0.2, vibration=0.1, distractors=1),
    'HARD': dict(motion='Figure-8', speed=40, atmosphere='fog',
                 turbulence=0.4, vibration=0.3, noise=0.2, distractors=2),
    'SEV':  dict(motion='Random', speed=50, atmosphere='rain',
                 turbulence=0.6, vibration=0.5, noise=0.4, distractors=3),
    'ADV':  dict(motion='Sinusoidal', speed=60, atmosphere='low_light',
                 turbulence=0.8, vibration=0.7, noise=0.6, jerk=0.3, distractors=4),
}


def _apply_motion(motion: str):
    try:
        from config.loader import cfg
        cfg['motion']['type'] = motion.lower().replace('-', '')
        shared['beacon_motion'] = motion
        shared['cmd_motion_change'] = True
    except Exception as e:
        print(f"[_apply_motion] Error: {e}")


def _apply_speed(speed: float):
    try:
        from config.loader import cfg
        cfg['motion']['speed_px_s'] = float(speed)
        shared['cmd_motion_change'] = True
    except Exception as e:
        print(f"[_apply_speed] Error: {e}")


def _apply_distractors(count: int):
    try:
        from config.loader import cfg
        cfg['distractors']['count'] = int(count)
        shared['num_distractors'] = int(count)
    except Exception as e:
        print(f"[_apply_distractors] Error: {e}")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
ATMOSPHERES = ('clear', 'haze', 'fog', 'rain', 'dense_fog')
TOGGLES = ('gaussian', 'saltpepper', 'poisson', 'jitter', 'low_light',
           'platform', 'occlusion', 'decoys', 'turbulence')


def toggle_state() -> dict:
    """On/off of every independent live toggle, derived from the backend
    state the sim thread reads (a noise type counts as on only when the
    noise level is non-zero)."""
    d = shared.get('disturbances') or {}
    noise_on = float(d.get('noise', 0.0) or 0.0) >= 0.01
    return {
        'gaussian':   noise_on and bool(d.get('noise_gaussian')),
        'saltpepper': noise_on and bool(d.get('noise_saltpepper')),
        'poisson':    noise_on and bool(d.get('noise_poisson')),
        'jitter':     float(d.get('vibration', 0.0) or 0.0) >= 0.01,
        'low_light':  bool(d.get('low_light')),
        'platform':   bool(d.get('platform_enabled')),
        'occlusion':  bool(shared.get('occlusion')),
        'decoys':     int(shared.get('num_distractors', 0) or 0) > 0,
        'turbulence': float(d.get('turbulence', 0.0) or 0.0) >= 0.01,
    }


def _dist_cfg() -> dict:
    from config.loader import cfg
    return dict(cfg.get('disturbance') or {})


def _set_atmosphere(mode: str):
    """Pick-one atmosphere. 'low_light' (legacy atmosphere name) sets the
    independent low-light flag instead and leaves the atmosphere alone."""
    m = str(mode).strip().lower().replace(' ', '_')
    d = shared.setdefault('disturbances', {})
    if m in ('low_light', 'lowlight'):
        d['low_light'] = True
        return
    if m not in ATMOSPHERES:
        raise HTTPException(status_code=400, detail=f"Unknown atmosphere: {mode}")
    d['atmosphere'] = m


def _set_toggle(name: str, on: bool):
    d = shared.setdefault('disturbances', {})
    c = _dist_cfg()
    if name in ('gaussian', 'saltpepper', 'poisson'):
        if float(d.get('noise', 0.0) or 0.0) < 0.01:
            # Noise was off: no type is "on", whatever the flags say.
            d['noise_gaussian'] = d['noise_saltpepper'] = d['noise_poisson'] = False
        d[f'noise_{name}'] = bool(on)
        if not (d['noise_gaussian'] or d['noise_saltpepper'] or d['noise_poisson']):
            d['noise'] = 0.0
        elif float(d.get('noise', 0.0) or 0.0) < 0.01:
            d['noise'] = float(c.get('toggle_noise_level', 1.0))
    elif name == 'jitter':
        d['vibration'] = float(c.get('toggle_jitter_level', 1.0)) if on else 0.0
    elif name == 'low_light':
        d['low_light'] = bool(on)
    elif name == 'platform':
        d['platform_enabled'] = bool(on)
    elif name == 'occlusion':
        shared['occlusion'] = bool(on)
    elif name == 'turbulence':
        d['turbulence'] = float(c.get('toggle_turbulence_level', 0.5)) if on else 0.0
    elif name == 'decoys':
        n = int(c.get('toggle_decoys', 3)) if on else 0
        shared['num_distractors'] = n
        _apply_distractors(n)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown toggle: {name}")


class ToggleRequest(BaseModel):
    name: str
    on: bool


class CommandRequest(BaseModel):
    cmd: str


class MotionRequest(BaseModel):
    motion: str


class AtmosphereRequest(BaseModel):
    mode: str


class DisturbanceRequest(BaseModel):
    type: str
    value: float


class DetectorRequest(BaseModel):
    mode: str


class ScenarioRequest(BaseModel):
    preset: str


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------
@app.get("/api/state")
async def get_state():
    return serialize_state()


@app.get('/api/sessions')
async def sessions_list():
    return await asyncio.to_thread(list_sessions, LOGS_DIR)

@app.post('/api/mission/preview')
async def mission_preview(data: dict):
    try:return preview_mission(data)
    except (ValueError,TypeError):raise HTTPException(422,'Invalid mission configuration')

@app.post('/api/lab/{action}')
async def camera_lab_action(action: str, data: dict):
    if action=='input':
        from simulation.camera_lab import CameraLab
        try:CameraLab().command(data)
        except (ValueError,TypeError):raise HTTPException(422,'Invalid camera control')
        if sim_thread is None or sim_thread.lab is None:raise HTTPException(409,'Camera Lab is not active')
        shared['pending_lab_input']=data
        return {'status':'ok'}
    if action not in ('start','exit'):raise HTTPException(404)
    if action=='start' and shared.get('running'):raise HTTPException(409,'Finish the current mission before entering Camera Lab')
    if action=='start':
        if data.get('renderer','classic') not in ('classic','optical'):raise HTTPException(422,'Unknown renderer')
        shared['lab_renderer']=data.get('renderer','classic')
    shared['lab_action_pending']=True;shared['pending_lab_action']=action
    for _ in range(600):
        await asyncio.sleep(.05)
        if not shared.get('lab_action_pending'):break
    if shared.get('lab_action_error'):raise HTTPException(500,shared['lab_action_error'])
    if shared.get('lab_action_pending'):raise HTTPException(504,'Camera Lab transition pending')
    return {'status':'ready'}

@app.post('/api/mission/configure')
async def mission_configure(data: dict):
    if shared.get('running'):raise HTTPException(409,'Finish the current mission first')
    try:config,dist=resolve_mission(data)
    except (ValueError,TypeError):raise HTTPException(422,'Invalid mission configuration')
    from config.loader import cfg
    cfg.clear();cfg.update(config)
    shared['disturbances'].update(dist,noise_gaussian=True,noise_saltpepper=False,noise_poisson=False,platform_enabled=False)
    shared['occlusion']=False;shared['num_distractors']=0
    shared['detector_mode']=data.get('tracking','Hybrid')
    shared['beacon_motion']=data.get('motion','Straight')
    shared['anchor_initial_motion']=True
    shared['cmd_motion_change']=False
    return {'configuration':config,'disturbances':dict(shared['disturbances'])}


@app.get('/api/sessions/{sid}')
async def session_detail(sid: str):
    try:
        return await asyncio.to_thread(read_session, LOGS_DIR, sid)
    except (ValueError, OSError):
        raise HTTPException(404, 'Session not found')


@app.get('/api/sessions/{sid}/frames')
async def session_frame_data(sid: str):
    try:
        return await asyncio.to_thread(session_frames, LOGS_DIR, sid)
    except (ValueError, OSError):
        raise HTTPException(404, 'Session data not found')


@app.get('/api/sessions/{sid}/artifacts/{kind}')
async def session_artifact(sid: str, kind: str):
    try:
        record = read_session(LOGS_DIR, sid)
        relative = record.get('artifacts', {}).get(kind)
        if not relative: raise ValueError()
        path = (Path(LOGS_DIR)/relative).resolve()
        if not path.is_relative_to(Path(LOGS_DIR).resolve()) or not path.is_file(): raise ValueError()
        return FileResponse(path, filename=path.name)
    except (ValueError, OSError):
        raise HTTPException(404, 'Artifact not available')


@app.get('/api/finalisation')
async def finalisation_state():
    return {k: shared.get(k) for k in ('finalisation', 'finished_session_id', 'finalisation_error')}


async def start_prepared_video(folder, metadata, mode):
    from input.video_source import VideoSource
    if shared.get('running') or shared.get('video_start_pending'):
        raise HTTPException(409, 'Finish the current mission before starting video analysis')
    source=VideoSource(str(folder/'source.mp4'))
    if metadata['gt_loaded']: source.load_ground_truth(str(folder/'ground_truth.csv'))
    shared['video_start_pending']=True
    shared['video_start_error']=None
    shared['pending_video_start']={'source':source,'name':metadata['name'],'mode':mode,'metadata':{k:v for k,v in metadata.items() if k!='thumbnails'}}
    for _ in range(600):
        await asyncio.sleep(.05)
        if not shared.get('video_start_pending'):break
    if shared.get('video_start_pending'):raise HTTPException(504,'Video preparation is still being applied')
    if shared.get('video_start_error'):raise HTTPException(500,shared['video_start_error'])
    return {'status':'ready'}

from server.video_preflight import router_for as video_router
app.include_router(video_router(INPUT_VIDEOS_DIR, start_prepared_video))
from server.comparison import router_for as comparison_router
app.include_router(comparison_router(LOGS_DIR, shared))


@app.post("/api/command")
async def post_command(req: CommandRequest):
    global sim_thread
    cmd = req.cmd
    try:
        if cmd == 'run':
            shared['cmd_pause'] = False
            shared['cmd_unpause'] = True
            shared['running'] = True
            if sim_thread is None or not sim_thread.is_alive():
                sim_thread = SimulationThread(shared)
                sim_thread.start()
            # No new metrics session here: sessions are opened by the sim
            # thread itself (at start-up and on reset). Starting one from
            # this thread cut the first frames after a reset and, after a
            # video load, replaced the video session with a sim one.
        elif cmd == 'pause':
            shared['cmd_pause'] = True
            shared['running'] = False
        elif cmd == 'stop':
            shared['cmd_pause'] = True
            shared['running'] = False
            if sim_thread is not None and sim_thread._metrics is not None:
                shared['finalisation'] = 'finalising'
                shared['cmd_finalise'] = True
                for _ in range(600):
                    await asyncio.sleep(.05)
                    if shared.get('finalisation') in ('ready', 'error'):
                        break
            return {'status': shared.get('finalisation', 'idle'),
                    'session_id': shared.get('finished_session_id'),
                    'error': shared.get('finalisation_error')}
        elif cmd == 'reset':
            if sim_thread is not None and sim_thread.is_video_mode():
                sim_thread.set_simulation_mode()
            shared['cmd_reset'] = True
            shared['running'] = False
            shared['track_state'] = 'SEARCHING'
            shared['track_error_px'] = 0.0
            shared['max_error_px'] = 0.0
            shared['rmse'] = 0.0
            shared['lock_rate'] = 0.0
            shared['target_loss'] = 0.0
            shared['acq_time'] = None
            shared['reacq_count'] = 0
            shared['confidence'] = 0.0
            shared['video_done'] = False
            shared['last_report_path'] = None
            # The sim thread closes the current metrics session and opens a
            # new one itself while handling cmd_reset, in the same step as
            # it zeroes sim_time — doing it from here raced with that.
        elif cmd == 'reset_tracker':
            # Drops the tracker only (fusion state + Kalman), leaving the
            # camera and beacon exactly where they are — unlike 'reset',
            # which restarts the whole mission. Used to test loss/recovery
            # without touching atmosphere/disturbance.
            shared['cmd_reset_tracker'] = True
        elif cmd == 'quit':
            # Stop the sim thread cleanly, then shut the server down.
            shared['cmd_quit'] = True
            if sim_thread is not None:
                sim_thread.stop()
                await asyncio.to_thread(sim_thread.join, 3.0)
            _request_shutdown()
        else:
            raise HTTPException(status_code=400, detail=f"Unknown command: {cmd}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "ok", "cmd": cmd}


@app.post("/api/set_motion")
async def set_motion(req: MotionRequest):
    try:
        _apply_motion(req.motion)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "ok", "motion": req.motion}


@app.post("/api/set_atmosphere")
async def set_atmosphere(req: AtmosphereRequest):
    try:
        _set_atmosphere(req.mode)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "ok", "mode": req.mode, "disturbances": dict(shared['disturbances'])}


@app.post("/api/set_toggle")
async def set_toggle(req: ToggleRequest):
    """Independent on/off disturbance switches (see TOGGLES); they combine
    freely with each other and with the atmosphere."""
    try:
        _set_toggle(req.name, req.on)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "ok", "toggles": toggle_state()}


@app.post("/api/set_disturbance")
async def set_disturbance(req: DisturbanceRequest):
    try:
        shared.setdefault('disturbances', {})[req.type] = req.value
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "ok", "type": req.type, "value": req.value}


@app.post("/api/set_detector")
async def set_detector(req: DetectorRequest):
    try:
        shared['detector_mode'] = req.mode
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "ok", "mode": req.mode}


@app.post("/api/set_scenario")
async def set_scenario(req: ScenarioRequest):
    preset = req.preset.upper()
    if preset not in PRESETS:
        raise HTTPException(status_code=400, detail=f"Unknown preset: {req.preset}")
    try:
        p = PRESETS[preset]
        _apply_motion(p['motion'])
        _apply_speed(p['speed'])
        low = p['atmosphere'] == 'low_light'
        _set_atmosphere('clear' if low else p['atmosphere'])
        shared['disturbances']['low_light'] = low
        for key in ('turbulence', 'vibration', 'noise', 'scintillation', 'jerk'):
            shared['disturbances'][key] = p.get(key, 0.0)

        if preset == 'EASY':
            shared['num_distractors'] = 0
            _apply_distractors(0)
            from config.loader import cfg
            cfg['target']['initial_position'] = 'near_center'
            shared['cmd_motion_change'] = True
        elif preset == 'MOD':
            shared['num_distractors'] = 1
            _apply_distractors(1)
        elif preset == 'HARD':
            shared['num_distractors'] = 2
            _apply_distractors(2)
        elif preset == 'SEV':
            shared['num_distractors'] = 3
            _apply_distractors(3)
        elif preset == 'ADV':
            shared['num_distractors'] = 4
            _apply_distractors(4)
        elif 'distractors' in p:
            _apply_distractors(p['distractors'])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "ok", "preset": preset}


class ModeRequest(BaseModel):
    mode: str


@app.post("/api/set_mode")
async def set_mode(req: ModeRequest):
    """Leave video mode: release the video, resume the simulator and start
    a fresh simulation session (done by the sim thread on cmd_reset)."""
    if req.mode != 'simulation':
        raise HTTPException(status_code=400, detail="Only 'simulation' is supported "
                            "(load a video with /api/load_video)")
    if sim_thread is not None and sim_thread.is_video_mode():
        sim_thread.set_simulation_mode()
    shared['cmd_pause'] = False
    shared['cmd_unpause'] = True
    shared['running'] = True
    return {"status": "ok", "mode": "simulation"}


@app.post("/api/load_video")
async def load_video(file: UploadFile = File(...),
                     gt: Optional[UploadFile] = File(None)):
    try:
        filename = os.path.basename(file.filename)
        dest_path = os.path.join(INPUT_VIDEOS_DIR, filename)
        contents = await file.read()
        with open(dest_path, 'wb') as f:
            f.write(contents)
        # Optional ground-truth CSV, saved as <video stem>_gt.csv so it
        # sits next to the video where find_gt_csv() looks for it.
        gt_uploaded = gt is not None and bool(gt.filename)
        if gt_uploaded:
            gt_path = os.path.splitext(dest_path)[0] + '_gt.csv'
            with open(gt_path, 'wb') as f:
                f.write(await gt.read())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save video: {e}")

    try:
        from input.video_source import VideoSource, find_gt_csv
        video_source = VideoSource(dest_path)
        # Optional ground truth (<video>_gt.csv next to the saved video):
        # scoring only — reaches the metrics layer, never the tracker.
        # Only a CSV uploaded with THIS request counts — an old
        # <name>_gt.csv left in input_videos/ is ignored.
        gt_csv = find_gt_csv(dest_path) if gt_uploaded else None
        gt_loaded = False
        if gt_csv:
            video_source.load_ground_truth(gt_csv)
            gt_loaded = bool(video_source._gt_data)
        if sim_thread is not None:
            sim_thread.set_video_mode(video_source)
        shared['video_file'] = filename      # display name only
        return {
            "status": "ok",
            "filename": filename,
            "fps": video_source.get_fps(),
            "frames": video_source._total_frames,
            "gt_loaded": gt_loaded,
            "gt_file": os.path.basename(gt_csv) if gt_loaded else None,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load video: {e}")


@app.get("/api/logs")
async def list_logs():
    try:
        results = []
        for name in os.listdir(LOGS_DIR):
            full_path = os.path.join(LOGS_DIR, name)
            if os.path.isfile(full_path):
                stat = os.stat(full_path)
                results.append({
                    "name": name,
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                })
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/logs/{filename}")
async def get_log(filename: str):
    safe_name = os.path.basename(filename)
    if not (safe_name.lower().endswith('.pdf') or safe_name.lower().endswith('.csv')):
        raise HTTPException(status_code=400, detail="Only PDF and CSV files are supported")
    full_path = os.path.join(LOGS_DIR, safe_name)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(full_path, filename=safe_name)


# Read-only diagnostics. Unmeasured stages remain null rather than estimated.
PERF_STAGES = ["Capture/Render", "Disturbance", "Detect", "Classify (CNN)",
               "Stabilise", "Scene estimate", "Track (IMM + fusion)",
               "Control (servo)", "Encode+Send"]
_perf_frames = deque(maxlen=120)
_perf_last = [None]

@app.get('/api/perf')
async def get_perf():
    import numpy as np
    frames = list(_perf_frames)
    stages = {}
    for name in PERF_STAGES:
        values = [f['stages'][name] for f in frames if f['stages'].get(name) is not None]
        stages[name] = {'mean': float(np.mean(values)) if values else None,
                        'p50': float(np.median(values)) if values else None,
                        'p95': float(np.percentile(values, 95)) if values else None}
    values = [f['pipeline_ms'] for f in frames if f.get('pipeline_ms')]
    return {'frames': frames, 'stages': stages,
            'pipeline_fps': 1000 / float(np.mean(values)) if values else None,
            'end_to_end_fps': shared.get('fps'), 'capacity': 120}

@lru_cache(maxsize=1)
def model_metadata():
    from config.loader import cfg
    path = Path(BASE_DIR) / (cfg.get('classifier') or {}).get('model_path', 'models/beacon_classifier.pt')
    return {'name': 'BeaconCNN v2 (custom)', 'file': path.name,
            'size_bytes': path.stat().st_size if path.exists() else None,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None,
            'input_patch': [1, 32, 32], 'classes': ['non-beacon', 'beacon']}

@app.get('/api/diagnostics')
async def get_diagnostics():
    import torch, cv2, numpy
    model = dict(model_metadata())
    model.update(mode=serialize_state().get('detector_mode'),
                 loaded=getattr(sim_thread, 'classifier', None) is not None)
    ram = None
    try:
        import psutil
        ram = psutil.Process().memory_info().rss
    except ImportError:
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            class Counters(ctypes.Structure):
                _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [(name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize', 'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage', 'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
            counter = Counters(); counter.cb = ctypes.sizeof(counter)
            ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counter), counter.cb):
                ram = counter.WorkingSetSize
    return {'model': model, 'system': {'Python': platform.python_version(),
            'torch': torch.__version__, 'OpenCV': cv2.__version__, 'numpy': numpy.__version__,
            'CPU': platform.processor() or os.environ.get('PROCESSOR_IDENTIFIER'),
            'Cores': os.cpu_count(), 'Process RAM bytes': ram, 'Device': 'CPU'}}

@app.get('/api/backend-log')
async def backend_log():
    # Tail a bounded byte window of the active server's redirected output.
    lines = []
    for name in ('server.out.log', 'server.err.log'):
        path = Path(os.environ.get('FSOC_UI_LOG_DIR') or Path(BASE_DIR) / 'scratch' / 'ui') / name
        if path.exists():
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size - 128000))
                lines.extend(stream.read().decode('utf-8', errors='replace').splitlines()[-500:])
    return {'lines': lines[-500:]}


# ---------------------------------------------------------------------------
# WebSocket endpoints
# ---------------------------------------------------------------------------
@app.websocket("/ws/frame")
async def ws_frame(websocket: WebSocket):
    await websocket.accept()
    previous = None
    while True:
        packet=shared.get('frame_packet')
        frame_rgb = packet['rgb'] if packet else shared.get('frame_rgb')
        try:
            # The simulation publishes a new array for each frame. Do not
            # encode and transmit the same array repeatedly between frames.
            if frame_rgb is not None and frame_rgb is not previous:
                started = time.perf_counter()
                img = Image.fromarray(frame_rgb)
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=75)
                b64 = base64.b64encode(buf.getvalue()).decode('ascii')
                frame_perf = shared.get('perf_frame')
                await websocket.send_text(json.dumps({"frame": b64, "timestamp": time.time(),
                    'telemetry':packet['telemetry'] if packet else None}))
                previous = frame_rgb
                if frame_perf and frame_perf.get('sim_time') != _perf_last[0]:
                    _perf_last[0] = frame_perf['sim_time']
                    sample = dict(frame_perf, stages=dict(frame_perf['stages']))
                    sample['stages']['Encode+Send'] = (time.perf_counter() - started) * 1000
                    sample['pipeline_ms'] = shared.get('pipeline_ms')
                    _perf_frames.append(sample)
            await asyncio.sleep(1 / 120)
        except Exception:
            break


@app.websocket("/ws/state")
async def ws_state(websocket: WebSocket):
    await websocket.accept()
    while True:
        try:
            await websocket.send_text(json.dumps(serialize_state()))
            await asyncio.sleep(0.1)
        except Exception:
            break


# ---------------------------------------------------------------------------
# Static frontend
# ---------------------------------------------------------------------------
app.mount('/static', StaticFiles(directory=str(FRONTEND_DIR / 'static')), name='static')


@app.get('/')
async def root():
    return FileResponse(str(FRONTEND_DIR / 'index.html'))


_uvicorn_server = None   # set when started via `python -m server.app`


def _request_shutdown():
    """Ask uvicorn to exit after the current response is sent. If the
    app was started some other way (no server handle), exit the process
    shortly instead."""
    if _uvicorn_server is not None:
        _uvicorn_server.should_exit = True
    else:
        asyncio.get_running_loop().call_later(0.5, os._exit, 0)


if __name__ == '__main__':
    import uvicorn
    _uvicorn_server = uvicorn.Server(
        uvicorn.Config(app, host='127.0.0.1', port=int(os.environ.get('FSOC_PORT', 8765)), log_level='warning'))
    _uvicorn_server.run()
