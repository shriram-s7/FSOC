# Phase 10 — Three-panel comparison and report

Use expected ui_2/comparison view.png and real artifacts from phase 09. Add comparison.js/css, connect index.html/pages/app/api, and add evaluation/comparison_report.py using the existing PDF tooling/shared result definitions.

Build three equal panels labelled CV, AI, Hybrid, each with its own actual camera recording, tracker overlay, measured state, confidence, pointing error, compute timing and lock/coverage value. Add one shared time axis/error chart with three distinct lines, legend and consistent units; missing measurements are gaps. Display 'Recorded comparison' visibly. Playback rate/FPS is not measured processing FPS. Match panels by timestamps, never independent free-running timers. Pause/play/seek/speed controls affect all panels together. Mark dropped preview frames explicitly when relevant; do not alter metric data to fit playback.

No PS pass/fail badges are needed on this screen. Keep motion selection Straight/Figure-8/Sinusoidal, generated-run history, Generate comparison and Export report clear. During generation show actual progress. Environment/dropout changes configure a NEW run; do not pretend playback controls inject live disturbances. Disable unavailable controls with explanation. Add comparison entry to Home/custom mission without hijacking existing single-mission mode.

The report includes scenario/configuration/seed/model identity, method ('isolated sequential execution, synchronized playback'), units and error definitions, per-mode metrics/coverage, common-axis error charts, configured PS requirement outcomes for ALL modes, and a conditional narrative. Hybrid PASS is shown only if measured results satisfy applicable checks. Do not force a winner. Summarise tradeoffs, e.g. lower error but higher compute cost, when observed. If actual data supports Hybrid being best on a declared metric in this scenario, state precisely that. If not, state actual results and list evidence needed for a stronger claim. Never substitute a different run's passing values.

Use actual generated data for production. Test fixtures may have deliberate PASS/FAIL cases solely to verify formatting/evaluation, clearly confined to tests. Do not show fixture numbers to users as experiment results. For unmeasured realtime requirements, use NOT TESTED with reason rather than claiming PS clearance.

Verify exported JSON/CSV, on-screen values and PDF agree, including zeros, no-lock mode, partial failed job, and ties. Render the PDF using the PDF skill. Inspect the UI at 1280x720, 1440x900, 1920x1080; permit readable vertical scrolling rather than clipping three panels. Verify seek synchronisation and reload of saved comparisons.

Acceptance: three genuine moving views and error lines communicate behaviour clearly; report is reproducible, readable and truthful; no requirement to manufacture Hybrid PASS or a preordained ranking.
