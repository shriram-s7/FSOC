# Phase 08 — Explain the live tracking/control loop

Inspect app.js camera HUD, world-view.js, camera.js, server frame/state streams, sim_thread.py, and existing tracker/servo state. Add engineering-view.js/css and read-only telemetry wiring. Keep algorithms and sensor pixels unchanged.

Add Engineering View toggle for camera/world with minimal default presentation. Camera overlays: selected measured centroid, actual predicted centroid with its true horizon/units, image centre, pointing-error vector, optional covariance/uncertainty only if available, and candidate information. World overlays: beacon trail, camera pointing trail, commanded pointing, FOV, search path, and fixed-world/follow viewport toggle. Use actual configured width/height rather than hardcoded FOV rectangle sizes. Scale canvases for device pixel ratio without scaling sensor metrics.

Provide an optional small Measure→Estimate→Command→Response strip with real values and units. Ground truth is optional, visibly labelled 'Simulation truth — evaluation only'. Do not expose it to tracker/control inputs. Do not call a scalar radius a covariance ellipse or show a fabricated prediction horizon. Null data hides the overlay with an availability explanation.

Make frame and telemetry alignment explicit. Attach frame ID and simulation timestamp plus relevant overlays captured from the same pipeline stage/frame. Preserve backward compatibility or update all stream consumers together. Bound queues and drop stale frames/metadata rather than displaying mismatched positions. Respect coordinate transformations between raw/stabilised/world views.

If exposing a brief dropout demonstration, use an explicit lab/demo input that suppresses detector observations and is recorded as an event; do not reset the tracker or move the beacon to fake recovery. The existing prediction/recovery mechanism supplies the response. Restrict demo perturbation controls from silently changing ordinary video analysis.

Test alignment, stale/missing metadata, reconnects, resize, truth-overlay isolation, and no additional image mutation in tests/test_frame_telemetry.py. Check render overhead and remove decorative work if it degrades the main loop.

Acceptance: the user can distinguish observation, prediction, command and physical simulated response, including loss/recovery, from real data. Engineering mode off retains a clean feed and existing behaviour.
