"""
Simulation thread — runs full pipeline in background.
Writes shared_state dict every frame for dashboard to read.
"""
import pygame
import numpy as np
import time
import threading
import cv2
import random
import os
import datetime
import copy
import uuid
from evaluation.session_record import make_record, save_record

from config.loader import cfg
from simulation.world import World
from simulation.target import Target
from simulation.camera import VirtualCamera
from simulation.camera_lab import CameraLab
from simulation.distractors import Distractors
from simulation.obstacles import Obstacles
from disturbance.disturbance import DisturbanceEngine
from detection.detector import BeaconDetector
from detection.classifier import BeaconClassifier
from detection.cv_scorer import CVScorer
from detection.ai_scanner import AIScanner
from tracking.tracker import MasterTracker
from tracking.temporal_fusion import TrackState
from control.pid_controller import PIDController
from control.camera_servo import CameraServo
from input.frame_source import FrameSource
from evaluation.metrics import MetricsAccumulator
from evaluation.logger import SessionLogger
from evaluation.report_generator import ReportGenerator
from evaluation.gt_metrics import CORRECT_LOCK_TOL_PX


# Detector modes (Step 5a) — only the find-and-score-candidates stage
# differs; stabiliser, IMM, fusion, gates and servo are identical.
#   hybrid  blob detector proposes -> CNN v2 scores
#   cv      blob detector proposes -> hand-made score (no CNN)
#   ai      CNN v2 scans the whole frame (no blob detector)
DETECTION_MODES = ('hybrid', 'cv', 'ai')
MODE_LABELS = {'hybrid': 'Hybrid', 'cv': 'CV Only', 'ai': 'AI Only'}


def normalise_mode(m):
    """'CV Only' / 'cv' / 'AI Only' / 'Hybrid' ... -> 'cv' | 'ai' | 'hybrid'."""
    m = str(m or 'hybrid').strip().lower()
    if m.startswith('cv'):
        return 'cv'
    if m.startswith('ai'):
        return 'ai'
    return 'hybrid'


FEED_W = 640
FEED_H = 480


class SimulationThread(threading.Thread):
    def __init__(self, shared_state):
        super().__init__(daemon=True, name='SimThread')
        self.state = shared_state
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._max_err = 0.0
        self._fps_samples = []
        self._last_t = time.perf_counter()
        self._err_sq_sum = 0.0
        self._err_count  = 0
        self._locked_streak = 0
        self._frame_count = 0
        self._video_mode = False
        self._video_source = None
        self._first_detection_time = None
        self._acquired = False
        self.lab = None
        self._lab_saved = None

        self._metrics = None
        self.output_dir = os.environ.get('FSOC_LOGS_DIR', 'logs')
        self._logger = SessionLogger(output_dir=self.output_dir)
        self._report_gen = ReportGenerator(output_dir=self.output_dir)
        self._state_durations = {'SEARCHING': 0.0, 'ACQUIRING': 0.0, 'LOCKED': 0.0, 'COASTING': 0.0, 'LOST': 0.0}
        self._current_state = 'SEARCHING'
        self._current_state_time = 0.0
        self._state_history = [{'state': 'SEARCHING', 'duration': 0.0}]
        self._start_new_session("simulation")

    def stop(self): self._stop_event.set()

    def set_detection_mode(self, mode):
        """Switch detector mode live: close the current metrics session
        (exported if it has frames), reset the tracker to SEARCHING (fresh
        tracker, servo and PID; the camera stays where it is) and start a
        new session labelled with the mode."""
        mode = normalise_mode(mode)
        self._finish_session()
        self.detection_mode = mode
        self.tracker = MasterTracker(cfg)
        self.servo = CameraServo(cfg, self.camera, self.pid)
        self.pid.reset()
        self._locked_streak = 0
        self._max_err = 0.0
        self._err_sq_sum = 0.0
        self._err_count = 0
        self._gt_lock = [0, 0]   # [correct-lock frames, frames with GT]
        self.state['track_state'] = TrackState.SEARCHING
        self.state['detector_mode_active'] = MODE_LABELS[mode]
        self._start_new_session('video' if self._video_mode else 'simulation')
        print(f'[Detector] mode -> {mode}')

    def _start_new_session(self, mode: str):
        """Start a new MetricsAccumulator for a fresh session (a
        simulation run or a video playback), replacing any previous
        one without exporting it."""
        if mode == "video" and self._video_source is not None:
            path = getattr(self._video_source, 'filepath', 'video')
            stem = os.path.splitext(os.path.basename(path))[0]
            session_id = f"VID_{stem}"
        else:
            ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            session_id = f"SIM_{ts}"
        det = getattr(self, 'detection_mode', None)
        if det is not None:
            session_id += f"_{det.upper()}"
        session_id += '_' + uuid.uuid4().hex[:8]
        self._metrics = MetricsAccumulator(session_id, mode)
        self._metrics.configuration = copy.deepcopy(dict(cfg))
        self._metrics.configuration['runtime_disturbances']=copy.deepcopy(self.state.get('disturbances',{}))
        if mode=='video':self._metrics.configuration['source_video']=copy.deepcopy(self.state.get('video_metadata',{}))
        self._metrics.events = []
        self._metrics.created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self._gt_lock = [0, 0]
        self._live_score_at = 0
        self._live_scores = {}
        self.state['finalisation'] = 'idle'
        self.state['last_report_path'] = None
        self._metrics.detector_mode = MODE_LABELS.get(det, 'Hybrid')
        self._first_detection_time = None
        self._acquired = False
        self.state['acq_time'] = None
        print(f"[Metrics] New session: {session_id}")

    def export_snapshot(self):
        """Export CSV and PDF for the current session without clearing the accumulator."""
        if self._metrics is None:
            return None
        try:
            self._logger.export_csv(self._metrics)
            pdf_path = self._report_gen.generate(self._metrics)
            self.state['last_report_path'] = pdf_path
            print(f"[Metrics] Snapshot exported: {pdf_path}")
            return pdf_path
        except Exception as e:
            print(f"[Metrics] Error exporting snapshot: {e}")
            return None

    def _finish_session(self):
        """Export CSV and PDF for the current session and clear it.
        Never raises — logs and continues on failure so the sim
        thread cannot crash from report generation."""
        if self._metrics is None:
            return
        if not self._metrics.timestamps:
            self._metrics = None
            self.state['finalisation'] = 'ready'
            self.state['finished_session_id'] = None
            self.state['finalisation_error'] = None
            return
        self.state['finalisation'] = 'finalising'
        try:
            csv_path = self._logger.export_csv(self._metrics)
            pdf_path = self._report_gen.generate(self._metrics)
            if not csv_path or not pdf_path:
                raise IOError('Session export failed; retry finalisation')
            sid = self._metrics.session_id
            record = make_record(self._metrics, {'pdf': os.path.basename(pdf_path),
                'frames': os.path.basename(csv_path), 'summary': sid+'_summary.csv',
                'centroid': sid+'/centroid_log.csv'})
            save_record(self.output_dir, record)
            self.state['last_report_path'] = pdf_path
            self.state['finished_session_id'] = sid
            self.state['finalisation'] = 'ready'
            self.state['finalisation_error'] = None
            self._metrics = None
            print("[Metrics] Session complete.")
        except Exception as e:
            print(f"[Metrics] Error finishing session: {e}")
            self.state['finalisation'] = 'error'
            self.state['finalisation_error'] = str(e)

    def set_video_mode(self, video_source: FrameSource):
        """
        Switch to video playback mode using the provided VideoSource.

        Args:
            video_source: An instance of FrameSource / VideoSource.
        """
        with self._lock:
            if video_source is not None:
                video_source.reset()
            self._video_source = video_source
            self._video_mode = True
            self._frame_count = 0

            # Reset RMSE accumulator
            self._err_sq_sum = 0.0
            self._err_count = 0
            self._gt_lock = [0, 0]   # [correct-lock frames, frames with GT]
            self._max_err = 0.0
            self._locked_streak = 0

            # Reset acquisition timer
            self._first_detection_time = None
            self._acquired = False

            # Reset shared state metrics
            self.state['video_mode'] = True
            self.state['video_done'] = False
            self.state['video_file'] = os.path.basename(
                getattr(video_source, 'filepath', '') or '')
            self.state['video_gt_loaded'] = bool(
                getattr(video_source, '_gt_data', None))
            self.state['tgt_wx'] = self.state['tgt_wy'] = None
            self.state['video_fps'] = video_source.get_fps() if video_source is not None else 30.0
            self.state['video_total_frames'] = getattr(video_source, '_total_frames', 0) if video_source is not None else 0
            self.state['video_resolution'] = f"{getattr(video_source, '_width', 640)}x{getattr(video_source, '_height', 480)}" if video_source is not None else "640x480"
            self.state['max_error_px'] = 0.0
            self.state['track_error_px'] = 0.0
            self.state['rmse'] = 0.0
            self.state['lock_rate'] = 0.0
            self.state['reacq_count'] = 0
            self.state['acq_time'] = None
            self.state['sim_time'] = 0.0
            self.state['reset_err_hist'] = True
            self.state['cmd_reset'] = True
            self._start_new_session("video")

    def set_simulation_mode(self):
        """Switch back to simulation mode and release any active video source."""
        with self._lock:
            self._video_mode = False
            if self._video_source is not None:
                self._video_source.release()
            self._video_source = None
            self._frame_count = 0
            self._max_err = 0.0
            self._err_sq_sum = 0.0
            self._err_count = 0
            self._gt_lock = [0, 0]   # [correct-lock frames, frames with GT]
            self._locked_streak = 0

            self._first_detection_time = None
            self._acquired = False

            self.state['video_mode'] = False
            self.state['video_done'] = False
            self.state['video_file'] = None
            self.state['video_gt_loaded'] = False
            self.state['max_error_px'] = 0.0
            self.state['track_error_px'] = 0.0
            self.state['rmse'] = 0.0
            self.state['lock_rate'] = 0.0
            self.state['reacq_count'] = 0
            self.state['acq_time'] = None
            self.state['sim_time'] = 0.0
            self.state['reset_err_hist'] = True
            self.state['cmd_reset'] = True
            self._start_new_session("simulation")

    def is_video_mode(self) -> bool:
        """Return True if currently in video playback mode, False otherwise."""
        with self._lock:
            return self._video_mode

    def build_pipeline(self, seed):
        """Construct the per-frame pipeline objects (world, target, camera,
        disturbance, detector, classifier, tracker, servo) as attributes.
        Shared by run() and the headless harness (harness/), so both drive
        exactly the same objects through step()."""
        if 'num_distractors' in self.state:
            cfg['distractors']['count'] = int(self.state['num_distractors'])

        self.seed        = seed
        self.camera      = VirtualCamera(cfg)
        from simulation.optical_world import make_world
        self.world       = make_world(cfg)
        self._world_profile=cfg.get('rendering',{}).get('profile','classic')
        self.target      = Target(cfg, seed)
        self.distractors = Distractors(cfg)
        self.obstacles   = Obstacles(cfg)
        self.disturbance = DisturbanceEngine(cfg)
        self.detector    = BeaconDetector(cfg)
        self.tracker     = MasterTracker(cfg)
        self.pid         = PIDController(cfg)
        self.servo       = CameraServo(cfg, self.camera, self.pid)

        print("Loading CNN classifier...")
        self.classifier = BeaconClassifier()
        print("Classifier ready. Simulation starting.")
        self.cv_scorer  = CVScorer(cfg)
        self.ai_scanner = AIScanner(cfg, self.classifier, self.detector)
        self.detection_mode = normalise_mode(
            (cfg.get('detection') or {}).get('mode', 'hybrid'))
        self.state['detector_mode_active'] = MODE_LABELS[self.detection_mode]

        self.sim_time = 0.0
        # Test hook for the harness: when True, the detector's output is
        # discarded (no candidates reach the classifier/tracker). Never
        # set by the live app.
        self.detector_blackout = False
        # Harness 'B' (real time): process only every k-th frame; the
        # tracker just predicts in between (tracker.predict_only). 1 =
        # every frame (live app, harness 'A').
        self.process_every_k = 1
        self._step_index = 0

    def run(self):
        seed = int(self.state.get('seed', 42))
        random.seed(seed)
        np.random.seed(seed)

        pygame.init()
        clock = pygame.time.Clock()

        self.build_pipeline(seed)
        self._start_new_session("simulation")

        # Initial baseline static render at rest (dt=0.0) so texture is populated without advancing simulation
        scene_surf, occ_list = self.world.render(
            self.camera.cam_x, self.camera.cam_y,
            [self.target],
            distractors=self.distractors.positions,
            obstacles=self.obstacles.rects,
            scintillation=0.0,
        )
        self._draw_overlay(scene_surf, [], self.tracker, self.camera)
        gt_sx, gt_sy = self.camera.world_to_screen(self.target.wx, self.target.wy)
        frame_rgb = self._surf_to_rgb(scene_surf)
        self.state.update({
            'frame_rgb':       frame_rgb,
            'fps':             0.0,
            'sim_time':        0.0,
            'track_state':     TrackState.SEARCHING,
            'track_error_px':  0.0,
            'max_error_px':    0.0,
            'rolling_conf':    0.0,
            'lock_rate':       0.0,
            'acq_time':        None,
            'reacq_count':     0,
            'uncertainty_px':  0.0,
            'cam_x':           self.camera.cam_x,
            'cam_y':           self.camera.cam_y,
            'cam_pan':         self.camera.pan,
            'cam_tilt':        self.camera.tilt,
            'tgt_wx':          self.target.wx,
            'tgt_wy':          self.target.wy,
            'gt_sx':           gt_sx,
            'gt_sy':           gt_sy,
            'gt_x':            gt_sx,
            'gt_y':            gt_sy,
            'tracker_sx':      None,
            'tracker_sy':      None,
            'tracker_x':       None,
            'tracker_y':       None,
            'occluded':        False,
            'candidates':      0,
            'det_ms':          0.0,
            'pid_i':           self.pid.integral_state,
            'running':         False,
            'world_w':         int(cfg.world.width),
            'world_h':         int(cfg.world.height),
            'rmse':            0.0,
            'scan_coverage_pct': 0.0,
            'acquire_confidence': 0.0,
            'acquire_frames':  0,
        })

        paused   = True

        while not self._stop_event.is_set():
            # Commands
            lab_action=self.state.pop('pending_lab_action',None)
            if lab_action:
                self._finish_session()
                if self.state.get('finalisation') != 'error':
                    if lab_action=='start':
                        self._lab_saved=(copy.deepcopy(dict(cfg)),copy.deepcopy(self.state.get('disturbances',{})),self.state.get('detector_mode'),self.state.get('occlusion',False),self.state.get('anchor_initial_motion',False))
                        self.set_simulation_mode()
                        self.lab=CameraLab()
                        cfg['rendering']={'profile':self.state.get('lab_renderer','classic')}
                        self.state['disturbances']=dict(turbulence=0.,vibration=0.,noise=0.,scintillation=0.,jerk=0.,atmosphere='clear',platform_enabled=False,low_light=False)
                        cfg['target']['initial_position']='in_fov'
                        cfg['distractors']['count']=0
                        self.state['num_distractors']=0
                        self.state['occlusion']=False
                        self.state['cmd_unpause']=True
                    else:
                        self.lab=None
                        if self._lab_saved:
                            saved,dist,mode,occlusion,anchor=self._lab_saved
                            cfg.clear();cfg.update(saved);self.state['disturbances']=dist;self.state['detector_mode']=mode
                            self.state['occlusion']=occlusion;self.state['anchor_initial_motion']=anchor
                            self.state['num_distractors']=cfg.distractors.count
                        self.set_simulation_mode()
                        paused=True;self.state['running']=False
                        self.state['lab_status']=None
                    self.state['lab_action_error']=None
                else:self.state['lab_action_error']=self.state.get('finalisation_error')
                self.state['lab_action_pending']=False
            lab_input=self.state.pop('pending_lab_input',None)
            if lab_input is not None and self.lab is not None:
                self.lab.command(lab_input)
            pending_video = self.state.pop('pending_video_start', None)
            if pending_video is not None:
                self._finish_session()
                if self.state.get('finalisation') == 'error':
                    pending_video['source'].release()
                    self.state['video_start_error'] = self.state.get('finalisation_error')
                else:
                    self.detection_mode = normalise_mode(pending_video['mode'])
                    self.state['video_metadata'] = pending_video.get('metadata',{})
                    self.state['detector_mode'] = pending_video['mode']
                    self.set_video_mode(pending_video['source'])
                    self.state['video_file'] = pending_video['name']
                    self.state['video_metadata'] = pending_video.get('metadata',{})
                    self.state['cmd_unpause'] = True
                self.state['video_start_pending'] = False
            if self.state.pop('cmd_finalise', False):
                paused = True
                self.state['running'] = False
                self._finish_session()
            if self.state.get('pending_events') and self._metrics is not None:
                pending = self.state.pop('pending_events', [])
                self._metrics.events.extend(dict(time_s=self.sim_time, **e) for e in pending)
            if self.state.get('cmd_pause'):
                self.state['cmd_pause'] = False
                paused = True
                self.state['running'] = False
            if self.state.get('cmd_unpause'):
                self.state['cmd_unpause'] = False
                if self._metrics is None:
                    self._start_new_session('video' if self._video_mode else 'simulation')
                paused = False
                self.state['running'] = True
            if self.state.get('cmd_reset'):
                self.state['cmd_reset'] = False
                # Close the current metrics session (exported if it has
                # frames) and start a new one, so a mid-session reset never
                # mixes two runs (sim_time restarts at 0 below).
                self._finish_session()
                if self.state.get('finalisation') == 'error':
                    paused=True
                    self.state['running']=False
                    continue
                self._start_new_session('video' if self._video_mode
                                        else 'simulation')
                if 'num_distractors' in self.state:
                    cfg['distractors']['count'] = int(self.state['num_distractors'])
                self.distractors = Distractors(cfg)
                from simulation.optical_world import make_world
                desired_profile=cfg.get('rendering',{}).get('profile','classic')
                if getattr(self,'_world_profile','classic')!=desired_profile:
                    self.world=make_world(cfg)
                    self._world_profile=desired_profile
                self.target = Target(cfg, seed)
                if self.state.get('anchor_initial_motion'):
                    self.target.change_motion()
                self.camera = VirtualCamera(cfg)
                self.servo = CameraServo(cfg, self.camera, self.pid)
                self.tracker = MasterTracker(cfg)
                self.detection_mode = normalise_mode(self.state.get('detector_mode'))
                if self._metrics is not None:
                    self._metrics.detector_mode = MODE_LABELS[self.detection_mode]
                self.pid.reset()
                self._max_err = 0.0
                self.state['max_error_px'] = 0.0
                self._err_sq_sum = 0.0
                self._err_count  = 0
                self._locked_streak = 0
                self._frame_count = 0
                self._first_detection_time = None
                self._acquired = False
                self.state['acq_time'] = None
                self.state['sim_time'] = 0.0
                self.state['track_error_px'] = 0.0
                self.state['rmse'] = 0.0
                self.state['lock_rate'] = 0.0
                self.state['reacq_count'] = 0
                self.state['confidence'] = 0.0
                self.state['rolling_conf'] = 0.0
                self.state['acquire_frames'] = 0
                self.state['scan_coverage_pct'] = 0.0
                self.state['track_state'] = TrackState.SEARCHING
                self._state_durations = {'SEARCHING': 0.0, 'ACQUIRING': 0.0, 'LOCKED': 0.0, 'COASTING': 0.0, 'LOST': 0.0}
                self._current_state = 'SEARCHING'
                self._current_state_time = 0.0
                self._state_history = [{'state': 'SEARCHING', 'duration': 0.0}]
                self.state['state_durations'] = dict(self._state_durations)
                self.state['current_state_time'] = 0.0
                self.state['state_history'] = list(self._state_history)
                self.state['target_loss'] = 0.0
                self.state['reacq_time'] = None
                self.state['predicted_x'] = None
                self.state['predicted_y'] = None
                self.sim_time = 0.0

                # Video mode: nothing from the simulated world is shown.
                if not self._video_mode:
                    scene_surf, occ_list = self.world.render(
                        self.camera.cam_x, self.camera.cam_y,
                        [self.target],
                        distractors=self.distractors.positions,
                        obstacles=self.obstacles.rects,
                        scintillation=0.0,
                    )
                    self._draw_overlay(scene_surf, [], self.tracker, self.camera)
                    gt_sx, gt_sy = self.camera.world_to_screen(self.target.wx, self.target.wy)
                    self.state.update({
                        'frame_rgb': self._surf_to_rgb(scene_surf),
                        'tgt_wx': self.target.wx,
                        'tgt_wy': self.target.wy,
                        'gt_sx': gt_sx,
                        'gt_sy': gt_sy,
                        'gt_x': gt_sx,
                        'gt_y': gt_sy,
                        'cam_x': self.camera.cam_x,
                        'cam_y': self.camera.cam_y,
                        'cam_pan': self.camera.pan,
                        'cam_tilt': self.camera.tilt,
                        'tracker_sx': None,
                        'tracker_sy': None,
                        'tracker_x': None,
                        'tracker_y': None,
                    })
            if self.state.get('cmd_quit'):
                break
            want = normalise_mode(self.state.get('detector_mode',
                                                 MODE_LABELS[self.detection_mode]))
            if want != self.detection_mode:
                self.set_detection_mode(want)
            if self.state.get('cmd_reset_tracker'):
                self.state['cmd_reset_tracker'] = False
                tracker = self.tracker
                tracker.fusion.reset()
                tracker.kalman.reset()
                tracker.search.stop()
                tracker._predictive_search_active = False
                tracker._predictive_search_frames = 0
                tracker._predictive_target = None
                tracker._last_locked_pos = None
                tracker._last_locked_vel = None
                tracker._gap = None
                self._locked_streak = 0
            if self.state.get('cmd_motion_change'):
                self.state['cmd_motion_change'] = False
                self.target.change_motion()
                if paused and not self._video_mode:
                    scene_surf, occ_list = self.world.render(
                        self.camera.cam_x, self.camera.cam_y,
                        [self.target],
                        distractors=self.distractors.positions,
                        obstacles=self.obstacles.rects,
                        scintillation=1.0,
                    )
                    self._draw_overlay(scene_surf, [], self.tracker, self.camera)
                    gt_sx, gt_sy = self.camera.world_to_screen(self.target.wx, self.target.wy)
                    self.state.update({
                        'frame_rgb': self._surf_to_rgb(scene_surf),
                        'tgt_wx': self.target.wx,
                        'tgt_wy': self.target.wy,
                        'gt_sx': gt_sx,
                        'gt_sy': gt_sy,
                        'gt_x': gt_sx,
                        'gt_y': gt_sy,
                    })

            if 'num_distractors' in self.state and int(self.state['num_distractors']) != len(self.distractors.positions):
                cfg['distractors']['count'] = int(self.state['num_distractors'])
                self.distractors = Distractors(cfg)
                if self.state.get('decoys_in_view'):
                    self.distractors.place_near(self.target.wx, self.target.wy)

            if paused:
                self.state['running'] = False
                time.sleep(0.016)
                continue

            if self._video_mode and self._video_source is not None:
                # Recorded video: fixed step of 1/native fps, paced to it.
                vfps = self._video_source.get_fps() or 30.0
                clock.tick(vfps)
                dt = 1.0 / vfps
            else:
                dt = clock.tick(60) / 1000.0
                dt = min(dt, 0.05)

            status = self.step(dt)

            if status == 'video_done':
                # Video ended — write completion flag to shared state
                with self._lock:
                    # Stay in (finished) video mode: last frame stays on
                    # screen, sim stays paused until the user leaves video
                    # mode (set_simulation_mode / reset).
                    self.state['video_done'] = True
                    self.state['report_ready'] = True
                    paused = True
                    self.state['running'] = False
                self._finish_session()
                continue

        if self._metrics is not None:
            self._finish_session()
        self.state['running'] = False
        pygame.quit()

    def _update_occlusion_toggle(self, target, sim_time):
        """Live UI 'Occlusion' switch (shared_state['occlusion']). Absent
        (headless harness) = legacy behaviour: the one ambient obstacle.
        False = no obstacle drawn. True = an occluder is placed over the
        beacon now and again every disturbance.occlusion_repeat_s; it drifts
        at its own speed, so the beacon is hidden for a few seconds each
        time."""
        on = self.state.get('occlusion')
        if on is None:
            return
        last = getattr(self, '_occl_placed_t', None)
        repeat = float((cfg.get('disturbance') or {}).get('occlusion_repeat_s', 12.0))
        if not on:
            self._occl_placed_t = None
            return
        if last is None or sim_time < last or sim_time - last >= repeat:
            o = self.obstacles.objects[0]
            o['wx'], o['wy'] = float(target.wx), float(target.wy)
            self._occl_placed_t = sim_time

    def step(self, dt):
        """Advance the full per-frame pipeline by dt seconds:
        disturbance levels -> world/camera update -> render -> disturbance
        -> detect -> classify -> track -> servo -> shared state + metrics.
        Called by run() with wall-clock dt, and by the headless harness
        with a fixed dt. Returns 'ok', 'no_frame' (video gave no frame) or
        'video_done' (video ended; caller handles the session end)."""
        camera      = self.camera
        world       = self.world
        target      = self.target
        distractors = self.distractors
        obstacles   = self.obstacles
        disturbance = self.disturbance
        detector    = self.detector
        classifier  = self.classifier
        tracker     = self.tracker
        pid         = self.pid
        servo       = self.servo

        # Disturbances
        d = self.state.get('disturbances', {})
        if d:
            disturbance.set_levels(
                turbulence        = d.get('turbulence', 0.0),
                vibration         = d.get('vibration',  0.0),
                noise             = d.get('noise',      0.0),
                scintillation     = d.get('scintillation', 0.0),
                jerk              = d.get('jerk',       0.0),
                atmosphere        = d.get('atmosphere', 'clear'),
                noise_gaussian    = d.get('noise_gaussian', True),
                noise_saltpepper  = d.get('noise_saltpepper', False),
                noise_poisson     = d.get('noise_poisson', False),
                platform_enabled  = d.get('platform_enabled', False),
                platform_speed    = d.get('platform_speed', 5.0),
                low_light         = d.get('low_light', False),
            )

        self.sim_time += dt
        sim_time = self.sim_time

        with self._lock:
            is_video = self._video_mode
            v_source = self._video_source

        # Video mode (PS Benchmark-2): the recorded camera is fixed, so the
        # virtual camera is never moved (no servo, ego-motion = 0) and no
        # synthetic disturbance is added on top of the recorded frames.
        if not is_video:
            if self.lab is None:
                target.update(dt)
            else:
                self.lab.update(camera,dt)
            camera.update(dt)
            distractors.update(dt)
            obstacles.update(dt)
            self._update_occlusion_toggle(target, sim_time)

        perf = {}
        perf_start = time.perf_counter()
        scint = disturbance.get_scintillation()

        if is_video and v_source is not None:
            with self._lock:
                frame, gt, done = v_source.get_frame()

            if done:
                return 'video_done'

            if frame is None:
                return 'no_frame'

            self._frame_count += 1

            # Store video ground truth in shared state if available
            # Use same key name as simulation ground truth so dashboard works unchanged
            gt_sx = gt[0] if gt is not None else None
            gt_sy = gt[1] if gt is not None else None
            occluded = False


            frame_t = np.transpose(frame, (1, 0, 2))
            scene_surf = pygame.surfarray.make_surface(frame_t)
        else:
            scene_surf, occ_list = world.render(
                camera.cam_x, camera.cam_y,
                [target],
                distractors=distractors.positions,
                obstacles=(obstacles.rects if self.state.get('occlusion', True)
                           else []),
                scintillation=scint,
            )
            occluded = occ_list[0] if occ_list else False

        perf["Capture/Render"] = (time.perf_counter() - perf_start) * 1000
        perf_start = time.perf_counter()
        if not is_video:
            scene_surf = disturbance.apply(scene_surf, dt)
        perf["Disturbance"] = (time.perf_counter() - perf_start) * 1000

        t_pipe0 = time.perf_counter()
        mode = self.detection_mode
        k = self.process_every_k
        skip = k > 1 and self._step_index % k != 0
        self._step_index += 1
        if skip:
            candidates = []                  # detector not run this frame
        elif mode == 'ai':
            candidates = self.ai_scanner.detect(scene_surf)   # scored already
        else:
            candidates = detector.detect(scene_surf)
        perf["Detect"] = (time.perf_counter() - t_pipe0) * 1000
        perf_start = time.perf_counter()
        if self.detector_blackout:
            candidates = []
        if candidates and mode != 'ai':
            scorer = self.cv_scorer if mode == 'cv' else classifier
            candidates = scorer.classify(candidates)

        perf["Classify (CNN)"] = (time.perf_counter() - perf_start) * 1000 if mode == "hybrid" else None

        # Acquisition time tracking — starts from the first frame the
        # detector finds any candidate blob, not from Run/reset/session
        # start. This is the PS-correct metric: time from first
        # detection to LOCKED.
        if self._first_detection_time is None and len(candidates) > 0:
            self._first_detection_time = time.time()
            print(f'[Acq] First detection at t={self._first_detection_time:.2f}')

        clean_rgb = self._surf_to_rgb(scene_surf)
        self._draw_overlay(scene_surf, candidates, tracker, camera)

        # Observe existing nested calls without changing their order or results.
        stage_originals = []
        for obj, label in ((tracker.stabiliser, "Stabilise"), (tracker.scene, "Scene estimate")):
            original = obj.update
            def measured(*args, _original=original, _label=label, **kwargs):
                started = time.perf_counter()
                try:
                    return _original(*args, **kwargs)
                finally:
                    perf[_label] = (time.perf_counter() - started) * 1000
            stage_originals.append((obj, original))
            obj.update = measured
        perf_start = time.perf_counter()
        try:
            if skip:
                track_state = tracker.predict_only(camera)
            else:
                track_state = tracker.process(candidates, camera, dt,
                                               gray=getattr(detector, 'last_cleaned', None),
                                               raw=getattr(detector, 'last_gray', None))
        finally:
            for obj, original in stage_originals:
                obj.update = original
        perf["Track (IMM + fusion)"] = max(0, (time.perf_counter() - perf_start) * 1000 - sum(perf.get(k, 0) for k in ("Stabilise", "Scene estimate")))
        perf_start = time.perf_counter()
        if not is_video and (self.lab is None or self.lab.mode=='auto'):
            servo.update(tracker, dt)
        perf["Control (servo)"] = (time.perf_counter() - perf_start) * 1000 if not is_video else None
        # Tracking-pipeline compute time (detect -> classify -> track ->
        # servo), excluding scene rendering and disturbance synthesis.
        self.last_pipeline_ms = (time.perf_counter() - t_pipe0) * 1000.0

        # Locked streak tracking
        if track_state == TrackState.LOCKED:
            self._locked_streak += 1
        else:
            self._locked_streak = 0

        # Acquisition time tracking (cont'd) — record elapsed time once
        # LOCKED is reached, measured from the first-detection moment set above.
        if (track_state == TrackState.LOCKED and not self._acquired
                and self._first_detection_time is not None):
            acq_time = time.time() - self._first_detection_time
            self._acquired = True
            self.state['acq_time'] = round(acq_time, 2)
            print(f'[Acq] Locked in {acq_time:.2f}s after first detection')

        # Tracking error — in stabilised coordinates (the camera's real
        # pointing error; image jitter doesn't move the camera). The raw,
        # jittered sensor position is kept for correct-lock scoring and
        # the raw image error.
        err_px = 0.0
        tx_screen = ty_screen = None
        sx_stab = sy_stab = None
        if track_state == TrackState.LOCKED and \
                tracker.tracked_pixel is not None:
            cx = cfg.camera.resolution_width  / 2
            cy = cfg.camera.resolution_height / 2
            tx_screen, ty_screen = tracker.tracked_pixel
            sx_stab, sy_stab = tracker.stabilised_pixel
            if self._locked_streak >= 10 and not is_video:
                err_px = float(np.hypot(sx_stab - cx, sy_stab - cy))
                self._max_err = max(self._max_err, err_px)

        if not is_video and track_state == TrackState.LOCKED and self._locked_streak >= 10:
            self._err_sq_sum += err_px ** 2
            self._err_count  += 1
            rmse = float(np.sqrt(
                self._err_sq_sum / self._err_count))
        elif track_state == TrackState.LOCKED and self._err_count > 0:
            rmse = float(np.sqrt(self._err_sq_sum / self._err_count))
        else:
            rmse = None

        # Ground truth in screen coords — where the beacon actually is in
        # the image the detector saw: world_to_screen plus the whole-image
        # translation (jitter/jerk/platform) the disturbance engine applied
        # this frame. Scoring only; never fed to the tracker.
        if not is_video:
            gt_sx, gt_sy = camera.world_to_screen(target.wx, target.wy)
            off_x, off_y = disturbance.applied_offset
            gt_sx += off_x
            gt_sy += off_y

        # Side-panel lock retention: the ground-truth correct-lock rate
        # (LOCKED within CORRECT_LOCK_TOL_PX of GT, as the harness scores it)
        # whenever GT exists; otherwise the tracker's own estimate, labelled
        # as such. Display/scoring only.
        gl = getattr(self, '_gt_lock', None)
        if gl is None:
            gl = self._gt_lock = [0, 0]
        if gt_sx is not None and gt_sy is not None:
            gl[1] += 1
            if (track_state == TrackState.LOCKED and tx_screen is not None
                    and np.hypot(tx_screen - gt_sx, ty_screen - gt_sy) <= CORRECT_LOCK_TOL_PX):
                gl[0] += 1
        if gl[1]:
            lock_rate, lock_rate_src = gl[0] / gl[1], 'gt'
        else:
            lock_rate, lock_rate_src = tracker.lock_retention_rate, 'tracker'

        # FPS
        now = time.perf_counter()
        dt_real = max(now - self._last_t, 1e-6)
        self._fps_samples.append(1.0 / dt_real)
        self._last_t = now
        if len(self._fps_samples) > 60:
            self._fps_samples.pop(0)
        fps = sum(self._fps_samples) / len(self._fps_samples)

        frame_rgb = self._surf_to_rgb(scene_surf)

        top_conf = candidates[0].confidence if candidates else 0.0
        n_wps = len(tracker.search._waypoints)
        scan_coverage_pct = (tracker.search._wp_index / n_wps * 100.0
                              if n_wps else 0.0)

        # State transitions & duration tracking
        st_name = getattr(track_state, 'name', str(track_state))
        if st_name != self._current_state:
            self._current_state = st_name
            self._current_state_time = 0.0
            self._state_history.append({'state': st_name, 'duration': 0.0})
            if len(self._state_history) > 40:
                self._state_history.pop(0)

        self._current_state_time += dt
        self._state_durations[st_name] = self._state_durations.get(st_name, 0.0) + dt
        if self._state_history:
            self._state_history[-1]['duration'] = round(self._current_state_time, 2)

        # Target loss calculation
        if self._metrics is not None and self._metrics.states:
            tot_f = len(self._metrics.states)
            lost_f = self._metrics.lost_count
            target_loss_pct = round(100.0 * lost_f / tot_f, 1) if tot_f > 0 else 0.0
        else:
            target_loss_pct = 0.0

        # Re-acquisition time
        reacq_val = None
        if self._metrics is not None and len(self._metrics.states) >= 15:
            try:
                # At most one full reduction per doubling of session length,
                # plus one per 120 frames for short runs. Final export is exact.
                n = len(self._metrics.states)
                if n >= self._live_score_at:
                    if self._metrics._has_ground_truth():
                        self._live_scores = self._metrics._gt_scores()
                    self._live_score_at = n + max(120, n)
                reacq_val = self._live_scores.get('reacq_mean_s')
            except Exception:
                pass

        # Predicted pixel position (from Kalman/IMM filter or predictive target)
        pred_px = pred_py = None
        if tracker.kalman.x is not None:
            kx = float(tracker.kalman.x[0])
            ky = float(tracker.kalman.x[1])
            kvx = float(tracker.kalman.x[2])
            kvy = float(tracker.kalman.x[3])
            pred_px = kx + kvx
            pred_py = ky + kvy
        elif tracker.predictive_target is not None:
            pred_px = float(tracker.predictive_target[0])
            pred_py = float(tracker.predictive_target[1])

        self.state.update({
            'frame_rgb':       frame_rgb,
            'lab_status': self.lab.status(camera,target) if self.lab else None,
            'fps':             fps,
            'sim_time':        sim_time,
            'pipeline_ms':     self.last_pipeline_ms,
            'perf_frame':      {'frame': self._step_index, 'sim_time': sim_time, 'stages': perf},
            'track_state':     track_state,
            'track_error_px':  None if is_video or track_state != TrackState.LOCKED or self._locked_streak < 10 else err_px,
            'max_error_px':    self._max_err,
            'rolling_conf':    tracker.rolling_confidence,
            'confidence':      tracker.rolling_confidence,
            'lock_rate':       lock_rate,
            'lock_rate_source': lock_rate_src,
            'reacq_count':     tracker.reacquire_count,
            'reacq_time':      reacq_val,
            'target_loss':     target_loss_pct,
            'current_state_time': round(self._current_state_time, 2),
            'state_durations': dict(self._state_durations),
            'state_history': list(self._state_history),
            'predicted_x':     pred_px,
            'predicted_y':     pred_py,
            'uncertainty_px':  tracker.uncertainty,
            'cam_x':           camera.cam_x,
            'cam_y':           camera.cam_y,
            'cam_pan':         camera.pan,
            'cam_tilt':        camera.tilt,
            'tgt_wx':          None if is_video else target.wx,
            'tgt_wy':          None if is_video else target.wy,
            'centroid_err_gt_px': (
                float(np.hypot(tx_screen - gt_sx, ty_screen - gt_sy))
                if is_video and None not in (tx_screen, ty_screen, gt_sx, gt_sy)
                else None),
            'gt_sx':           gt_sx,
            'gt_sy':           gt_sy,
            'gt_x':            gt_sx,
            'gt_y':            gt_sy,
            'tracker_sx':      tx_screen,
            'tracker_sy':      ty_screen,
            'tracker_x':       tx_screen,
            'tracker_y':       ty_screen,
            'tracker_stab_sx': sx_stab,
            'tracker_stab_sy': sy_stab,
            'occluded':        occluded,
            'candidates':      len(candidates),
            'det_ms':          (self.ai_scanner if self.detection_mode == 'ai'
                                else detector).last_processing_ms,
            'detector_mode_active': MODE_LABELS[self.detection_mode],
            'pid_i':           pid.integral_state,
            'running':         True,
            'world_w':         int(cfg.world.width),
            'world_h':         int(cfg.world.height),
            'rmse':            rmse,
            'scan_coverage_pct': scan_coverage_pct,
            'acquire_confidence': top_conf,
            'acquire_frames':  tracker.fusion._acq_count,
            'kalman_pred_x':   float(tracker.kalman.x[0]) if tracker.kalman.x is not None else None,
            'kalman_pred_y':   float(tracker.kalman.x[1]) if tracker.kalman.x is not None else None,
            'kalman_vx':       float(tracker.kalman.x[2]) if tracker.kalman.x is not None else 0.0,
            'kalman_vy':       float(tracker.kalman.x[3]) if tracker.kalman.x is not None else 0.0,
            'predictive_target': tracker.predictive_target,
            'predictive_search': tracker.predictive_search_active,
            'predicted_target': (tracker.predictive_target
                                  if tracker.predictive_search_active
                                  else None),
            'search_target_wx': (camera.W / 2 + tracker.search_target[0] * camera.ppd_h
                                  if tracker.search_target is not None else None),
            'search_target_wy': (camera.H / 2 - tracker.search_target[1] * camera.ppd_v
                                  if tracker.search_target is not None else None),
        })

        # Only record frames from the source the session belongs to — a
        # sim frame already in flight when a video is loaded (from the
        # server thread) must not open the video session.
        if (self._metrics is not None
                and (self._metrics.mode == 'video') == bool(is_video)):
            self._metrics.record_frame(self.state)

        # One immutable published packet keeps image and overlays on one frame.
        telemetry = {key:self.state.get(key) for key in (
            'tracker_x','tracker_y','track_error_px','predicted_x','predicted_y',
            'cam_x','cam_y','gt_sx','gt_sy','pipeline_ms','sim_time')}
        telemetry.update(frame_id=self._step_index,track_state=st_name,
            measured_x=(getattr(tracker,'last_measurement',None) or (None,None))[0],
            measured_y=(getattr(tracker,'last_measurement',None) or (None,None))[1],
            measurement_score=getattr(tracker,'last_measurement_score',None),
            display_prediction=getattr(tracker,'display_prediction',None),
            tracker_x=None if tracker.tracked_pixel is None else float(tracker.tracked_pixel[0]),
            tracker_y=None if tracker.tracked_pixel is None else float(tracker.tracked_pixel[1]),
            candidate_count=len(candidates),uncertainty=float(tracker.uncertainty),
            command_x=camera.cmd_x,command_y=camera.cmd_y,
            target_wx=None if is_video else target.wx,target_wy=None if is_video else target.wy,
            camera_config={'width':camera.cam_w,'height':camera.cam_h},
            candidates=[{'x':float(c.x),'y':float(c.y),'radius':float(c.radius),'score':float(c.confidence)} for c in candidates])
        self.state['frame_packet']={'rgb':clean_rgb,'telemetry':telemetry}

        return 'ok'

    def _surf_to_rgb(self, surf):
        raw = pygame.surfarray.array3d(surf)
        return np.transpose(raw, (1, 0, 2))

    def _draw_overlay(self, surface, candidates, tracker, camera):
        state = tracker.state
        sc = {
            TrackState.LOCKED:    (61, 220, 132),
            TrackState.ACQUIRING: (255, 208, 96),
            TrackState.COASTING:  (255, 160, 60),
            TrackState.SEARCHING: (255, 96, 96),
            TrackState.LOST:      (200, 0, 0),
        }.get(state, (255,255,255))

        for c in candidates:
            col = (61,220,132) if c.confidence>=0.75 else \
                  (255,208,96) if c.confidence>=0.40 else (0,150,200)
            r = int(c.radius) + 5
            pygame.draw.circle(surface, col, (int(c.x),int(c.y)), r, 1)

        # Spiral search path — dim dots for visited/queued waypoints, a
        # brighter ring on the current target, and a faint direction line
        # from frame center. Only while actively searching/acquiring;
        # search.is_active naturally goes False once LOCKED (search.stop()).
        if state in (TrackState.SEARCHING, TrackState.ACQUIRING):
            search = tracker.search
            if search.is_active and search._waypoints:
                W = surface.get_width()
                H = surface.get_height()

                def wp_to_screen(pan, tilt):
                    wx = camera.W / 2 + pan * camera.ppd_h
                    wy = camera.H / 2 - tilt * camera.ppd_v
                    return camera.world_to_screen(wx, wy)

                for i, (pan, tilt) in enumerate(search._waypoints):
                    if i == search._wp_index:
                        continue
                    sx, sy = wp_to_screen(pan, tilt)
                    if 0 <= sx <= W and 0 <= sy <= H:
                        pygame.draw.circle(surface, (0, 80, 120), (int(sx), int(sy)), 2)

                target = tracker.search_target
                if target is not None:
                    tsx, tsy = wp_to_screen(target[0], target[1])
                    pygame.draw.line(surface, (0, 80, 120),
                                      (W // 2, H // 2), (int(tsx), int(tsy)), 1)
                    if 0 <= tsx <= W and 0 <= tsy <= H:
                        pygame.draw.circle(surface, (0, 150, 200), (int(tsx), int(tsy)), 4)
                        pygame.draw.circle(surface, (0, 150, 200), (int(tsx), int(tsy)), 8, 1)

        if tracker.tracked_pixel is not None:
            tx = int(tracker.tracked_pixel[0])
            ty = int(tracker.tracked_pixel[1])
            cross_col = (0, 212, 255)   # cyan crosshair, fixed regardless of state
            r, l = 18, 12
            pygame.draw.circle(surface, cross_col, (tx,ty), r, 1)
            pygame.draw.line(surface,cross_col,(tx-r-l,ty),(tx-r,ty),1)
            pygame.draw.line(surface,cross_col,(tx+r,ty),(tx+r+l,ty),1)
            pygame.draw.line(surface,cross_col,(tx,ty-r-l),(tx,ty-r),1)
            pygame.draw.line(surface,cross_col,(tx,ty+r),(tx,ty+r+l),1)

        font = getattr(self,'_overlay_font',None)
        if font is None:
            font = self._overlay_font = pygame.font.SysFont('Consolas', 13, bold=True)
        W = surface.get_width()
        txt = font.render(f'● {state.name}', True, sc)
        surface.blit(txt, (W//2 - txt.get_width()//2, 8))
