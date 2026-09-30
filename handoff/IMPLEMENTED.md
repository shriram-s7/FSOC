# Implementation handover — 29 September 2026

The user authorized the remaining roadmap in this conversation. Phase 00's baseline is preserved; source backups and all new verification outputs are under `scratch/handoff-verification/`. No deployment, dependency installation, training, model replacement, or user-server restart was performed.

## What is implemented

- Motion changes continue from the current position with a short velocity transition and local randomness. Mission time, camera and target identity remain intact. Initial legacy harness motion remains unchanged.
- Session finalisation saves CSV, PDF and an atomic `session.json` with unique IDs, configuration and events. Stop waits for readiness; failed exports can retry the same session. Empty setup sessions produce no report.
- Results and archive resolve one session and display recorded measurements, charts, configuration, events and matching exports. PASS, FAIL, INCOMPLETE and NOT SCORED are data-driven outcomes. Missing recovery evidence is INCOMPLETE, not an assumed pass.
- Home has the mission choices, highlighted Camera Lab, comparison entry and real recent sessions. The space styling is decorative CSS outside the sensor image.
- Video preflight inspects metadata/thumbnails before analysis. Optional GT explicitly selects original/processing coordinates and zero/one-based frame numbering. All GT is canonicalized once to zero-based 640×480. Video EOF opens its saved results; no-GT accuracy is unavailable.
- Builder settings affect runtime motion/speed/position/environment/mode. Brief previews use the same motion definitions without mutating the live simulation. Edit/back preserves selections. Stop visibly shows saving progress.
- Camera Lab uses a stationary world beacon, held arrow/WASD controls, fine/coarse angular rates, home, a 5-degree manual envelope and focus-loss watchdog. Manual and assist leave pointing to the user; automatic mode owns the servo. Assist displays measured tracking overlays. Leaving restores prior configuration.
- Basic engineering overlays show actual candidate scores, tracked position, error vector and next-step prediction. Clean images and telemetry share a frame packet. World FOV dimensions use configuration. The later requested Tracking Dynamics instrument remains **held**.
- Comparison generates independent CV, AI and Hybrid recordings sequentially, then synchronizes their three views and telemetry on source time. Straight, figure-eight and sinusoidal scenarios share a fixed-seed schedule and optional explicit observation dropout. Replay/seek, saved comparisons, cancellation, measured error plots, JSON and PDF are connected.
- Benchmark table now uses finalized backend measurements and requirement outcomes instead of scoring one-second UI samples. AI mode refreshes the raw frame used by scene estimation; thresholds, model weights and controller gains are unchanged.

## Main files

Backend: `simulation/motion.py`, `simulation/target.py`, `simulation/camera_lab.py`, `ui/sim_thread.py`, `input/video_source.py`, `server/app.py`, `server/sessions.py`, `server/video_preflight.py`, `server/mission_config.py`, `server/comparison.py`, `comparison/scenario.py`, `comparison/worker.py`.

Results: `evaluation/metrics.py`, `evaluation/logger.py`, `evaluation/requirements.py`, `evaluation/session_record.py`, `evaluation/report_generator.py`, `evaluation/report_layout.py`, `evaluation/comparison_report.py`.

Frontend: `frontend/src/index.html`; `frontend/src/static/js/{app,api,pages,camera,world-view,results,shell,video-preflight,mission-flow,camera-lab,engineering-view,comparison}.js`; scoped styles in `frontend/src/static/css/{results,shell,camera-lab,comparison}.css`.

Tests added: `tests/test_motion_continuity.py`, `tests/test_session_record.py`, `tests/test_camera_lab.py`, `tests/test_comparison_contract.py`, `tests/test_finalisation.py`.

## Verification and observed results

- `venv/Scripts/python.exe -B -m unittest discover -s tests -q`, with `FSOC_SKIP_SLOW=1`: **52 tests successful, one slow test skipped**.
- The skipped behavioural test was separately executed with `python -B -m unittest -v tests.test_no_leak.TestBehaviouralNoLeak`: **passed in 76.676 seconds**. It checks identical tracking traces when truth-side disturbance settings are falsified.
- Playwright/Edge on isolated port 8766: Quick Demo → Stop → Results; Camera Lab manual/assist/auto → exit; video upload with and without GT → EOF → Results; custom builder → brief → edit → execute → motion change → pause/resume → stop → archive selection; comparison load/seek/play. Successful final flow scripts reported no browser page errors. Pausing can finish the currently executing frame before becoming stationary.
- Home and live-control screenshots were captured at 1280×720, 1440×900 and 1920×1080. Other workflow screenshots were captured at 1440×900. See `scratch/handoff-verification/{home-*,control-*,lab,brief,comparison,video-*}.png`.
- Representative simulation, GT-video, no-GT-video and comparison PDFs were generated and rendered with Poppler. Tables wrap, status explanations fit and session reports have a useful chart/configuration second page. Full exhaustive PDF and viewport permutations were not run.
- Synthetic 90-frame video: without GT, accuracy remained NOT SCORED. With GT, centroid RMSE **0.245 px**, mean centroid error **0.207 px**, loss **0%**, correct lock **95.556%**. Overall INCOMPLETE because no recovery event occurred. This is a fixture test, not a real-camera validation.
- Actual 5-second figure-eight comparison, seed 42, common 0.5-second dropout, 300 frames per mode: CV/AI/Hybrid pointing RMSE **4.551 / 4.482 / 4.551 px**; correct lock **87.667%** for each; loss **10.239%** for each; reacquisition **0.500 s** for each. Pipeline rates **28.946 / 4.697 / 49.730 FPS** are observations under shared-machine load, not calibrated speed rankings. All failed this scenario's loss check. Realtime throughput is NOT TESTED for unpaced generation. No overall Hybrid PASS or universal superiority is claimed.
- The comparison was saved at `scratch/handoff-verification/integration/logs/comparisons/8c32335754a54f12b0910a965e3d1131/`. An earlier job was correctly cancelled when a live mission began.
- Model SHA-256 values match phase00: original `0C0C5B5952EB61FD68E75855B53D2594C2F0DEB13E023F022E4AE661A9B97EFB`; v2 `21B4A687336FBF3E9D10D0E785C5D25F47728C6A0EDC0D6546C709E709EFC8A6`. No model/dataset/sensor-renderer appearance edits.

## Limits and deliberately held work

- Full Tracking Dynamics, commanded-versus-actual FOV instruments, additional world search-path instrumentation and a fixed/follow viewport switch are deferred with the user's held visualization proposal. The basic existing tracking overlays are available.
- Camera Lab is a 2D angular viewport approximation, not a physically calibrated 3D optical bench.
- No photorealistic sensor stars/beacon or retraining. UI background styling does not alter model inputs.
- Comparison is recorded playback, not three concurrent realtime pipelines. All modes use their actual implemented pipelines; AI/Hybrid share the existing v2 CNN. Preview recordings are 12 Hz, telemetry is 60 source steps/s. Generation takes longer than source duration, especially AI.
- Storage is bounded per upload (512 MB), comparison preview (80 MB/mode), and total prepared/comparison budgets. Existing data is never automatically deleted; reaching a budget requires archiving unneeded files. There is no archive-management UI for storage cleanup yet.
- Live acquisition/target-loss estimates retain their original definitions, while final GT results use the authoritative scoring reducer. Live recovery summaries are cached to avoid whole-history rescoring every frame. Final results are exact reductions. Use final results for requirement conclusions.
- Official PS specification is not present. Thresholds remain the configured application checks. The full harness matrix, every benchmark preset, forced network reconnect, every viewport/page permutation and long-duration soak were not rerun. Export failure/retry and idempotence are covered with unit tests.

## Walkthrough

Restart the usual application/backend after ending any current mission to load the Python changes. Quick Demo or Custom Mission → Stop → Results → Export PDF. Home → Load Video → choose file → optionally attach GT → Run Analysis. Home → Camera Lab → hold arrows/WASD; use Track assist or Auto acquire; Finish lab to restore configuration. Home → Compare CV / AI / Hybrid → select scenario → Generate → replay/seek/export once complete. View all opens the session archive.

No additional phase prompt is needed to use the implemented flow. Review the held visualization separately if you decide to resume it.
