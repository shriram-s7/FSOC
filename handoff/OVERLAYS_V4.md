# Tracking overlays and Camera Lab alignment

- Camera feed always draws a green fixed-size tracking marker for a currently measured LOCKED target. This is a tracking marker, not a detector-estimated object extent. Prediction-only positions use a dashed amber marker.
- Engineering toggle adds accepted measurement, next-step estimate, centre error vector, candidate markers/scores and a compact telemetry legend. These displays use tracker measurements, not simulation ground truth.
- Camera Lab draws the marker in manual, assist and automatic modes. Alignment requires a measured LOCKED position within 10 sensor pixels for 0.5 simulation seconds; 14 px exit hysteresis reduces flicker. Lost measurements clear alignment immediately; a stale feed clears the badge after 1.5 wall-clock seconds.
- Assist indicates pan/tilt directions. Automatic mode uses the same measured alignment criteria. Alignment is not mission certification.
- Added read-only tracker telemetry; no training or controller changes.
- Validation: 53 Python tests passed, one slow test skipped. Isolated live browser test verified initial alignment, manual displacement, correct assist direction, automatic recovery, green marker with details disabled, detailed rendering, loss indication and no browser script errors. Script and screenshot: scratch/overlay-v4/check.cjs and lab.png.
- Restart backend and hard-refresh browser to load the new telemetry and scripts.
