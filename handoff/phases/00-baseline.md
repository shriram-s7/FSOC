# Phase 00 — Baseline and contracts

Read MASTER_PROMPT.md first. This phase is analysis/documentation only; do not change application behaviour.

Inspect index.html, frontend JS/CSS, server/app.py, ui/sim_thread.py, evaluation modules, simulation modules, comparison-related harness code, config/default.yaml and tests. Inspect every expected ui_2 image. Check applicable repository instructions and existing local modifications.

Create handoff/CONTRACTS.md describing existing endpoints, page IDs, stream formats, session IDs, summary keys, coordinate conventions, timestamps, detector modes, and units. Record the current requirement definitions and their provenance. Pay particular attention to acquisition from first detection versus mission start, pointing error versus centroid error, and lock percentage denominators. Do not silently redefine these.

Create handoff/EVIDENCE.md with baseline commands/results, observed defects, screenshots if safe, relevant process/port details, and read-only hashes of model files. Record Python/library versions actually found. Do not install or upgrade anything. Run the existing relevant non-destructive tests with output directed to scratch/handoff-verification when they generate files; inspect test side effects first. A pre-existing failure remains a pre-existing failure.

Confirm these earlier findings against current code: PDF selection clears report metrics; Stop opens the generic archive; motion changes construct a new Target; periodic motion centres on world centre; Camera Lab reuses simulation with no manual control; video selection immediately starts analysis; live comparison does not exist; v2 classifier weights are shared by AI and Hybrid. Record discrepancies.

Acceptance: contracts and evidence identify the real architecture and available tests, untouched data/model files, and exact phase dependencies. Do not promise pixel-perfect reference reproduction without viewing the references. Finish with phase 01 ready, or precise blockers.
