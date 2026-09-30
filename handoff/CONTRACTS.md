# FSOC-PAT existing contracts (baseline)

Recorded in phase 00 on 2026-09-28 from the source files as they exist on disk
(no git repository; see EVIDENCE.md for file modification times). This file
describes what the code does **now**. It does not redefine anything. Later
phases must update it deliberately when they change a public interface.

Line numbers are indicative for 2026-09-28 and can drift.

---

## 1. Architecture

| Layer | Path | Notes |
|---|---|---|
| Desktop shell | `frontend/electron.js` | Spawns `F:\FSOC\venv\Scripts\python.exe -m server.app` (cwd `F:\FSOC`), waits for `GET /api/state`, loads `http://127.0.0.1:8765`. Electron 38.8.6 in `frontend/node_modules`. |
| Web UI | `frontend/src/index.html` + `static/js/*.js` + `static/css/*.css` | Plain JS, no bundler. Served by FastAPI (`/` and `/static`). |
| API server | `server/app.py` | FastAPI + uvicorn, `127.0.0.1:8765` hard-coded (`__main__`). One process-wide `shared` dict and one `SimulationThread`. |
| Simulation / pipeline loop | `ui/sim_thread.py` (`SimulationThread`) | Thread started in FastAPI lifespan. `build_pipeline()` + `step(dt)` are also driven headlessly by `harness/runner.py`. |
| World / target / camera | `simulation/{world,target,motion,camera,distractors,obstacles}.py` | 2000x2000 world px, 640x480 viewport. `geometry3d.py`, `orbital.py` are not used by the live pipeline. |
| Disturbance | `disturbance/disturbance.py` | Applied to the rendered surface (sim only; never to video). |
| Detection | `detection/detector.py` (blob), `classifier.py` (CNN), `cv_scorer.py`, `ai_scanner.py` | See §7. |
| Tracking | `tracking/tracker.py` (`MasterTracker`), `temporal_fusion.py`, `imm_tracker.py`, `kalman_tracker.py`, `stabiliser.py`, `scene_estimator.py`, `search_pattern.py` | |
| Control | `control/camera_servo.py`, `pid_controller.py` | |
| Evaluation | `evaluation/{metrics,gt_metrics,logger,report_generator,centroid_log}.py` | |
| Harness | `harness/{__main__,runner,_one,scenarios,video,t1_in_frame}.py`, `harness/scenarios.yaml` | Deterministic headless runs, one mode per batch (`--mode`). |
| Legacy UI | `main.py`, `ui/dashboard.py`, `ui/hud.py` | DearPyGui/pygame app; not used by the Electron/web app. |
| Config | `config/default.yaml`, `config/loader.py` | Single module-level `cfg`, **mutated at runtime** by the server (`cfg['motion']['type']`, `speed_px_s`, `distractors.count`, `target.initial_position`). |

---

## 2. HTTP endpoints (`server/app.py`)

All JSON unless noted. No authentication. CORS `*`. Every HTTP response carries no-cache headers.

| Method, path | Request | Response / effect |
|---|---|---|
| `GET /api/state` | — | `serialize_state()` (see §4). `{}` on internal error. |
| `POST /api/command` | `{"cmd": str}` | `{"status":"ok","cmd":cmd}`. Commands below. 400 for unknown. |
| `POST /api/set_motion` | `{"motion": str}` | Sets `cfg.motion.type = motion.lower().replace('-','')`, `shared.beacon_motion`, raises `cmd_motion_change`. No validation of the name (unknown → `StraightLine` at 45° in `create_motion_model`). |
| `POST /api/set_atmosphere` | `{"mode": str}` | `clear|haze|fog|rain|dense_fog`; `low_light`/`lowlight` sets the independent low-light flag instead. 400 otherwise. Returns the disturbances dict. |
| `POST /api/set_toggle` | `{"name": str, "on": bool}` | Names: `gaussian, saltpepper, poisson, jitter, low_light, platform, occlusion, decoys, turbulence`. Levels from `cfg.disturbance.toggle_*`. Returns `toggle_state()`. |
| `POST /api/set_disturbance` | `{"type": str, "value": float}` | Writes `shared.disturbances[type] = value` with **no validation** of the key. |
| `POST /api/set_detector` | `{"mode": str}` | Writes `shared.detector_mode`; the sim thread normalises (`cv*`→cv, `ai*`→ai, else hybrid) and, if different, calls `set_detection_mode()` (finalises session, new tracker/servo, new session). |
| `POST /api/set_scenario` | `{"preset": "EASY|MOD|HARD|SEV|ADV"}` | Applies `PRESETS` (motion, speed, atmosphere, levels, distractors). EASY also sets `cfg.target.initial_position='near_center'` (persists in `cfg` for later sessions). |
| `POST /api/set_mode` | `{"mode":"simulation"}` | Leaves video mode (`set_simulation_mode()` → session finalised/new via `cmd_reset`) and unpauses. 400 for any other mode. |
| `POST /api/load_video` | multipart `file` (+ optional `gt`) | Writes upload to `input_videos/<basename>` (**overwrites** an existing file of that name), optional `gt` to `<stem>_gt.csv`. Immediately switches the sim thread to video mode. Returns `{status, filename, fps, frames, gt_loaded, gt_file}`. There is no separate preflight/inspect endpoint. |
| `GET /api/logs` | — | List of **top-level files only** in `logs/`: `[{name, size, modified(epoch s)}]`. Session subfolders are not listed. |
| `GET /api/logs/{filename}` | — | `FileResponse` for `.pdf`/`.csv` in top-level `logs/` only (basename enforced). |
| `GET /api/perf` | — | `{frames:[{frame, sim_time, stages{...ms}, pipeline_ms}], stages:{name:{mean,p50,p95}}, pipeline_fps, end_to_end_fps, capacity:120}`. Samples are taken per **delivered** WS frame, not per sim step. |
| `GET /api/diagnostics` | — | Model name/file/size/sha256/input_patch/classes/mode/loaded; system versions, CPU, cores, RAM, device `CPU`. The model name string is hard-coded `'BeaconCNN v2 (custom)'`. |
| `GET /api/backend-log` | — | Last ≤500 lines of `scratch/ui/server.out.log` and `server.err.log` if present (concatenated, not merged). |
| `GET /` | — | `frontend/src/index.html` |
| `/static/*` | — | `frontend/src/static` |

### `/api/command` semantics (current, verbatim behaviour)

| cmd | Effect |
|---|---|
| `run` | `cmd_unpause`, `running=True`; restarts the thread if dead. Does **not** start a new session. |
| `pause` | `cmd_pause`, `running=False`. Session continues. |
| `stop` | Same as pause **plus** `export_snapshot()`: writes CSV+PDF for the current session **without closing it**. A later `run` continues the same session, and a later finalisation overwrites the same files. |
| `reset` | If in video mode, leaves it. Sets `cmd_reset`; the thread then `_finish_session()` (exports if ≥1 frame), opens a new session, **new `Target(cfg, seed)`, new `VirtualCamera`, new tracker/servo, PID reset**, `sim_time=0`. |
| `reset_tracker` | Resets fusion/Kalman/search/predictive state only; camera, target, session unchanged. |
| `quit` | Stops the thread and shuts the server down. |

The frontend "Home" button sends `reset` (finalises the current session). `startMission()` sends `reset`, waits 500 ms, applies config, then `run`.

---

## 3. WebSocket streams

| Path | Payload | Rate |
|---|---|---|
| `/ws/frame` | `{"frame": <base64 JPEG q75, 640x480>, "timestamp": <server epoch s at send>}` | Sent only when `shared.frame_rgb` is a new array; loop polls at ~120 Hz. |
| `/ws/state` | `serialize_state()` JSON | Every 0.1 s (10 Hz) regardless of sim rate. |

The JPEG is the rendered sensor image **with pipeline overlays burned in** (`SimulationThread._draw_overlay`: candidate circles, spiral-search dots/line, cyan tracker crosshair, state text). Overlays are drawn after detection; the detector and blob-based stabiliser input (`detector.last_cleaned`/`last_gray`) are computed before the overlay. There is no clean-sensor stream.

Client URLs are **hard-coded** in `frontend/src/static/js/api.js` (`http://127.0.0.1:8765`, `ws://127.0.0.1:8765`). A second server on another port still sends its UI's API calls to 8765 unless this is changed.

---

## 4. `/api/state` keys (`serialize_state`) and units

| Key | Source (`shared`) | Unit / meaning |
|---|---|---|
| `track_state` | `track_state.name` | `SEARCHING|ACQUIRING|LOCKED|COASTING|LOST` (`TrackState` enum). There is no `DETECTED` state. |
| `camera_config` | `cfg.camera` | `{width, height, hfov (deg), vfov (deg), update_rate (Hz, config value, not measured), max_slew (deg/s)}` |
| `state_update_hz` | constant | `10` |
| `session_id` | `sim_thread._metrics.session_id` | See §6. `null` between sessions. |
| `track_error_px` | `err_px` | Sim: stabilised tracker position's distance from image centre (px), only when LOCKED for ≥10 consecutive frames; **`0.0` otherwise (not null)**. Video: `null`. Not GT-verified. |
| `fps` | rolling mean of last 60 `1/Δwall` between `step()` calls | End-to-end loop rate (Hz). Includes rendering, disturbance, metrics bookkeeping. |
| `lock_rate` | `_gt_lock` or tracker | **Fraction 0–1.** With GT: frames `LOCKED` and tracker within 25 px of GT ÷ **all frames with GT** since `_gt_lock` was last zeroed (includes pre-detection search time). `_gt_lock` is zeroed only by a detector-mode change, `set_video_mode` and `set_simulation_mode` — **not** by `reset`, so it spans consecutive simulation missions in the same mode. Without GT: `tracker.lock_retention_rate`. |
| `lock_rate_source` | | `'gt'` or `'tracker'` |
| `acq_time` | | Seconds, **wall clock** (`time.time()`), from the first frame with ≥1 detector candidate to the first `LOCKED` frame; lock correctness not checked. `null` until then. See §8. |
| `rmse` | | Running RMS of `err_px` over LOCKED frames with streak ≥10 and `err_px>0`; `0.0` when not LOCKED. |
| `max_error_px` | | Max of `err_px` (px). |
| `target_loss` | | Percent 0–100: frames in `LOST` or `COASTING` ÷ all session frames (tracker state, not GT). Differs from summary `target_loss_pct`. |
| `gt_sx`, `gt_sy` | | GT beacon position in screen px, including the disturbance whole-image offset (sim) or GT CSV value (video). Scoring/overlay only. |
| `tracker_x`, `tracker_y` | `tracker.tracked_pixel` | Screen px (raw, jittered image position); `null` unless LOCKED. |
| `confidence` | `rolling_conf` | Tracker rolling confidence 0–1. |
| `running`, `video_mode`, `video_done`, `video_file`, `video_fps`, `video_gt_loaded` | | Flags / file display name / native video fps. |
| `centroid_err_gt_px` | | Video+GT only: `|tracker − GT|` px. |
| `last_report_path` | | Relative path, e.g. `logs\SIM_..._report.pdf`. |
| `sim_time` | | Seconds of simulation time since session reset (see §9). |
| `reacq_count` | `tracker.reacquire_count` | Count. |
| `uncertainty` | `tracker.uncertainty` | px. |
| `pid_integral` | `pid.integral_state` | `[pan, tilt]`. |
| `scan_coverage_pct` | spiral waypoint index ÷ count × 100 | %. |
| `acquire_confidence`, `acquire_frames` | top candidate conf; fusion acquire count | |
| `cam_x`, `cam_y` | camera centre | World px. |
| `target_wx`, `target_wy` | `tgt_wx/tgt_wy` | GT beacon world px (sim only; `null` in video). Used by World view (display only). |
| `pan_deg`, `tilt_deg` | camera | Degrees. |
| `search_target_wx/wy` | | World px of current spiral waypoint. |
| `num_distractors` | | Count. |
| `detector_mode` | `detector_mode_active` or requested | `'Hybrid'|'CV Only'|'AI Only'` |
| `disturbances`, `atmosphere`, `toggles` | | Current backend disturbance settings / derived toggles. |
| `occluded` | | Sim: beacon behind obstacle. |
| `predicted_x`, `predicted_y` | Kalman `x + v` (one step) or predictive target | Screen px. |
| `pipeline_ms` | `last_pipeline_ms` | Detect→classify→track→servo compute (ms), excludes render/disturbance/metrics. |
| `det_ms` | | Detector (or AI scanner) ms. |
| `reacq_time` | `_gt_scores()['reacq_mean_s']` | Seconds (sim time), mean GT re-acquisition; only after ≥15 frames and with GT. Recomputed over the **whole session every frame**. |
| `current_state_time`, `state_durations`, `state_history` | | Seconds of **sim dt** in current state / per state / last 40 transitions. |

Additional `shared` keys not serialised: `perf_frame`, `tracker_stab_sx/sy`, `kalman_*`, `predictive_*`, `candidates` (**blob detector count even in AI mode**), `report_ready`, `video_total_frames`, `video_resolution`.

---

## 5. Frontend page IDs and lifecycle

Pages are `div.page` with IDs `page-<id>`; `PageManager.showPage(id)` toggles `.active`.

| Page id | Entry | Notes |
|---|---|---|
| `splash` | default | Four cards: Quick Demo (`startQuickDemo`: `set_scenario EASY` + `startMission`), Custom Mission (`builder`), Benchmark (`benchmark`), Load Video (file picker → `load_video` → `startMission({isVideo})` immediately). Secondary nav (`#secondary-navigation`): Camera Lab, Reports. |
| `builder` | | Motion (Straight, Circular, Figure-8, Random, Spiral, Sinusoidal), Speed (Slow/Normal/Fast), Initial position, Atmosphere, Disturbance chips + intensity, Detector mode. Step indicator Build→Brief→Execute→Results is decorative. |
| `brief` | builder Next | Summary + camera config from `/api/state`. START → `startMission()`. |
| `control` | `startMission` | Execute view; ids listed in EVIDENCE.md. |
| `cameralab` | `startCameraLab()` | Sends `run`, opens a second frame stream on the **same live simulation**; detector mode + atmosphere buttons only. No manual pan/tilt. |
| `benchmark` | | Frontend loop over EASY..ADV, 60 s each via `reset`/`set_scenario`/`run`, 1 Hz `GET /api/state` sampling, **PASS computed in the browser** (`_computeBenchmarkRow`). |
| `reports` | Stop / nav | Lists top-level `logs/` files. Selecting a CSV loads summary/frames; selecting anything else (PDF) clears the metric cards. |

`applyMissionConfigToBackend()` sends motion, atmosphere, low-light, detector and five disturbance levels. It does **not** send Speed or Initial position (these builder choices have no backend effect; `speedToPxS` is unused).

Leaving `control` stops the recorder and control camera stream; leaving `cameralab` stops the lab stream. The state WebSocket is shared (`app.stateWS`) and is only closed by `stopMission`/reconnect.

---

## 6. Sessions, IDs and persisted files

- Session object: `evaluation.metrics.MetricsAccumulator(session_id, mode)`; `mode ∈ {'simulation','video'}`.
- IDs: `SIM_<YYYYmmdd_HHMMSS>_<HYBRID|CV|AI>` (local time, 1 s resolution) and `VID_<video stem>_<MODE>`. **Video IDs repeat** for the same file and mode, so a re-run overwrites the previous exports. Two SIM sessions started within the same second with the same mode would also collide.
- A new session starts on: thread start, `reset` (incl. Home, `startMission`), detector-mode change, `load_video`, `set_mode simulation`. `_finish_session()` exports (if ≥1 frame) and discards the accumulator.
- Frames are recorded only if the session mode matches the current source.
- Files written to `logs/` (CWD-relative):
  - `<id>_frames.csv` — columns `frame,timestamp_s,state,track_error_px,fps,confidence,gt_x,gt_y,tracker_x,tracker_y,tracker_stab_x,tracker_stab_y,sim_time,occluded`.
  - `<id>_summary.csv` — `metric,value`; **every boolean is written as `PASS`/`FAIL`** (including `scored_with_gt`, `not_scored`); floats rounded to 3 dp; `None` → empty.
  - `<id>_report.pdf` — reportlab, letter, 2 pages.
  - `<id>/centroid_log.csv` — `frame,time_s,state,x_est,y_est,confidence,detector_mode[,gt_x,gt_y,err_px]`.
- There is no `session.json` manifest; the configuration (motion, speed, seed, disturbance schedule) is not persisted with a session except the per-frame disturbance tuple held in memory.
- Harness outputs: `logs/harness/<stamp>_<mode>[_kN]/{runs.csv,summary.csv,frames/<scenario>_s<seed>.csv}` (default `--out`); `harness.video` writes to its `--out`.

### Summary keys (`MetricsAccumulator.compute_summary`)

`session_id, mode, detector_mode, total_frames, duration_sec, mean_fps, acquisition_time_s, lock_rate_pct, target_loss_pct, reacq_time_s, reacq_max_s, reacq_events, reacq_unrecovered, pull_in_mean_s, pull_in_max_s, mean_track_error_px, max_track_error_px, rmse_px, raw_sensor_err_mean_px, raw_sensor_err_max_px, centroid_rmse_px, pass_acq_time, pass_track_error, pass_target_loss, pass_reacq_time, pass_fps, overall_pass, scored_with_gt` + (with GT) `centroid_err_mean_px, centroid_err_max_px, correct_lock_pct, correct_lock_visible_pct, lock_retention_pct, wrong_lock_events, beacon_out_of_fov_pct` + (video, no GT) `not_scored` + `processing_fps`.

- `duration_sec` = **wall** seconds from accumulator creation to last frame.
- `mean_fps` = mean of the per-frame `shared.fps` values (end-to-end loop rate).
- `processing_fps` = `1000 / mean(pipeline_ms)` (pipeline compute only; excludes render, disturbance, JPEG, metrics).
- Scoring path: GT path if any `gt_x` and all `sim_times` present (all sim sessions; video with GT CSV); otherwise live-only path.

---

## 7. Detector modes

| Mode | Label | Candidate generation | Scoring |
|---|---|---|---|
| `hybrid` | `Hybrid` | `BeaconDetector.detect` (blob/contour) | `BeaconClassifier` (CNN v2) |
| `cv` | `CV Only` | `BeaconDetector.detect` | `CVScorer` (logistic on 4 hand features, `cfg.detection.cv_weights/cv_bias`, operating-point rescale) |
| `ai` | `AI Only` | `AIScanner.detect`: stride-8 whole-frame CNN confidence map + NMS (`ai_min_conf` 0.3) | same CNN |

- AI and Hybrid share **one** `BeaconClassifier` instance (`AIScanner.model = classifier.model`) → same file `models/beacon_classifier_v2.pt` (`cfg.classifier.model_path`).
- Everything after candidates (stabiliser, scene estimator, IMM/fusion, gates, servo) is shared code.
- In AI mode the AI scanner refreshes `detector.last_cleaned` but not `detector.last_gray`; `tracker.process(..., raw=detector.last_gray)` therefore receives `None` (AI from start) or the last Hybrid/CV frame (after a live switch). Runtime effect not yet measured (EVIDENCE.md D-13).
- Live mode switch finalises the session and resets the tracker; camera position is kept.

---

## 8. Metric definitions (do not silently redefine)

Constants (`evaluation/gt_metrics.py`): `FRAME_W=640, FRAME_H=480, CORRECT_LOCK_TOL_PX=25.0, PULL_IN_THRESH_PX=10.0, PULL_IN_CAP_S=1.0`.

Per-frame flags: `in_fov` = GT inside `[0,640)×[0,480)` (occlusion ignored); `correct_lock` = `LOCKED` and `|tracker_raw − GT| ≤ 25 px` (screen space); `wrong_lock` = LOCKED and not correct; `visible` = in_fov and not occluded.

### Acquisition time — three different definitions exist

| Where | Start | End | Clock |
|---|---|---|---|
| A. Live `shared.acq_time` (Execute panel, Benchmark table) | First frame with ≥1 detector candidate (any blob / AI peak ≥0.3; could be a star or decoy) | First `LOCKED` frame (correctness not checked) | **Wall clock** `time.time()` |
| B. Summary/PDF, GT path (`gt_metrics.acquisition_time`) — every simulation session, video with GT | First `in_fov` frame | First `correct_lock` frame at/after it | Sim time (`sim_times`, relative) |
| C. Summary/PDF, no-GT path (video without GT) | First frame with `candidate_count>0` | First `LOCKED` frame (loop stops at the first LOCKED; if no candidate before it → `None`) | Sim/video time |

None of them measures from mission start (Run/reset). A beacon that starts outside the FOV is only timed from first FOV entry (B) or first candidate (A, C).

### Pointing error vs centroid error

- **Pointing (tracking) error, simulation** — `track_err_*`: distance of the tracker's **stabilised** position (`stab_sx/sy`, falls back to raw) from the image centre (320,240), over `correct_lock` frames **excluding pull-in** (each lock stretch, until error first < 10 px, capped at 1.0 s). `mean_track_error_px`, `max_track_error_px`, `rmse_px` in summary. The pass/fail uses the **mean**, not RMS.
- `raw_sensor_err_*`: same frames, raw (jittered) tracker position vs centre.
- `boresight_err_*` (harness only): `|GT world − camera centre world|`.
- **Centroid error** — `|tracker_raw − GT|` in screen px, over **all** correct_lock frames (no pull-in exclusion): `centroid_err_mean/max_px`, `centroid_rmse_px`. In **video** mode the summary's `mean/max_track_error_px` and `rmse_px` are the **centroid** statistics (`err='centroid_err'`), and the PDF row is labelled "Centroid Error vs GT".
- Live `track_error_px` (§4) is neither: any LOCKED (not GT-verified) after a 10-frame streak, stabilised, and 0.0 when unavailable.
- µrad in UI: `px × 109` (4°/640 px = 109.08 µrad/px; vertical 3°/480 px identical). The PS angular unit is not used by any pass/fail check.

### Lock percentages — different denominators

| Key | Numerator | Denominator |
|---|---|---|
| `lock_rate_pct` (summary) | frames in `LOCKED` (any) | all session frames |
| `correct_lock_pct` | correct_lock frames | all session frames |
| `correct_lock_visible_pct` | correct_lock ∧ in_fov | in_fov frames |
| `lock_retention_pct` | correct_lock ∧ in_fov from first correct lock | in_fov frames from first correct lock |
| live `lock_rate` (fraction) | correct_lock frames | frames with GT since the last detector-mode change or video/sim switch (not reset by `reset`) |
| `tracker.lock_retention_rate` (live fallback) | tracker-internal | tracker-internal |

The PDF metrics table shows `correct_lock_pct` when GT exists, otherwise `lock_rate_pct`; the Reports page card shows `lock_rate_pct` always.

### Target loss, re-acquisition

- `target_loss_pct` (GT): from the first correct_lock frame to the end, frames with beacon in_fov but not correct_lock ÷ **all** frames from first correct lock (out-of-FOV frames are in the denominator, reported separately as `beacon_out_of_fov_pct`). `None` → summary substitutes **100.0**.
- `target_loss_pct` (no GT): `LOST`+`COASTING` frames ÷ all frames.
- Re-acquisition (`reacquisition_times`): for each correct→not-correct transition, the clock starts at the first frame that is visible and not event-active, stops at the next correct_lock; lock regained before the clock starts = 0.0 s. `reacq_time_s` = mean, `reacq_max_s` = max. Live sessions mark any frame whose disturbance settings differ from the session's first frame as `event_active`.

### Requirement checks (`MetricsAccumulator._finish_summary`)

| Requirement | Check in code | PDF "Required" text | Value used |
|---|---|---|---|
| Acquisition time | `acq ≤ 2.0` s; `None` → FAIL | `≤ 2.0 s` | B (sim/GT) or C |
| Tracking error | `mean_track_error_px ≤ 10.0`; `None` → FAIL | `≤ 10 px` | mean pointing error (sim) / mean centroid error (video+GT) |
| Target loss | `target_loss_pct ≤ 5.0` | `< 5%` (text and code disagree at exactly 5.0) | |
| Re-acquisition | `reacq ≤ 1.0` s, or **`None` → PASS** | `≤ 1.0 s` | mean |
| Processing speed | `mean_fps ≥ 20.0` | `≥ 20 FPS` labelled "Processing Speed" | **end-to-end loop `mean_fps`, not `processing_fps`** |
| Overall | all five | | Video without GT: requirements set `None`, `overall_pass=None`, `not_scored=True` |

Provenance: the thresholds appear only in code/comments/UI text attributed to "PS 26169" (SIH 2025, ISRO). No official requirement document exists in the repository. Legacy `ui/dashboard.py` text says "Tracking Error <= 10.0 px RMS" while the evaluator uses the mean. Treat these as **configured PS checks**; the reference images' limits (µrad pointing, 10 s acquisition, events/5 min, uptime, 50 ms latency) are **not** the application's requirements.

The browser Benchmark computes its own PASS: `acq_time(A) ≤ 2.0 ∧ mean(sampled track_error_px while LOCKED) ≤ 10 ∧ (LOST samples ÷ samples) < 5 %` from 1 Hz samples — a second, inconsistent evaluator.

---

## 9. Coordinates and time

- **World**: pixels, origin top-left, x right, y down, `0..2000` (config `world.width/height`). Beacon, distractors, obstacles, camera centre live here. Motion models clamp the beacon to `[10, W−10]`.
- **Screen / sensor**: 640×480 px, origin top-left. `world_to_screen(wx,wy) = (wx − cam_x + 320, wy − cam_y + 240)`. Sim GT additionally adds `disturbance.applied_offset` (image jitter/jerk/platform).
- **Angles**: `ppd_h = 640/4.0 = 160 px/deg`, `ppd_v = 480/3.0 = 160 px/deg`. `pan = (cam_x − 1000)/ppd_h`, `tilt = −(cam_y − 1000)/ppd_v` (tilt positive = up = smaller y). Limits pan ±30°, tilt −20..+20° → `cam_x ∈ [−3800, 5800]`, `cam_y ∈ [−2200, 4200]` world px (camera may point past the world edge). Slew ≤5 °/s per axis, 2-frame command latency. This is a flat 2-D angular approximation (translation of a viewport), not 3-D optics.
- **Video**: frames resized to 640×480; GT CSV `frame,x,y` (extra columns such as `t,visible` ignored) must already be in 640×480 screen px; lookup tries index `i` then `i+1`.
- **Time bases**:
  - `sim_time`: sum of `dt`. Live sim `dt = min(clock.tick(60)/1000, 0.05)` → sim time runs **slower than wall time whenever the loop is below 20 FPS**. Video `dt = 1/native_fps`. Harness fixed `dt` (default 1/60).
  - `MetricsAccumulator.timestamps`: `perf_counter` since accumulator creation (wall).
  - `acq_time` live: wall. Summary acquisition/re-acq/pull-in: sim time.
  - State timeline durations: sim dt.
  - `/ws/frame.timestamp`: server epoch at send. `/api/logs.modified`: file mtime epoch.
  - PDF chart x-axis: wall `timestamp_s` in simulation mode, `sim_time` in video mode.
  - Motion model time: `Target.t` (sum of dt since the Target object was constructed; reset on every new `Target`).

---

## 10. Motion model contract

`simulation/motion.py` `create_motion_model(cfg, seed)` reseeds Python `random` and `numpy.random` globally with `seed`, then:

| type | Model | Centre / start |
|---|---|---|
| `straight` | `StraightLine(speed, random angle)`; bounces off world edges | start overwritten by `Target` initial position |
| `circular` | `cx + r cos(ωt)`, `ω = circular_omega` (default 0.3) | **world centre (1000,1000)**, r=300 |
| `figure8` | `cx + ax sin(ωt), cy + ay sin(2ωt)/2` | **world centre** |
| `random` | velocity random walk | starts at initial position |
| `spiral` | `r = 50 + growth·t` | **world centre** |
| `sinusoidal` | `cx + ax sin(ωt), cy + ay cos(2ωt)` | **world centre** |

Periodic models ignore the initial position after the first `update()` (they are absolute functions of `t`). `speed_px_s` affects only `straight`. `Target(cfg, seed)` sets the initial position from `cfg.target.initial_position` (`random`: world centre ± 250 px seeded with `seed+1`; `near_center`: centre +25,+25; `center`).


## Post-implementation contracts — 29 September 2026 (supersedes baseline where different)

- Environment overrides: FSOC_PORT (default 8765), FSOC_LOGS_DIR, FSOC_VIDEOS_DIR. Browser API/WS use current HTTP origin; Electron file origin retains 8765.
- Motion changes use an anchored MotionSegment with local time/RNG and a 0.25-second incoming-velocity transition. Legacy initial harness motion is retained. Builder-created missions enable anchored initial motion; world-edge reflection keeps targets in bounds.
- POST /api/command stop returns status, session_id, error after finalisation readiness or timeout; retry preserves failed accumulator/session ID. Empty sessions do not export. GET /api/finalisation exposes readiness/error.
- GET /api/sessions, /api/sessions/{sid}, /frames, /artifacts/{kind}. New manifests are logs/{sid}/session.json schema_version=1, with summary/configuration/events/requirements/artifact paths. UUID suffixes avoid overwrite. Legacy flat triplets remain readable. Frame response is sampled to at most 1000 rows; plot_gap preserves missing-lock intervals across sample buckets.
- Requirements use configured thresholds: acquisition <=2 s, error <=10 px, loss <=5%, reacquisition <=1 s, end-to-end >=20 FPS. Missing values remain null. Overall PASS requires every check measured/passed; missing recovery => INCOMPLETE, no-GT video => NOT_SCORED. Pipeline rate is separate.
- POST /api/videos/prepare multipart file returns metadata/thumbnails; /{id}/gt takes CSV file, coordinates native|processing, index_base 0|1; canonical GT is zero-based 640x480 with visibility. /{id}/start accepts mode Hybrid|CV Only|AI Only. No sim mutation until explicit Start. Legacy video source now reads canonical zero-based indices without i+1 fallback.
- POST /api/mission/preview and /configure use builder motion/speed/position/environment/mode. Preview is isolated; configure rejects an active running mission.
- POST /api/lab/start, /exit, /input. Input is mode manual|assist|auto, pan/tilt in degrees/s (absolute rate <=2), optional home. Manual envelope radius 5 degrees, stale-input watchdog 0.35 s. Beacon is fixed. lab_status states control owner and 2D approximation.
- Frame WebSocket sends clean RGB image plus matching frame_id/source-time telemetry from one published frame_packet. Overlays are client-side, detector inputs unchanged. State WebSocket remains independently sampled.
- POST /api/comparisons starts fixed-seed scenarios (straight|figure8|sinusoidal; 1–30 s API, 5/10/20 UI) with optional shared dropout. GET list/status/results/frames/report and POST cancel. Modes execute sequentially in independent processes; replay is synchronized recorded evidence. Realtime PS throughput is NOT_TESTED. Scenario hash and model hash are persisted. New jobs after model-hash addition include it; older verification jobs may lack it. Restart-interrupted jobs report error rather than staying running forever.
- Budgets: 512 MB/video, 80 MB preview/mode, approximately 2 GB prepared-video / 1 GB comparison aggregate caps. Reject further generation/upload rather than deleting old data.

## V3 additions
Mission configure/preview accepts renderer classic|optical. Comparison create accepts renderer, fresh (false default); default duration is now 5 and dropout false. Exact completed scenario/engine/model matches return reused:true. Status adds total_frames, completed_frames, percent; progress adds elapsed_s and compute_fps. Lab start accepts renderer and restores prior config on exit. Session scoring_version is 2-explicit-events: persistent atmosphere/settings changes no longer pause recovery. Old reports preserved. See POLISH_V3.md for optical limitations and historical frame audit.

