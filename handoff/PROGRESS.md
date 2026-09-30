# Implementation progress

No implementation phases have been executed. This file was created as part of the handoff documentation only.

Initial analysis inspected the expected ui_2 images, frontend flow, simulation pipeline, metrics/report code, saved summaries, and read-only live state. It was not a complete runtime regression test.

---

## Phase 00 — Baseline and contracts

**Status: complete** (2026-09-28 23:27 – 2026-09-29 00:10 IST). Analysis and documentation only.

### Files changed
- Created `handoff/CONTRACTS.md` — architecture, endpoints, command semantics, WS formats, `/api/state` keys and units, page IDs, session IDs/files, summary keys, detector modes, metric definitions (three acquisition definitions, pointing vs centroid error, lock-% denominators, target loss, re-acquisition), requirement checks and provenance, coordinates, time bases, motion model contract.
- Created `handoff/EVIDENCE.md` — environment/versions, model hashes, live process/port observations, checks run with results, verification of the 8 earlier findings, defects D-01…D-22, reference image review, phase dependencies, unresolved items.
- Appended this section to `handoff/PROGRESS.md`.
- New artifacts only under `scratch/handoff-verification/00-baseline/` (`unittest_fast.log`, `slow_and_harness.log`, `probe_P1.log`, `probe_baseline.py`, `harness/…`).
- No application, config, model, data, log or reference-image file was modified (verified with an mtime scan after the runs; model SHA-256 re-checked unchanged). Tests ran with `-B`/`PYTHONDONTWRITEBYTECODE=1`.

### Checks run (exact)
From `F:\FSOC`, `venv\Scripts\python.exe -B`, `SDL_VIDEODRIVER=dummy`:
1. `python -m unittest -v tests.test_gt_metrics tests.test_scene_reference tests.test_no_leak` with `FSOC_SKIP_SLOW=1` → **38 tests OK, 1 skipped** (slow behavioural test).
2. `python -m unittest -v tests.test_no_leak.TestBehaviouralNoLeak` → **1 test OK** (108.9 s).
3. `python -m harness --scenarios S01,S03,S05 --seed-list 1 --duration 30 --workers 1 --out scratch/handoff-verification/00-baseline/harness` → exit 0; S01 hash **`3e748074bc5f3943` = prior anchor**; S03 `d823750315eb30db`; S05 `770395fa83a6558e`.
4. Same with `--scenarios S01 --mode cv` → exit 0, hash `3e748074bc5f3943` (mode verified applied; the hash excludes confidence).
5. Same with `--scenarios S01 --mode ai` → exit 0, hash `275b2230758d57b6`, 689 s wall (≈3 FPS, contended).
6. `probe_baseline.py` (read-only) → motion-switch jump 600–835 px; per-frame live rescoring 74 ms at 20k frames, 219 ms at 60k frames.
7. Read-only `GET /api/state`, `/api/diagnostics`, `/api/perf` on the live server.

No pre-existing test failures. Not run: full harness baseline (S01–S15 × 5 seeds × 60 s), video harness, PDF generation, browser/UI screenshots.

### Earlier findings
All eight confirmed (PDF selection clears metrics; Stop opens generic Reports; motion change constructs new Target (+ new distractors, global RNG reseed); periodic motion centred on world centre; Camera Lab = same simulation, no manual control; video selection starts analysis immediately; no live comparison (only offline `logs/comparison` harness CSV/PNG); AI and Hybrid share the v2 classifier instance). Additional discrepancies recorded as D-01…D-22 in EVIDENCE.md §8, notably:
- live `acq_time` (wall clock, first candidate → any LOCKED) ≠ summary acquisition (sim time, first in-FOV → first correct lock);
- FPS requirement uses end-to-end `mean_fps`, labelled "Processing Speed";
- live lock-rate counters not reset by `reset`;
- per-frame whole-session rescoring degrades the live loop (user's live session at 5.6 → 4.45 FPS);
- AI mode never refreshes `detector.last_gray` (scene estimator gets None/stale raw frame);
- `api.js` hard-codes port 8765.

### Contract / compatibility decisions
None changed. CONTRACTS.md documents current behaviour only; requirement thresholds are recorded as configured PS checks (no authoritative spec document in the repo). The reference images' requirement limits and model name are appearance-only.

### Known limitations of this phase
- No new screenshots: the only UI server (8765) hosts the user's active mission (`SIM_20260928_225108_HYBRID`, running throughout; not paused/stopped), and the frontend cannot target another port (D-15). Prior-session captures in `scratch/ui/A_allpages` were referenced, not re-verified; no 1920×1080 capture exists.
- Harness timings/FPS were measured while the live server was running; hashes are deterministic, performance numbers are not baselines.
- No git: local modifications identified by mtime only (EVIDENCE.md §6).

### Next phase
`handoff/phases/01-motion-continuity.md` — **ready**. It can be implemented and verified headlessly (unit tests + harness hashes in EVIDENCE.md §4 as regression anchors). Unresolved dependencies for later phases: D-15 (configurable port/base URL/output dir) before any isolated UI verification (phases 03–10); a PDF rendering route for phase 03 (no PDF library in venv); uncontended AI throughput measurement for phase 09.


## Implementation outcome — 29 September 2026

The user's later instruction authorized execution of the remaining flow in one task, superseding the one-phase-at-a-time handoff rule. See `handoff/IMPLEMENTED.md` for the full file map, walkthrough, evidence and limitations.

| Phase | Status | Outcome |
|---|---|---|
| 01 Motion | Complete | Anchored continuous switches, velocity transition, bounds/local RNG tests |
| 02 Session data | Complete | Unique IDs, atomic manifest, finalise readiness/retry and legacy archive support |
| 03 Results/PDF | Complete for implemented flow | Populated selected-session results and matching readable PDFs; exhaustive PDF fixture matrix not run |
| 04 Home | Complete | Mission cards, Camera Lab feature, real recent sessions, decorative CSS space shell |
| 05 Video | Complete for implemented flow | Validated prepare/GT/start; EOF results; aggregate storage cap; cleanup remains manual |
| 06 Mission flow | Complete | Effective builder/brief/execute, stop-to-results, events, real benchmark outcomes |
| 07 Camera Lab | Complete | Stationary beacon, manual/assist/auto, bounds/watchdog, config restoration |
| 08 Engineering view | Partial / advanced work held | Frame-aligned basic overlays available; advanced world instrumentation and Tracking Dynamics held |
| 09 Comparison engine | Complete | Independent sequential workers, identical scenario schedule, bounded previews, cancellation |
| 10 Comparison UI/report | Complete | Three synchronized recorded views, error chart, seek/history/export, honest outcomes |
| 11 Integration | Completed scoped review | Principal flows exercised; remaining verification limits explicitly listed in IMPLEMENTED.md |

Verification: 52 fast tests run (51 passed, one skipped); skipped slow behavioural test separately passed in 76.676s. Browser scripts `check_ui.cjs`, `flows.cjs`, `final_flows.cjs` exercised the isolated 8766 backend; final successful runs emitted no page errors. Home/control inspected at three target resolutions; representative PDFs rendered. Export failure/retry and repeated Stop tested. Original/v2 model hashes unchanged. Final video confidence correction verified in the saved CSV (actual fixture scores 1.0); GT/no-GT outputs remain consistent with their requirements.

All verification files and source backup are under `scratch/handoff-verification/`; original logs, videos, references and weights were preserved. No Git repository exists here. The user's backend on 8765 was not interrupted. Restart the normal app after ending its active mission to load changes. No next phase prompt is required for the implemented flow; advanced visualization remains held.

## Polish V3 — 29 September 2026
Implemented six-card Home, shared waiting states, measured comparison progress/reuse, mode colours, benchmark preview/cancel/results and opt-in optical rendering with Classic fallback. Corrected persistent disturbance changes incorrectly suspending recovery scoring. Full evidence, 12 renderer runs and limitations: handoff/POLISH_V3.md. Final preview benchmark completed five scenarios without page errors; comparison cache reuse verified. Fast suite 54 run (53 passed, one skipped). No retraining or changed weights; optical mode is experimental and cannot claim realtime/real-space equivalence.

