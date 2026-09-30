# Phase 05 — Video preparation before analysis

Use expected ui_2/before_video.png. Inspect app.js setupSplash/loadVideo/startMission, api.js, server/app.py load_video, and input/video_source.py. Add video-preflight.js/css and server/video_preflight.py if appropriate.

Separate uploading/preparing a video from starting tracking. Build drag/drop and browse, selected file card, optional separately attachable GT CSV, metadata, representative thumbnails, CV/AI/Hybrid choice, Cancel and Run Analysis. Show native width/height, source FPS, duration, frame count, file size and codec only when actually measured. Render upload/decode/CSV errors inline. A cancel must not interrupt or replace an unrelated active session.

Introduce prepare/inspect/start semantics with an opaque prepared-upload ID. Reuse the prepared file rather than uploading twice. Do not leave unbounded temporary uploads or traversal-accessible files. Preserve existing load_video compatibility where needed; never silently start on prepare. Handle duplicate filenames without overwriting prior user files or silently attaching stale GT.

Keep the current processing resolution and transformation unless a real bug requires correction. Document the exact transform, native and processing coordinates, aspect ratio policy, and GT coordinate expectation. Do not guess the CSV coordinate system. Show the supported convention to the user; if native coordinates are supported, transform them exactly once. Preserve no-GT analysis as a valid mode. Do not alter source video pixels for realism.

Test metadata, unsupported/corrupt video, missing/invalid/empty GT, frame-index conventions, non-4:3 source, repeated upload/start/cancel, EOF finalisation, and selected mode routing in tests/test_video_preflight.py. Use new fixtures in scratch, not edits to existing videos.

Acceptance: file selection stops at preflight; Run starts the selected video/mode/GT; metadata and thumbnails belong to that file; EOF reaches its own Results page after successful finalisation.
