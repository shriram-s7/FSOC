# Phase 07 — Stationary beacon and manual camera lab

Read common instructions. Inspect current Camera Lab page/startCameraLab, simulation/camera.py, target.py, ui/sim_thread.py, and control/camera_servo.py. Add simulation/camera_lab.py and camera-lab.js/css as needed. Do not change tracker algorithms/gains.

Create a distinct lab session with a fixed beacon world coordinate. Camera movement, not beacon motion, changes its image position. Provide Manual, Track Assist and Auto Acquire. Manual: keyboard/buttons command pan/tilt and automatic servo is disabled. Track Assist: detector/tracker overlays run but the user still owns camera movement. Auto Acquire: release manual commands and let the existing controller acquire/track. Display control ownership explicitly.

Controls: arrows/WASD, hold-to-move, fine/coarse rate, home, pan/tilt readouts, and a bounded angular cone around the home orientation subject also to existing mechanical limits. Start with a documented 5-degree cone, clipped by configured mechanical limits. Home is pointing home, not teleporting to the beacon. Honour existing slew rate and latency. Release all manual input on keyup, blur, page exit, disconnected control, or mode change; do not intercept typing in inputs. Validate finite bounded command values on the backend.

Show camera image beside a 2D gimbal/pointing diagram: fixed beacon marker, camera pointing, field of view and allowed cone. Explain why panning right moves the stationary beacon left in the image. Describe this as the simulator's angular/viewport approximation. No translation controls, roll, 3D orbital claims, or visual weather focus in this phase. Atmosphere controls are secondary.

Entering/exiting Lab must not accidentally reuse video mode or overwrite normal mission config. Use an explicit lab lifecycle and restore normal configuration, including automatic servo ownership. Start lab only after safely handling any active session through the existing lifecycle.

Test in tests/test_camera_lab.py: target coordinate invariance; pan/tilt sign; cone/mechanical limits; manual commands not opposed by servo; hold/release; blur/disconnect stop; switching back to automatic; configuration cleanup. Inspect actual camera and world movement.

Acceptance: a user can move the camera away from the fixed beacon, bring it back, and hand control to Auto Acquire. Target does not move and the UI clearly explains the source of image motion.
