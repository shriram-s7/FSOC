# FSOC-PAT baseline evidence (phase 00)

Collected 2026-09-28 23:27 – 2026-09-29 00:10 IST, by read-only inspection plus non-destructive test runs.
No application file was modified. Interfaces are described in `CONTRACTS.md`.

## 1. Environment actually found

| Item | Value | How obtained |
|---|---|---|
| OS | Windows 11 Home Single Language 10.0.26200 | `platform.platform()` |
| Python (venv) | 3.12.6 (`venv/pyvenv.cfg` → `C:\Users\shrir\AppData\Local\Programs\Python\Python312`) | venv interpreter |
| numpy | 2.5.3 | import |
| opencv (cv2) | 5.0.0 | import |
| torch / torchvision | 2.14.0+cpu / 0.29.0+cpu | import |
| pygame | 2.6.1 (SDL 2.28.4) | import |
| fastapi / starlette / uvicorn / pydantic | 0.141.1 / 1.6.0 / 0.53.0 / 2.13.5 | import |
| Pillow | 12.3.0 | import |
| reportlab | 5.0.1 | import |
| PyYAML / scipy / filterpy / matplotlib | 6.0.3 / 1.18.1 / 1.4.5 / 3.11.2 | import |
| websockets / python-multipart / dearpygui | 17.1 / 0.0.32 / 2.3.1 | import |
| **Not installed** | psutil, pytest, PyMuPDF (fitz), pypdf, pdfplumber | import fails |
| Node (system) | v20.20.2 | `node --version` |
| Electron | 38.8.6 (`frontend/node_modules/electron`) | package.json |
| ffmpeg/ffprobe | not on PATH | `which` |
| Git | **Not a git repository** — no diff/stash/branch history; local modifications can only be judged by mtime (§6). | environment |
| AGENTS.md | **None found** anywhere under `F:\FSOC` (excluding venv/node_modules). Only instructions: `handoff/*`. | `find` |

Nothing was installed or upgraded. `pip_install.log` (2026-09-16) records an earlier failed install (`WinError 32` on scipy) — historical only.

Consequences for later phases: there is no pytest (tests run with `python -m unittest`), no PDF text/render library in the venv (PDF inspection needs another route or explicit approval to install), and no ffmpeg (phase 09 must not assume a video encoder; OpenCV's writer availability is unverified).

## 2. Model files (read-only hashes)

| File | Size (B) | mtime | SHA-256 |
|---|---|---|---|
| `models/beacon_classifier.pt` (v1, unused by config) | 165070 | 2026-09-16 22:17:35 | `21b4a687336fbf3e9d10d0e785c5d25f47728c6a0edc0d6546c709e709efc8a6` |
| `models/beacon_classifier_v2.pt` (configured) | 165163 | 2026-09-24 01:14:59 | `0c0c5b5952eb61fd68e75855b53d2594c2f0deb13e023f022e4ae661a9b97efb` |

The live server's `/api/diagnostics` reports the same v2 SHA-256, `loaded: true`. Later phases must re-hash and compare against these values.

Training data (`data/training`, `data/training_v2`), generators (`detection/generate_training_data.py`, `train_classifier.py`), `models/`, `logs/`, `input_videos/`, `data/test_videos/`, reference images were not modified.

## 3. Live processes and ports (observed, not touched)

| PID | Process | Detail |
|---|---|---|
| 4776 | `venv\Scripts\python.exe -u -B -m server.app` | venv launcher, started 2026-09-28 19:45:47; its parent (9492) no longer exists |
| 21436 | `Python312\python.exe -u -B -m server.app` | actual server, **listening 127.0.0.1:8765** |
| 14808 / 16144 | chrome / ChatGPT | established connections to 8765 (1 and 2) |
| several | Codex `node.exe`/`node_repl.exe` under `codex.exe` | another agent tool runtime; not related to FSOC ports |

At 23:44 a **simulation mission was running** (`GET /api/state`: `running=true`, session `SIM_20260928_225108_HYBRID`, `track_state=LOCKED`, `sim_time≈1550 s`, `lock_rate=0.99 (gt)`, `acq_time=0.15`, clear atmosphere, 0 distractors). Only `GET /api/state`, `/api/diagnostics`, `/api/perf` were called. No command was sent; the mission was not paused, stopped or reset. No Electron process was running (the UI is being viewed from a browser).

The server started at 19:45:47, after the last `server/app.py` (19:44) and `ui/sim_thread.py` (19:13) edits, so it runs the current backend code. Frontend files are served from disk, so browser reloads get current files.

### Live performance sample (read-only, 23:44:38–39)

| Quantity | Value |
|---|---|
| `/api/perf` `end_to_end_fps` (= `shared.fps`) | 5.63–5.65 |
| `/api/perf` `pipeline_fps` | 60.7–60.8 |
| Stage means (ms): Capture/Render 0.44, Disturbance 0.01, Detect 7.8–7.9, Classify 1.68, Stabilise 1.5, Scene 3.5, Track 0.75, Control 0.02, Encode+Send 5.81 | |
| Last 120 perf frames span 5.95 s of sim time | every step used the `dt` cap of 0.05 s |

A second read at ~00:10 (end of phase 00) gave `fps 4.45` at `sim_time 1897.7`, same session, still LOCKED — the rate keeps falling as the session grows.

So the pipeline needs ~17 ms but the loop runs at ~5.6 Hz, and simulation time advances at ≈0.28× wall time. See D-12 for the suspected cause.

## 4. Checks run

All commands from `F:\FSOC`, environment `PYTHONDONTWRITEBYTECODE=1 SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`, interpreter `venv\Scripts\python.exe -B`. Side effects were inspected first: the unit tests are in-memory; the behavioural leak test runs `harness.runner.run_one` with no CSV/session output; harness runs were redirected to scratch. Output: `scratch/handoff-verification/00-baseline/`.

| # | Command | Result |
|---|---|---|
| T1 | `python -m unittest -v tests.test_gt_metrics tests.test_scene_reference tests.test_no_leak` with `FSOC_SKIP_SLOW=1` | **38 run, OK, 1 skipped** (the slow behavioural test), 0.133 s. Log `unittest_fast.log`. |
| T2 | `python -m unittest -v tests.test_no_leak.TestBehaviouralNoLeak` | **1 run, OK**, 108.9 s. S08 seed 1 trace hash identical with and without corrupted disturbance state. Log `slow_and_harness.log`. |
| T3 | `python -m harness --scenarios S01,S03,S05 --seed-list 1 --duration 30 --workers 1 --out scratch/handoff-verification/00-baseline/harness` | exit 0, 180 s. Output `harness/20260928_235023_hybrid`. |
| T4 | same, `--scenarios S01 --mode cv` | exit 0, 60 s. Output `harness/20260928_235324_cv`. |
| T5 | same, `--scenarios S01 --mode ai` | exit 0, **689 s** wall for 30 s sim. Output `harness/20260928_235425_ai`. |
| P1 | `scratch/handoff-verification/00-baseline/probe_baseline.py` (imports `simulation.target`, `evaluation.metrics`; writes nothing) | exit 0. Log `probe_P1.log`. |

Harness results (seed 1, 30 s, dt 1/60; GT-scored by `gt_metrics.score_frames`):

| Run | Trace hash | Acq s | CorrLock % | Reacq n / mean / max s | Loss % | TrkErr mean/max/rmse px | Centroid mean/max/rmse px | Loop/pipe FPS (contended) |
|---|---|---|---|---|---|---|---|---|
| S01 straight, hybrid | `3e748074bc5f3943` | 0.12 | 99.6 | 0 / – / – | 0.0 | 1.23 / 9.3 / 1.34 | 0.53 / 1.5 / 0.59 | 32 / 37 |
| S03 figure-8, hybrid | `d823750315eb30db` | 0.12 | 99.6 | 0 / – / – | 0.0 | 3.51 / 5.0 / 3.57 | 0.55 / 1.4 / 0.62 | 31 / 37 |
| S05 sinusoidal, hybrid | `770395fa83a6558e` | 0.12 | 97.6 | 9 / 0.07 / 0.13 | 2.1 | 3.55 / 27.6 / 3.80 | 0.62 / 2.2 / 0.71 | 31 / 37 |
| S01 straight, cv | `3e748074bc5f3943` | 0.12 | 99.6 | 0 / – / – | 0.0 | 1.23 / 9.3 / 1.34 | 0.53 / 1.5 / 0.59 | 32 / 38 |
| S01 straight, ai | `275b2230758d57b6` | 0.12 | 99.6 | 0 / – / – | 0.0 | 1.24 / 9.1 / 1.34 | 0.54 / 1.5 / 0.59 | **3 / 3** |

Regression anchor: `scratch/ui/FINAL_REPORT.md` recorded S01 seed 1 30 s hybrid trace hash `3e748074bc5f3943` before and after the UI repair. **T3 reproduced it.**

CV = Hybrid hash is not a harness error: the per-frame `detector_mode` in `sessions/S01_s1/centroid_log.csv` is `CV Only` (mean confidence 0.9634) vs `Hybrid` (1.0000). `trace_hash` covers only `(state, trk_sx, trk_sy, cam_x, cam_y, tgt_wx, tgt_wy)`, which coincide on clean S01. The hash is therefore insensitive to confidence; comparison work (phase 09) must not use it as proof that two modes behaved differently or identically beyond those fields.

AI mode ran at ≈3 FPS loop/pipeline in the harness while the machine was shared with the live server; uncontended AI throughput was not measured. Phase 09 must measure it before promising any real-time AI comparison.

P1 — motion change (reproduces `self.target = Target(cfg, 42)` after 20 s of the first motion; `random` initial position):

| Change | Position before | New Target at construction | After 1 frame | Jump after 1 frame |
|---|---|---|---|---|
| straight → figure8 | (385.2, 637.2) | (769.3, 1098.1) = spawn | (1003.4, 1001.7) ≈ world centre | 717.6 px |
| straight → sinusoidal | (385.2, 637.2) | spawn | (1002.5, 1200.0) | 835.4 px |
| sinusoidal → figure8 | (1380.4, 838.2) | spawn | (1003.4, 1001.7) | 411.0 px |
| straight → straight | (385.2, 637.2) | spawn | (769.0, 1097.7) | 599.5 px |
| figure8 → straight | (764.9, 1095.1) | spawn | (769.0, 1097.7) | 4.8 px (coincidence: figure-8 at t=20 s is near spawn) |

A 600–835 px world jump is 1.25–1.7 frame widths; the camera (5 °/s = 800 px/s) cannot follow within one frame, so the tracker loses the beacon.

P1 — cost of the per-frame live bookkeeping in `step()` (`_gt_scores()` + LOST/COASTING scan) on a synthetic session:

| Session frames | `_gt_scores` ms | loss scan ms | Loop-rate ceiling from this alone |
|---|---|---|---|
| 1 000 | 6.11 | 0.03 | ~163 Hz |
| 5 000 | 18.88 | 0.18 | ~52 Hz |
| 20 000 | 74.19 | 0.72 | ~13 Hz |
| 60 000 | 218.71 | 2.15 | ~4.5 Hz |

This grows linearly with session length and is outside `pipeline_ms`, consistent with the live 5.6 FPS at ~1550 s sim time (D-12). Measured offline, not on the live process.

Harness runs executed while the user's live mission was running on the same machine (12 cores; harness pins torch/OpenCV to 1 thread). Trace hashes are deterministic; `processing_fps`/`pipeline_fps`/wall times from T3–T5 are contended measurements and must not be used as performance baselines.

Not run: full harness baseline (S01–S15 × 5 seeds × 60 s, estimated >1 h), video harness, PDF generation, browser/UI checks (see §5). No pre-existing test failures were found.

## 5. Screenshots / UI verification

No new screenshots were taken. The only UI server is the live one on 8765 serving an active mission, and `static/js/api.js` hard-codes `127.0.0.1:8765`, so a separately started test instance on another port would still drive the live backend from its UI (D-15). Existing captures from the 2026-09-28 UI repair session are in `scratch/ui/A_allpages/` (69 files, 1280 and 1440 widths, captured 19:40–19:50 — before the last `app.js`/`world-view.js` edit at 19:52) and `scratch/ui/A_execute`, `B_diagnostics`. Two were viewed in this phase (`home_1440.png`, `execute_camera_final_1440.png`); that report states they were captured at ~80 % compositor scale. They are prior-session evidence, not re-verified here. No 1920×1080 capture exists.

## 6. Local modifications (mtime-based, no git)

Source files modified on 2026-09-28 (outside `scratch/`):
- 02:05–02:53: `tracking/{imm_tracker,kalman_tracker,stabiliser,tracker,scene_estimator,temporal_fusion}.py`, `detection/detector.py`, `evaluation/{centroid_log,logger,metrics,report_generator}.py`, `harness/{__main__,runner}.py`, `tests/test_no_leak.py`, `config/default.yaml`, `harness/scenarios.yaml` (01:04). Documented by `scratch/p3/REPORT.md`, `STATUS.md`.
- 11:57–19:52: `frontend/src/static/js/{chart.umd.min,api,diagnostics,pages,app,world-view}.js`, `static/css/{pages,main,tokens,repair}.css`, `index.html`, `ui/sim_thread.py` (19:13), `server/app.py` (19:44). Documented by `scratch/ui/FINAL_REPORT.md`; originals retained in `scratch/ui/repair_original`, `scratch/ui/pre-repair-baseline`.
- 19:49 `input_videos/test_seed1.mp4` + `test_seed1_gt.csv`, 20:31 `input_videos/test_seed3.mp4` (uploads overwrite by name).
- `handoff/*` 23:27–23:37.

All of these are treated as user work to preserve.

Saved data present: `logs/` 548 MB, 494 top-level files (163 sessions × frames/summary/report + 5 debug CSVs), 79 directories (71 SIM session folders, VID_* folders, `harness*`, `video`, `comparison`). None were modified.

## 7. Verification of earlier findings

| # | Earlier finding | Status | Evidence |
|---|---|---|---|
| F1 | PDF selection clears report metrics | **Confirmed** | `app.js` `selectReport`: any non-`.csv` name → `_clearReportMetrics()` and return. (The UI repair changed the *Export PDF* button to open the sibling PDF; selecting a PDF in the list still blanks the cards and chart/table are left from the previous selection.) |
| F2 | Stop opens the generic archive | **Confirmed** | `stopMission()`: `command('stop')` → `showPage('reports')` + `refreshReportsList()`; no selection of the session just stopped. Backend `stop` = pause + `export_snapshot()` without closing the session. |
| F3 | Motion changes construct a new Target | **Confirmed** | `sim_thread.py` `cmd_motion_change` branch: `self.distractors = Distractors(cfg)` and `self.target = Target(cfg, seed)` (same session seed). Also re-creates distractors (new random positions) and reseeds global `random`/`numpy.random`. Quantified in P1. |
| F4 | Periodic motion centres on world centre | **Confirmed** | `create_motion_model`: `cx, cy = W//2, H//2` for circular, figure8, spiral, sinusoidal; their `update()` is an absolute function of `t`, overriding the spawn position on the first frame. |
| F5 | Camera Lab reuses the simulation with no manual control | **Confirmed** | `startCameraLab()`: `command('run')` + second `CameraFeed` on the same `/ws/frame`; page has detector and atmosphere buttons only. No pan/tilt endpoint exists; camera is only moved by `CameraServo`. Opening it after Stop resumes the stopped session. |
| F6 | Video selection immediately starts analysis | **Confirmed** | `setupSplash` change handler: `API.loadVideo()` → `startMission({isVideo})`. Backend `load_video` already switches the sim thread to video mode and resets the session before the UI does anything; no inspect/preflight step, no metadata before analysis. |
| F7 | Live comparison does not exist | **Confirmed**, with a note | No comparison page, endpoint or JS. There is **offline** harness comparison output: `logs/comparison/` (per-mode harness batches from 2026-09-24/26, `comparison.csv`, `correct_lock_by_scenario.png`) produced by `scratch/s5b/compare.py`. It is a CSV/PNG, not a synchronized recorded comparison. |
| F8 | v2 classifier weights are shared by AI and Hybrid | **Confirmed** | `AIScanner.__init__`: `self.model = classifier.model`; one `BeaconClassifier()` per pipeline, path `cfg.classifier.model_path = models/beacon_classifier_v2.pt`. |

## 8. Observed defects and risks (not fixed in phase 00)

IDs are for reference by later phases. "Static" = found by reading code; "measured" = reproduced by a check in §4.

| ID | Area | Observation | Evidence | Owner phase |
|---|---|---|---|---|
| D-01 | Motion | Changing motion replaces Target (position back to spawn / world-centre pattern, `t=0`), replaces distractors, reseeds global RNGs. | Static + P1 | 01 |
| D-02 | Metrics | Three different acquisition-time definitions (live wall clock from first candidate to any LOCKED; GT summary sim time from first in-FOV to first correct lock; no-GT from first candidate to first LOCKED). The Execute panel and Benchmark show A while the PDF/CSV use B. | Static | 02 |
| D-03 | Metrics | Live `track_error_px`, `rmse` are `0.0` (not null) when not LOCKED / streak<10; Reports chart plots missing `track_error_px` as 0; `errorHistory` stores `|| 0`. Missing shown as zero. | Static | 02/03 |
| D-04 | Metrics | FPS requirement uses end-to-end `mean_fps` labelled "Processing Speed"; `processing_fps` is reported separately. Example `SIM_20260928_224832_HYBRID`: `mean_fps 17.9 → pass_fps FAIL`, `processing_fps 20.6`. | Static + saved summary | 02 |
| D-05 | Metrics | Target-loss check `≤ 5.0` vs displayed `< 5%`; tracking-error check uses mean vs legacy text "RMS"; re-acquisition `None → PASS`; `target_loss None → 100`. | Static | 02 (document, don't silently change) |
| D-06 | Metrics | Live `lock_rate` counters (`_gt_lock`) are not reset on `reset`, so they accumulate across consecutive missions in the same mode. | Static (grep: zeroed only at `sim_thread.py:103,180,221`) | 02 |
| D-07 | Metrics | Live `target_loss` (LOST+COASTING ÷ all frames) differs from summary `target_loss_pct` (GT-based, from first correct lock). | Static | 02 |
| D-08 | Persistence | `summary.csv` writes every boolean as `PASS`/`FAIL` (e.g. `scored_with_gt,PASS`). | Saved file | 02 |
| D-09 | Persistence | `VID_<stem>_<MODE>` IDs repeat → re-running a video overwrites its prior CSV/PDF/centroid log; SIM IDs have 1-s resolution. Uploads overwrite `input_videos/<name>`. No session manifest/config persisted. | Static | 02/05 |
| D-10 | Persistence | `stop` exports a snapshot but keeps the session open; later `run` continues it and a later finalisation overwrites the same files with different contents. | Static | 02 |
| D-11 | Time | `duration_sec` and the simulation PDF chart x-axis use wall time while scoring uses sim time; live `dt` is capped at 0.05 s, so sim and wall time diverge whenever the loop is <20 FPS. | Static + live sample | 02/03 |
| D-12 | Performance | `step()` recomputes `_gt_scores()` over the whole session and scans all states for target loss **every frame** (O(n) per frame). Live loop measured at 5.6 FPS vs 60 FPS pipeline capacity at ~1550 s; P1 shows 74 ms/frame at 20k frames and 219 ms at 60k. Strongly supported cause; not proven on the live process. It also depresses `mean_fps` → `pass_fps` for long sessions. | Static + live sample + P1 | 02 (or a scoped perf fix) |
| D-21 | Harness | `trace_hash` excludes confidence and detector output; CV and Hybrid give the same hash on S01. | T3/T4 | 09 |
| D-22 | Performance | AI mode harness loop ≈3 FPS (contended) vs ≈32 FPS for CV/Hybrid. | T5 | 09 |
| D-13 | Detection fairness | AI mode never refreshes `detector.last_gray`; tracker's scene estimator gets `raw=None` (AI from start) or a stale Hybrid/CV frame (after live switch). `shared.candidates` shows the blob detector's stale count in AI mode. Runtime effect unmeasured. | Static | 08/09 (investigate; changing it touches the pipeline) |
| D-14 | UI flow | Builder Speed and Initial Position are not sent to the backend; the Brief shows them anyway. `set_scenario EASY` leaves `cfg.target.initial_position='near_center'` for later missions. | Static | 06 |
| D-15 | Test isolation | `api.js` hard-codes `127.0.0.1:8765` for HTTP and WS; `server/app.py` hard-codes the port and `FRONTEND_DIR='F:/FSOC/frontend/src'`; sessions write to CWD-relative `logs/`. A test instance cannot be isolated (port or output dir) without a change. | Static | 01+ (first phase needing UI verification) |
| D-16 | Benchmark | Browser computes PASS from 1 Hz samples with its own loss definition (LOST only, `< 5 %`) and live acquisition A; no re-acq/FPS criteria. | Static | 03/10 |
| D-17 | Sensor stream | Overlays (candidate circles, crosshair, state text, search path) are burned into the only published camera image; there is no clean sensor frame for recording/comparison. | Static | 08/09 |
| D-18 | Reports | `/api/logs` lists only top-level files; `centroid_log.csv` in session folders is unreachable from the UI; Reports list is file-centred, not session-centred. | Static | 03 |
| D-19 | Video GT | GT CSV coordinates are used as-is after the frame is resized to 640×480 (no scaling); lookup falls back from index `i` to `i+1`; `visible` column ignored. | Static | 05 |
| D-20 | Diagnostics | `/api/diagnostics` model name is a hard-coded string. The reference images' "YOLOv8n", µrad limits, uptime/latency requirements, Python 3.10/torch 2.3 versions and sample sessions do not match the application. | Static + image review | 04 |

## 9. Reference image review (`expected ui_2`, all 8 viewed)

| Image | Content | Conflicts with agreed scope / code (appearance only) |
|---|---|---|
| `home.png` | Top bar (latency, clock, Diagnostics Ctrl+D, Home), Earth/satellite artwork, 4 cards with footer mini-graphics, status strip, Recent Sessions table | "Detector: YOLOv8n" (actual BeaconCNN v2); sample PASS/FAIL rows and "57.3 FPS" are illustrative, not data |
| `before_video.png` | Load-video page: drop zone, video card, GT card, metadata table, 8 frame thumbnails, "scaled to 640×480" note, CV/AI/Hybrid selector, Cancel / Run analysis | Needs a preflight endpoint (none exists) |
| `create mission.png` | Build step with breadcrumbs, motion tiles, speed/initial position, atmosphere, 11 disturbance toggles + per-type slider, detector mode, live preview, difficulty and "estimated performance" | "Estimated FPS/error" would be fabricated unless computed from measurements; "≈40 px/s" differs from Normal = 30 px/s |
| `mission_control.png` | Brief: trajectory preview with time ticks, mission spec, PS requirements PENDING, expected flow | Requirement limits (5 µrad RMS, 10 s acquisition, ≤2 events/5 min, ≥95 % uptime, ≤50 ms) are **not** the app's configured checks (§CONTRACTS 8) |
| `live_mission.png` | Execute: state pill, mode buttons, REC, camera view with reticle, predicted point, error label, minimap, telemetry with 6 metrics, disturbances, 5-segment timeline, actions | Sensor image is a photographic mountain/lake scene — must **not** be reproduced in the sensor feed (decision 1); "DETECTED" state does not exist; µrad values internally inconsistent (2.1 px = 229 µrad vs 1.8 px = 0.42 µrad) |
| `mission_results.png` | PASS banner, certification table, config snapshot, mid-run changes, analysis chart with state bands, replay, detailed metrics, versions footer | Same requirement-limit conflict; CPU/GPU usage not measured; versions shown (Python 3.10.19, torch 2.3.1, OpenCV 4.10.0) differ from actual |
| `comparison view.png` | Three panels CV/AI/Hybrid each with own camera, state, conf, FPS/ms, error, lock %, minimap; combined error-over-time chart; controls incl. "Inject dropout" | Implies live simultaneous run; agreed design is **recorded** comparison (decision 4) labelled as such; no mid-run injection in playback |
| `diagnostc_bar_at_all_screens.png` | Diagnostics drawer: Pipeline stacked bars, stage timing, pipeline/end-to-end FPS, pipeline time sparkline; Model/System/Raw log tabs | Stage names differ (actual 9 measured stages); already largely implemented |

Pixel-perfect reproduction is not promised; the images give layout and styling only.

## 10. Phase dependencies (from the phase prompts and the findings above)

| Phase | Hard dependencies | Baseline facts it relies on |
|---|---|---|
| 01 motion continuity | 00 | D-01, CONTRACTS §10. Six motion types reachable from the builder (Straight, Circular, Figure-8, Random, Spiral, Sinusoidal); Execute exposes five (no Spiral). `Target` is also built by `harness/runner.py` → initial-scene behaviour must stay identical so S01/S03/S05 hashes in §4 remain reproducible (motion *switching* is not exercised by the harness). `reset` must keep creating a new `Target`. Verifiable headlessly; does not need D-15. |
| 02 session data | 00 (01 independent) | D-02…D-12, CONTRACTS §6, §8. Must keep the three acquisition definitions distinguishable, not silently merged. |
| 03 results & PDF | 02 | D-03, D-16, D-18, F1, F2; no PDF text library in venv (§1). |
| 04 home & shell | 02 (recent sessions) | D-20; Compare entry disabled until 10. |
| 05 video preflight | 02 | F6, D-09, D-19. |
| 06 mission flow | 01–05 (stated in prompt) | D-14, F2, D-10. |
| 07 camera lab | 02, 06 lifecycle | F5; no manual pointing API exists; camera moves only via `CameraServo` → `command_world/command_delta_deg`. |
| 08 engineering view | 02 (frame telemetry), 07 routing | D-13, D-17. |
| 09 comparison engine | 02 (requirement evaluator) | F7, F8, D-13, D-21, D-22; harness runner is the existing headless path to reuse. |
| 10 comparison UI/report | 09 real artifacts, 03 report tooling | Recorded-comparison labelling. |
| 11 integration | all | Model hashes §2, test commands §4. |

Cross-cutting: D-15 (hard-coded port/base URL/output dir) blocks isolated UI verification for every UI phase (03–10) while the user's server occupies 8765.

## 11. Unresolved items

1. D-15 blocks isolated UI verification (separate port/output dir) for later phases until the port/base URL and output directory can be configured. Phase 01 can be verified headlessly (harness + unit tests) without it.
2. No PDF inspection library in the venv; phase 03 needs a rendering route (e.g. the PDF skill's tooling) or explicit permission to install.
3. The live mission on 8765 belongs to the user; nothing in phase 00 stopped it. Its eventual session files will be written by the running server as normal.


## Implementation evidence — 29 September 2026

See `handoff/IMPLEMENTED.md` for measured values and the explicit verification limits. Fast suite: `FSOC_SKIP_SLOW=1 venv/Scripts/python.exe -B -m unittest discover -s tests -q`: 52 run, 51 passed, one skipped. Separate slow no-leak behavioural check passed in 76.676s. Browser flow scripts in `scratch/handoff-verification/` successfully exercised live mission, custom builder/edit/motion/pause, lab ownership, video with/without GT, archive selection and comparison playback; no page errors in final runs.

New screenshots: home-1280/1440/1920.png; control-1280/1440/1920.png; lab.png; brief.png; comparison.png; video-prepare-false/true.png; video-result-false/true.png. PDF renders: nogt-final-*.png, sim-final-*.png, comparison-pdf.png; earlier gt-report-*.png shows the initial readable but verbose layout before appendix compaction.

Comparison 8c32335754a54f12b0910a965e3d1131: CV/AI/Hybrid RMSE 4.551/4.482/4.551 px, equal 87.667% correct lock, 10.239% loss and 0.500s recovery under an explicit common dropout. These data do not support a forced Hybrid winner/PASS. Throughput is workload-contended and replay is not realtime certification. The user's backend at 8765 remained untouched.

Latest verification video sessions: VID_source_HYBRID_98730790 (no GT), VID_source_HYBRID_49c9876b (GT), both 90 frames. The stale confidence field was corrected and CSV scores verified; source-video metadata persisted. GT centroid RMSE 0.245366 px. Actual video EOF cleanup opens the exact saved result, stops streams/timer, and archive selection returns matching data.
