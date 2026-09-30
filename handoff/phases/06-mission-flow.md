# Phase 06 — Mission builder, brief, live control and completion

Use expected ui_2/create mission.png, mission_control.png, live_mission.png, mission_results.png. Extend existing index.html/pages.js/app.js and scoped styling. Depend on phases 01-05.

Implement Build→Brief→Execute→Finalising→Results with Back/Edit preserving configuration. Builder controls must update the actual runtime settings: motion, speed, initial position, atmosphere, disturbances and mode. Do not display a selected option that the backend ignores. Preview trajectories using the same motion definitions in an isolated preview path; preview must not mutate the active simulation or reset global RNG/config. Clearly distinguish a planned path from observed live data.

Brief shows the effective config and confirmed requirement limits. Remove fabricated expected-FPS/error estimates unless a measured calibration source exists; a plain 'measured during run' is acceptable. Runtime state names must match the actual state machine; a conceptual DETECT stage must not be presented as a measured state duration if it is not one.

Live screen: functional camera/world switch, telemetry/environment/events tabs, accurate source/mode, state timeline, pause/stop/screenshot/diagnostics and elapsed time. Keep the actual camera feed unchanged. Log changes durably into the session record. Distinguish user duration from wall-clock time and pauses. Stop waits for phase 02 readiness and opens the exact finished session; retry export failures without duplicating the session.

Acceptance: test Quick Demo, custom mission with edit/back, mid-run motion change, pause/resume, manual stop, video return to simulation, repeated start/stop, and navigation cleanup. No hardcoded result or fake recording indicator. Inspect reference fidelity at the three target sizes. No introduced API/config drift.
