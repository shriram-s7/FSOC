# FSOC-PAT presentation and four-minute demo

## Ten-slide technical presentation

| Slide | Main message | Visual / evidence | Speaker emphasis |
|---|---|---|---|
| 1. The alignment problem | A narrow optical beam needs coarse acquisition before fine pointing | Beacon outside then inside camera FOV | We demonstrate coarse camera alignment, not a physical communications link. |
| 2. What the statement requests | Virtual camera, moving beacon, disturbances, measured performance | Threshold table from supplied 26169.pdf | Loss is strictly below 5%; the statement explicitly lists rain and fog. |
| 3. Closed-loop architecture | Images drive estimates; estimates drive camera commands | Render -> detect -> track -> servo -> next frame | Ground truth is an evaluation reference, not the controller's target coordinate. |
| 4. Virtual optics | Configured angular geometry, latency and speed caps create a control problem | World FOV plus camera feed | 640 x 480, default 4 x 3 degrees, 5 degrees/s slew caps. |
| 5. Three approaches | CV, AI and Hybrid differ in detection/scoring strategy | Three parallel pipeline diagrams | The same CNN serves AI and Hybrid; common tracking/control helps isolate the detection choice. |
| 6. Learned classifier | Small grayscale CNN evaluates beacon candidates | 32 x 32 -> convolution blocks -> 64 -> 2 | 38,962 parameters; stored 99.946% validation is patch accuracy, not mission accuracy. |
| 7. Tracking and servo | Temporal confidence, prediction and feedback sustain acquisition | State machine plus engineering view | Prediction during loss is explicitly different from a measured detection. |
| 8. Measured comparison | Show trade-offs, ties and failures by metric | Saved comparison ID, three traces, coverage and rates | Teal emphasises Hybrid; it does not manufacture a winner. |
| 9. Demonstration and report | Measurements persist beyond the live view | Camera Lab alignment, results and matching PDF | Green alignment is an interaction result; report PASS requires all checks. |
| 10. Limits and next work | A reproducible software testbed ready for further validation | Synthetic -> recorded camera -> hardware roadmap | Real-camera tests, agreed scoring and clean-machine packaging remain important. |

## Four-minute shot list and narration

### 0:00-0:25 | Home and problem

Show the new homepage and move to the camera/world view.

Narration: “Free-space optical links need precise pointing. Before fine steering can operate, coarse alignment must find a remote beacon and keep it inside the camera's field of view. FSOC-PAT implements that process in software, allowing us to explore tracking algorithms without an optical bench.”

### 0:25-0:55 | Architecture

Show the architecture slide, then a moving target and changing camera FOV.

Narration: “The simulator generates a scene and a constrained camera image. Detection supplies candidate measurements; temporal tracking estimates motion and manages acquisition; the controller commands pan and tilt. Those commands change the next image. Ground truth is retained separately to evaluate the estimate. This is a feedback loop, rather than a box animated from a known target path.”

### 0:55-1:40 | Acquisition and engineering overlay

Start a prepared mission. Allow lock. Toggle engineering details. Briefly introduce one controlled disturbance only if it has been rehearsed.

Narration: “The marker turns green when the tracker has a measured lock. The engineering overlay exposes the accepted measurement, estimated next position, candidate scores and centre error. A dashed amber marker represents prediction during an observation gap. The camera's speed and latency constrain how quickly the error can be corrected. We log both successful tracking and recovery failures.”

Do not narrate a recovery as successful unless it actually occurs. If lost, say: “This condition exceeded the available measurement or control margin; the log records the loss.”

### 1:40-2:20 | Camera Lab

Enter Camera Lab, pan away, select assist, follow the direction hint and then select auto.

Narration: “Here the beacon remains fixed and I move the camera. Assist explains the direction needed to bring the measurement back toward centre. Automatic mode gives control to the servo. The alignment indicator turns green only after a measured lock remains near centre for half a source second. This demonstrates pointing ownership; it is not the mission certification result.”

### 2:20-3:05 | Three-way comparison

Open a saved comparison, show its run ID and play the same source-time interval. Toggle trace visibility if traces overlap.

Narration: “CV uses classical proposals and a feature score. AI scans the image with a CNN. Hybrid applies the CNN to classical proposals. Each mode runs independently against the same scheduled scenario; the recordings then play together. Hybrid is highlighted in teal as our featured architecture. The values and per-metric leaders remain measured, including ties. Pipeline rate describes only part of processing and is not playback FPS.”

Use the actual displayed table to name winners. Do not read a fixed claim of Hybrid superiority over a contradictory run.

### 3:05-3:40 | Results and PDF

Show finalized results and its PDF, with the same session ID. Point to one error measure, one timing measure and one untested/failed check if present.

Narration: “The finalized record preserves configuration, frame measurements and summary values. Mean error, maximum error, RMSE and lock coverage describe different aspects of performance. Untested recovery stays incomplete; a video without ground truth cannot establish centroid accuracy. The PDF and saved data provide an auditable record of the demonstration.”

### 3:40-4:00 | Scope and future work

Return to architecture or a clean closing slide.

Narration: “The problem statement includes haze, fog, rain and low light for atmospheric operating conditions. Our star-themed interface does not imply weather exists in a vacuum. The next validation steps are representative recorded-camera data, repeated scenario benchmarks and a verified standalone package. The current result is a modular, inspectable coarse-alignment software testbed.”

## Rehearsal and evaluator questions

- Why do CV and Hybrid sometimes overlap? Similar candidate positions and a shared controller can produce similar trajectories on easy scenes. Compare difficult conditions, false locks and processing cost too.
- Why is Hybrid not always best? Its proposal detector can miss a target; each architecture has trade-offs. Results must determine the conclusion.
- Does the green box prove detection extent? No. It is a fixed-size position marker tied to the tracker. Candidate outlines and measured centroid give more precise context.
- Is 99.946% the system accuracy? No. It is stored synthetic patch-validation accuracy. Mission performance is evaluated independently.
- Why does five seconds take longer to generate? There are 300 steps per mode, three sequential modes and image/telemetry recording overhead. Source time and wall time differ.
- Is the system operating in physical 3D space? The core camera testbed is an angular/image-space approximation. Decorative graphics do not establish calibrated 3D optics.
- What if a test fails? Show which measure failed and the source condition; retain the record and explain the limitation without adjusting the result.
- Has the supplied video benchmark passed? Only claim this for the specific supplied video and GT pairing actually evaluated. Synthetic fixture tests are not a substitute.

Prepare the demo run before recording, keep its ID on the slide, close unrelated CPU-heavy applications and use measured timings from that same run. Do not edit numeric results to fit the narration.
