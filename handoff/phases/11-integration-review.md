# Phase 11 — Integration review and handover

Read all phase outcomes and contracts. Review implemented changes, not just their summaries. Fix integration defects within the agreed scope; do not add new features or retune models/controllers.

Verify full flows on an isolated test instance: Home→Quick Demo→Stop→Results→PDF; Builder→Brief→Edit→Execute→motion switch→pause/resume→Results; Video prepare with and without GT→EOF→Results; Home→Camera Lab→manual/assist/auto→Home→normal mission; comparison generation→three-view replay/seek→report→reload; backend reconnect and export error recovery. Check that entering Lab/video/comparison does not leak config or control ownership into other modes.

Run relevant existing and added tests, including no-leak checks and appropriate slow behavioural tests if runnable. Record exact commands and timeouts; never claim skipped slow checks passed. Compare current model hashes to phase 00. Confirm no changes to training data/weights or sensor appearance. Inspect true/estimated coordinates and numeric units; verify no fake fallback values, hardcoded PASS, altered competitors, mislabeled replay FPS or stale session links.

Inspect all pages at the three target sizes and representative PDFs. Check keyboard focus, long filenames, empty archive, zero values, no-GT unavailable values, repeated navigation, disconnected backend, cancelled comparison, bounded recording memory/storage and no old-data deletion. Screen captures should show actual running states, not reference images or mocked final results.

Write final handoff/EVIDENCE.md findings and update PROGRESS.md. Include a short end-user walkthrough, explicit feature limitations, actual Hybrid comparison results, and any incomplete acceptance checks. Do not claim universal superiority or official certification from a selected demonstration. No deployment or packaging is required by this phase.

Acceptance: report exact completed functionality and evidence, or a clearly scoped remaining defect list. 'Looks good' without execution evidence is insufficient.
