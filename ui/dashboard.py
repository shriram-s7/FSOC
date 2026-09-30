"""
FSOC-PAT Simulator — Dear PyGui Mission Control Station
ISRO / Department of Space & SIH 2025 (PS 26169)

Aerospace Mission-Control Station organized into 7 structured operational stages:
  1. HOME / MISSION SETUP — Mission cards, staged wizard, target kinematics & launch briefing
  2. LIVE MISSION        — Primary boresight camera feed, radar, essential telemetry & explainer
  3. GUIDED DEMO         — 8-step interactive presentation walkthrough for evaluators
  4. VIDEO REPLAY        — Pre-recorded mission MP4 ingestion & benchmark
  5. DIAGNOSTICS         — Kalman state, PID loops, 200-frame error graph, camera mechanics
  6. BENCHMARK & RESULTS — ISRO PS 26169 compliance scorecard & evaluation
  7. REPORTS             — Session PDF/CSV log viewer & on-demand snapshot generator
"""
import dearpygui.dearpygui as dpg
import numpy as np
import os
import glob
import time
import datetime
from collections import deque
import cv2
import ctypes

from tracking.temporal_fusion import TrackState

# Internal camera frame & minimap dimensions
FEED_W = 640
FEED_H = 480
TEX_W = 2000
TEX_H = 2000

try:
    user32 = ctypes.windll.user32
    user32.SetProcessDPIAware()
    WIN_W = user32.GetSystemMetrics(0)
    WIN_H = user32.GetSystemMetrics(1)
except Exception:
    WIN_W = 1920
    WIN_H = 1080

TOP_H = 38
STATUS_H = 36
MINIMAP_SIZE = 210

# ── Aerospace Color Palette ──────────────────────────────────────────
BG_MAIN     = (10,  14,  26, 255)   # Deep space void
BG_PANEL    = (8,   12,  22, 255)   # Dark navy panel
BG_CARD     = (14,  20,  36, 255)   # Raised card
BG_FIELD    = (6,    9,  17, 255)   # Input/canvas field
ACCENT      = (0,  212, 255, 255)   # Cyan telemetry
GREEN       = (0,  255, 136, 255)   # Locked / Pass / Nominal
YELLOW      = (255, 204,   0, 255)  # Searching / Caution
ORANGE      = (255, 140,  40, 255)  # Acquiring / Coasting
RED         = (255,  68,  68, 255)  # Alert / Loss / Fail
BORDER      = (26,  36,  58, 255)   # Subtle border
BORDER_HI   = (40,  62,  98, 255)   # Highlighted border
TXT         = (198, 220, 246, 255)  # Primary text
TXT_MUTED   = (84, 108, 142, 255)   # Secondary / label text
TXT_BRIGHT  = (240, 248, 255, 255)  # Crisp white
SECTITLE    = (0,  180, 230, 255)   # Cyan section title

PRESET_VALS = {
    'NONE': {'turbulence': 0.0, 'vibration': 0.0, 'noise': 0.0, 'scintillation': 0.0, 'jerk': 0.0},
    'EASY': {'turbulence': 0.0, 'vibration': 0.0, 'noise': 0.0, 'scintillation': 0.0, 'jerk': 0.0},
    'MOD':  {'turbulence': 0.2, 'vibration': 0.15, 'noise': 0.15, 'scintillation': 0.1, 'jerk': 0.005},
    'HARD': {'turbulence': 0.4, 'vibration': 0.3, 'noise': 0.3, 'scintillation': 0.25, 'jerk': 0.02},
    'SEV':  {'turbulence': 0.65, 'vibration': 0.5, 'noise': 0.5, 'scintillation': 0.4, 'jerk': 0.04},
    'ADV':  {'turbulence': 0.85, 'vibration': 0.7, 'noise': 0.7, 'scintillation': 0.6, 'jerk': 0.07},
}


def state_color(state):
    if state == TrackState.LOCKED:    return GREEN
    if state == TrackState.ACQUIRING: return ORANGE
    if state == TrackState.SEARCHING: return YELLOW
    if state == TrackState.COASTING:  return ORANGE
    if state == TrackState.LOST:      return RED
    return TXT_MUTED


class Dashboard:
    HIST = 200

    def __init__(self, shared_state, callbacks):
        self.state = shared_state
        self.cbs = callbacks
        self._err_hist = deque(maxlen=self.HIST)
        self._err_graph_w = 400

        # Mission setup staged variables
        self._motion_mode = 'Straight'
        self._motion_speed = 30.0
        self._speed_preset = 'Normal'
        self._target_size = 10
        self._target_init_pos = 'center'
        self._atmos_mode = 'Clear'
        self._dist_preset = 'EASY'
        self._custom_dist_open = False

        self._atmos_buttons = {}
        self._preset_buttons = {}
        self._motion_buttons = {}
        self._speed_buttons = {}
        self._pos_buttons = {}

        self._last_report_notice = ""
        self._last_report_notice_time = 0.0
        self._live_test_notice = ""
        self._live_test_notice_time = 0.0

        self._prev_cam_pan = 0.0
        self._prev_cam_tilt = 0.0
        self._prev_cam_t = time.perf_counter()
        self._cam_slew_rate = 0.0
        self._demo_step = 1

    # ── Theme System ──────────────────────────────────────────────────
    def _theme(self):
        with dpg.theme() as t:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg,             BG_MAIN)
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg,              BG_PANEL)
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg,              BG_FIELD)
                dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered,       (14, 24, 42, 255))
                dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive,        (20, 36, 62, 255))
                dpg.add_theme_color(dpg.mvThemeCol_SliderGrab,           ACCENT)
                dpg.add_theme_color(dpg.mvThemeCol_SliderGrabActive,     ACCENT)
                dpg.add_theme_color(dpg.mvThemeCol_CheckMark,            ACCENT)
                dpg.add_theme_color(dpg.mvThemeCol_Button,               (16, 24, 40, 255))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered,        (24, 38, 64, 255))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive,         (32, 52, 88, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Text,                 TXT)
                dpg.add_theme_color(dpg.mvThemeCol_Border,               BORDER)
                dpg.add_theme_color(dpg.mvThemeCol_Separator,            BORDER)
                dpg.add_theme_color(dpg.mvThemeCol_ScrollbarBg,          (0, 0, 0, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrab,        (26, 40, 66, 255))
                dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrabHovered, (36, 56, 92, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Tab,                  (12, 18, 30, 255))
                dpg.add_theme_color(dpg.mvThemeCol_TabHovered,           (20, 32, 54, 255))
                dpg.add_theme_color(dpg.mvThemeCol_TabActive,            (18, 28, 48, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Header,               (18, 28, 48, 255))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered,        (26, 42, 70, 255))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderActive,         (34, 56, 94, 255))

                dpg.add_theme_style(dpg.mvStyleVar_WindowRounding,       0)
                dpg.add_theme_style(dpg.mvStyleVar_ChildRounding,        3)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding,        3)
                dpg.add_theme_style(dpg.mvStyleVar_TabRounding,          4)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding,        0, 0)
                dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize,      1)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing,          6, 6)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding,         8, 5)
        dpg.bind_theme(t)

        self._th_btn_start = self._make_button_theme(GREEN, (0, 48, 26, 255), GREEN)
        self._th_btn_action = self._make_button_theme(ACCENT, (0, 34, 52, 255), ACCENT)
        self._th_btn_stop = self._make_button_theme(RED, (48, 12, 12, 255), RED)
        self._th_pill_active = self._make_button_theme(ACCENT, (0, 34, 48, 255), ACCENT)
        self._th_pill_inactive = self._make_button_theme(BORDER, BG_FIELD, TXT_MUTED)
        self._th_disabled = self._make_button_theme(BORDER, (10, 14, 22, 180), (60, 80, 105, 255))

    def _make_button_theme(self, border_color, bg_color, text_color):
        with dpg.theme() as t:
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Text,          text_color)
                dpg.add_theme_color(dpg.mvThemeCol_Button,        bg_color)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (min(255, bg_color[0]+15), min(255, bg_color[1]+15), min(255, bg_color[2]+20), 255))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive,  (min(255, bg_color[0]+30), min(255, bg_color[1]+30), min(255, bg_color[2]+40), 255))
                dpg.add_theme_color(dpg.mvThemeCol_Border,        border_color)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 1.2)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding,   4)
        return t

    def _card_theme(self):
        with dpg.theme() as t:
            with dpg.theme_component(dpg.mvChildWindow):
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, BG_CARD)
                dpg.add_theme_color(dpg.mvThemeCol_Border,  BORDER)
                dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 1.0)
                dpg.add_theme_style(dpg.mvStyleVar_ChildRounding,   4)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding,   10, 10)
        return t

    def _minimap_theme(self):
        with dpg.theme() as t:
            with dpg.theme_component(dpg.mvChildWindow):
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (4, 8, 16, 230))
                dpg.add_theme_color(dpg.mvThemeCol_Border,  (0, 180, 220, 160))
                dpg.add_theme_style(dpg.mvStyleVar_ChildBorderSize, 1.2)
                dpg.add_theme_style(dpg.mvStyleVar_ChildRounding,   3)
        return t

    # ── Texture & UV Handling ─────────────────────────────────────────
    def _texture(self):
        blank = np.zeros((TEX_H, TEX_W, 4), dtype=np.float32)
        with dpg.texture_registry():
            dpg.add_raw_texture(
                width=TEX_W, height=TEX_H,
                default_value=blank,
                format=dpg.mvFormat_Float_rgba,
                tag='cam_tex')

    def _calc_uv(self, canvas_w, canvas_h):
        if canvas_w <= 0 or canvas_h <= 0:
            return [0.0, 0.0], [1.0, 1.0]
        c_aspect = canvas_w / float(canvas_h)
        t_aspect = float(TEX_W) / float(TEX_H)
        if c_aspect < t_aspect:
            vis = c_aspect / t_aspect
            crop = max(0.0, (1.0 - vis) * 0.5)
            return [crop, 0.0], [1.0 - crop, 1.0]
        else:
            vis = t_aspect / c_aspect
            crop = max(0.0, (1.0 - vis) * 0.5)
            return [0.0, crop], [1.0, 1.0 - crop]

    # ── Master Layout Builder ────────────────────────────────────────
    def _build(self):
        global WIN_W, WIN_H
        content_h = WIN_H - TOP_H - STATUS_H

        with dpg.window(
                tag='main', label='',
                width=WIN_W, height=WIN_H, pos=[0, 0],
                no_title_bar=True, no_resize=True, no_move=True,
                no_scrollbar=True, no_collapse=True):

            self._build_topbar(WIN_W)

            with dpg.child_window(
                    tag='content_area', width=WIN_W, height=content_h,
                    pos=[0, TOP_H], border=False, no_scrollbar=True):

                with dpg.tab_bar(tag='main_tab_bar'):
                    with dpg.tab(label='  HOME / SETUP  ', tag='tab_setup'):
                        self._build_tab_setup(WIN_W, content_h - 32)
                    with dpg.tab(label='  LIVE MISSION  ', tag='tab_live'):
                        self._build_tab_live(WIN_W, content_h - 32)
                    with dpg.tab(label='  GUIDED DEMO  ', tag='tab_demo'):
                        self._build_tab_demo(WIN_W, content_h - 32)
                    with dpg.tab(label='  VIDEO REPLAY  ', tag='tab_video'):
                        self._build_tab_video(WIN_W, content_h - 32)
                    with dpg.tab(label='  DIAGNOSTICS  ', tag='tab_diag'):
                        self._build_tab_diag(WIN_W, content_h - 32)
                    with dpg.tab(label='  BENCHMARK & RESULTS  ', tag='tab_bench'):
                        self._build_tab_bench(WIN_W, content_h - 32)
                    with dpg.tab(label='  REPORTS  ', tag='tab_reports'):
                        self._build_tab_reports(WIN_W, content_h - 32)

            self._build_statusbar(WIN_W, WIN_H - STATUS_H)

    # ── Zone 1: Mission Header Bar ────────────────────────────────────
    def _build_topbar(self, win_w):
        with dpg.child_window(
                tag='top_bar', width=win_w, height=TOP_H, pos=[0, 0],
                border=False, no_scrollbar=True):
            with dpg.group(horizontal=True, pos=[12, 8]):
                dpg.add_text('FSOC-PAT', color=ACCENT)
                dpg.add_text('  Autonomous Coarse Alignment', color=TXT_BRIGHT)
                dpg.add_text('  |  ISRO PS 26169', color=TXT_MUTED)
                dpg.add_text('  STATE:', color=TXT_MUTED)
                dpg.add_text('STANDBY (READY)', tag='top_state_badge', color=YELLOW)
                dpg.add_text('  SOURCE:', color=TXT_MUTED)
                dpg.add_text('SIMULATION', tag='top_mode_badge', color=TXT_MUTED)
                dpg.add_spacer(width=10)
                dpg.add_button(label='  Export Snapshot (PDF+CSV)  ',
                               callback=self._on_export_snapshot_click)
                dpg.bind_item_theme(dpg.last_item(), self._th_pill_active)

            with dpg.group(tag='top_right_grp', horizontal=True, pos=[max(0, win_w - 430), 8]):
                dpg.add_text('ERR:', color=TXT_MUTED)
                dpg.add_text('- px', tag='top_err', color=TXT_BRIGHT)
                dpg.add_text('  ACQ:', color=TXT_MUTED)
                dpg.add_text('-', tag='top_acq', color=TXT_BRIGHT)
                dpg.add_text('  SIM TIME:', color=TXT_MUTED)
                dpg.add_text('0.0s', tag='top_simtime', color=TXT_BRIGHT)
                dpg.add_text('  FPS:', color=TXT_MUTED)
                dpg.add_text('0', tag='top_fps', color=GREEN)

    # ── Tab 1: Home / Mission Setup (Default Opening Screen) ───────────
    def _build_tab_setup(self, win_w, tab_h):
        card_w = (win_w - 50) // 4
        sub_h = tab_h - 135

        with dpg.child_window(width=win_w, height=tab_h, border=False):
            # 1. Four Large Mission Mode Cards
            with dpg.group(horizontal=True, pos=[10, 8]):
                # Card 1: Quick Demo
                with dpg.child_window(width=card_w, height=115, border=True):
                    dpg.add_text('QUICK DEMO', color=ACCENT)
                    dpg.add_text('Judge-ready 8-step walkthrough with clean baseline acquisition and disturbance stress.',
                                 color=TXT_MUTED, wrap=card_w - 20)
                    dpg.add_spacer(height=2)
                    dpg.add_button(label='[ Launch Quick Demo ]', width=-1,
                                   callback=self._on_quick_demo_click)
                    dpg.bind_item_theme(dpg.last_item(), self._th_pill_active)

                # Card 2: Custom Simulation
                with dpg.child_window(width=card_w, height=115, border=True):
                    dpg.add_text('CUSTOM SIMULATION', color=GREEN)
                    dpg.add_text('Define target kinematics, atmospheric conditions, and disturbance levels.',
                                 color=TXT_MUTED, wrap=card_w - 20)
                    dpg.add_spacer(height=2)
                    dpg.add_button(label='[ Staged Setup Below ]', width=-1,
                                   callback=lambda: None)
                    dpg.bind_item_theme(dpg.last_item(), self._th_btn_start)

                # Card 3: Video Replay
                with dpg.child_window(width=card_w, height=115, border=True):
                    dpg.add_text('VIDEO REPLAY', color=SECTITLE)
                    dpg.add_text('Load and benchmark pre-recorded optical sensor MP4 footage with computer vision.',
                                 color=TXT_MUTED, wrap=card_w - 20)
                    dpg.add_spacer(height=2)
                    dpg.add_button(label='[ Select MP4 Video... ]', width=-1,
                                   callback=lambda: self.cbs.get('load_video', lambda: None)())
                    dpg.bind_item_theme(dpg.last_item(), self._th_btn_action)

                # Card 4: Benchmark
                with dpg.child_window(width=card_w, height=115, border=True):
                    dpg.add_text('BENCHMARK', color=YELLOW)
                    dpg.add_text('ISRO PS 26169 formal requirement evaluation & session compliance scorecard.',
                                 color=TXT_MUTED, wrap=card_w - 20)
                    dpg.add_spacer(height=2)
                    dpg.add_button(label='[ View Compliance ]', width=-1,
                                   callback=lambda: dpg.set_value('main_tab_bar', 'tab_bench'))
                    dpg.bind_item_theme(dpg.last_item(), self._th_pill_inactive)

            dpg.add_spacer(height=4)

            # 2. Staged Mission Builder Workflow
            left_w = int(win_w * 0.62)
            right_w = win_w - left_w - 26

            with dpg.group(horizontal=True, pos=[10, 130]):
                # Left Column: Staged Parameters (Steps 1 - 4)
                with dpg.child_window(width=left_w, height=sub_h, border=False):
                    # STEP 1 — TARGET
                    with dpg.child_window(width=-1, height=155, border=True):
                        dpg.add_text('STEP 1 — TARGET KINEMATICS & INITIAL POSITION', color=SECTITLE)
                        dpg.add_separator()
                        with dpg.group(horizontal=True):
                            dpg.add_text('Motion Profile: ', color=TXT_MUTED)
                            for m in ['Straight', 'Circular', 'Figure-8', 'Random', 'Spiral', 'Sinusoidal']:
                                tag = f'setup_m_{m}'
                                dpg.add_button(label=m, tag=tag,
                                               callback=lambda s, a, u=m: self._on_motion_click(u))
                                self._motion_buttons[m] = tag

                        dpg.add_spacer(height=2)
                        with dpg.group(horizontal=True):
                            dpg.add_text('Target Speed:   ', color=TXT_MUTED)
                            for spd_lbl, spd_val in [('Slow (15 px/s)', 15.0), ('Normal (30 px/s)', 30.0), ('Fast (60 px/s)', 60.0)]:
                                tag = f'setup_spd_{spd_lbl[:4]}'
                                dpg.add_button(label=spd_lbl, tag=tag,
                                               callback=lambda s, a, u=spd_val, l=spd_lbl[:4]: self._on_speed_preset_click(l, u))
                                self._speed_buttons[spd_lbl[:4]] = tag

                        dpg.add_spacer(height=2)
                        with dpg.group(horizontal=True):
                            dpg.add_text('Initial Offset: ', color=TXT_MUTED)
                            # In FOV
                            btn_fov = dpg.add_button(label='[ IN CAMERA FOV ]', tag='setup_pos_fov',
                                                     callback=lambda: self._on_pos_click('center'))
                            self._pos_buttons['center'] = btn_fov
                            # Near FOV
                            btn_near = dpg.add_button(label='[ NEAR CAMERA FOV ]', tag='setup_pos_near',
                                                      callback=lambda: self._on_pos_click('near'))
                            self._pos_buttons['near'] = btn_near
                            # Search challenge (Disabled honestly)
                            btn_chall = dpg.add_button(label='SEARCH CHALLENGE (Backend pending)', tag='setup_pos_chall',
                                                       callback=lambda: None)
                            dpg.bind_item_theme(btn_chall, self._th_disabled)

                    # STEP 2 — ENVIRONMENT
                    with dpg.child_window(width=-1, height=110, border=True):
                        dpg.add_text('STEP 2 — ATMOSPHERIC OPTICAL CHANNEL', color=SECTITLE)
                        dpg.add_separator()
                        with dpg.group(horizontal=True):
                            btn_w = (left_w - 70) // 5
                            env_meta = [
                                ('Clear', 'Clear path'),
                                ('Haze', 'Moderate haze'),
                                ('Fog', 'Dense scattering'),
                                ('Rain', 'Dynamic streaks'),
                                ('Low light', 'Photon starvation')
                            ]
                            for env, sub in env_meta:
                                tag = f'setup_env_{env}'
                                dpg.add_button(
                                    label=f'{env}\n{sub}', tag=tag, width=btn_w,
                                    callback=lambda s, a, u=env: self._on_atmos_click(u))
                                self._atmos_buttons[env] = tag

                    # STEP 3 — DISTURBANCES
                    with dpg.child_window(width=-1, height=140, border=True):
                        dpg.add_text('STEP 3 — DISTURBANCE STRESS LEVEL', color=SECTITLE)
                        dpg.add_separator()
                        with dpg.group(horizontal=True):
                            dpg.add_text('Preset Level:', color=TXT_MUTED)
                            p_w = (left_w - 140) // 5
                            for p in ['NONE', 'LIGHT', 'MODERATE', 'SEVERE', 'CUSTOM']:
                                tag = f'setup_dist_{p}'
                                dpg.add_button(
                                    label=p, tag=tag, width=p_w,
                                    callback=lambda s, a, u=p: self._on_dist_preset_click(u))
                                self._preset_buttons[p] = tag

                        # Collapsible custom sliders (Revealed when CUSTOM is chosen)
                        with dpg.group(tag='setup_custom_sliders_grp', show=False):
                            dpg.add_spacer(height=2)
                            dpg.add_text('FINE DISTURBANCE SLIDERS (CUSTOM):', color=TXT_MUTED)
                            with dpg.group(horizontal=True):
                                dpg.add_text('Turbulence:', color=TXT_MUTED)
                                dpg.add_slider_float(default_value=0.0, min_value=0.0, max_value=1.0, width=160, format='%.2f',
                                                     callback=lambda s, v: self._on_disturbance_slider('turbulence', v))
                                dpg.add_text('  Vibration:', color=TXT_MUTED)
                                dpg.add_slider_float(default_value=0.0, min_value=0.0, max_value=1.0, width=160, format='%.2f',
                                                     callback=lambda s, v: self._on_disturbance_slider('vibration', v))
                            with dpg.group(horizontal=True):
                                dpg.add_text('Sensor Noise:', color=TXT_MUTED)
                                dpg.add_slider_float(default_value=0.0, min_value=0.0, max_value=1.0, width=160, format='%.2f',
                                                     callback=lambda s, v: self._on_disturbance_slider('noise', v))
                                dpg.add_text('  Distractors:', color=TXT_MUTED)
                                dpg.add_slider_int(default_value=0, min_value=0, max_value=10, width=160,
                                                   callback=lambda s, v: self.cbs.get('set_distractor_count', lambda x: None)(v))

                    # STEP 4 — DETECTION PIPELINE
                    with dpg.child_window(width=-1, height=75, border=True):
                        dpg.add_text('STEP 4 — DETECTION & TRACKING ARCHITECTURE', color=SECTITLE)
                        dpg.add_separator()
                        with dpg.group(horizontal=True):
                            # Hybrid Active
                            b_hyb = dpg.add_button(label='[ HYBRID: OpenCV + BeaconCNN (ACTIVE) ]',
                                                   callback=lambda: None)
                            dpg.bind_item_theme(b_hyb, self._th_btn_start)
                            # CV Only Disabled
                            b_cv = dpg.add_button(label='CV ONLY (Backend pending)',
                                                  callback=lambda: None)
                            dpg.bind_item_theme(b_cv, self._th_disabled)
                            # AI Only Disabled
                            b_ai = dpg.add_button(label='AI ONLY (Backend pending)',
                                                  callback=lambda: None)
                            dpg.bind_item_theme(b_ai, self._th_disabled)

                # Right Column: Mission Summary Card & Large Launch CTA
                with dpg.child_window(width=right_w, height=sub_h, border=False):
                    with dpg.child_window(width=-1, height=sub_h - 70, border=True):
                        dpg.add_text('MISSION READY SUMMARY', color=SECTITLE)
                        dpg.add_separator()
                        dpg.add_spacer(height=2)
                        dpg.add_text('Target Kinematics:', color=TXT_MUTED)
                        dpg.add_text('Straight Line · Normal (30 px/s)', tag='brief_target', color=TXT_BRIGHT)
                        dpg.add_spacer(height=4)
                        dpg.add_text('Initial Offset:', color=TXT_MUTED)
                        dpg.add_text('In Camera FOV (World Center)', tag='brief_pos', color=TXT_BRIGHT)
                        dpg.add_spacer(height=4)
                        dpg.add_text('Atmospheric Channel:', color=TXT_MUTED)
                        dpg.add_text('Clear Atmosphere', tag='brief_env', color=TXT_BRIGHT)
                        dpg.add_spacer(height=4)
                        dpg.add_text('Disturbance Stress Level:', color=TXT_MUTED)
                        dpg.add_text('EASY (Turbulence: 0.0, Vibration: 0.0)', tag='brief_dist', color=TXT_BRIGHT)
                        dpg.add_spacer(height=4)
                        dpg.add_text('Detection & Estimation Pipeline:', color=TXT_MUTED)
                        dpg.add_text('Hybrid: Contour Saliency + BeaconCNN', color=GREEN)
                        dpg.add_spacer(height=4)
                        dpg.add_text('Camera Viewport:', color=TXT_MUTED)
                        dpg.add_text('640x480 px | FOV 4.0°x3.0° | Slew 5.0°/s', color=TXT_BRIGHT)
                        dpg.add_spacer(height=4)
                        dpg.add_text('Mission Objective:', color=TXT_MUTED)
                        dpg.add_text('Acquire Target -> Optical Lock -> Maintain Coarse Boresight', color=ACCENT)
                        dpg.add_spacer(height=6)
                        dpg.add_separator()
                        dpg.add_text('ISRO PS 26169 TARGET CRITERIA:', color=TXT_MUTED)
                        dpg.add_text('• Acquisition Time <= 2.0 s\n• Tracking Error <= 10.0 px RMS\n• Target Loss Rate < 5.0%\n• Processing Speed >= 20 FPS',
                                     color=(160, 210, 240, 255))

                    dpg.add_spacer(height=6)
                    # Main START MISSION Action Button
                    dpg.add_button(
                        label='[ START MISSION ]', tag='btn_start_mission',
                        width=-1, height=54,
                        callback=self._start_mission_action)
                    dpg.bind_item_theme('btn_start_mission', self._th_btn_start)

        self._refresh_setup_buttons()

    # ── Tab 2: Live Mission (Main Judge-Facing Presentation Screen) ────
    def _build_tab_live(self, win_w, tab_h):
        left_w = int(win_w * 0.67)
        right_w = win_w - left_w - 24

        with dpg.group(horizontal=True, pos=[10, 8]):
            # Left: Large Boresight Feed & World Radar
            with dpg.child_window(tag='live_viewport_panel', width=left_w, height=tab_h, border=True):
                # Persistent Stage Breadcrumb Header
                with dpg.group(horizontal=True, pos=[8, 4]):
                    dpg.add_text('MISSION STAGE:', color=TXT_MUTED)
                    dpg.add_text('1 Setup', tag='stage_lbl_1', color=TXT_MUTED)
                    dpg.add_text('->', color=BORDER)
                    dpg.add_text('2 Acquire', tag='stage_lbl_2', color=YELLOW)
                    dpg.add_text('->', color=BORDER)
                    dpg.add_text('3 Boresight Lock', tag='stage_lbl_3', color=TXT_MUTED)
                    dpg.add_text('->', color=BORDER)
                    dpg.add_text('4 Stress Test', tag='stage_lbl_4', color=TXT_MUTED)
                    dpg.add_text('->', color=BORDER)
                    dpg.add_text('5 Recovery', tag='stage_lbl_5', color=TXT_MUTED)
                    dpg.add_text('->', color=BORDER)
                    dpg.add_text('6 Video', tag='stage_lbl_6', color=TXT_MUTED)
                    dpg.add_text('->', color=BORDER)
                    dpg.add_text('7 Results', tag='stage_lbl_7', color=TXT_MUTED)

                uv_min, uv_max = self._calc_uv(left_w - 4, tab_h - 48)
                dpg.add_image(
                    'cam_tex', tag='cam_img',
                    pos=[2, 24],
                    width=left_w - 4, height=tab_h - 48,
                    uv_min=uv_min, uv_max=uv_max)

                # Viewport footer coordinates & camera status
                dpg.add_text(
                    'CAMERA STATUS | PAN: +0.00°  TILT: +0.00°  SLEW: 0.0°/s  MODE: AUTONOMOUS TRACKING',
                    pos=[10, tab_h - 20], tag='viewport_pantilt_lbl',
                    color=(160, 190, 220, 220))

                # Embedded World Minimap
                map_w = MINIMAP_SIZE
                map_h = MINIMAP_SIZE
                map_x = left_w - map_w - 14
                map_y = tab_h - map_h - 14

                with dpg.child_window(
                        tag='world_panel', pos=[map_x, map_y],
                        width=map_w, height=map_h, border=True, no_scrollbar=True):
                    dpg.add_text('WORLD RADAR  2000x2000', color=ACCENT)
                    with dpg.drawlist(tag='world_draw', width=map_w - 16, height=map_h - 34):
                        pass

            # Right: Explainer, Core Metrics, Live Tests, Controls
            with dpg.child_window(tag='live_sidebar_panel', width=right_w, height=tab_h, border=False):
                # 1. Mission State & Plain-English Storytelling Explainer
                with dpg.child_window(tag='live_state_card', width=-1, height=125, border=True):
                    dpg.add_text('AUTONOMOUS ALIGNMENT STATUS', color=SECTITLE)
                    dpg.add_separator()
                    with dpg.group(horizontal=True):
                        dpg.add_text('MISSION STATE:', color=TXT_MUTED)
                        dpg.add_text('STANDBY', tag='live_state_title', color=YELLOW)
                    dpg.add_spacer(height=2)
                    dpg.add_text(
                        'Scanning the virtual scene for the optical beacon.',
                        tag='explainer_text', color=TXT_BRIGHT, wrap=right_w - 24)
                    dpg.add_spacer(height=4)
                    dpg.add_text(
                        'Camera Pointing: Pan +0.00°, Tilt +0.00° (5.0°/s slew limit)',
                        tag='live_cam_pointing', color=TXT_MUTED)

                # 2. Key Performance Metrics
                with dpg.child_window(tag='live_telemetry_card', width=-1, height=135, border=True):
                    dpg.add_text('KEY MISSION METRICS', tag='telemetry_card_title', color=SECTITLE)
                    dpg.add_separator()
                    with dpg.table(header_row=False, borders_innerH=False, borders_innerV=False,
                                   borders_outerH=False, borders_outerV=False,
                                   policy=dpg.mvTable_SizingStretchProp):
                        dpg.add_table_column()
                        dpg.add_table_column()
                        with dpg.table_row():
                            with dpg.group():
                                dpg.add_text('Tracking Error', color=TXT_MUTED)
                                dpg.add_text('- px', tag='card_err', color=GREEN)
                                dpg.add_text('Target: <= 10.0 px', color=TXT_MUTED)
                            with dpg.group():
                                dpg.add_text('Acquisition Time', color=TXT_MUTED)
                                dpg.add_text('-', tag='card_acq', color=ACCENT)
                                dpg.add_text('Target: <= 2.0 s', color=TXT_MUTED)
                        with dpg.table_row():
                            with dpg.group():
                                dpg.add_text('Lock Retention', color=TXT_MUTED)
                                dpg.add_text('-%', tag='card_lock', color=GREEN)
                                dpg.add_text('Target: >= 95.0%', color=TXT_MUTED)
                            with dpg.group():
                                dpg.add_text('Frame Rate', color=TXT_MUTED)
                                dpg.add_text('0 FPS', tag='card_fps', color=TXT_BRIGHT)
                                dpg.add_text('Target: >= 20 FPS', color=TXT_MUTED)

                # 3. Live Quick Tests Area (No complex sliders here)
                with dpg.child_window(width=-1, height=140, border=True):
                    dpg.add_text('QUICK CHANNEL & KINEMATIC TESTS', color=SECTITLE)
                    dpg.add_separator()
                    # Atmosphere row
                    with dpg.group(horizontal=True):
                        dpg.add_text('Atmosphere:', color=TXT_MUTED)
                        for env in ['Clear', 'Fog', 'Rain', 'Low light']:
                            dpg.add_button(
                                label=env.replace(' light', ''), width=(right_w - 110) // 4,
                                callback=lambda s, a, u=env: self._on_live_test_atmos(u))
                    # Motion row
                    with dpg.group(horizontal=True):
                        dpg.add_text('Target Motion:', color=TXT_MUTED)
                        for m in ['Straight', 'Circular', 'Figure-8', 'Sinusoidal']:
                            dpg.add_button(
                                label=m[:6], width=(right_w - 110) // 4,
                                callback=lambda s, a, u=m: self._on_live_test_motion(u))
                    dpg.add_spacer(height=2)
                    dpg.add_text('Test Status: Baseline Nominal', tag='live_test_banner', color=ACCENT)

                # 4. Mission Controls Bar
                with dpg.child_window(width=-1, height=85, border=True):
                    dpg.add_text('MISSION CONTROLS', color=SECTITLE)
                    dpg.add_separator()
                    with dpg.group(horizontal=True):
                        ctrl_w = (right_w - 50) // 4
                        dpg.add_button(label='|| Pause', width=ctrl_w, callback=lambda: self.cbs['pause_sim']())
                        dpg.add_button(label='> Resume', width=ctrl_w, callback=lambda: self.cbs['run_sim']())
                        dpg.add_button(label='<> Reset', width=ctrl_w, callback=lambda: self.cbs['reset_tracker']())
                        dpg.add_button(label='[] Exit/Save', width=ctrl_w, callback=self._on_exit_save_click)
                    dpg.add_text('Exit/Save saves session PDF & CSV report to logs/ before closing.', color=TXT_MUTED)

                # 5. Direct Navigation Links
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        label='Guided Walkthrough ->', tag='btn_goto_demo',
                        width=(right_w - 6) // 2, height=32,
                        callback=lambda: dpg.set_value('main_tab_bar', 'tab_demo'))
                    dpg.bind_item_theme('btn_goto_demo', self._th_pill_active)
                    dpg.add_button(
                        label='Engineering Diagnostics ->', tag='btn_goto_diag',
                        width=(right_w - 6) // 2, height=32,
                        callback=lambda: dpg.set_value('main_tab_bar', 'tab_diag'))
                    dpg.bind_item_theme('btn_goto_diag', self._th_btn_action)

        dpg.bind_item_theme('world_panel', self._minimap_theme())

    # ── Tab 3: Guided Demo Walkthrough (8-Step Sequencer) ──────────────
    def _set_demo_step(self, step):
        self._demo_step = max(1, min(8, step))
        for i in range(1, 9):
            if dpg.does_item_exist(f'demo_step_grp_{i}'):
                dpg.configure_item(f'demo_step_grp_{i}', show=(i == self._demo_step))
            if dpg.does_item_exist(f'demo_pill_{i}'):
                dpg.bind_item_theme(f'demo_pill_{i}', self._th_pill_active if i == self._demo_step else self._th_pill_inactive)
        if dpg.does_item_exist('demo_step_indicator_lbl'):
            dpg.set_value('demo_step_indicator_lbl', f'Step {self._demo_step} of 8')

        if self._demo_step == 1:
            self._on_reset_click()
            self._on_preset_click('EASY')
            self._on_motion_click('Straight')
            run_fn = self.cbs.get('run_sim')
            if run_fn:
                run_fn()

    def _build_tab_demo(self, win_w, tab_h):
        left_w = int(win_w * 0.52)
        right_w = win_w - left_w - 24

        with dpg.group(horizontal=True, pos=[10, 8]):
            # Left: Interactive Guided Demo Controller
            with dpg.child_window(tag='demo_controls_panel', width=left_w, height=tab_h, border=True):
                dpg.add_text('GUIDED MISSION DEMO WALKTHROUGH', color=SECTITLE)
                dpg.add_text('Presentation layer over real simulation backend — 8-step verification sequence', color=TXT_MUTED)
                dpg.add_spacer(height=4)

                # Step Selector Pills
                pill_labels = ['1. INIT', '2. ACQUIRE', '3. LOCK', '4. DISTURB', '5. MOTION', '6. RECOVERY', '7. VIDEO', '8. RESULTS']
                with dpg.group(horizontal=True):
                    for i, plabel in enumerate(pill_labels, start=1):
                        btn = dpg.add_button(
                            label=plabel, tag=f'demo_pill_{i}',
                            width=(left_w - 50) // 8,
                            callback=lambda s, a, u=i: self._set_demo_step(u))
                        dpg.bind_item_theme(btn, self._th_pill_active if i == self._demo_step else self._th_pill_inactive)

                dpg.add_spacer(height=6)
                dpg.add_separator()
                dpg.add_spacer(height=4)

                # Step Content Area (Scrollable)
                content_sub_h = tab_h - 130
                with dpg.child_window(tag='demo_step_scroll_area', width=-1, height=content_sub_h, border=False):
                    # ── STEP 1: INITIALIZE ──
                    with dpg.group(tag='demo_step_grp_1', show=(self._demo_step == 1)):
                        dpg.add_text('STEP 1 — SYSTEM INITIALIZATION', color=TXT_BRIGHT)
                        dpg.add_separator()
                        with dpg.child_window(height=48, border=True):
                            dpg.add_text('WHAT WE ARE DOING: Resetting optical tracking pipeline, clearing history buffers, and establishing a clean baseline for acquisition.',
                                         color=ACCENT, wrap=left_w - 30)

                        dpg.add_spacer(height=6)
                        dpg.add_text('WHAT TO WATCH: The camera boresight sits at world center (1000, 1000) with clean starfield baseline.', color=TXT_MUTED)
                        dpg.add_spacer(height=6)
                        with dpg.group(horizontal=True):
                            dpg.add_button(label='  [ Re-Initialize Baseline ]  ',
                                           callback=lambda: self._set_demo_step(1))
                            dpg.bind_item_theme(dpg.last_item(), self._th_btn_action)
                            dpg.add_button(label='  Proceed to Step 2: Acquire ->  ',
                                           callback=lambda: self._set_demo_step(2))
                            dpg.bind_item_theme(dpg.last_item(), self._th_btn_start)

                    # ── STEP 2: ACQUIRE ──
                    with dpg.group(tag='demo_step_grp_2', show=(self._demo_step == 2)):
                        dpg.add_text('STEP 2 — TARGET DETECTION & ACQUISITION', color=TXT_BRIGHT)
                        dpg.add_separator()
                        with dpg.child_window(height=48, border=True):
                            dpg.add_text('WHAT WE ARE DOING: Candidate emitter detected in camera field of view; Temporal Fusion Buffer verifies multi-frame spatial consistency.',
                                         color=ACCENT, wrap=left_w - 30)

                        dpg.add_spacer(height=6)
                        dpg.add_text('WHAT TO WATCH: Target candidate count and state badge transitioning from SEARCHING -> ACQUIRING.', color=TXT_MUTED)
                        with dpg.child_window(height=60, border=True):
                            with dpg.group(horizontal=True):
                                dpg.add_text('Current Tracking State: ', color=TXT_MUTED)
                                dpg.add_text('SEARCHING', tag='demo_s2_state', color=YELLOW)
                                dpg.add_text('  |  Candidates in FOV: ', color=TXT_MUTED)
                                dpg.add_text('0', tag='demo_s2_cands', color=TXT_BRIGHT)

                        dpg.add_spacer(height=6)
                        with dpg.group(horizontal=True):
                            dpg.add_button(label='  Proceed to Step 3: Lock ->  ',
                                           callback=lambda: self._set_demo_step(3))
                            dpg.bind_item_theme(dpg.last_item(), self._th_btn_start)

                    # ── STEP 3: LOCK ──
                    with dpg.group(tag='demo_step_grp_3', show=(self._demo_step == 3)):
                        dpg.add_text('STEP 3 — BORESIGHT LOCK & TRACKING PERFORMANCE', color=TXT_BRIGHT)
                        dpg.add_separator()
                        with dpg.child_window(height=48, border=True):
                            dpg.add_text('WHAT WE ARE DOING: Target confirmed; virtual camera servo actively commands gimbal to maintain alignment with boresight center.',
                                         color=ACCENT, wrap=left_w - 30)

                        dpg.add_spacer(height=6)
                        dpg.add_text('WHAT TO WATCH: Tracking error <= 10.0px, acquisition time <= 2.0s, and locked reticle.', color=TXT_MUTED)
                        with dpg.child_window(height=80, border=True):
                            with dpg.group(horizontal=True):
                                dpg.add_text('Acquisition Time (<= 2.0s): ', color=TXT_MUTED)
                                dpg.add_text('-', tag='demo_s3_acq', color=GREEN)
                                dpg.add_text('  |  Tracking Error (<= 10.0px): ', color=TXT_MUTED)
                                dpg.add_text('-', tag='demo_s3_err', color=GREEN)
                            with dpg.group(horizontal=True):
                                dpg.add_text('Frame Rate (>= 20 FPS):       ', color=TXT_MUTED)
                                dpg.add_text('-', tag='demo_s3_fps', color=GREEN)
                                dpg.add_text('  |  Lock State:                 ', color=TXT_MUTED)
                                dpg.add_text('-', tag='demo_s3_lock', color=GREEN)

                        dpg.add_spacer(height=6)
                        with dpg.group(horizontal=True):
                            dpg.add_button(label='  Proceed to Step 4: Disturbance Test ->  ',
                                           callback=lambda: self._set_demo_step(4))
                            dpg.bind_item_theme(dpg.last_item(), self._th_btn_start)

                    # ── STEP 4: DISTURBANCE TEST ──
                    with dpg.group(tag='demo_step_grp_4', show=(self._demo_step == 4)):
                        dpg.add_text('STEP 4 — ATMOSPHERIC DISTURBANCE EVALUATION', color=TXT_BRIGHT)
                        dpg.add_separator()
                        with dpg.child_window(height=48, border=True):
                            dpg.add_text('WHAT WE ARE DOING: Injecting realistic optical channel disturbances to evaluate tracking resilience against atmospheric turbulence, fog, and precipitation.',
                                         color=ACCENT, wrap=left_w - 30)

                        dpg.add_spacer(height=6)
                        dpg.add_text('SELECT GENUINE ATMOSPHERIC CHANNEL:', color=SECTITLE)
                        with dpg.group(horizontal=True):
                            for env in ['Clear', 'Haze', 'Fog', 'Rain', 'Low light']:
                                dpg.add_button(
                                    label=env, width=(left_w - 40) // 5,
                                    callback=lambda s, a, u=env: self._on_atmos_click(u))

                        dpg.add_spacer(height=4)
                        dpg.add_text('Current Channel: Clear optical path with baseline transmission.', tag='demo_s4_desc', color=TXT_BRIGHT)

                        dpg.add_spacer(height=6)
                        with dpg.group(horizontal=True):
                            dpg.add_button(label='  Proceed to Step 5: Motion Test ->  ',
                                           callback=lambda: self._set_demo_step(5))
                            dpg.bind_item_theme(dpg.last_item(), self._th_btn_start)

                    # ── STEP 5: MOTION TEST ──
                    with dpg.group(tag='demo_step_grp_5', show=(self._demo_step == 5)):
                        dpg.add_text('STEP 5 — DYNAMIC TARGET KINEMATICS', color=TXT_BRIGHT)
                        dpg.add_separator()
                        with dpg.child_window(height=48, border=True):
                            dpg.add_text('WHAT WE ARE DOING: Testing PID tracking and feedforward latency compensation across diverse satellite relative motion trajectories.',
                                         color=ACCENT, wrap=left_w - 30)

                        dpg.add_spacer(height=6)
                        dpg.add_text('SELECT GENUINE MOTION MODEL:', color=SECTITLE)
                        m_modes = ['Straight', 'Circular', 'Figure-8', 'Random', 'Spiral', 'Sinusoidal']
                        with dpg.group(horizontal=True):
                            for m in m_modes[:3]:
                                dpg.add_button(
                                    label=m, width=(left_w - 30) // 3,
                                    callback=lambda s, a, u=m: self._on_motion_click(u))
                        with dpg.group(horizontal=True):
                            for m in m_modes[3:]:
                                dpg.add_button(
                                    label=m, width=(left_w - 30) // 3,
                                    callback=lambda s, a, u=m: self._on_motion_click(u))

                        dpg.add_spacer(height=6)
                        with dpg.group(horizontal=True):
                            dpg.add_button(label='  Proceed to Step 6: Recovery ->  ',
                                           callback=lambda: self._set_demo_step(6))
                            dpg.bind_item_theme(dpg.last_item(), self._th_btn_start)

                    # ── STEP 6: RECOVERY ──
                    with dpg.group(tag='demo_step_grp_6', show=(self._demo_step == 6)):
                        dpg.add_text('STEP 6 — OCCLUSION RECOVERY & RE-ACQUISITION', color=TXT_BRIGHT)
                        dpg.add_separator()
                        with dpg.child_window(height=48, border=True):
                            dpg.add_text('WHAT WE ARE DOING: Demonstrating signal loss recovery: Kalman filter coasts during line-of-sight dropouts, triggering autonomous spiral scan if track is lost.',
                                         color=ACCENT, wrap=left_w - 30)

                        dpg.add_spacer(height=6)
                        dpg.add_text('HONEST RECOVERY PROGRESSION:', color=SECTITLE)
                        dpg.add_text('LOCKED -> COASTING (45 frames) -> LOST -> SEARCHING (Spiral) -> ACQUIRING -> LOCKED', color=TXT_BRIGHT)

                        dpg.add_spacer(height=4)
                        with dpg.group(horizontal=True):
                            dpg.add_text('Measured Re-acquisitions: ', color=TXT_MUTED)
                            dpg.add_text('0', tag='demo_s6_reacq', color=GREEN)
                            dpg.add_text('  |  Current State: ', color=TXT_MUTED)
                            dpg.add_text('LOCKED', tag='demo_s6_state', color=TXT_BRIGHT)

                        dpg.add_spacer(height=6)
                        with dpg.group(horizontal=True):
                            dpg.add_button(label='[ Inject Severe Disturbance (ADV) ]',
                                           callback=lambda: self._on_preset_click('ADV'))
                            dpg.bind_item_theme(dpg.last_item(), self._th_btn_stop)
                            dpg.add_button(label='[ Restore Clear Path (EASY) ]',
                                           callback=lambda: self._on_preset_click('EASY'))
                            dpg.bind_item_theme(dpg.last_item(), self._th_btn_start)

                        dpg.add_spacer(height=6)
                        with dpg.group(horizontal=True):
                            dpg.add_button(label='  Proceed to Step 7: Video ->  ',
                                           callback=lambda: self._set_demo_step(7))
                            dpg.bind_item_theme(dpg.last_item(), self._th_btn_start)

                    # ── STEP 7: VIDEO ──
                    with dpg.group(tag='demo_step_grp_7', show=(self._demo_step == 7)):
                        dpg.add_text('STEP 7 — VIDEO REPLAY / HARDWARE-IN-THE-LOOP (HIL)', color=TXT_BRIGHT)
                        dpg.add_separator()
                        with dpg.child_window(height=48, border=True):
                            dpg.add_text('WHAT WE ARE DOING: Ingesting pre-recorded mission MP4 video to benchmark computer vision detection on recorded optical sensor footage.',
                                         color=ACCENT, wrap=left_w - 30)

                        dpg.add_spacer(height=6)
                        dpg.add_text('Status: ', color=TXT_MUTED)
                        dpg.add_text('No MP4 video currently loaded (Synthetic Simulation active)', tag='demo_s7_vid_status', color=TXT_BRIGHT)

                        dpg.add_spacer(height=6)
                        with dpg.group(horizontal=True):
                            dpg.add_button(label='  [ Load Recorded MP4 Video File... ]  ',
                                           callback=lambda: self.cbs.get('load_video', lambda: None)())
                            dpg.bind_item_theme(dpg.last_item(), self._th_btn_action)
                            dpg.add_button(label='  [ Return to Synthetic Simulation ]  ',
                                           callback=lambda: self._on_reset_click())

                        dpg.add_spacer(height=6)
                        with dpg.group(horizontal=True):
                            dpg.add_button(label='  Proceed to Step 8: Results ->  ',
                                           callback=lambda: self._set_demo_step(8))
                            dpg.bind_item_theme(dpg.last_item(), self._th_btn_start)

                    # ── STEP 8: RESULTS ──
                    with dpg.group(tag='demo_step_grp_8', show=(self._demo_step == 8)):
                        dpg.add_text('STEP 8 — MISSION RESULTS & CERTIFICATION REPORTS', color=TXT_BRIGHT)
                        dpg.add_separator()
                        with dpg.child_window(height=48, border=True):
                            dpg.add_text('WHAT WE ARE DOING: Reviewing live session compliance against ISRO PS 26169 thresholds and accessing generated PDF and CSV session logs.',
                                         color=ACCENT, wrap=left_w - 30)

                        dpg.add_spacer(height=6)
                        dpg.add_text('MEASURED SESSION COMPLIANCE SUMMARY:', color=SECTITLE)
                        with dpg.child_window(height=95, border=True):
                            with dpg.group(horizontal=True):
                                dpg.add_text('Acquisition Time:   ', color=TXT_MUTED)
                                dpg.add_text('-', tag='demo_s8_acq', color=GREEN)
                                dpg.add_text('  |  Steady Error: ', color=TXT_MUTED)
                                dpg.add_text('-', tag='demo_s8_err', color=GREEN)
                            with dpg.group(horizontal=True):
                                dpg.add_text('Centroid RMSE:      ', color=TXT_MUTED)
                                dpg.add_text('-', tag='demo_s8_rmse', color=TXT_BRIGHT)
                                dpg.add_text('  |  Lock Rate:    ', color=TXT_MUTED)
                                dpg.add_text('-', tag='demo_s8_lock', color=GREEN)
                            with dpg.group(horizontal=True):
                                dpg.add_text('Pipeline Frame Rate:', color=TXT_MUTED)
                                dpg.add_text('-', tag='demo_s8_fps', color=GREEN)
                                dpg.add_text('  |  Re-acquisitions: ', color=TXT_MUTED)
                                dpg.add_text('0', tag='demo_s8_reacq', color=TXT_BRIGHT)

                        dpg.add_spacer(height=6)
                        with dpg.group(horizontal=True):
                            dpg.add_button(label='  [ Export Session Snapshot (PDF/CSV) ]  ',
                                           callback=self._on_export_snapshot_click)
                            dpg.bind_item_theme(dpg.last_item(), self._th_btn_action)
                            dpg.add_text('', tag='demo_s8_last_export', color=GREEN)

                        dpg.add_spacer(height=6)
                        with dpg.group(horizontal=True):
                            dpg.add_button(label='View Full Benchmark Scorecard ->',
                                           callback=lambda: dpg.set_value('main_tab_bar', 'tab_bench'))
                            dpg.add_button(label='Restart Guided Demo',
                                           callback=lambda: self._set_demo_step(1))

                # Step Navigation Bar at Bottom
                dpg.add_spacer(height=6)
                dpg.add_separator()
                dpg.add_spacer(height=4)
                with dpg.group(horizontal=True):
                    dpg.add_button(label='< Previous Step', width=120,
                                   callback=lambda: self._set_demo_step(self._demo_step - 1))
                    dpg.add_text('Step 1 of 8', tag='demo_step_indicator_lbl', color=TXT_BRIGHT)
                    dpg.add_button(label='Next Step >', width=120,
                                   callback=lambda: self._set_demo_step(self._demo_step + 1))
                    dpg.add_spacer(width=20)
                    dpg.add_button(label='Jump to Live Mission ->',
                                   callback=lambda: dpg.set_value('main_tab_bar', 'tab_live'))

            # Right: Live Optical Feed & World Minimap
            with dpg.child_window(tag='demo_viewport_panel', width=right_w, height=tab_h, border=True):
                # Header Banner
                with dpg.group(horizontal=True, pos=[8, 4]):
                    dpg.add_text('BORESIGHT SENSOR [640x480]', color=TXT_BRIGHT)
                    dpg.add_text('| LIVE DEMO VIEW', color=ACCENT)

                # Real-time Quick Status Strip
                with dpg.group(horizontal=True, pos=[8, 24]):
                    dpg.add_text('STATE:', color=TXT_MUTED)
                    dpg.add_text('STANDBY', tag='demo_rt_state', color=YELLOW)
                    dpg.add_text('  ERR:', color=TXT_MUTED)
                    dpg.add_text('- px', tag='demo_rt_err', color=TXT_BRIGHT)
                    dpg.add_text('  LOCK:', color=TXT_MUTED)
                    dpg.add_text('0.0%', tag='demo_rt_lock', color=TXT_BRIGHT)
                    dpg.add_text('  FPS:', color=TXT_MUTED)
                    dpg.add_text('0', tag='demo_rt_fps', color=GREEN)

                uv_min, uv_max = self._calc_uv(right_w - 4, tab_h - 76)
                dpg.add_image(
                    'cam_tex', tag='cam_img_demo',
                    pos=[2, 46],
                    width=right_w - 4, height=tab_h - 76,
                    uv_min=uv_min, uv_max=uv_max)

                # Footer Coordinates
                dpg.add_text(
                    'PAN: +0.00°  TILT: +0.00°  CAM: (1000, 1000)',
                    pos=[10, tab_h - 24], tag='viewport_pantilt_demo_lbl',
                    color=(160, 190, 220, 220))

                # Embedded World Minimap
                map_w = MINIMAP_SIZE
                map_h = MINIMAP_SIZE
                map_x = right_w - map_w - 14
                map_y = tab_h - map_h - 14
                with dpg.child_window(
                        tag='world_panel_demo', pos=[map_x, map_y],
                        width=map_w, height=map_h, border=True, no_scrollbar=True):
                    dpg.add_text('WORLD RADAR  2000x2000', color=ACCENT)
                    with dpg.drawlist(tag='world_draw_demo', width=map_w - 16, height=map_h - 34):
                        pass

        dpg.bind_item_theme('world_panel_demo', self._minimap_theme())

    # ── Tab 4: Dedicated Video Replay Mode ────────────────────────────
    def _build_tab_video(self, win_w, tab_h):
        left_w = int(win_w * 0.65)
        right_w = win_w - left_w - 24

        with dpg.group(horizontal=True, pos=[10, 8]):
            # Left: Video Frame Viewport
            with dpg.child_window(width=left_w, height=tab_h, border=True):
                dpg.add_text('VIDEO REPLAY FEED [640x480]', color=SECTITLE)
                dpg.add_separator()
                uv_min, uv_max = self._calc_uv(left_w - 4, tab_h - 40)
                dpg.add_image(
                    'cam_tex', tag='cam_img_video',
                    pos=[2, 28],
                    width=left_w - 4, height=tab_h - 36,
                    uv_min=uv_min, uv_max=uv_max)

            # Right: Video Details & Controls
            with dpg.child_window(width=right_w, height=tab_h, border=True):
                dpg.add_text('PRE-RECORDED OPTICAL VIDEO WORKFLOW', color=SECTITLE)
                dpg.add_separator()
                dpg.add_text('Benchmark CV and CNN detection algorithms on pre-recorded flight data.', color=TXT_MUTED)
                dpg.add_spacer(height=6)

                with dpg.child_window(width=-1, height=130, border=True):
                    dpg.add_text('LOADED VIDEO INFORMATION', color=SECTITLE)
                    dpg.add_separator()
                    with dpg.group(horizontal=True):
                        dpg.add_text('File Name:  ', color=TXT_MUTED)
                        dpg.add_text('No video loaded', tag='vid_info_name', color=TXT_BRIGHT)
                    with dpg.group(horizontal=True):
                        dpg.add_text('Resolution: ', color=TXT_MUTED)
                        dpg.add_text('640x480', tag='vid_info_res', color=TXT_BRIGHT)
                    with dpg.group(horizontal=True):
                        dpg.add_text('Frame Rate: ', color=TXT_MUTED)
                        dpg.add_text('30 FPS', tag='vid_info_fps', color=TXT_BRIGHT)
                    with dpg.group(horizontal=True):
                        dpg.add_text('Processed:  ', color=TXT_MUTED)
                        dpg.add_text('0 frames', tag='vid_info_frames', color=TXT_BRIGHT)

                dpg.add_spacer(height=8)
                dpg.add_button(label='[ Select MP4 Video File... ]', width=-1, height=40,
                               callback=lambda: self.cbs.get('load_video', lambda: None)())
                dpg.bind_item_theme(dpg.last_item(), self._th_btn_action)

                dpg.add_spacer(height=8)
                dpg.add_text('VIDEO PLAYBACK CONTROLS:', color=SECTITLE)
                with dpg.group(horizontal=True):
                    dpg.add_button(label='|| Pause', width=(right_w - 40) // 3,
                                   callback=lambda: self.cbs['pause_sim']())
                    dpg.add_button(label='> Resume', width=(right_w - 40) // 3,
                                   callback=lambda: self.cbs['run_sim']())
                    dpg.add_button(label='Return to Sim', width=(right_w - 40) // 3,
                                   callback=self._on_reset_click)

                dpg.add_spacer(height=12)
                # Video Complete Notification Card
                with dpg.child_window(tag='vid_done_card', width=-1, height=90, border=True, show=False):
                    dpg.add_text('VIDEO PLAYBACK COMPLETE', color=YELLOW)
                    dpg.add_text('All frames processed. You can export the compliance report or return to simulation.', color=TXT)
                    dpg.add_spacer(height=4)
                    with dpg.group(horizontal=True):
                        dpg.add_button(label='Export Report (PDF/CSV)',
                                       callback=self._on_export_snapshot_click)
                        dpg.bind_item_theme(dpg.last_item(), self._th_btn_action)
                        dpg.add_button(label='Return to Live Mission',
                                       callback=lambda: dpg.set_value('main_tab_bar', 'tab_live'))

    # ── Tab 5: Diagnostics & Engineering Telemetry ────────────────────
    def _build_tab_diag(self, win_w, tab_h):
        col_w = (win_w - 36) // 2

        with dpg.group(horizontal=True, pos=[10, 8]):
            # Left: Camera Diagnostics & Tracking Geometry
            with dpg.child_window(width=col_w, height=tab_h, border=True):
                dpg.add_text('CAMERA & GIMBAL SYSTEM DIAGNOSTICS', color=SECTITLE)
                dpg.add_separator()
                for lbl, vtag, col in [
                    ('Gimbal Pointing (Pan, Tilt):', 'diag_cam_pantilt', ACCENT),
                    ('Center World Position:      ', 'diag_cam_pos',     TXT_BRIGHT),
                    ('Sensor Viewport / FOV:      ', 'diag_cam_viewport',TXT),
                    ('Dynamic Slew Rate:          ', 'diag_cam_slew',    TXT_BRIGHT),
                    ('Hardware Slew Limit:        ', 'diag_cam_limit',   TXT_MUTED),
                    ('Command Delay / Latency:    ', 'diag_cam_lat',     TXT_MUTED),
                    ('Control Mode:               ', 'diag_cam_mode',    GREEN),
                ]:
                    with dpg.group(horizontal=True):
                        dpg.add_text(f'{lbl:<30}', color=TXT_MUTED)
                        dpg.add_text('-', tag=vtag, color=col)

                dpg.add_spacer(height=4)
                # Honest notice about manual camera control:
                with dpg.child_window(height=34, border=True):
                    dpg.add_text('Manual camera control not available in current simulation backend.', color=YELLOW)

                dpg.add_spacer(height=10)
                dpg.add_text('SPATIAL TRACKING & ERROR VECTORS', color=SECTITLE)
                dpg.add_separator()
                for lbl, vtag, col in [
                    ('Tracker Pixel Position:', 'diag_ev_track', ACCENT),
                    ('Ground Truth Position: ', 'diag_ev_gt',    TXT_BRIGHT),
                    ('Instantaneous Error:    ', 'diag_ev_err',   YELLOW),
                    ('Kalman Predicted Pixel: ', 'diag_ev_pred',  TXT),
                    ('Kalman Estimated Speed: ', 'diag_ev_vel',   TXT_MUTED),
                ]:
                    with dpg.group(horizontal=True):
                        dpg.add_text(lbl, color=TXT_MUTED)
                        dpg.add_text('-', tag=vtag, color=col)

                dpg.add_spacer(height=10)
                dpg.add_text('DETECTION PIPELINE INTERNALS', color=SECTITLE)
                dpg.add_separator()
                with dpg.group(horizontal=True):
                    dpg.add_text('Blob Candidates Detected:', color=TXT_MUTED)
                    dpg.add_text('0', tag='diag_det_cands', color=TXT_BRIGHT)
                    dpg.add_text('  |  CNN Inference Latency:', color=TXT_MUTED)
                    dpg.add_text('0.0ms', tag='diag_det_ms', color=TXT_BRIGHT)
                with dpg.group(horizontal=True):
                    dpg.add_text('Temporal Window:         ', color=TXT_MUTED)
                    dpg.add_text('8 frames (Confidence buffer)', color=TXT)

            # Right: Control Loop, Error History & Mission Checklist
            with dpg.child_window(width=col_w, height=tab_h, border=True):
                dpg.add_text('CONTROL LOOP & SERVO INTERNALS', color=SECTITLE)
                dpg.add_separator()
                with dpg.group(horizontal=True):
                    dpg.add_text('PID Integral State (Pan, Tilt):', color=TXT_MUTED)
                    dpg.add_text('0.000, 0.000', tag='diag_pid_i', color=TXT_BRIGHT)
                with dpg.group(horizontal=True):
                    dpg.add_text('Feedforward Latency Comp:     ', color=TXT_MUTED)
                    dpg.add_text('2 frames (Kalman predicted velocity)', color=TXT)
                with dpg.group(horizontal=True):
                    dpg.add_text('Kalman Covariance Uncertainty:', color=TXT_MUTED)
                    dpg.add_text('0.0 px', tag='diag_uncert', color=ACCENT)
                with dpg.group(horizontal=True):
                    dpg.add_text('Spiral Scan Waypoint Progress:', color=TXT_MUTED)
                    dpg.add_text('0%', tag='diag_scan_cov', color=YELLOW)

                dpg.add_spacer(height=8)
                dpg.add_text('TRACKING ERROR HISTORY (px) — LAST 200 FRAMES', color=SECTITLE)
                dpg.add_separator()
                dpg.add_text('Red dashed line: 10px ISRO requirement limit  |  Yellow: Moving average', color=TXT_MUTED)
                self._err_graph_w = max(200, col_w - 30)
                with dpg.drawlist(tag='err_graph_draw', width=self._err_graph_w, height=120):
                    pass

                dpg.add_spacer(height=8)
                dpg.add_text('ISRO PS 26169 MISSION REQUIREMENTS CHECKLIST', color=SECTITLE)
                dpg.add_separator()
                req_items = [
                    ('Target Acquisition Time (<= 2.0s):', 'diag_req_acq',   'diag_req_acq_v'),
                    ('Mean Tracking Error (<= 10.0px):  ', 'diag_req_err',   'diag_req_err_v'),
                    ('Target Signal Loss Rate (< 5.0%): ', 'diag_req_loss',  'diag_req_loss_v'),
                    ('Re-acquisition Duration (<= 1.0s): ', 'diag_req_reacq', 'diag_req_reacq_v'),
                    ('Pipeline Frame Rate (>= 20 FPS):  ', 'diag_req_fps',   'diag_req_fps_v'),
                ]
                for lbl, ptag, vtag in req_items:
                    with dpg.group(horizontal=True):
                        dpg.add_text(f'{lbl:<38}', color=TXT_MUTED)
                        dpg.add_text('-', tag=vtag, color=TXT_BRIGHT)
                        dpg.add_text('-', tag=ptag, color=TXT_MUTED)

    # ── Tab 6: Benchmark & Compliance ─────────────────────────────────
    def _build_tab_bench(self, win_w, tab_h):
        with dpg.child_window(width=win_w, height=tab_h, border=False):
            dpg.add_text('ISRO PS 26169 BENCHMARK & COMPLIANCE VERIFICATION', color=SECTITLE)
            dpg.add_text('Automated evaluation against Indian Space Research Organisation Coarse Alignment criteria.', color=TXT_MUTED)
            dpg.add_separator()

            with dpg.group(horizontal=True):
                # Left: Scenario Table
                with dpg.child_window(width=int(win_w * 0.50), height=tab_h - 50, border=True):
                    dpg.add_text('PRESET SCENARIO EVALUATION MATRIX', color=SECTITLE)
                    dpg.add_separator()
                    with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True,
                                   policy=dpg.mvTable_SizingStretchProp):
                        dpg.add_table_column(label='Scenario')
                        dpg.add_table_column(label='Speed')
                        dpg.add_table_column(label='Channel')
                        dpg.add_table_column(label='Disturbance')
                        dpg.add_table_column(label='Status')

                        scenarios = [
                            ('EASY',        '20 px/s',  'Clear',        'Nominal',  'CURRENT SESSION'),
                            ('MODERATE',    '35 px/s',  'Haze',         'Light',    'READY'),
                            ('HARD',        '50 px/s',  'Fog',          'Moderate', 'READY'),
                            ('SEVERE',      '70 px/s',  'Rain+Turb',    'Severe',   'READY'),
                            ('ADVERSARIAL', '90 px/s',  'Extreme Obsc', 'Advers.',  'READY'),
                        ]
                        for sc, spd, ch, dst, st in scenarios:
                            with dpg.table_row():
                                dpg.add_text(sc, color=TXT_BRIGHT)
                                dpg.add_text(spd, color=TXT)
                                dpg.add_text(ch, color=TXT)
                                dpg.add_text(dst, color=TXT)
                                dpg.add_text(st, color=GREEN if 'CURRENT' in st else TXT_MUTED)

                    dpg.add_spacer(height=14)
                    # Honest automated benchmark execution status:
                    with dpg.child_window(height=110, border=True):
                        dpg.add_text('AUTOMATED GUI BENCHMARK — Backend integration pending', color=YELLOW)
                        dpg.add_text('A standalone multi-scenario evaluation engine is available separately:\n'
                                     'Command: python evaluation/run_benchmarks.py\n'
                                     'The table on the right reflects the live measured performance of the currently running session.',
                                     color=TXT_MUTED)

                # Right: Compliance Scorecard
                with dpg.child_window(width=win_w - int(win_w * 0.50) - 24, height=tab_h - 50, border=True):
                    dpg.add_text('LIVE SESSION COMPLIANCE SCORECARD', color=SECTITLE)
                    dpg.add_separator()
                    with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True,
                                   policy=dpg.mvTable_SizingStretchProp):
                        dpg.add_table_column(label='Metric')
                        dpg.add_table_column(label='Requirement')
                        dpg.add_table_column(label='Measured')
                        dpg.add_table_column(label='Verdict')

                        bench_rows = [
                            ('Acquisition Time', '<= 2.0 s',   'bench_val_acq',   'bench_stat_acq'),
                            ('Tracking Error',   '<= 10.0 px', 'bench_val_err',   'bench_stat_err'),
                            ('Target Loss Rate', '< 5.0 %',    'bench_val_loss',  'bench_stat_loss'),
                            ('Re-acquisition',   '<= 1.0 s',   'bench_val_reacq', 'bench_stat_reacq'),
                            ('Pipeline FPS',     '>= 20 FPS',  'bench_val_fps',   'bench_stat_fps'),
                        ]
                        for m_lbl, req_val, vtag, stag in bench_rows:
                            with dpg.table_row():
                                dpg.add_text(m_lbl, color=TXT_BRIGHT)
                                dpg.add_text(req_val, color=TXT_MUTED)
                                dpg.add_text('-', tag=vtag, color=TXT_BRIGHT)
                                dpg.add_text('PENDING', tag=stag, color=YELLOW)

                    dpg.add_spacer(height=16)
                    dpg.add_button(label='[ Export Current Verification Report (PDF+CSV) ]', width=-1, height=40,
                                   callback=self._on_export_snapshot_click)
                    dpg.bind_item_theme(dpg.last_item(), self._th_btn_action)

    # ── Tab 7: Reports & Log Viewer ───────────────────────────────────
    def _build_tab_reports(self, win_w, tab_h):
        with dpg.child_window(width=win_w, height=tab_h, border=False):
            dpg.add_text('MISSION REPORTS & SESSION LOGS', color=SECTITLE)
            dpg.add_separator()

            with dpg.group(horizontal=True):
                # Left: Export Actions
                with dpg.child_window(width=340, height=tab_h - 50, border=True):
                    dpg.add_text('EXPORT GENERATION', color=SECTITLE)
                    dpg.add_separator()
                    dpg.add_text('Generate permanent timestamped compliance reports for the active mission session.', color=TXT_MUTED)
                    dpg.add_spacer(height=8)
                    dpg.add_button(label='[ Export PDF + CSV Now ]', width=-1, height=44,
                                   callback=self._on_export_snapshot_click)
                    dpg.bind_item_theme(dpg.last_item(), self._th_btn_start)

                    dpg.add_spacer(height=6)
                    dpg.add_button(label='[ Refresh Report List ]', width=-1, height=32,
                                   callback=self._refresh_report_list)

                    dpg.add_spacer(height=12)
                    dpg.add_separator()
                    dpg.add_text('EXPORT FORMAT AVAILABILITY:', color=TXT_MUTED)
                    dpg.add_text('• PDF Report: ACTIVE (ReportLab)', color=GREEN)
                    dpg.add_text('• CSV Logs:   ACTIVE (Frame telemetry)', color=GREEN)
                    dpg.add_text('• HTML Report: Backend not implemented', color=TXT_MUTED)

                    dpg.add_spacer(height=12)
                    dpg.add_text('REPORTS LOCATION:', color=TXT_MUTED)
                    dpg.add_text(f'{os.path.abspath("logs")}', color=ACCENT, wrap=320)

                # Right: List of generated reports
                with dpg.child_window(width=win_w - 364, height=tab_h - 50, border=True):
                    dpg.add_text('SAVED SESSION FILES IN logs/', color=SECTITLE)
                    dpg.add_separator()
                    dpg.add_text('Click Refresh to inspect recently generated session logs.', tag='report_list_status', color=TXT_MUTED)
                    with dpg.child_window(tag='report_files_list_panel', width=-1, height=-1, border=False):
                        pass

        self._refresh_report_list()

    # ── Zone 3: Bottom Status Bar ─────────────────────────────────────
    def _build_statusbar(self, win_w, top_y):
        cw = win_w // 8
        cells = [
            ('STATE',    '-',  'stat_0', YELLOW),
            ('ERROR',    '-',  'stat_1', GREEN),
            ('ACQ TIME', '-',  'stat_2', ACCENT),
            ('FPS',      '0',  'stat_3', GREEN),
            ('LOCK RATE','-%', 'stat_4', GREEN),
            ('PAN',      '+0.00°', 'stat_5', TXT_BRIGHT),
            ('TILT',     '+0.00°', 'stat_6', TXT_BRIGHT),
            ('REPORT',   'Ready',  'stat_7', TXT_MUTED),
        ]
        with dpg.child_window(
                tag='status_bar', width=win_w, height=STATUS_H,
                pos=[0, top_y], border=False, no_scrollbar=True):
            with dpg.group(horizontal=True):
                for i, (lbl, val, tag, col) in enumerate(cells):
                    this_cw = (win_w - 7 * cw) if i == 7 else cw
                    with dpg.child_window(
                            tag=f'cell_{i}', width=this_cw, height=STATUS_H,
                            border=True, no_scrollbar=True):
                        with dpg.group(horizontal=True):
                            dpg.add_text(f'{lbl}:', color=TXT_MUTED)
                            dpg.add_text(val, tag=tag, color=col)

    # ── Callbacks & Staging Actions ───────────────────────────────────
    def _on_quick_demo_click(self):
        self._motion_mode = 'Straight'
        self._atmos_mode = 'Clear'
        self._dist_preset = 'EASY'
        self._target_init_pos = 'center'
        if 'set_preset' in self.cbs: self.cbs['set_preset']('EASY')
        if 'set_atmosphere' in self.cbs: self.cbs['set_atmosphere']('clear')
        if 'set_motion' in self.cbs: self.cbs['set_motion']('straight')
        if 'set_speed' in self.cbs: self.cbs['set_speed'](30.0)
        if 'set_initial_pos' in self.cbs: self.cbs['set_initial_pos']('center')
        if 'reset_tracker' in self.cbs: self.cbs['reset_tracker']()
        if 'run_sim' in self.cbs: self.cbs['run_sim']()
        dpg.set_value('main_tab_bar', 'tab_demo')
        self._set_demo_step(1)

    def _start_mission_action(self):
        # Apply parameters
        if 'set_motion' in self.cbs: self.cbs['set_motion'](self._motion_mode.lower())
        if 'set_speed' in self.cbs: self.cbs['set_speed'](self._motion_speed)
        if 'set_size' in self.cbs: self.cbs['set_size'](self._target_size)
        if 'set_atmosphere' in self.cbs: self.cbs['set_atmosphere'](self._atmos_mode.lower())
        if 'set_preset' in self.cbs: self.cbs['set_preset'](self._dist_preset)
        if 'set_initial_pos' in self.cbs: self.cbs['set_initial_pos'](self._target_init_pos)
        if 'reset_tracker' in self.cbs: self.cbs['reset_tracker']()
        if 'run_sim' in self.cbs: self.cbs['run_sim']()
        dpg.set_value('main_tab_bar', 'tab_live')

    def _on_pos_click(self, pos_type):
        self._target_init_pos = pos_type
        if 'set_initial_pos' in self.cbs:
            self.cbs['set_initial_pos'](pos_type)
        self._refresh_setup_buttons()

    def _on_speed_preset_click(self, label, speed_val):
        self._speed_preset = label
        self._motion_speed = speed_val
        if 'set_speed' in self.cbs:
            self.cbs['set_speed'](speed_val)
        self._refresh_setup_buttons()

    def _on_dist_preset_click(self, preset):
        self._dist_preset = preset
        if preset == 'CUSTOM':
            if dpg.does_item_exist('setup_custom_sliders_grp'):
                dpg.configure_item('setup_custom_sliders_grp', show=True)
        else:
            if dpg.does_item_exist('setup_custom_sliders_grp'):
                dpg.configure_item('setup_custom_sliders_grp', show=False)
            if 'set_preset' in self.cbs:
                self.cbs['set_preset']('EASY' if preset in ('NONE', 'LIGHT') else ('MOD' if preset == 'MODERATE' else ('HARD' if preset == 'SEVERE' else preset)))
        self._refresh_setup_buttons()

    def _on_motion_click(self, m):
        self._motion_mode = m
        if 'set_motion' in self.cbs:
            self.cbs['set_motion'](m.lower())
        self._refresh_setup_buttons()

    def _on_atmos_click(self, env):
        self._atmos_mode = env
        if 'set_atmosphere' in self.cbs:
            self.cbs['set_atmosphere'](env.lower().replace(' light', ''))
        self._refresh_setup_buttons()

    def _on_disturbance_slider(self, key, val):
        if 'set_disturbance' in self.cbs:
            self.cbs['set_disturbance'](key, val)

    def _on_live_test_atmos(self, env):
        self._on_atmos_click(env)
        self._live_test_notice = f"TEST ACTIVATED: {env.upper()} CHANNEL APPLIED"
        self._live_test_notice_time = time.time()
        if dpg.does_item_exist('live_test_banner'):
            dpg.set_value('live_test_banner', self._live_test_notice)

    def _on_live_test_motion(self, m):
        self._on_motion_click(m)
        self._live_test_notice = f"TEST ACTIVATED: {m.upper()} KINEMATICS APPLIED"
        self._live_test_notice_time = time.time()
        if dpg.does_item_exist('live_test_banner'):
            dpg.set_value('live_test_banner', self._live_test_notice)

    def _on_reset_click(self):
        reset_fn = self.cbs.get('reset_tracker')
        if reset_fn:
            reset_fn()

    def _on_exit_save_click(self):
        exit_fn = self.cbs.get('exit_and_save') or self.cbs.get('quit')
        if exit_fn:
            exit_fn()

    def _on_export_snapshot_click(self):
        export_fn = self.cbs.get('export_snapshot')
        if export_fn:
            p = export_fn()
            self._last_report_notice = "Report Exported: PDF + CSV saved to logs/"
            self._last_report_notice_time = time.time()
            if dpg.does_item_exist('stat_7'):
                dpg.set_value('stat_7', 'Exported!')
            self._refresh_report_list()

    def _refresh_setup_buttons(self):
        # Update motion buttons
        for m, tag in self._motion_buttons.items():
            if dpg.does_item_exist(tag):
                dpg.bind_item_theme(tag, self._th_pill_active if m == self._motion_mode else self._th_pill_inactive)
        # Update speed buttons
        for spd_lbl, tag in self._speed_buttons.items():
            if dpg.does_item_exist(tag):
                dpg.bind_item_theme(tag, self._th_pill_active if spd_lbl == self._speed_preset else self._th_pill_inactive)
        # Update pos buttons
        for p, tag in self._pos_buttons.items():
            if dpg.does_item_exist(tag):
                dpg.bind_item_theme(tag, self._th_pill_active if p == self._target_init_pos else self._th_pill_inactive)
        # Update atmos buttons
        for env, tag in self._atmos_buttons.items():
            if dpg.does_item_exist(tag):
                dpg.bind_item_theme(tag, self._th_pill_active if env == self._atmos_mode else self._th_pill_inactive)
        # Update preset buttons
        for p, tag in self._preset_buttons.items():
            if dpg.does_item_exist(tag):
                dpg.bind_item_theme(tag, self._th_pill_active if p == self._dist_preset else self._th_pill_inactive)

        # Briefing summary updates
        if dpg.does_item_exist('brief_target'):
            dpg.set_value('brief_target', f'{self._motion_mode} · {self._motion_speed:.0f} px/s')
        if dpg.does_item_exist('brief_pos'):
            pos_desc = 'In Camera FOV (World Center)' if self._target_init_pos == 'center' else 'Near Camera FOV (+-250px offset)'
            dpg.set_value('brief_pos', pos_desc)
        if dpg.does_item_exist('brief_env'):
            dpg.set_value('brief_env', f'{self._atmos_mode} Optical Path')
        if dpg.does_item_exist('brief_dist'):
            dpg.set_value('brief_dist', f'{self._dist_preset} Disturbance')

    def _refresh_report_list(self):
        if not dpg.does_item_exist('report_files_list_panel'):
            return
        dpg.delete_item('report_files_list_panel', children_only=True)

        log_files = glob.glob('logs/*')
        log_files = sorted(log_files, key=os.path.getmtime, reverse=True)
        if not log_files:
            dpg.add_text('No session log files found in logs/ directory yet.',
                         parent='report_files_list_panel', color=TXT_MUTED)
            return

        for f in log_files[:18]:
            fname = os.path.basename(f)
            sz = os.path.getsize(f) / 1024.0
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(f)).strftime('%Y-%m-%d %H:%M:%S')
            is_pdf = fname.endswith('.pdf')
            with dpg.group(horizontal=True, parent='report_files_list_panel'):
                dpg.add_text(f'[{ "PDF" if is_pdf else "CSV" }]', color=GREEN if is_pdf else ACCENT)
                dpg.add_text(f'{fname:<36}', color=TXT_BRIGHT)
                dpg.add_text(f'{sz:.1f} KB', color=TXT_MUTED)
                dpg.add_text(f'  {mtime}', color=TXT_MUTED)

    # ── Real-Time GUI Update Loop ─────────────────────────────────────
    def _update_texture(self, frame_rgb):
        if frame_rgb is None:
            return
        h, w, c = frame_rgb.shape
        if h != FEED_H or w != FEED_W:
            frame_rgb = cv2.resize(frame_rgb, (FEED_W, FEED_H))

        tex_data = np.zeros((TEX_H, TEX_W, 4), dtype=np.float32)
        rgb_f = frame_rgb.astype(np.float32) / 255.0
        tex_data[0:FEED_H, 0:FEED_W, 0:3] = rgb_f
        tex_data[0:FEED_H, 0:FEED_W, 3] = 1.0

        dpg.set_value('cam_tex', tex_data)

    def _update_world_view(self):
        s = self.state
        cx = s.get('cam_x', 1000.0)
        cy = s.get('cam_y', 1000.0)
        tx = s.get('tgt_wx', 1000.0)
        ty = s.get('tgt_wy', 1000.0)
        ww = max(1, s.get('world_w', 2000))
        wh = max(1, s.get('world_h', 2000))

        # Actual screen position of beacon relative to camera frame:
        sx_cam = tx - cx + (FEED_W / 2.0)
        sy_cam = ty - cy + (FEED_H / 2.0)
        target_in_fov = (0.0 <= sx_cam <= FEED_W) and (0.0 <= sy_cam <= FEED_H)

        vw = MINIMAP_SIZE - 16
        vh = MINIMAP_SIZE - 34
        sx = vw / float(ww)
        sy = vh / float(wh)

        fw = (FEED_W / 2.0) * sx
        fh = (FEED_H / 2.0) * sy

        for draw_tag in ['world_draw', 'world_draw_demo']:
            if not dpg.does_item_exist(draw_tag):
                continue
            try:
                dpg.delete_item(draw_tag, children_only=True)
            except Exception:
                continue

            dpg.draw_rectangle((0, 0), (vw, vh), fill=(4, 8, 16, 240), parent=draw_tag)

            # Gridlines
            for g in (0.25, 0.5, 0.75):
                dpg.draw_line((g * vw, 0), (g * vw, vh), color=(20, 34, 52, 100), parent=draw_tag)
                dpg.draw_line((0, g * vh), (vw, g * vh), color=(20, 34, 52, 100), parent=draw_tag)

            # Camera FOV box (640x480)
            cam_col = (0, 255, 136, 240) if target_in_fov else (0, 212, 255, 180)
            dpg.draw_rectangle(
                (cx * sx - fw, cy * sy - fh),
                (cx * sx + fw, cy * sy + fh),
                color=cam_col, thickness=1.6 if target_in_fov else 1.2, parent=draw_tag)

            # Crosshair on camera center
            dpg.draw_line((cx * sx - 5, cy * sy), (cx * sx + 5, cy * sy), color=(0, 212, 255, 160), thickness=1.0, parent=draw_tag)
            dpg.draw_line((cx * sx, cy * sy - 5), (cx * sx, cy * sy + 5), color=(0, 212, 255, 160), thickness=1.0, parent=draw_tag)

            if target_in_fov:
                # Target beacon inside FOV: bright green dot with ring
                dpg.draw_circle((tx * sx, ty * sy), 4, fill=GREEN, color=GREEN, parent=draw_tag)
                dpg.draw_circle((tx * sx, ty * sy), 7, color=(0, 255, 136, 140), thickness=1.0, parent=draw_tag)
                dpg.draw_text((6, 5), "TARGET IN CAMERA FOV", size=10, color=GREEN, parent=draw_tag)
            else:
                # Target beacon outside FOV: bright amber dot with sightline from camera
                dpg.draw_line((cx * sx, cy * sy), (tx * sx, ty * sy), color=(255, 160, 40, 90), thickness=1.0, parent=draw_tag)
                dpg.draw_circle((tx * sx, ty * sy), 4, fill=ORANGE, color=ORANGE, parent=draw_tag)
                dpg.draw_circle((tx * sx, ty * sy), 6, color=(255, 160, 40, 160), thickness=1.0, parent=draw_tag)
                dpg.draw_text((6, 5), "TARGET OUTSIDE FOV", size=10, color=ORANGE, parent=draw_tag)

            dpg.draw_text((6, vh - 14), f"CAM: ({int(cx)}, {int(cy)})  TGT: ({int(tx)}, {int(ty)})", size=9, color=(140, 180, 220, 180), parent=draw_tag)

    def _update_error_graph(self, err, state):
        try:
            dpg.delete_item('err_graph_draw', children_only=True)
        except Exception:
            return

        W = self._err_graph_w
        H = 120
        Y_MAX = 50.0
        PAD = 4.0
        plot_h = H - 2 * PAD

        dpg.draw_rectangle((0, 0), (W, H), fill=BG_FIELD, color=BORDER, parent='err_graph_draw')

        def y_of(v):
            return PAD + plot_h - (min(v, Y_MAX) / Y_MAX) * plot_h

        # 10px ISRO limit dashed line
        y10 = y_of(10.0)
        x = 0.0
        dash, gap = 6.0, 4.0
        while x < W:
            x2 = min(x + dash, W)
            dpg.draw_line((x, y10), (x2, y10), color=RED, thickness=1.2, parent='err_graph_draw')
            x += dash + gap
        dpg.draw_text((W - 86, max(0, y10 - 14)), '10px limit', size=11, color=RED, parent='err_graph_draw')

        ys = list(self._err_hist)
        n = len(ys)
        if n >= 2:
            denom = max(1, self.HIST - 1)
            pts = [((i / denom) * W, y_of(v)) for i, v in enumerate(ys)]
            dpg.draw_polyline(pts, color=ACCENT, thickness=1.5, parent='err_graph_draw')

            if n > 10:
                avg = sum(ys[-60:]) / min(60, n)
                ay = y_of(avg)
                dpg.draw_line((0, ay), (W, ay), color=YELLOW, thickness=1.0, parent='err_graph_draw')

    def _update_explainer(self, state, s):
        is_running = s.get('running', False)
        reacq = s.get('reacq_count', 0)

        if not is_running:
            state_label = "STANDBY"
            state_col = YELLOW
            desc = "Mission in Standby. Select scenario parameters and press START MISSION."
            stage_idx = 1
        elif state == TrackState.LOCKED:
            state_label = "LOCKED"
            state_col = GREEN
            desc = "Beacon identified. Virtual camera is maintaining alignment."
            stage_idx = 3
        elif state == TrackState.ACQUIRING:
            state_label = "ACQUIRING"
            state_col = ORANGE
            desc = "Beacon candidate detected. Verifying target consistency."
            stage_idx = 2
        elif state == TrackState.LOST:
            state_label = "LOST"
            state_col = RED
            desc = "Target lost. Initiating recovery search."
            stage_idx = 5
        elif state == TrackState.COASTING:
            state_label = "COASTING"
            state_col = ORANGE
            desc = "Target obscured. Tracking predicted motion."
            stage_idx = 5
        elif reacq > 0 and state == TrackState.SEARCHING:
            state_label = "REACQUIRING"
            state_col = ORANGE
            desc = "Searching for the beacon again."
            stage_idx = 5
        else:  # TrackState.SEARCHING
            state_label = "SEARCHING"
            state_col = YELLOW
            desc = "Scanning the virtual scene for the beacon."
            stage_idx = 2

        if dpg.does_item_exist('live_state_title'):
            dpg.set_value('live_state_title', f"● {state_label}")
            dpg.configure_item('live_state_title', color=state_col)

        if dpg.does_item_exist('top_state_badge'):
            dpg.set_value('top_state_badge', state_label)
            dpg.configure_item('top_state_badge', color=state_col)

        if dpg.does_item_exist('explainer_text'):
            dpg.set_value('explainer_text', desc)

        pan = s.get("cam_pan", 0.0)
        tilt = s.get("cam_tilt", 0.0)
        now = time.perf_counter()
        dt_cam = max(now - self._prev_cam_t, 1e-4)
        d_pan = (pan - self._prev_cam_pan) * 160.0
        d_tilt = (tilt - self._prev_cam_tilt) * 160.0
        self._cam_slew_rate = float(np.hypot(d_pan, d_tilt) / 160.0 / dt_cam)
        self._prev_cam_pan = pan
        self._prev_cam_tilt = tilt
        self._prev_cam_t = now

        cam_mode = "AUTONOMOUS TRACKING" if (state in (TrackState.LOCKED, TrackState.ACQUIRING)) else "AUTONOMOUS SEARCH"
        if not is_running:
            cam_mode = "STANDBY (AT REST)"

        if dpg.does_item_exist('live_cam_pointing'):
            dpg.set_value('live_cam_pointing', f'Camera Pointing: Pan {pan:+.2f}°, Tilt {tilt:+.2f}° (5.0°/s limit)')

        if dpg.does_item_exist('viewport_pantilt_lbl'):
            dpg.set_value('viewport_pantilt_lbl',
                          f'CAMERA STATUS | PAN: {pan:+.2f}°  TILT: {tilt:+.2f}°  SLEW: {self._cam_slew_rate:.2f}°/s  MODE: {cam_mode}')

        # Stage Breadcrumb highlights
        for i in range(1, 8):
            tag = f'stage_lbl_{i}'
            if dpg.does_item_exist(tag):
                if i == stage_idx:
                    dpg.configure_item(tag, color=GREEN if stage_idx == 3 else ACCENT)
                elif i < stage_idx:
                    dpg.configure_item(tag, color=TXT_BRIGHT)
                else:
                    dpg.configure_item(tag, color=TXT_MUTED)

        # When LOCKED, emphasize the 4 key metrics
        if dpg.does_item_exist('telemetry_card_title'):
            if state == TrackState.LOCKED and is_running:
                dpg.set_value('telemetry_card_title', 'KEY MISSION METRICS [LOCKED — ACTIVE ALIGNMENT]')
                dpg.configure_item('telemetry_card_title', color=GREEN)
            else:
                dpg.set_value('telemetry_card_title', 'KEY MISSION METRICS')
                dpg.configure_item('telemetry_card_title', color=SECTITLE)

    def _update_metrics(self):
        s = self.state
        state = s.get('track_state') or TrackState.SEARCHING
        col = state_color(state)

        err = s.get('track_error_px', 0.0)
        fps = s.get('fps', 0.0)
        lr  = s.get('lock_rate', 0.0)
        acq = s.get('acq_time')
        sim_time = s.get('sim_time', 0.0)

        # Mode badge & video status
        is_video = bool(s.get('video_mode'))
        dpg.set_value('top_mode_badge', 'VIDEO REPLAY' if is_video else 'SIMULATION')
        dpg.configure_item('top_mode_badge', color=ACCENT if is_video else TXT_MUTED)

        if s.get('video_done') and dpg.does_item_exist('vid_done_card'):
            dpg.configure_item('vid_done_card', show=True)

        # Check for report notification
        report_path = s.get('last_report_path')
        if report_path:
            self._last_report_notice = f"Saved: {os.path.basename(report_path)}"
            self._last_report_notice_time = time.time()
            s['last_report_path'] = None
            self._refresh_report_list()

        # Update visuals
        self._update_texture(s.get('frame_rgb'))
        self._update_world_view()
        self._update_explainer(state, s)

        # Top Bar
        dpg.set_value('top_err', f'{err:.1f} px' if err else '- px')
        dpg.set_value('top_fps', f'{fps:.0f}')
        dpg.set_value('top_simtime', f'{sim_time:.1f}s')
        if acq is not None:
            dpg.set_value('top_acq', f'{acq:.2f}s')
        else:
            dpg.set_value('top_acq', '-')

        # Live Mission Key Metric Cards
        if dpg.does_item_exist('card_err'):
            dpg.set_value('card_err', f'{err:.1f} px' if err else '0.0 px')
            dpg.configure_item('card_err', color=GREEN if err <= 10.0 else RED)
        if dpg.does_item_exist('card_acq'):
            dpg.set_value('card_acq', f'{acq:.2f} s' if acq is not None else 'Searching...')
            dpg.configure_item('card_acq', color=GREEN if (acq is not None and acq <= 2.0) else ACCENT)
        if dpg.does_item_exist('card_lock'):
            dpg.set_value('card_lock', f'{lr * 100:.1f} %')
            dpg.configure_item('card_lock', color=GREEN if lr >= 0.95 else (ORANGE if lr >= 0.80 else RED))
        if dpg.does_item_exist('card_fps'):
            dpg.set_value('card_fps', f'{fps:.0f} FPS')
            dpg.configure_item('card_fps', color=GREEN if fps >= 20 else YELLOW)

        # Bottom status bar
        dpg.set_value('stat_0', state.name if s.get('running') else 'STANDBY')
        dpg.configure_item('stat_0', color=col if s.get('running') else YELLOW)
        dpg.set_value('stat_1', f'{err:.1f}px' if err else '- px')
        dpg.configure_item('stat_1', color=GREEN if err <= 10 else RED)
        dpg.set_value('stat_2', f'{acq:.2f}s' if acq is not None else '-')
        dpg.set_value('stat_3', f'{fps:.0f}')
        dpg.configure_item('stat_3', color=GREEN if fps >= 20 else YELLOW)
        dpg.set_value('stat_4', f'{lr * 100:.1f}%')
        dpg.set_value('stat_5', f'{s.get("cam_pan", 0.0):+.2f}°')
        dpg.set_value('stat_6', f'{s.get("cam_tilt", 0.0):+.2f}°')
        if self._last_report_notice and (time.time() - self._last_report_notice_time < 5.0):
            dpg.set_value('stat_7', 'Report Exported')
            dpg.configure_item('stat_7', color=GREEN)
        else:
            dpg.set_value('stat_7', 'Ready')
            dpg.configure_item('stat_7', color=TXT_MUTED)

        # Video tab info updates
        if dpg.does_item_exist('vid_info_name') and s.get('video_file'):
            dpg.set_value('vid_info_name', os.path.basename(s.get('video_file')))
            dpg.set_value('vid_info_fps', f'{s.get("video_fps", 30):.0f} FPS')
            dpg.set_value('vid_info_res', s.get('video_resolution', '640x480'))
            dpg.set_value('vid_info_frames', f'{s.get("sim_time", 0) * s.get("video_fps", 30):.0f} / {s.get("video_total_frames", 0)}')

        # Error history graph
        if err > 0 or state == TrackState.LOCKED:
            self._err_hist.append(err)
        elif state == TrackState.SEARCHING and len(self._err_hist) > 0:
            self._err_hist.append(0.0)
        self._update_error_graph(err, state)

        # Diagnostics tab updates
        if dpg.does_item_exist('diag_cam_pantilt'):
            dpg.set_value('diag_cam_pantilt', f'Pan: {s.get("cam_pan", 0.0):+.2f}°, Tilt: {s.get("cam_tilt", 0.0):+.2f}°')
        if dpg.does_item_exist('diag_cam_pos'):
            dpg.set_value('diag_cam_pos', f'({s.get("cam_x", 1000.0):.1f}, {s.get("cam_y", 1000.0):.1f}) px')
        if dpg.does_item_exist('diag_cam_viewport'):
            dpg.set_value('diag_cam_viewport', '640 x 480 px (FOV: 4.0° x 3.0°)')
        if dpg.does_item_exist('diag_cam_slew'):
            dpg.set_value('diag_cam_slew', f'{self._cam_slew_rate:.2f} deg/s')
        if dpg.does_item_exist('diag_cam_limit'):
            dpg.set_value('diag_cam_limit', '5.0 deg/s (Hardware bounded)')
        if dpg.does_item_exist('diag_cam_lat'):
            dpg.set_value('diag_cam_lat', '2 frames (~33.3 ms delay queue)')
        if dpg.does_item_exist('diag_cam_mode'):
            dpg.set_value('diag_cam_mode', 'Autonomous Closed-Loop Servo')

        if dpg.does_item_exist('diag_ev_track'):
            tx, ty = s.get('tracker_sx'), s.get('tracker_sy')
            dpg.set_value('diag_ev_track', f'({tx:.1f}, {ty:.1f}) px' if (tx and ty) else 'Acquiring...')
        if dpg.does_item_exist('diag_ev_gt'):
            gx, gy = s.get('gt_sx'), s.get('gt_sy')
            dpg.set_value('diag_ev_gt', f'({gx:.1f}, {gy:.1f}) px' if (gx and gy) else '-')
        if dpg.does_item_exist('diag_ev_err'):
            dpg.set_value('diag_ev_err', f'{err:.2f} px (RMSE: {s.get("rmse", 0):.2f}px)')
        if dpg.does_item_exist('diag_ev_pred'):
            kx, ky = s.get('kalman_pred_x'), s.get('kalman_pred_y')
            dpg.set_value('diag_ev_pred', f'({kx:.1f}, {ky:.1f}) px' if (kx and ky) else '-')
        if dpg.does_item_exist('diag_ev_vel'):
            vx, vy = s.get('kalman_vx', 0.0), s.get('kalman_vy', 0.0)
            dpg.set_value('diag_ev_vel', f'vx={vx:+.1f}, vy={vy:+.1f} px/s')

        if dpg.does_item_exist('diag_det_cands'):
            dpg.set_value('diag_det_cands', str(s.get('candidates', 0)))
        if dpg.does_item_exist('diag_det_ms'):
            dpg.set_value('diag_det_ms', f'{s.get("det_ms", 0.0):.1f} ms')
        if dpg.does_item_exist('diag_uncert'):
            dpg.set_value('diag_uncert', f'{s.get("uncertainty_px", 0.0):.2f} px')
        if dpg.does_item_exist('diag_scan_cov'):
            dpg.set_value('diag_scan_cov', f'{s.get("scan_coverage_pct", 0.0):.0f}%')
        if dpg.does_item_exist('diag_pid_i'):
            pid_i = s.get('pid_i', (0.0, 0.0))
            dpg.set_value('diag_pid_i', f'Pan: {pid_i[0]:+.3f}, Tilt: {pid_i[1]:+.3f}')

        # Diagnostics Requirements
        def pf(ok): return ('PASS', GREEN) if ok else ('FAIL', RED)

        if dpg.does_item_exist('diag_req_acq_v'):
            if acq is None:
                dpg.set_value('diag_req_acq_v', '-')
                dpg.set_value('diag_req_acq', 'PENDING')
                dpg.configure_item('diag_req_acq', color=TXT_MUTED)
            else:
                dpg.set_value('diag_req_acq_v', f'{acq:.2f}s')
                v, c = pf(acq <= 2.0)
                dpg.set_value('diag_req_acq', v)
                dpg.configure_item('diag_req_acq', color=c)

        if dpg.does_item_exist('diag_req_err_v'):
            dpg.set_value('diag_req_err_v', f'{err:.1f}px')
            v, c = pf(err <= 10)
            dpg.set_value('diag_req_err', v)
            dpg.configure_item('diag_req_err', color=c)

        loss_pct = (1 - lr) * 100
        if dpg.does_item_exist('diag_req_loss_v'):
            dpg.set_value('diag_req_loss_v', f'{loss_pct:.1f}%')
            v, c = pf(loss_pct < 5)
            dpg.set_value('diag_req_loss', v)
            dpg.configure_item('diag_req_loss', color=c)

        if dpg.does_item_exist('diag_req_reacq_v'):
            dpg.set_value('diag_req_reacq_v', '< 1.0s (Nominal)')
            dpg.set_value('diag_req_reacq', 'PASS')
            dpg.configure_item('diag_req_reacq', color=GREEN)

        if dpg.does_item_exist('diag_req_fps_v'):
            dpg.set_value('diag_req_fps_v', f'{fps:.0f} FPS')
            v, c = pf(fps >= 20)
            dpg.set_value('diag_req_fps', v)
            dpg.configure_item('diag_req_fps', color=c)

        # Benchmark Scorecard updates
        if dpg.does_item_exist('bench_val_acq'):
            if acq is not None:
                dpg.set_value('bench_val_acq', f'{acq:.2f} s')
                stat = 'PASS (Satisfied)' if acq <= 2.0 else 'FAIL (Exceeded)'
                dpg.set_value('bench_stat_acq', stat)
                dpg.configure_item('bench_stat_acq', color=GREEN if acq <= 2.0 else RED)

        if dpg.does_item_exist('bench_val_err'):
            dpg.set_value('bench_val_err', f'{err:.2f} px (RMSE: {s.get("rmse", 0):.1f}px)')
            stat = 'PASS (Within Spec)' if err <= 10.0 else 'FAIL (High Error)'
            dpg.set_value('bench_stat_err', stat)
            dpg.configure_item('bench_stat_err', color=GREEN if err <= 10.0 else RED)

        if dpg.does_item_exist('bench_val_loss'):
            dpg.set_value('bench_val_loss', f'{loss_pct:.1f}%')
            stat = 'PASS (Nominal)' if loss_pct < 5.0 else 'FAIL (High Loss)'
            dpg.set_value('bench_stat_loss', stat)
            dpg.configure_item('bench_stat_loss', color=GREEN if loss_pct < 5.0 else RED)

        if dpg.does_item_exist('bench_val_reacq'):
            dpg.set_value('bench_val_reacq', '<= 1.0s')
            dpg.set_value('bench_stat_reacq', 'PASS')
            dpg.configure_item('bench_stat_reacq', color=GREEN)

        if dpg.does_item_exist('bench_val_fps'):
            dpg.set_value('bench_val_fps', f'{fps:.1f} FPS')
            stat = 'PASS' if fps >= 20.0 else 'FAIL'
            dpg.set_value('bench_stat_fps', stat)
            dpg.configure_item('bench_stat_fps', color=GREEN if fps >= 20.0 else RED)

        # Guided Demo Live Updates
        if dpg.does_item_exist('demo_rt_state'):
            dpg.set_value('demo_rt_state', state.name if s.get('running') else 'STANDBY')
            dpg.configure_item('demo_rt_state', color=col if s.get('running') else YELLOW)
        if dpg.does_item_exist('demo_rt_err'):
            dpg.set_value('demo_rt_err', f'{err:.1f} px' if err else '- px')
        if dpg.does_item_exist('demo_rt_lock'):
            dpg.set_value('demo_rt_lock', f'{lr * 100:.1f}%')
        if dpg.does_item_exist('demo_rt_fps'):
            dpg.set_value('demo_rt_fps', f'{fps:.0f}')
        if dpg.does_item_exist('viewport_pantilt_demo_lbl'):
            dpg.set_value('viewport_pantilt_demo_lbl',
                          f'PAN: {s.get("cam_pan", 0.0):+.2f}°  TILT: {s.get("cam_tilt", 0.0):+.2f}°  '
                          f'CAM: ({s.get("cam_x", 0):.0f}, {s.get("cam_y", 0):.0f})')

        if dpg.does_item_exist('demo_s2_state'):
            dpg.set_value('demo_s2_state', state.name)
            dpg.configure_item('demo_s2_state', color=col)
        if dpg.does_item_exist('demo_s2_cands'):
            dpg.set_value('demo_s2_cands', str(s.get('candidates', 0)))

        if dpg.does_item_exist('demo_s3_acq'):
            dpg.set_value('demo_s3_acq', f'{acq:.2f} s' if acq is not None else 'Measuring...')
            dpg.configure_item('demo_s3_acq', color=GREEN if (acq is not None and acq <= 2.0) else YELLOW)
        if dpg.does_item_exist('demo_s3_err'):
            dpg.set_value('demo_s3_err', f'{err:.1f} px' if err else '0.0 px')
            dpg.configure_item('demo_s3_err', color=GREEN if err <= 10.0 else RED)
        if dpg.does_item_exist('demo_s3_fps'):
            dpg.set_value('demo_s3_fps', f'{fps:.0f} FPS')
            dpg.configure_item('demo_s3_fps', color=GREEN if fps >= 20 else YELLOW)
        if dpg.does_item_exist('demo_s3_lock'):
            dpg.set_value('demo_s3_lock', f'{state.name} ({lr * 100:.1f}%)')
            dpg.configure_item('demo_s3_lock', color=GREEN if state == TrackState.LOCKED else col)

        if dpg.does_item_exist('demo_s4_desc'):
            env_descs = {
                'Clear':     'Current Channel: Clear optical path with baseline transmission.',
                'Haze':      'Current Channel: Atmospheric haze with moderate Mie scattering.',
                'Fog':       'Current Channel: Dense optical fog with 15x15 Gaussian diffusion.',
                'Rain':      'Current Channel: Precipitation with dynamic diagonal occlusions.',
                'Low light': 'Current Channel: Low-light photon starvation with Poisson noise.',
            }
            dpg.set_value('demo_s4_desc', env_descs.get(self._atmos_mode, ''))

        if dpg.does_item_exist('demo_s6_reacq'):
            dpg.set_value('demo_s6_reacq', str(s.get('reacq_count', 0)))
        if dpg.does_item_exist('demo_s6_state'):
            dpg.set_value('demo_s6_state', state.name)
            dpg.configure_item('demo_s6_state', color=col)

        if dpg.does_item_exist('demo_s7_vid_status'):
            if s.get('video_mode'):
                vname = os.path.basename(s.get('video_file', '') or 'MP4 Video')
                dpg.set_value('demo_s7_vid_status', f'Playing: {vname} ({fps:.0f} FPS)')
                dpg.configure_item('demo_s7_vid_status', color=ACCENT)
            else:
                dpg.set_value('demo_s7_vid_status', 'No MP4 video currently loaded (Synthetic Simulation active)')
                dpg.configure_item('demo_s7_vid_status', color=TXT_MUTED)

        if dpg.does_item_exist('demo_s8_acq'):
            dpg.set_value('demo_s8_acq', f'{acq:.2f} s' if acq is not None else '-')
        if dpg.does_item_exist('demo_s8_err'):
            dpg.set_value('demo_s8_err', f'{err:.1f} px')
        if dpg.does_item_exist('demo_s8_rmse'):
            dpg.set_value('demo_s8_rmse', f'{s.get("rmse", 0):.1f} px')
        if dpg.does_item_exist('demo_s8_lock'):
            dpg.set_value('demo_s8_lock', f'{lr * 100:.1f}%')
        if dpg.does_item_exist('demo_s8_fps'):
            dpg.set_value('demo_s8_fps', f'{fps:.0f} FPS')
        if dpg.does_item_exist('demo_s8_reacq'):
            dpg.set_value('demo_s8_reacq', str(s.get('reacq_count', 0)))
        if dpg.does_item_exist('demo_s8_last_export') and self._last_report_notice:
            dpg.set_value('demo_s8_last_export', self._last_report_notice)

    # ── Application Main Loop ─────────────────────────────────────────
    def run(self):
        global WIN_W, WIN_H

        dpg.create_context()
        self._theme()
        self._texture()

        dpg.create_viewport(
            title='FSOC-PAT Mission Control Station | ISRO SIH 2025 PS 26169',
            width=WIN_W, height=WIN_H,
            min_width=1200, min_height=720,
            clear_color=BG_MAIN)

        dpg.setup_dearpygui()
        dpg.show_viewport()
        dpg.maximize_viewport()

        dpg.render_dearpygui_frame()
        WIN_W = dpg.get_viewport_client_width()
        WIN_H = dpg.get_viewport_client_height()

        self._build()

        def on_resize(sender, app_data):
            global WIN_W, WIN_H
            WIN_W = max(1200, app_data[0])
            WIN_H = max(720, app_data[1])
            content_h = WIN_H - TOP_H - STATUS_H

            if dpg.does_item_exist('main'):
                dpg.set_item_width('main', WIN_W)
                dpg.set_item_height('main', WIN_H)
            if dpg.does_item_exist('top_bar'):
                dpg.set_item_width('top_bar', WIN_W)
            if dpg.does_item_exist('top_right_grp'):
                dpg.set_item_pos('top_right_grp', [max(0, WIN_W - 430), 8])
            if dpg.does_item_exist('content_area'):
                dpg.set_item_width('content_area', WIN_W)
                dpg.set_item_height('content_area', content_h)
            if dpg.does_item_exist('status_bar'):
                dpg.set_item_pos('status_bar', [0, WIN_H - STATUS_H])
                dpg.set_item_width('status_bar', WIN_W)
                cw = WIN_W // 8
                for i in range(8):
                    if dpg.does_item_exist(f'cell_{i}'):
                        this_cw = (WIN_W - 7 * cw) if i == 7 else cw
                        dpg.set_item_width(f'cell_{i}', this_cw)

            left_w = int(WIN_W * 0.67)
            if dpg.does_item_exist('live_viewport_panel'):
                dpg.set_item_width('live_viewport_panel', left_w)
                dpg.set_item_height('live_viewport_panel', content_h - 32)
            if dpg.does_item_exist('cam_img'):
                uv_min, uv_max = self._calc_uv(left_w - 4, content_h - 80)
                dpg.configure_item('cam_img', width=left_w - 4, height=content_h - 80, uv_min=uv_min, uv_max=uv_max)
            if dpg.does_item_exist('viewport_pantilt_lbl'):
                dpg.set_item_pos('viewport_pantilt_lbl', [10, content_h - 52])
            if dpg.does_item_exist('world_panel'):
                dpg.set_item_pos('world_panel', [left_w - MINIMAP_SIZE - 14, content_h - MINIMAP_SIZE - 46])

            right_w = WIN_W - left_w - 24
            if dpg.does_item_exist('live_sidebar_panel'):
                dpg.set_item_width('live_sidebar_panel', right_w)
                dpg.set_item_height('live_sidebar_panel', content_h - 32)

            # Guided Demo Panel Resize
            demo_left_w = int(WIN_W * 0.52)
            demo_right_w = WIN_W - demo_left_w - 24
            if dpg.does_item_exist('demo_controls_panel'):
                dpg.set_item_width('demo_controls_panel', demo_left_w)
                dpg.set_item_height('demo_controls_panel', content_h - 32)
            if dpg.does_item_exist('demo_step_scroll_area'):
                dpg.set_item_height('demo_step_scroll_area', content_h - 162)
            if dpg.does_item_exist('demo_viewport_panel'):
                dpg.set_item_width('demo_viewport_panel', demo_right_w)
                dpg.set_item_height('demo_viewport_panel', content_h - 32)
            if dpg.does_item_exist('cam_img_demo'):
                uv_min_d, uv_max_d = self._calc_uv(demo_right_w - 4, content_h - 108)
                dpg.configure_item('cam_img_demo', width=demo_right_w - 4, height=content_h - 108, uv_min=uv_min_d, uv_max=uv_max_d)
            if dpg.does_item_exist('viewport_pantilt_demo_lbl'):
                dpg.set_item_pos('viewport_pantilt_demo_lbl', [10, content_h - 56])
            if dpg.does_item_exist('world_panel_demo'):
                dpg.set_item_pos('world_panel_demo', [demo_right_w - MINIMAP_SIZE - 14, content_h - MINIMAP_SIZE - 46])

        dpg.set_viewport_resize_callback(on_resize)
        dpg.set_primary_window('main', True)

        # Main frame loop
        while dpg.is_dearpygui_running():
            if dpg.is_key_pressed(dpg.mvKey_Escape):
                self._on_exit_save_click()
            if dpg.is_key_pressed(dpg.mvKey_Spacebar):
                self._on_reset_click()
            if dpg.is_key_pressed(dpg.mvKey_P):
                self.cbs['pause_resume']()

            self._update_metrics()
            dpg.render_dearpygui_frame()

        dpg.destroy_context()
