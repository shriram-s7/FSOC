# Phase 04 — Home and shared shell

Read common instructions. Use expected ui_2/home.png and diagnostc_bar_at_all_screens.png as visual references. Work in index.html, current CSS, pages.js/app.js and diagnostics.js only as needed. Add scoped shell.css and an optional space-shell image asset.

Implement the home composition: space backdrop, FSOC-PAT identity, Quick Demo / Custom Mission / Benchmark / Load Video cards, measured backend/model/device status, and recent sessions from phase 02. Add a prominent full-width Camera Lab feature card describing manual pan/tilt of a stationary beacon. Reserve a clear Compare Modes entry that may be disabled with an accurate availability label until phase 10, not a fake action.

Improve shared navigation, breadcrumbs, focus/hover states, readable typography, consistent cards, and diagnostics access on every page. Keep existing font assets. Use measured model metadata (BeaconCNN where applicable), never the reference's YOLO label or example version/FPS values. Live status must handle offline/reconnecting states. Decorative stars may be high-quality CSS/canvas/image assets outside the sensor view. No sensor renderer, training or model changes. Do not use a screenshot of the reference as the interactive page itself.

Do not force an image-generation dependency. If an appropriate background asset is unavailable, create a restrained procedural shell background and document the remaining art difference. Preserve reference images unchanged.

Acceptance: inspect 1280x720, 1440x900, 1920x1080; cards fit, navigation works, Camera Lab is unmistakably discoverable, recent sessions load real data, backend-disconnected state is readable, no duplicate listeners/timers after navigation. Existing mission/video/reports flows remain functional.
