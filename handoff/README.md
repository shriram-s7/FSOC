# FSOC implementation handoff

Prepared 2026-09-28 from read-only repository analysis. No application changes are included in this handoff.

## Decisions

1. Keep the detector input, 640x480 simulation renderer, beacon shape, model weights, training datasets, and training procedures unchanged. No realistic sensor profile or realistic generated videos in this project scope. Improve space artwork only in the UI shell, cards, and surrounding world-view presentation. Never composite decorative imagery into the camera sensor image or present an embellished image as the measured feed.
2. Preserve the existing Electron/plain-JavaScript/FastAPI/Python architecture. No React migration, new frontend build system, model replacement, or blanket refactor.
3. Comparison means three synchronized CV / AI / Hybrid panels, each showing actual tracking and its own simulated camera response. Use identical target trajectories and exogenous disturbance schedules. Three motion presets are Straight, Figure-8, and Sinusoidal, selected one at a time. A full sweep is three motions times three modes.
4. First comparison version: run the modes sequentially in isolated worker processes, save actual frames/telemetry, then play the three recordings together on a common simulation clock. Label the screen 'Recorded comparison' and show measured processing performance separately from playback FPS. This is a deliberate reliability choice, not a claim of simultaneous live inference. No interactive mid-run changes in recorded playback; new settings generate a new comparison.
5. Comparison display prioritizes tracking, pointing error, confidence, and recovery. Do not clutter it with PS pass/fail badges. The comparison report still includes measured requirements and outcomes for all modes, including Hybrid. Target a useful Hybrid-passing demonstration, but never force PASS, suppress failures, alter thresholds, or weaken competing modes. A selected demonstration proves only that scenario; it is not broad superiority evidence.
6. Camera Lab is a prominent feature: stationary world beacon, manual pan/tilt within limits, track-assist, and auto-acquire. Existing simulated 2D angular approximation remains explicit; no claim of full 3D optics.
7. Motion changes continue from the current position without resetting the target, camera, tracker, mission time, or disturbances.
8. Results are session-centred and persisted; PDFs and UI share one authoritative summary and requirement evaluation. Reference images supply appearance, not model names, numerical results, requirement limits, or certification authority.

## How to use

Use the coding model you intend to use; these prompts do not depend on a particular model name. No model was specified by the user, and this pack does not claim a particular lower-cost model will pass every acceptance check.

For a fresh chat, paste the starter below. Execute only one phase per turn. Use a fresh chat for a large phase if context becomes cluttered. The files carry the context forward.

> Work in F:\FSOC. Read F:\FSOC\handoff\MASTER_PROMPT.md and F:\FSOC\handoff\README.md. Then read F:\FSOC\handoff\phases\00-baseline.md and execute only that phase. Do not implement later phases. Implement and verify the authorized scope; do not stop after a plan. Preserve all unrelated work. Update F:\FSOC\handoff\PROGRESS.md with exact evidence and remaining issues.

For later phases, replace `00-baseline.md` with the next filename below. If a required acceptance check fails, repair that phase before proceeding. A blocked check must remain visibly blocked; do not declare it passed.

| Order | Prompt file | Outcome |
|---|---|---|
| 00 | phases/00-baseline.md | Evidence, contracts, working baseline |
| 01 | phases/01-motion-continuity.md | No jump when changing motion |
| 02 | phases/02-session-data.md | Reliable session finalisation and shared results data |
| 03 | phases/03-results-and-pdf.md | Populated results, session archive, readable PDFs |
| 04 | phases/04-home-and-shell.md | Expected home UI and prominent Camera Lab entry |
| 05 | phases/05-video-preflight.md | Inspect video before analysis |
| 06 | phases/06-mission-flow.md | Build, Brief, Execute, Finalise, Results |
| 07 | phases/07-camera-lab.md | Stationary beacon and real manual camera control |
| 08 | phases/08-engineering-view.md | Frame-aligned tracking/control explanation |
| 09 | phases/09-comparison-engine.md | Isolated reproducible comparison recordings |
| 10 | phases/10-comparison-ui-report.md | Three-panel comparison and honest report |
| 11 | phases/11-integration-review.md | End-to-end verification and remaining limitations |

## Existing files to preserve and extend

All paths below are relative to F:\FSOC. These are observed existing paths, not proposed replacements.

```text
expected ui_2/
  home.png
  before_video.png
  create mission.png
  mission_control.png
  live_mission.png
  mission_results.png
  comparison view.png
  diagnostc_bar_at_all_screens.png
frontend/
  electron.js
  package.json
  src/index.html
  src/static/css/{tokens,main,pages,repair}.css
  src/static/js/{api,app,pages,camera,world-view,diagnostics}.js
  src/static/js/chart.umd.min.js
server/app.py
simulation/{motion,target,camera,world,geometry3d}.py
ui/sim_thread.py
control/{camera_servo,pid_controller}.py
tracking/{tracker,imm_tracker,kalman_tracker,temporal_fusion,stabiliser,scene_estimator,search_pattern}.py
detection/{detector,classifier,ai_scanner,cv_scorer,generate_training_data,train_classifier}.py
input/{frame_source,simulation_source,video_source}.py
evaluation/{metrics,gt_metrics,logger,report_generator,centroid_log}.py
harness/{runner,scenarios,_one,video}.py
harness/scenarios.yaml
tools/make_test_video.py
tests/{test_gt_metrics,test_no_leak,test_scene_reference}.py
config/{default.yaml,loader.py}
models/beacon_classifier_v2.pt
logs/
```

## Proposed additions, owned by phases

Do not pre-create empty application modules. Add each file only when its phase needs it. If the implementation already has an equivalent, reuse it and document the actual path.

```text
handoff/
  README.md                         # this handoff
  MASTER_PROMPT.md                   # binding project scope for these phases
  PROGRESS.md                       # append verified phase outcomes
  CONTRACTS.md                      # created in phase 00, updated deliberately
  EVIDENCE.md                       # baseline, verification and limitations
  phases/*.md                       # exact phase prompts
server/
  sessions.py                       # session lookup/normalisation, phase 02
  video_preflight.py                # prepared uploads/metadata, phase 05
  comparison.py                     # job management, phase 09
evaluation/
  session_record.py                 # versioned persisted record, phase 02
  requirements.py                   # shared requirement evaluator, phase 02
  comparison_report.py              # phase 10
simulation/
  camera_lab.py                     # lab state/control, phase 07
frontend/src/static/js/
  results.js                        # phase 03
  video-preflight.js                # phase 05
  camera-lab.js                     # phase 07
  engineering-view.js               # phase 08
  comparison.js                     # phase 10
frontend/src/static/css/
  results.css                       # phase 03
  shell.css                         # phase 04
  video-preflight.css               # phase 05
  camera-lab.css                    # phase 07
  engineering-view.css              # phase 08
  comparison.css                    # phase 10
frontend/src/static/img/
  space-shell.*                     # optional decorative UI asset, phase 04
comparison/
  __init__.py
  scenario.py                       # immutable common schedule, phase 09
  worker.py                         # isolated runner, phase 09
  recorder.py                       # artifacts/manifest, phase 09
  presets.json                      # explicit demonstration presets, phase 09
tests/
  test_motion_continuity.py
  test_session_record.py
  test_requirements.py
  test_video_preflight.py
  test_camera_lab.py
  test_frame_telemetry.py
  test_comparison.py
scratch/handoff-verification/        # only new test artifacts, never old logs
logs/<session-id>/session.json       # new session manifest alongside existing exports
logs/comparisons/<comparison-id>/
  manifest.json
  scenario.json
  cv/{telemetry.jsonl,frames/...}
  ai/{telemetry.jsonl,frames/...}
  hybrid/{telemetry.jsonl,frames/...}
  comparison_report.pdf
```

The comparison recorder may use video files instead of frame directories if a browser-compatible encoder is actually available and verified. Do not add an unverified FFmpeg dependency. Store bounded preview recordings, not unlimited full-session image sequences. The manifest must identify the actual storage format.

## What 'Hybrid is better' may mean

Report separate measured dimensions: pointing RMSE, centroid RMSE, correct-lock percentage, recovery, and compute latency. Hybrid can be better on one and worse on another. The default recommendation may explain its design, but 'best on this run' is computed from a declared rule. A PASS on one scenario does not establish superiority over AI/CV or general PS certification.

If Hybrid does not meet the required values, retain that outcome and identify whether the cause is the scenario, runtime performance, an implementation bug, or an algorithm limitation. Fix demonstrable bugs within scope. Detector/controller tuning and retraining require a separate scoped task; they are not hidden work in a UI phase.
