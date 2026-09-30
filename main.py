"""FSOC-PAT Simulator — main entry point. Stage 7B."""
import threading
from ui.dashboard import Dashboard
from ui.sim_thread import SimulationThread

PRESETS = {
    'EASY': dict(turbulence=0.0, vibration=0.0,
                 noise=0.0, scintillation=0.0, jerk=0.0),
    'MOD':  dict(turbulence=0.2, vibration=0.15,
                 noise=0.15, scintillation=0.1, jerk=0.005),
    'HARD': dict(turbulence=0.4, vibration=0.3,
                 noise=0.3, scintillation=0.25, jerk=0.02),
    'SEV':  dict(turbulence=0.65, vibration=0.5,
                 noise=0.5, scintillation=0.4, jerk=0.04),
    'ADV':  dict(turbulence=0.85, vibration=0.7,
                 noise=0.7, scintillation=0.6, jerk=0.07),
}

def main():
    shared = {
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
        'occluded': False, 'candidates': 0,
        'det_ms': 0.0, 'pid_i': (0.0, 0.0),
        'running': False, 'seed': 42,
        'world_w': 2000, 'world_h': 2000,
        'video_mode': False,
        'video_file': None,
        'video_done': False,
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
        },
        'cmd_pause': False, 'cmd_unpause': False, 'cmd_reset': False,
        'cmd_quit': False, 'cmd_motion_change': False,
    }

    def set_disturbance(key, value):
        shared['disturbances'][key] = value

    def set_atmosphere(mode):
        shared['disturbances']['atmosphere'] = mode

    def set_noise_type(ntype, enabled):
        key_map = {
            'Gaussian':  'noise_gaussian',
            'Salt-Pep':  'noise_saltpepper',
            'Poisson':   'noise_poisson',
        }
        if ntype in key_map:
            shared['disturbances'][key_map[ntype]] = enabled

    def set_preset(name):
        if name in PRESETS:
            shared['disturbances'].update(PRESETS[name])
            dist_map = {'EASY': 0, 'MOD': 1, 'HARD': 2, 'SEV': 3, 'ADV': 4}
            if name in dist_map:
                shared['num_distractors'] = dist_map[name]
                from config.loader import cfg
                cfg['distractors']['count'] = dist_map[name]
                shared['cmd_motion_change'] = True

    def set_motion(mtype):
        from config.loader import cfg
        cfg['motion']['type'] = mtype.lower().replace('-','')
        shared['cmd_motion_change'] = True

    def set_speed(v):
        from config.loader import cfg
        cfg['motion']['speed_px_s'] = float(v)
        shared['cmd_motion_change'] = True

    def set_size(v):
        from config.loader import cfg
        cfg['target']['size_px'] = int(v)
        shared['cmd_motion_change'] = True

    def reset_tracker():
        shared['cmd_reset'] = True
        sim_thread._start_new_session('simulation')

    def run_simulation():
        shared['cmd_unpause'] = True
        shared['running'] = True

    def pause_simulation():
        shared['cmd_pause'] = True

    def quit_app():
        shared['cmd_quit'] = True
        # cmd_quit only stops the sim thread's own loop; the DPG viewport
        # loop keeps running until told to stop explicitly.
        import dearpygui.dearpygui as dpg
        dpg.stop_dearpygui()

    def load_mp4_callback():
        import tkinter as tk
        from tkinter import filedialog
        import os
        from input.video_source import VideoSource
        import dearpygui.dearpygui as dpg

        try:
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            filepath = filedialog.askopenfilename(
                title="Select MP4 Video File",
                filetypes=[("MP4 Video", "*.mp4"), ("All Files", "*.*")]
            )
            root.destroy()
        except Exception as e:
            print(f"Error opening file dialog: {e}")
            return

        if not filepath:
            return

        try:
            video_source = VideoSource(filepath)
            sim_thread.set_video_mode(video_source)
            shared['video_mode'] = True
            shared['video_file'] = filepath
            shared['video_done'] = False

            filename = os.path.basename(filepath)
            display_name = (filename[:18] + '...') if len(filename) > 20 else filename
            if dpg.does_item_exist('video_status_lbl'):
                dpg.set_value('video_status_lbl', display_name)
                dpg.configure_item('video_status_lbl', color=(61, 220, 132, 255))
            if dpg.does_item_exist('mode_badge'):
                dpg.set_value('mode_badge', 'VIDEO')
                dpg.configure_item('mode_badge', color=(96, 170, 255, 255))
            if dpg.does_item_exist('top_mode_badge'):
                dpg.set_value('top_mode_badge', 'VIDEO REPLAY')
                dpg.configure_item('top_mode_badge', color=(0, 212, 255, 255))
            if dpg.does_item_exist('demo_s7_vid_status'):
                dpg.set_value('demo_s7_vid_status', f'Playing: {filename} ({video_source.get_fps():.0f} FPS)')
                dpg.configure_item('demo_s7_vid_status', color=(0, 212, 255, 255))
            print(f"[UI] Loaded MP4: {filepath} ({video_source.get_fps():.1f} FPS, {video_source._total_frames} frames)")
        except Exception as e:
            print(f"Error loading video: {e}")
            if dpg.does_item_exist('video_status_lbl'):
                dpg.set_value('video_status_lbl', 'Load Failed')
                dpg.configure_item('video_status_lbl', color=(255, 96, 96, 255))
            if dpg.does_item_exist('mode_badge'):
                dpg.set_value('mode_badge', 'ERR')
                dpg.configure_item('mode_badge', color=(255, 96, 96, 255))

    def set_initial_pos(pos_type):
        from config.loader import cfg
        if pos_type in ('center', 'in_fov', 'fov'):
            cfg['target']['initial_position'] = 'center'
        else:
            cfg['target']['initial_position'] = 'random'
        shared['cmd_motion_change'] = True

    def exit_and_save():
        try:
            sim_thread.export_snapshot()
        except Exception as e:
            print(f"[Exit] Snapshot export notice: {e}")
        quit_app()

    callbacks = {
        'set_disturbance': set_disturbance,
        'set_preset':      set_preset,
        'set_motion':      set_motion,
        'set_speed':       set_speed,
        'set_size':        set_size,
        'set_initial_pos': set_initial_pos,
        'reset_tracker':   reset_tracker,
        'run_sim':         run_simulation,
        'pause_sim':       pause_simulation,
        'pause_resume':    pause_simulation,  # kept for compatibility
        'quit':            quit_app,
        'exit_and_save':   exit_and_save,
        'set_detector':    lambda x: print(f'Detector: {x}'),
        'set_atmosphere':  set_atmosphere,
        'set_noise_type':  set_noise_type,
        'load_video':      load_mp4_callback,
        'run_benchmark':   lambda: print('Benchmark TBD'),
        'export_snapshot': lambda: sim_thread.export_snapshot(),
        'export_csv':      lambda: sim_thread.export_snapshot(),
        'export_pdf':      lambda: sim_thread.export_snapshot(),
    }

    sim_thread = SimulationThread(shared)
    sim_thread.start()

    dash = Dashboard(shared, callbacks)
    dash.run()

    shared['cmd_quit'] = True
    sim_thread.join(timeout=3.0)

if __name__ == '__main__':
    main()
