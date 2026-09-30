# Phase 03 — Results page, archive, and PDF

Use phase 02 session endpoints. Inspect expected ui_2/mission_results.png, current reports screenshot if available, index.html reports section, app.js reports methods and report_generator.py. New UI files: results.js and results.css; load and wire them correctly.

Create a Results page for one session and a Reports archive grouped by session. Selecting a PDF, summary CSV, frame CSV, or archive row must resolve the same session. Populate metrics, requirement table, configuration, event history, and charts from saved data. Never show sample values while loading. Clear stale content on selection; show loading, no-data and failure states. Handle long session names without overflow. Export PDF and data must resolve the selected session, and copying a localhost URL must not be described as public sharing.

Use a large PASS/FAIL/NOT SCORED/INCOMPLETE banner as appropriate. The reference is visual only. Show pointing error separately from centroid-vs-GT error, correct lock versus tracker-state lock, and pipeline versus overall throughput. Use correct denominators and units. Charts must preserve gaps/unavailable values and mark lock/loss intervals; do not connect missing detections as zero error. Do not double-label one number as different metrics.

Repair PDF layout using ReportLab: full-width outcome banner; wrapped table cells; adequate column widths; long session IDs/links wrap; no-GT explanation outside the narrow result column; charts chosen for available measurements; no unconditional mostly-empty second page. Include configuration and key results from session.json. Sim reports retain their meaningful error chart; unscored video may show confidence/states/FPS instead. Include page numbers and compact provenance. Old reports remain untouched; generate new verification outputs elsewhere.

Use the PDF skill to render and visually inspect representative simulation PASS/FAIL, no-GT video, GT video, empty/short session, and long-name reports. Compare displayed values with JSON/CSV. Verify zero errors and zero losses display as zero. If replay is unavailable, explain that it was not recorded and do not render a fake playable control.

Acceptance: archive selection never creates an unexplained blank results panel; selected-session values match exports; PDFs have no clipping or crushed status cells at normal reading scale; all actions are functional or explicitly unavailable.
