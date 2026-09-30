# Phase 01 — Continuous motion switching

Read the common prompt and contracts. Modify only motion switching and directly related tests/wiring.

Inspect simulation/motion.py, simulation/target.py, server/app.py (_apply_motion, _apply_speed), and ui/sim_thread.py cmd_motion_change handling. Current code recreates Target and Distractors and periodic equations refer to world centre.

Implement a Target operation that changes its motion model at the current world position without replacing target identity, resetting target/session time, moving the camera, resetting tracking, or recreating unrelated disturbances/decoys. Give the new segment a local elapsed time and origin. For periodic patterns use p(t)=p_switch+q(t_local)-q(0), or an equivalent explicitly verified formulation. Circular and sinusoidal q(0) are not zero. Preserve heading where practical; bound transition velocity/acceleration with a brief configurable blend rather than a position jump. Make speed control semantics consistent for periodic motion; do not merely set an unused straight-line speed field.

Specify boundary behaviour. Avoid clamping a large curve into a flat line. Fit allowable amplitude or use an explicitly documented boundary response. Do not recenter the target as a hidden correction. Avoid resetting global random generators on every switch; random motion must use local deterministic state.

Create tests/test_motion_continuity.py. Check each ordered pair of supported patterns at multiple non-centre positions, paused and running switches, circular/sinusoidal first-step offsets, edges, repeated switches, and independent random state. Assert no immediate position discontinuity, finite bounded next-step movement, and preserved camera/tracker/session state. Do not require velocity continuity where an explicit bounded transition is documented.

Acceptance: demonstrate Straight→Figure-8→Sinusoidal→Circular from the current position, without centre jumps or unrelated resets. Verify reset still intentionally starts a new initial scene. Record exact boundaries/transition semantics.
