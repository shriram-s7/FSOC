# Dashboard, waiting states and optical rendering — 29 September 2026

## Implemented

- Six equal Home cards in a 3 × 2 grid: Quick Demo, Custom Mission, Benchmark, Load Video, Camera Lab and Model Comparison.
- Shared waiting panels with an animated ring, operation explanation and elapsed time. Used for mission start/stop, Lab entry/exit, video inspection/GT validation, results and comparison loading. Unknown operations remain indeterminate; no invented percentages.
- Comparison generation shows measured total frame completion, current mode and a current-mode remaining-time estimate. Five source seconds is the default; observation dropout is explicitly opt-in. Ten seconds means 600 frames per mode, 1,800 total.
- Exact completed comparisons can be reused when scenario, engine source and model hashes match. Force fresh run bypasses reuse. Reused timing values are historical measurements, not a new speed test.
- CV is amber/solid, AI purple/dashed, Hybrid teal/dotted in plots and PDF; panel borders and overlays match. Equal traces still overlap; legend toggles isolate them. No numerical offsets or invented differences.
- Benchmark has queued scenario rows, clear duration explanation, a progress ring, live collection status, cancel, 15-second preview or full 60-second scenarios, and links from finished results. Preview/cancelled results are identified as such. The previously obscured Run button is now accessible below the global toolbar.
- Synthetic Optical space profile is selectable on Home; Classic remains the default fallback. It applies a small point-spread response and restrained halo before detection. It remains 640×480, uses the original weights and preserves uploaded-video pixels. Lab accepts the selected profile and restores prior configuration on exit.
- Profile is saved in configuration and included in new results/PDFs. Overlay font creation is cached (local microbenchmark: 1.04 ms with new font each frame versus 0.008 ms for cached render).

## Important scoring correction

The old accumulator treated any persistent change from initial disturbance settings as an active event for the remainder of the session. This could pause the recovery clock indefinitely and produce misleading 0-second recovery. New scoring pauses only for explicit evaluation events; a changed atmosphere alone no longer pauses it. New session manifests identify `2-explicit-events`. Historical reports are retained, not overwritten.

Read-only audit of the user's saved frames:

| Session suffix | Original outcome | Finding |
|---|---|---|
| c79e8192 | PASS | Mean pointing error 3.402 px; loss 1.062%; mean FPS 37.986. Recovery recalculates from 0 to 0.1195 s (max 0.238 s); still below 1 s, so overall outcome remains PASS. |
| ef20285d | NOT SCORED | Video has no GT. 94.833% tracker-state lock and ~29.98 FPS are measured, but accuracy cannot be concluded. |
| 3fcb72be | INCOMPLETE | 1.570 px mean error, zero loss, ~37.29 FPS. No recovery event occurred; recovery performance was not tested. |
| c66246b5 | FAIL | Loss 5.088% exceeds 5%; mean error 5.801 px passes. Recovery audit 0.1399 s still passes. Failure outcome remains correct. |

These results do not modify weights or impair future sessions. They also do not establish robustness in every environment. The FAIL matters for that scenario and should remain visible.

## Optical experiment: measured, limited evidence

Ran 12 real worker evaluations: two motions × two render profiles × CV/AI/Hybrid. Each uses seed 42, three simulated seconds, 180 frames, mild sensor noise, no deliberate dropout. Results: `scratch/polish-v3/profiles/results.json`; raw mode summaries, telemetry and frames are in each profile folder.

All runs measured 96.111% correct lock over all frames and 0% loss after acquisition. This is a short smoke test, not a held-out accuracy benchmark. No training was performed or warranted solely by these results.

| Motion / mode | Classic pointing RMSE | Optical pointing RMSE | Classic compute FPS | Optical compute FPS |
|---|---:|---:|---:|---:|
| Straight / CV | 2.008 px | 1.954 px | 17.30 | 13.69 |
| Straight / AI | 1.998 px | 2.021 px | 5.35 | 4.77 |
| Straight / Hybrid | 2.008 px | 1.954 px | 17.59 | 12.13 |
| Figure-eight / CV | 4.837 px | 4.826 px | 18.52 | 8.91 |
| Figure-eight / AI | 4.841 px | 4.848 px | 3.54 | 3.91 |
| Figure-eight / Hybrid | 4.837 px | 4.826 px | 12.37 | 6.22 |

Compute FPS includes simulation rendering and processing in unpaced workers, excluding paced playback. Pipeline-only rate is separately saved. Timing runs occurred under variable shared-machine load (including browser tests), so they are observations, not controlled speed comparisons. Optical adds real rendering work; it is **not established to meet 20 FPS end-to-end**. Classic remains recommended for performance demonstrations.

This option is a synthetic optical appearance experiment, **not a high-resolution photorealistic space simulator or a validated physical camera model**. Changing to real camera imagery needs held-out labelled videos across optics, exposure, noise and motion; evaluate current weights first, then fine-tune a separate model only if needed. Keep old data/weights and use separate versioned checkpoints. No real-camera equivalence or 99.9% operational accuracy is claimed.

## Comparison report interpretation

Reviewed the user's 10-second figure-eight comparison `cde09336b50a407c8b34ab4690f5abac`. The 0.5-second common dropout accounts for the gap around the midpoint and the post-reacquisition error transient. Source time is simulated time. The measured loss is 5.059%, narrowly failing 5%; that is expected under this deliberately stressful short run, not evidence of a plotting defect. CV and Hybrid traces overlap because their selected positions/control responses can be equal in this simple scene. Classifier differences need not produce different trajectories.

New PDF colour/dash/tick/explanation changes were generated in a scratch copy and rendered to `scratch/polish-v3/report-review/page-*.png`; original report retained.

## Verification

- Fast suite: `FSOC_SKIP_SLOW=1 venv/Scripts/python.exe -B -m unittest discover -s tests -q` — 54 run, 53 passed, one slow test skipped. Added pixel-identical Classic fallback and nonzero recovery-after-atmosphere-change tests. The earlier slow no-leak test remains documented; it was not repeated in this polish pass.
- `scratch/polish-v3/check_ui.cjs`: six cards, three Home viewport sizes, optical Quick Demo → results, benchmark start/cancel, comparison start/cancel. No page errors on final run.
- `scratch/polish-v3/final_check.cjs`: completed comparison playback and exact cached reuse; complete five-scenario benchmark preview.
- Existing original/v2 model SHA-256 hashes unchanged. No training files modified. Live user server at 8765 was not restarted for these checks.

Restart the normal backend to load Python changes, then refresh the browser. New scripts are versioned independently. Choose Classic for the original image appearance; Optical space is optional. Full long-duration/real-world/photorealistic validation remains outside these short checks.
