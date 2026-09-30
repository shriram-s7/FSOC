# Phase 02 — Session records and finalisation

Read common instructions and prior phase results. Build reliable persisted session data without redesigning screens yet.

Inspect evaluation/metrics.py, gt_metrics.py, logger.py, report_generator.py; ui/sim_thread.py session creation/export/finish; server/app.py stop/state/log endpoints. Reuse existing metric calculations. New files may be evaluation/session_record.py, evaluation/requirements.py and server/sessions.py.

Define versioned session.json: session ID, source, completion status/reason, timestamps, simulation and wall durations, initial configuration, timestamped mid-run changes, detector/model metadata, metrics with units/availability, requirement results, and artifact links. Preserve the existing CSV/PDF paths for compatibility. Store under logs/<session-id>/session.json and expose a session list/detail endpoint. Safely adapt older flat PDF/summary/frames triplets without rewriting them.

Centralise requirement presentation/evaluation around existing confirmed definitions. Preserve thresholds and metric meanings. Represent each result as PASS/FAIL/NOT_TESTED/NOT_SCORED with reason, measured value, unit, limit and sample coverage. A missing measurement is not a successful test. Explicitly document overall-result treatment of conditions such as no reacquisition event; do not silently turn N/A into PASS. Keep no-GT video unscored for accuracy.

Finalisation must happen at a safe simulation-thread frame boundary: pause/stop acknowledged, take one immutable snapshot, write artifacts, atomically publish readiness, and return the exact finished session ID. Repeated stop/finalise requests must be idempotent. Expose finalising/ready/error; do not point a current run at an older PDF. Distinguish snapshot export from ending a mission. Handle video EOF through the same finalisation contract. Heavy export work must not hold the live shared-state lock unnecessarily.

Test in tests/test_session_record.py and test_requirements.py: idempotence, failure during export, no-GT sessions, zero-valued metrics, legacy data, correct artifact/session linkage, and a stop racing with a frame. Preserve the existing single-run harness scoring unless a separately documented inconsistency is corrected with a test.

Acceptance: a finished run has one complete, internally consistent record; a failed export reports an error and allows retry; no stale report is presented as current. UI and PDF can consume the exact same result object.
