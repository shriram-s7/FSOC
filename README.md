# FSOC-PAT Simulator

AI-Based Virtual Camera Tracking System for Coarse Alignment of Mobile
Free Space Optical Communication (FSOC) Terminals.

**SIH 2025 | PS 26169 | ISRO / Department of Space**

## Quick Start

> **Note:** Requires Python 3.10–3.12 (pygame/torch wheels aren't yet available
> for 3.14). If your default `python` is 3.14, create a venv with an older
> interpreter, e.g. `py -3.12 -m venv venv`.

```bash
py -3.12 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Controls
- `ESC` — Quit
- `1-5` — Difficulty presets (added in Stage 8)
- `P` — Pause (added in Stage 7)

## Build Status
- [x] Stage 1 — Foundation (world rendering, moving target, HUD)
- [ ] Stage 2 — Simulation Core (orbital model, virtual camera)
- [ ] Stage 3 — Disturbance Engine
- [ ] Stage 4 — Detection + CNN Classifier
- [ ] Stage 5 — Tracking Engine (Kalman + temporal fusion)
- [ ] Stage 6 — PID Control Loop
- [ ] Stage 7 — Metrics, Logging, Full UI
- [ ] Stage 8 — Packaging & Polish

## Architecture
See implementation plan document for full technical details.
