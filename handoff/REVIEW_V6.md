# Specification and comparison presentation review - 29 September 2026

## Changes

- Beta comparison explicitly identifies CV, AI and Hybrid detection approaches. Hybrid is featured in teal with a heavier solid trace; CV is amber dashed and AI purple dotted. No measured result was modified or fabricated.
- `evaluation/comparison_presentation.py` supplies metric directions, leaders, ties and descriptions to both the API/UI and comparison PDF. Ranking uses 0.001 precision and preserves missing values.
- `evaluation/pdf_theme.py` shares report table treatment and page footer between session and comparison PDF generators. Print colours retain the screen colour families with stronger contrast.
- Supplied specification `C:/Users/shrir/Desktop/FSOC SIH related docs/26169.pdf` inspected. Atmospheric disturbance row explicitly includes Clear, Haze, Fog, Rain and Low light. Explain weather as an atmospheric path condition rather than vacuum weather.
- New-session target loss check corrected from <=5% to <5%. Provenance now cites the supplied document and explains that tracking-error aggregation uses the application's mean. New session scoring version is `3-ps-strict-loss`. Historical saved results and PDFs are preserved, including their original thresholds; a regenerated comparison PDF identifies historical scoring explicitly.
- Produced `docs/TECHNICAL_REPORT.md`, `output/pdf/FSOC_PAT_Technical_Report.pdf` (12 pages) and `docs/PRESENTATION_AND_DEMO.md` (ten-slide plan and four-minute narration).

## Verification and limits

- Python suite: 57 tests run, 56 passed and one slow behavioural test skipped. New cases cover honest ranking, ties/missing values and strict loss boundary.
- Isolated browser on port 8766: three panels, four measured comparison rows, correct API-derived leaders, Hybrid heavy trace, no page errors. Used a copy of saved comparison 8143c19e8bbb419aad63a4df3f0ddaf1; did not run a new timing experiment.
- Technical report and comparison QA PDF rendered and visually inspected. Session PDF QA uses a copy of existing recorded data. No original recordings or reports were rewritten for QA.
- Checkpoint inspection: 38,962 CNN parameters; stored v2 val_acc 0.9994597514856834 at epoch 23. This is checkpoint metadata, not a newly measured test-set or mission accuracy.
- No training, model edits, full benchmark sweep or real-camera evaluation. User backend at 8765 remains untouched; restart it and hard refresh to load new API/scoring/UI code.
